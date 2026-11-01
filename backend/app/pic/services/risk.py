"""M06 supplier risk monitor (SLM-04), performance scorecard (SLM-03), CAPA and the Supplier Risk Agent.

Signals come from the platform's own evidence: sanctions screening, certificate expiry, scorecard OTIF/PPM,
the twin's late-delivery probability, financial-health tiers and the bank-change fraud rule (§14: alert on a
bank change followed by an invoice within 30 days). External risk feeds plug in through `ingest`.
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import (
    AppUser, BankChangeRequest, Capa, Certificate, GoodsReceipt, InfoRecord, Invoice, Material, PurchaseOrder, RiskSignal, Scorecard, SpendLine,
    Supplier, SupplierAssessment, SupplierCategoryStatus, Task, TwinSnapshot,
)
from app.pic.platform import agents, audit, clock, outbox, rules, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem
from app.pic.services.common import principal

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
MITIGATIONS = {
    "COMPLIANCE": "Hold new awards, re-screen and escalate to compliance",
    "CERTIFICATE": "Request the renewed certificate; status turns Conditional on expiry",
    "DELIVERY": "Open a CAPA on delivery performance and increase expediting on open POs",
    "QUALITY": "Open a CAPA with 8D root-cause analysis; tighten incoming inspection",
    "FINANCIAL": "Review exposure (open POs and contracts) and qualify an alternate source",
    "FRAUD": "Hold payments until the bank change is re-verified by call-back",
    # pending workflow 31
    "CONCENTRATION": "Rebalance volume to qualified alternates (sourcing event) or set a share cap for the next awards",
    "GEOGRAPHIC": "Qualify a supplier in another region for the category and review buffer stock for the concentrated region",
    "SINGLE_SOURCE": "Start qualification of a second source for the material (RFI / sourcing event) and agree safety stock meanwhile",
    "CYBER": "Request the cyber-security questionnaire and certificate evidence; restrict data and system access until accepted",
}
# Categories raised by the concentration / single-source / cyber rules: each opens a mitigation task for the supplier manager.
TASKED_CATEGORIES = ("CONCENTRATION", "GEOGRAPHIC", "SINGLE_SOURCE", "CYBER")
MITIGATION_TASK = "RISK_MITIGATION"
# Rule SUPPLIER-RISK-EXT (tenants bootstrapped before it existed use these built-in values).
EXT_DEFAULT = {
    "riskPoints": {"Critical": 40, "High": 25, "Medium": 10, "Low": 3}, "highTierPoints": 15, "maxScore": 100,
    "concentration": {"windowMonths": 12, "minSpendMinor": 10_00_000 * 100, "supplierSharePct": 30, "regionSharePct": 50,
                      "categoryRegionSharePct": 70},
    "singleSource": {"enabled": True},
    "cyber": {"requiredSegments": ["STRATEGIC", "BOTTLENECK"], "minScore": 60, "warnDays": 60, "certificateTypes": ["ISO27001", "SOC2"]},
}
STATE_NAMES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other territory",
}


def ext_rule(session: Session) -> dict:
    """The SUPPLIER-RISK-EXT rule body merged over the built-in defaults."""
    try:
        body = rules.resolve(session, "SUPPLIER-RISK-EXT").body
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        body = {}
    merged = {k: (({**v, **(body.get(k) or {})}) if isinstance(v, dict) else body.get(k, v)) for k, v in EXT_DEFAULT.items()}
    return merged


def region_of(supplier: Supplier) -> str:
    if (supplier.country or "IN") == "IN":
        return f"IN-{supplier.state_code}" if supplier.state_code else "IN"
    return supplier.country


def region_name(region: str) -> str:
    return STATE_NAMES.get(region.split("-", 1)[1], region) if region.startswith("IN-") else region


def supplier_risk_score(session: Session, supplier: Supplier) -> dict:
    """A 0-100 score from the supplier's open risk signals (severity points), a HIGH financial tier and a block. Used by award
    optimisation constraints (pending workflow 21), bid scoring (23) and supplier segmentation (28)."""
    ext = ext_rule(session)
    points = ext["riskPoints"]
    cap = int(ext["maxScore"])
    if supplier.status == "BLOCKED":
        return {"score": cap, "level": "CRITICAL", "factors": [{"code": "BLOCKED", "points": cap, "evidence": "supplier is blocked"}]}
    factors = []
    for signal in session.execute(select(RiskSignal).where(RiskSignal.supplier_id == supplier.id, RiskSignal.status != "CLOSED")).scalars():
        factors.append({"code": signal.category, "points": int(points.get(signal.severity, 0)), "evidence": signal.title,
                        "severity": signal.severity})
    if supplier.risk_tier == "HIGH" and not any(f["code"] == "FINANCIAL" for f in factors):
        factors.append({"code": "FINANCIAL_TIER", "points": int(ext["highTierPoints"]), "evidence": "financial-health tier HIGH"})
    score = min(sum(f["points"] for f in factors), cap)
    level = "CRITICAL" if score >= 70 else "HIGH" if score >= 40 else "MEDIUM" if score >= 15 else "LOW"
    return {"score": score, "level": level, "factors": factors}


def _signal(session: Session, supplier: Supplier, key: str, category: str, severity: str, source: str, title: str, detail: dict) -> Optional[RiskSignal]:
    existing = session.execute(select(RiskSignal).where(RiskSignal.supplier_id == supplier.id, RiskSignal.dedup_key == key)).scalar_one_or_none()
    if existing is not None:
        if existing.status != "CLOSED":
            existing.detail, existing.severity = detail, severity
        return None
    owner = session.execute(select(AppUser.id).where(AppUser.roles.any("SUPPLIER_MANAGER"), AppUser.active.is_(True)).order_by(AppUser.email)).scalar()
    signal = RiskSignal(tenant_id=supplier.tenant_id, supplier_id=supplier.id, dedup_key=key, category=category, severity=severity, source=source,
                        title=title, detail=detail, owner_id=owner, detected_at=clock.now(), created_by=principal(session).user_id)
    session.add(signal)
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "RISK_SIGNAL", object_ref=supplier.code, after={"category": category, "severity": severity, "title": title})
    return signal


def scan(session: Session) -> list[RiskSignal]:
    """Supplier Risk Agent run: derive signals from platform evidence, then recommend mitigations (L1)."""
    body = rules.resolve(session, "SUPPLIER-RISK").body
    today = clock.today()
    created = []
    for supplier in session.execute(select(Supplier).order_by(Supplier.code)).scalars():
        screening = supplier.screening or {}
        if screening.get("sanctionsHits"):
            created.append(_signal(session, supplier, "sanctions", "COMPLIANCE", "Critical", "SCREENING",
                                   f"Sanctions-list match ({', '.join(screening['sanctionsHits'])})", {"screenedAt": screening.get("screenedAt")}))
        profile = screening.get("legacyProfile") or {}
        if profile and profile.get("complianceStatus") not in (None, "COMPLIANT"):
            created.append(_signal(session, supplier, "legacy-compliance", "COMPLIANCE", "High", "LEGACY_PROFILE",
                                   f"Compliance status {profile.get('complianceStatus')} in the legacy profile", profile))
        if supplier.risk_tier == "HIGH":
            created.append(_signal(session, supplier, "financial-tier", "FINANCIAL", "High", "FINANCIAL_HEALTH",
                                   "Financial-health tier HIGH", {"riskTier": supplier.risk_tier, "profile": profile or None}))
        for cert in session.execute(select(Certificate).where(Certificate.supplier_id == supplier.id)).scalars():
            days = (cert.expires_on - today).days
            if days <= int(body["certificateWarnDays"]):
                created.append(_signal(session, supplier, f"cert:{cert.type}:{cert.expires_on}", "CERTIFICATE",
                                       "High" if days < 0 else "Medium", "CERTIFICATE",
                                       f"{cert.type} {'expired' if days < 0 else f'expires in {days} days'} ({cert.expires_on.isoformat()})",
                                       {"certificate": cert.number, "expiresOn": cert.expires_on.isoformat()}))
        cards = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier.id).order_by(Scorecard.period.desc()).limit(3)).scalars().all()
        for card in cards:
            if card.otif_pct is not None and card.otif_pct < Decimal(str(body["minOtifPct"])):
                created.append(_signal(session, supplier, f"otif:{card.period}", "DELIVERY", "High" if card.otif_pct < 80 else "Medium", "SCORECARD",
                                       f"OTIF {card.otif_pct}% in {card.period} (target {body['minOtifPct']}%)", {"period": card.period, "otif": str(card.otif_pct)}))
            if card.ppm is not None and card.ppm > Decimal(str(body["maxPpm"])):
                created.append(_signal(session, supplier, f"ppm:{card.period}", "QUALITY", "High" if card.ppm > 5 * Decimal(str(body["maxPpm"])) else "Medium",
                                       "SCORECARD", f"PPM {card.ppm} in {card.period} (limit {body['maxPpm']})", {"period": card.period, "ppm": str(card.ppm)}))
        for twin in session.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier.id)).scalars():
            if twin.late_delivery_prob is not None and twin.late_delivery_prob >= Decimal(str(body["maxLateProb"])):
                created.append(_signal(session, supplier, f"twin-late:{twin.category}:{twin.as_of}", "DELIVERY", "Medium", "SUPPLIER_TWIN",
                                       f"Twin late-delivery probability {twin.late_delivery_prob} for {twin.category}",
                                       {"category": twin.category, "lateProb": str(twin.late_delivery_prob), "asOf": str(twin.as_of)}))
        for change in session.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == supplier.id)).scalars():
            window_end = change.created_at + timedelta(days=int(body["bankChangeInvoiceDays"]))
            invoices = session.execute(select(Invoice.number).where(Invoice.supplier_id == supplier.id, Invoice.created_at >= change.created_at,
                                                                    Invoice.created_at <= window_end)).scalars().all()
            if invoices:
                created.append(_signal(session, supplier, f"bank-change-invoice:{change.number}", "FRAUD", "High", "BANK_CHANGE_RULE",
                                       f"Invoice within {body['bankChangeInvoiceDays']} days of bank change {change.number}",
                                       {"bankChange": change.number, "status": change.status, "invoices": invoices}))
    created += _extended_signals(session, today)
    created = [c for c in created if c is not None]
    for signal in created:
        if signal.category in TASKED_CATEGORIES:
            _open_mitigation_task(session, signal)
    for signal in created:
        supplier = session.get(Supplier, signal.supplier_id)
        exposure = session.execute(select(func.coalesce(func.sum(PurchaseOrder.total_minor), 0)).where(
            PurchaseOrder.supplier_id == supplier.id, PurchaseOrder.status.notin_(("CLOSED", "CANCELLED", "INVOICED")))).scalar()
        agents.recommend(session, "SUPPLIER_RISK", object_type="SUPPLIER", object_id=supplier.id, object_ref=supplier.code,
                         dedup_key=f"{supplier.code}:{signal.dedup_key}", title=f"{supplier.code}: {signal.title}",
                         rationale=f"{signal.category.title()} risk ({signal.severity}) from {signal.source.replace('_', ' ').lower()}. "
                                   f"Open PO exposure {exposure / 100:,.2f}. Suggested mitigation: {MITIGATIONS[signal.category]}.",
                         proposal={"signal": str(signal.id), "mitigation": MITIGATIONS[signal.category]}, candidate_role="SUPPLIER_MANAGER",
                         deep_link=f"/pic/suppliers/{supplier.code}", value_at_risk_minor=int(exposure), evidence=[signal.dedup_key], confidence=0.75)
    return created


def _extended_signals(session: Session, today) -> list:
    """Pending workflow 31: geographic and supplier spend concentration, single-source materials and cyber questionnaire gaps."""
    ext = ext_rule(session)
    out = []
    suppliers = {s.id: s for s in session.execute(select(Supplier).where(Supplier.status != "BLOCKED").order_by(Supplier.code)).scalars()}
    conc = ext["concentration"]
    # -- spend concentration by supplier and region over the window
    cutoff_month = today.year * 12 + today.month - 1 - int(conc["windowMonths"])
    cutoff = f"{cutoff_month // 12:04d}-{cutoff_month % 12 + 1:02d}"
    by_supplier: dict = {}
    by_category_region: dict = {}
    for supplier_id, category, amount in session.execute(
            select(SpendLine.supplier_id, SpendLine.category, func.sum(SpendLine.amount_minor)).where(SpendLine.period > cutoff)
            .group_by(SpendLine.supplier_id, SpendLine.category)).all():
        by_supplier[supplier_id] = by_supplier.get(supplier_id, 0) + int(amount)
        supplier = suppliers.get(supplier_id)
        if supplier is not None:
            key = (category, region_of(supplier))
            by_category_region.setdefault(key, {})[supplier_id] = by_category_region.get(key, {}).get(supplier_id, 0) + int(amount)
    total = sum(by_supplier.values())
    if total >= int(conc["minSpendMinor"]):
        by_region: dict = {}
        for supplier_id, amount in by_supplier.items():
            supplier = suppliers.get(supplier_id)
            if supplier is not None:
                by_region.setdefault(region_of(supplier), {})[supplier_id] = amount
        for supplier_id, amount in sorted(by_supplier.items(), key=lambda kv: -kv[1]):
            supplier = suppliers.get(supplier_id)
            share = Decimal(amount) * 100 / total
            if supplier is not None and share >= Decimal(str(conc["supplierSharePct"])):
                out.append(_signal(session, supplier, "conc-supplier", "CONCENTRATION",
                                   "High" if share >= 2 * Decimal(str(conc["supplierSharePct"])) else "Medium", "SPEND_CUBE",
                                   f"{share:.1f}% of the last {conc['windowMonths']} months' spend is with {supplier.code} "
                                   f"(limit {conc['supplierSharePct']}%)",
                                   {"sharePct": str(share.quantize(Decimal("0.1"))), "spendMinor": amount, "totalMinor": total,
                                    "windowMonths": conc["windowMonths"]}))
        for region, members in sorted(by_region.items()):
            region_total = sum(members.values())
            share = Decimal(region_total) * 100 / total
            lead_id = max(members, key=members.get)
            if share >= Decimal(str(conc["regionSharePct"])) and len(by_region) > 1:
                out.append(_signal(session, suppliers[lead_id], f"geo:{region}", "GEOGRAPHIC", "Medium", "SPEND_CUBE",
                                   f"{share:.1f}% of spend sits in {region_name(region)} (limit {conc['regionSharePct']}%); largest supplier here",
                                   {"region": region, "sharePct": str(share.quantize(Decimal("0.1"))), "regionSpendMinor": region_total,
                                    "suppliers": sorted(suppliers[i].code for i in members)}))
        categories: dict = {}
        for (category, region), members in by_category_region.items():
            categories.setdefault(category, {})[region] = members
        for category, regions in sorted(categories.items()):
            category_total = sum(sum(m.values()) for m in regions.values())
            if category_total < int(conc["minSpendMinor"]) or len(regions) < 1:
                continue
            for region, members in sorted(regions.items()):
                share = Decimal(sum(members.values())) * 100 / category_total
                if share >= Decimal(str(conc["categoryRegionSharePct"])) and len(members) >= 1 and len(regions) > 1:
                    lead_id = max(members, key=members.get)
                    out.append(_signal(session, suppliers[lead_id], f"geo-cat:{category}:{region}", "GEOGRAPHIC", "High" if share >= 90 else "Medium",
                                       "SPEND_CUBE", f"{share:.0f}% of {category} spend is in {region_name(region)}",
                                       {"category": category, "region": region, "sharePct": str(share.quantize(Decimal("0.1"))),
                                        "suppliers": sorted(suppliers[i].code for i in members)}))
    # -- single-source materials: exactly one qualified supplier holds an info record for the material
    if ext["singleSource"].get("enabled", True):
        qualified = {(r.supplier_id, r.category) for r in session.execute(
            select(SupplierCategoryStatus).where(SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED")))).scalars()}
        sources: dict = {}
        for supplier_id, material_id, number, category in session.execute(
                select(InfoRecord.supplier_id, InfoRecord.material_id, Material.number, Material.category).join(
                    Material, Material.id == InfoRecord.material_id).where(Material.status == "ACTIVE")).all():
            if supplier_id in suppliers and (supplier_id, category) in qualified:
                sources.setdefault((material_id, number), set()).add(supplier_id)
        sole: dict = {}
        for (_, number), ids in sources.items():
            if len(ids) == 1:
                sole.setdefault(next(iter(ids)), []).append(number)
        for supplier_id, numbers in sorted(sole.items(), key=lambda kv: suppliers[kv[0]].code):
            out.append(_signal(session, suppliers[supplier_id], "single-source", "SINGLE_SOURCE", "High" if len(numbers) >= 3 else "Medium",
                               "SOURCING_DATA", f"{suppliers[supplier_id].code} is the only qualified source of {len(numbers)} material(s)",
                               {"materials": sorted(numbers)[:50], "count": len(numbers)}))
    # -- cyber: required segments need an accepted, valid questionnaire with a passing score
    cyber = ext["cyber"]
    latest: dict = {}
    for item in session.execute(select(SupplierAssessment).where(SupplierAssessment.kind == "CYBER", SupplierAssessment.status == "ACCEPTED")
                                .order_by(SupplierAssessment.as_of)).scalars():
        latest[item.supplier_id] = item
    for cert in session.execute(select(Certificate).where(Certificate.type.in_(list(cyber["certificateTypes"])))).scalars():
        supplier = suppliers.get(cert.supplier_id)
        days = (cert.expires_on - today).days
        if supplier is not None and days <= int(cyber["warnDays"]):
            out.append(_signal(session, supplier, f"cyber-cert:{cert.type}:{cert.expires_on}", "CYBER", "High" if days < 0 else "Medium",
                               "CERTIFICATE", f"Cyber-security certificate {cert.type} {'expired' if days < 0 else f'expires in {days} days'} "
                               f"({cert.expires_on})", {"certificate": cert.number, "expiresOn": cert.expires_on.isoformat()}))
    for supplier_id, supplier in suppliers.items():
        assessment = latest.get(supplier_id)
        if supplier.segment not in cyber["requiredSegments"] and assessment is None:
            continue
        if assessment is not None:  # the gap that raised "cyber-missing" is closed by an accepted questionnaire
            for gap in session.execute(select(RiskSignal).where(RiskSignal.supplier_id == supplier.id, RiskSignal.dedup_key == "cyber-missing",
                                                                RiskSignal.status != "CLOSED")).scalars():
                gap.status, gap.closed_at = "CLOSED", clock.now()
                gap.mitigation = f"Resolved: cyber questionnaire of {assessment.as_of} accepted"
                for task in session.execute(select(Task).where(Task.kind == MITIGATION_TASK, Task.object_id == gap.id, Task.status == "OPEN")).scalars():
                    task.status = "CANCELLED"
        if assessment is None:
            out.append(_signal(session, supplier, "cyber-missing", "CYBER", "Medium", "CYBER_QUESTIONNAIRE",
                               f"No accepted cyber-security questionnaire for {supplier.segment} supplier {supplier.code}", {"segment": supplier.segment}))
            continue
        days = (assessment.expires_on - today).days if assessment.expires_on else None
        if days is not None and days <= int(cyber["warnDays"]):
            out.append(_signal(session, supplier, f"cyber-expiry:{assessment.as_of}", "CYBER", "High" if days < 0 else "Medium",
                               "CYBER_QUESTIONNAIRE", f"Cyber questionnaire {'expired' if days < 0 else f'expires in {days} days'} "
                               f"({assessment.expires_on})", {"asOf": str(assessment.as_of), "expiresOn": str(assessment.expires_on)}))
        if assessment.score < Decimal(str(cyber["minScore"])):
            out.append(_signal(session, supplier, f"cyber-score:{assessment.as_of}", "CYBER", "High", "CYBER_QUESTIONNAIRE",
                               f"Cyber questionnaire score {assessment.score} is below {cyber['minScore']}",
                               {"asOf": str(assessment.as_of), "score": str(assessment.score), "minScore": cyber["minScore"]}))
    return out


def _open_mitigation_task(session: Session, signal: RiskSignal) -> None:
    """A task for the supplier manager to agree and record the mitigation (APPROVE = mitigation under way, REJECT = risk accepted)."""
    supplier = session.get(Supplier, signal.supplier_id)
    workflow.start_approval(session, None, MITIGATION_TASK, object_type="RISK_SIGNAL", object_id=signal.id,
                            object_ref=f"{supplier.code}:{signal.category}", chain=["SUPPLIER_MANAGER"], step_id=None, initiator_id=None,
                            sla_business_days=10, evidence={"signal": signal.title, "category": signal.category, "severity": signal.severity,
                                                            "suggested": MITIGATIONS[signal.category], "detail": signal.detail})


@workflow.on_task(MITIGATION_TASK)
def _mitigation_decided(session: Session, task: Task, outcome: str) -> None:
    signal = session.get(RiskSignal, task.object_id)
    if signal is None or signal.status == "CLOSED":
        return
    supplier = session.get(Supplier, signal.supplier_id)
    signal.owner_id = task.completed_by
    if outcome == "APPROVED":
        signal.status, signal.mitigation = "MITIGATING", task.comment or MITIGATIONS[signal.category]
    else:
        signal.status, signal.mitigation, signal.closed_at = "CLOSED", f"Risk accepted: {task.comment}", clock.now()
    audit.record(session, "SUPPLIER", supplier.id, "RISK_MITIGATED" if signal.status == "MITIGATING" else "RISK_ACCEPTED", object_ref=supplier.code,
                 after={"signal": signal.title, "status": signal.status}, reason=task.comment)


def ingest(session: Session, supplier: Supplier, *, source: str, category: str, severity: str, title: str, detail: dict, key: str) -> Optional[RiskSignal]:
    """Adapter entry point for licensed risk feeds (financial, news, sanctions)."""
    if category not in MITIGATIONS or severity not in SEVERITY_ORDER:
        raise Problem(422, "INVALID_SIGNAL", "Unknown risk category or severity")
    return _signal(session, supplier, f"{source}:{key}", category, severity, source, title, detail)


def mitigate(session: Session, signal: RiskSignal, action: str, close: bool) -> RiskSignal:
    p = principal(session)
    if not set(p.roles) & {"SUPPLIER_MANAGER", "CATEGORY_MANAGER", "PROCUREMENT_HEAD"}:
        raise Problem(403, "FORBIDDEN", "Risk signals are handled by supplier or category management", rule_ref="SLM-04")
    if signal.status == "CLOSED":
        raise Problem(409, "ILLEGAL_TRANSITION", "The signal is already closed")
    signal.mitigation, signal.owner_id = action, p.user_id
    signal.status = "CLOSED" if close else "MITIGATING"
    if close:
        signal.closed_at = clock.now()
    supplier = session.get(Supplier, signal.supplier_id)
    audit.record(session, "SUPPLIER", supplier.id, "RISK_MITIGATED" if not close else "RISK_CLOSED", object_ref=supplier.code,
                 after={"signal": signal.title, "status": signal.status}, reason=action)
    return signal


def monitor(session: Session) -> dict:
    master = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    signals = session.execute(select(RiskSignal).order_by(RiskSignal.detected_at.desc())).scalars().all()
    by_supplier: dict = {}
    for s in signals:
        entry = by_supplier.setdefault(s.supplier_id, {"supplier": master[s.supplier_id].code, "name": master[s.supplier_id].legal_name,
                                                       "status": master[s.supplier_id].status, "open": 0, "categories": set(), "worst": "Low"})
        if s.status != "CLOSED":
            entry["open"] += 1
            entry["categories"].add(s.category)
            if SEVERITY_ORDER[s.severity] < SEVERITY_ORDER[entry["worst"]]:
                entry["worst"] = s.severity
    heat = sorted(({**v, "categories": sorted(v["categories"])} for v in by_supplier.values() if v["open"]),
                  key=lambda v: (SEVERITY_ORDER[v["worst"]], -v["open"]))
    total = len(master) or 1
    high = sum(1 for v in heat if v["worst"] in ("Critical", "High"))
    return {"highRiskSupplierPct": f"{high * 100 / total:.1f}", "suppliersWithSignals": len(heat), "heat": heat,
            "signals": [{"id": str(s.id), "supplier": master[s.supplier_id].code, "category": s.category, "severity": s.severity, "source": s.source,
                         "title": s.title, "status": s.status, "mitigation": s.mitigation, "detail": s.detail, "detectedAt": s.detected_at.isoformat()}
                        for s in sorted(signals, key=lambda s: (s.status == "CLOSED", SEVERITY_ORDER[s.severity]))]}


# ---------------------------------------------------------------- SLM-03 performance and CAPA
def performance(session: Session) -> list[dict]:
    master = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    out = {}
    for card in session.execute(select(Scorecard).order_by(Scorecard.period)).scalars():
        entry = out.setdefault(card.supplier_id, {"supplier": master[card.supplier_id].code, "name": master[card.supplier_id].legal_name, "trend": []})
        entry["trend"].append({"period": card.period, "otifPct": str(card.otif_pct) if card.otif_pct is not None else None,
                               "ppm": str(card.ppm) if card.ppm is not None else None,
                               "invoiceAccuracyPct": str(card.invoice_accuracy_pct) if card.invoice_accuracy_pct is not None else None,
                               "receipts": card.receipts, "invoices": card.invoices})
    capas = session.execute(select(Capa)).scalars().all()
    for entry_id, entry in out.items():
        entry["latest"] = entry["trend"][-1]
        entry["openCapas"] = sum(1 for c in capas if c.supplier_id == entry_id and c.status != "CLOSED")
        entry["categories"] = [f"{c.category}:{c.status}" for c in session.execute(select(SupplierCategoryStatus).where(
            SupplierCategoryStatus.supplier_id == entry_id)).scalars()]
    return sorted(out.values(), key=lambda e: e["supplier"])


def open_capa(session: Session, supplier: Supplier, *, source_type: str, source_ref: str, finding: str, due_days: int = 30) -> Capa:
    existing = session.execute(select(Capa).where(Capa.supplier_id == supplier.id, Capa.source_ref == source_ref)).scalar_one_or_none()
    if existing:
        return existing
    owner = session.execute(select(AppUser.id).where(AppUser.roles.any("QUALITY_INSPECTOR"), AppUser.active.is_(True)).order_by(AppUser.email)).scalar() \
        or principal(session).user_id
    capa = Capa(tenant_id=supplier.tenant_id, number=next_number(session, "CAPA"), supplier_id=supplier.id, source_type=source_type,
                source_ref=source_ref, finding=finding, due_date=clock.today() + timedelta(days=due_days), owner_id=owner,
                created_by=principal(session).user_id)
    session.add(capa)
    session.flush()
    audit.record(session, "CAPA", capa.id, "OPENED", object_ref=capa.number, after={"supplier": supplier.code, "source": source_ref, "finding": finding})
    return capa


@outbox.consumer("quality.usage_decision", "capa-on-rejection")
def _capa_on_rejection(session: Session, event) -> None:
    if Decimal(event.payload.get("rejected") or "0") <= 0:
        return
    gr = session.get(GoodsReceipt, event.object_id)
    po = session.get(PurchaseOrder, gr.po_id)
    supplier = session.get(Supplier, po.supplier_id)
    open_capa(session, supplier, source_type="INSPECTION_LOT", source_ref=event.payload["lot"],
              finding=f"{event.payload['rejected']} rejected on {gr.number} ({po.number}), defect {event.payload.get('defect') or 'not coded'}")


def respond_capa(session: Session, capa: Capa, *, root_cause: str, actions: list[dict]) -> Capa:
    p = principal(session)
    if p.supplier_id != capa.supplier_id and "QUALITY_INSPECTOR" not in p.roles and "SUPPLIER_MANAGER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Only the supplier or quality can respond to this CAPA")
    if capa.status not in ("OPEN", "RESPONDED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"{capa.number} is {capa.status}")
    if not actions:
        raise Problem(422, "ACTIONS_REQUIRED", "A CAPA response lists at least one corrective action")
    capa.root_cause, capa.actions, capa.status = root_cause, actions, "RESPONDED"
    audit.record(session, "CAPA", capa.id, "RESPONDED", object_ref=capa.number, after={"rootCause": root_cause, "actions": actions})
    from app.pic.services import supplier_mgmt  # pending workflow 30: CAPA response time feeds the scorecard

    supplier_mgmt.update_scorecard_measures(session, session.get(Supplier, capa.supplier_id), clock.at_ist(capa.created_at.date(), 12).strftime("%Y-%m"))
    return capa


def verify_capa(session: Session, capa: Capa, effective: bool, comment: str) -> Capa:
    p = principal(session)
    if "QUALITY_INSPECTOR" not in p.roles:
        raise Problem(403, "FORBIDDEN", "CAPA effectiveness is verified by quality", rule_ref="SLM-03")
    if capa.status != "RESPONDED":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{capa.number} must be RESPONDED before verification")
    capa.status = "CLOSED" if effective else "OPEN"
    capa.verified_by = p.user_id
    if effective:
        capa.closed_at = clock.now()
    audit.record(session, "CAPA", capa.id, "VERIFIED" if effective else "REOPENED", object_ref=capa.number, reason=comment)
    return capa


def set_preferred(session: Session, supplier: Supplier, category: str, preferred: bool, reason: str) -> SupplierCategoryStatus:
    """Preferred needs Qualified plus scorecard evidence over the last three periods; Exited ends the category relationship."""
    from app.pic.services import supplier as supplier_svc
    p = principal(session)
    if not set(p.roles) & {"SUPPLIER_MANAGER", "CATEGORY_MANAGER"}:
        raise Problem(403, "FORBIDDEN", "Supplier category status is changed by supplier or category management")
    row = session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id,
                                                               SupplierCategoryStatus.category == category)).scalar_one_or_none()
    if row is None:
        raise Problem(404, "NOT_FOUND", f"{supplier.code} has no status for {category}")
    if preferred:
        if row.status != "QUALIFIED":
            raise Problem(409, "ILLEGAL_TRANSITION", f"Only a QUALIFIED supplier can become PREFERRED (now {row.status})", rule_ref="SLM")
        body = rules.resolve(session, "SUPPLIER-RISK").body
        cards = [c for c in session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier.id).order_by(Scorecard.period.desc())
                                            .limit(3)).scalars() if c.otif_pct is not None]
        minimum, max_ppm = Decimal(str(body["preferredOtifPct"])), Decimal(str(body["maxPpm"]))
        otif = sum(c.otif_pct for c in cards) / len(cards) if cards else None
        worst_ppm = max((c.ppm or Decimal(0) for c in cards), default=None)
        if otif is None or otif < minimum or worst_ppm > max_ppm:
            raise Problem(409, "RULE_VIOLATION", f"Preferred status needs average OTIF ≥ {minimum}% and PPM ≤ {max_ppm} over the last three "
                          f"scorecards (now OTIF {otif if otif is not None else 'n/a'}, worst PPM {worst_ppm if worst_ppm is not None else 'n/a'})",
                          rule_ref="SUPPLIER-RISK")
        return supplier_svc._set_category_status(session, supplier, category, "PREFERRED", reason)
    if row.status == "EXITED":
        raise Problem(409, "ILLEGAL_TRANSITION", "Already exited")
    open_pos = session.execute(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.supplier_id == supplier.id, PurchaseOrder.status.in_(("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")))).scalar()
    status = supplier_svc._set_category_status(session, supplier, category, "EXITED", reason)
    if open_pos:
        audit.record(session, "SUPPLIER", supplier.id, "EXIT_WITH_OPEN_POS", object_ref=supplier.code, after={"openPos": open_pos}, reason=reason)
    return status
