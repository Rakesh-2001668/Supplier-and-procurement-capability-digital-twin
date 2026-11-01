"""M01 spend governance: taxonomy classification, maverick rules and hits, concentration, contract compliance,
spend forecast and category strategy (blueprint §7, SPD-01..09).

Classification below the tenant threshold (default 0.80) goes to the steward queue; maverick rules are
configurable per tenant and every hit carries an owner and a disposition; intercompany spend is not addressable.
"""
import math
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import case, exists, func, select, text
from sqlalchemy.orm import Session

from app.pic.models import (
    AppUser, CatalogueItem, CategoryPlan, ClassificationReview, MaverickHit, MaverickRule, PoLine, PurchaseOrder, SpendCommitmentSummary,
    SpendCubeSummary, SpendLine, SpendViewState, Supplier, SupplierCategoryStatus, TaxonomyNode, TwinSnapshot,
)
from app.pic.platform import agents, audit, clock, rules
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, not_found
from app.pic.services import spend_cube
from app.pic.services.common import principal

# Default manufacturing taxonomy (segment → family → category); tenants extend it in ADM-02.
TAXONOMY = [
    ("DIRECT", None, 1, "Direct materials", [], True),
    ("DIR-METALS", "DIRECT", 2, "Metal parts", [], True),
    ("ALU-DIECAST", "DIR-METALS", 3, "Aluminium die castings", ["die cast", "diecast", "die-cast", "casting", "housing", "adc12", "hpdc"], True),
    ("FORGINGS", "DIR-METALS", 3, "Forgings", ["forging", "forged", "crankshaft", "knuckle", "yoke"], True),
    ("MACHINING", "DIR-METALS", 3, "Machined components", ["machined", "machining", "cnc", "turned", "milling", "5-axis", "flange", "shaft"], True),
    ("RAW-MATERIALS", "DIR-METALS", 3, "Raw materials", ["ingot", "billet", "coil", "sheet", "bar stock", "resin", "alloy", "aluminium", "steel"], True),
    ("DIR-COMPONENTS", "DIRECT", 2, "Bought-out components", [], True),
    ("FASTENERS", "DIR-COMPONENTS", 3, "Fasteners", ["fastener", "bolt", "screw", "nut", "washer", "rivet", "stud"], True),
    ("ELECTRONICS", "DIR-COMPONENTS", 3, "Electronics", ["pcb", "mcu", "sensor", "connector", "harness", "ecu", "capacitor", "cortex"], True),
    ("RUBBER-SEALS", "DIR-COMPONENTS", 3, "Seals and gaskets", ["seal", "gasket", "o-ring", "oring", "grommet"], True),
    ("PACKAGING", "DIR-COMPONENTS", 3, "Packaging", ["carton", "pallet", "crate", "packaging", "bin", "stretch film"], True),
    ("INDIRECT", None, 1, "Indirect spend", [], True),
    ("IND-SERVICES", "INDIRECT", 2, "Services", [], True),
    ("TOOLING-SERVICES", "IND-SERVICES", 3, "Tooling and die services", ["tooling", "fixture", "die repair", "mould", "mold", "die maintenance", "insert"], True),
    ("LOGISTICS", "IND-SERVICES", 3, "Freight and logistics", ["freight", "transport", "trucking", "lane", "courier", "shipment", "ftl"], True),
    ("IT-SERVICES", "IND-SERVICES", 3, "IT and software", ["software", "licence", "license", "cloud", "saas", "laptop", "it support", "subscription"], True),
    ("FACILITIES", "IND-SERVICES", 3, "Facilities", ["housekeeping", "security guard", "canteen", "amc", "facility", "electricity"], True),
    ("PROF-SERVICES", "IND-SERVICES", 3, "Professional services", ["consulting", "consultancy", "audit fee", "legal", "advisory", "training"], True),
    ("IND-MRO", "INDIRECT", 2, "Maintenance, repair and operations", [], True),
    ("MRO", "IND-MRO", 3, "MRO supplies", ["bearing", "lubricant", "spare", "maintenance", "abrasive", "cutting tool", "coolant", "gloves"], True),
    ("CAPEX", "INDIRECT", 2, "Capital equipment", [], True),
    ("CAPEX-MACHINERY", "CAPEX", 3, "Machinery and equipment", ["machine", "press", "furnace", "compressor", "robot"], True),
    ("INTERCOMPANY", None, 1, "Intercompany", [], False),
    ("IC-TRANSFER", "INTERCOMPANY", 3, "Intercompany transfers", ["intercompany", "inter-company", "stock transfer", "group company"], False),
    ("UNCLASSIFIED", None, 1, "Unclassified", [], True),
]

# Blueprint §7.2 default maverick rules.
MAVERICK_RULES = [
    ("PO_AFTER_INVOICE", "PO after invoice date", "The PO was created after the supplier invoice date (retrospective PO).", "High", "CATEGORY_MANAGER"),
    ("SPLIT_PO", "Split POs below threshold", "Same supplier, material group and cost object within 7 days summing above the approval band.", "High", "PROCUREMENT_HEAD"),
    ("NON_CATALOGUE", "Non-catalogue purchase where a catalogue exists", "Free-text purchase in a material group that has an active catalogue.", "Medium", "CATEGORY_MANAGER"),
    ("OFF_CONTRACT", "Off-contract purchase", "An active contract covers the material but the PO did not use it.", "High", "CATEGORY_MANAGER"),
    ("OFF_CONTRACT_PRICE", "Off-contract price", "The PO price left the contract tolerance.", "Medium", "CATEGORY_MANAGER"),
    ("ONE_TIME_VENDOR", "One-time vendor above limit", "Supplier is not qualified for the category and the line is above the one-time-vendor limit.", "High", "PROCUREMENT_HEAD"),
    ("NO_GOODS_RECEIPT", "Paid without goods receipt", "The invoice was paid with no goods receipt (no 3-way match).", "Critical", "FINANCE_CONTROLLER"),
    ("PO_NOT_APPROVED", "Paid before PO approval", "The invoice was paid while its PO was still awaiting approval.", "Critical", "FINANCE_CONTROLLER"),
    ("OVER_INVOICED", "Invoiced above PO value", "More was invoiced against the PO than its value.", "Critical", "FINANCE_CONTROLLER"),
]
DISPOSITIONS = ("ACCEPTED_EXCEPTION", "RECOVERY", "POLICY_BREACH", "FALSE_POSITIVE")
DISPOSERS = {"CATEGORY_MANAGER", "PROCUREMENT_HEAD", "CPO", "FINANCE_CONTROLLER"}

LEVERS = {
    "STRATEGIC": ["Long-term partnership with joint cost roadmap", "Dual sourcing within verified capacity", "Should-cost negotiation"],
    "LEVERAGE": ["Competitive RFQ or reverse auction", "Volume consolidation across plants", "Index-linked pricing"],
    "BOTTLENECK": ["Qualify an alternate source", "Safety stock or consignment", "Long-term supply agreement"],
    "NON_CRITICAL": ["Catalogue or punch-out buying", "Supplier rationalisation", "Automate with touchless POs"],
}
WAVES = {
    "STRATEGIC": ["Q1: supplier capability review with the twin", "Q2: should-cost model and negotiation", "Q3: contract renewal"],
    "LEVERAGE": ["Q1: demand aggregation", "Q2: RFQ / e-auction", "Q3: award and contract"],
    "BOTTLENECK": ["Q1: alternate-source search", "Q2: qualification (PPAP)", "Q4: dual-source split"],
    "NON_CRITICAL": ["Q1: catalogue set-up", "Q2: tail-spend consolidation", "Q3: touchless release"],
}
TARGET_PCT = {"STRATEGIC": Decimal("3"), "LEVERAGE": Decimal("6"), "BOTTLENECK": Decimal("1"), "NON_CRITICAL": Decimal("4")}


def _rule(session: Session):
    return rules.resolve(session, "SPEND-GOVERNANCE")


# ---------------------------------------------------------------- taxonomy and classification
def ensure_taxonomy(session: Session, tenant_id: uuid.UUID) -> None:
    """Default nodes plus every category already used by the tenant (materials, supplier qualification, spend)."""
    have = set(session.execute(select(TaxonomyNode.code)).scalars())
    for code, parent, level, name, keywords, addressable in TAXONOMY:
        if code not in have:
            session.add(TaxonomyNode(tenant_id=tenant_id, code=code, parent_code=parent, level=level, name=name, keywords=keywords,
                                     addressable=addressable))
            have.add(code)
    used = set(session.execute(select(SpendLine.category).distinct()).scalars()) | set(
        session.execute(select(SupplierCategoryStatus.category).distinct()).scalars())
    for code in sorted(c for c in used if c and c not in have):
        words = [w for w in re.split(r"[-_ ]+", code.lower()) if len(w) > 2]
        session.add(TaxonomyNode(tenant_id=tenant_id, code=code, parent_code="DIRECT", level=3, name=code.replace("-", " ").title(),
                                 keywords=words, addressable=True))
        have.add(code)
    for code, name, description, severity, owner in MAVERICK_RULES:
        if not session.execute(select(MaverickRule.id).where(MaverickRule.code == code)).first():
            session.add(MaverickRule(tenant_id=tenant_id, code=code, name=name, description=description, severity=severity, owner_role=owner))
    session.flush()


def _nodes(session: Session) -> list[TaxonomyNode]:
    return session.execute(select(TaxonomyNode).where(TaxonomyNode.level == 3)).scalars().all()


_KEYWORD_PATTERNS: dict[str, re.Pattern] = {}
_TAXONOMY_ORDER = {code: index for index, (code, *_rest) in enumerate(TAXONOMY)}
# Start of the qualifier of an item description: what follows says what the item is for / of / with, not what it is.
_QUALIFIER = re.compile(r"\s(?:for|of|with|incl\.?|including)\s")


def _keyword_pattern(keyword: str) -> re.Pattern:
    """A taxonomy keyword matches whole words only ("ecu" not in "security", "seal" not in "sealed", "mould" not in
    "moulding"); words of a phrase may be separated by any whitespace, and the last word may carry a plain plural
    (-s / -es: "bolts", "presses", "castings"). Other inflections are listed explicitly in the keyword lists
    ("forging"/"forged", "machined"/"machining")."""
    pattern = _KEYWORD_PATTERNS.get(keyword)
    if pattern is None:
        words = keyword.lower().split()
        body = r"\s+".join(re.escape(w) for w in words) if words else re.escape(keyword.lower())
        if words and words[-1][-1:].isalpha():
            body += "(?:e?s)?"
        pattern = _KEYWORD_PATTERNS[keyword] = re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")
    return pattern


def _specificity(keyword: str) -> int:
    """Words in a keyword: a phrase ("die cast", "security guard", "cutting tool") is more specific than one word."""
    return len([w for w in re.split(r"[\s\-/]+", keyword) if w])


def classify_text(session: Session, description: str, supplier_id: Optional[uuid.UUID], nodes: Optional[list] = None) -> tuple[str, Decimal, list]:
    """Keyword evidence plus the supplier's qualified categories as a prior. Returns (category, confidence, alternatives).
    Equal scores go, in turn, to the category whose keyword names the item rather than a "for / of / with …" qualifier
    ("EPDM grommet for harness" is a grommet), to the more specific keyword (more words: "die cast" over "aluminium"),
    then to the earlier taxonomy node."""
    text = f" {(description or '').lower()} "
    supplier_cats = set()
    if supplier_id:
        supplier_cats = set(session.execute(select(SupplierCategoryStatus.category).where(
            SupplierCategoryStatus.supplier_id == supplier_id)).scalars())
    scored = []
    for node in nodes if nodes is not None else _nodes(session):
        hits = [k for k in node.keywords or [] if k and _keyword_pattern(k).search(text)]
        score = len(hits) * 2 + (1.5 if node.code in supplier_cats else 0)
        if score:
            scored.append((score, node.code, hits))
    if not scored:
        return "UNCLASSIFIED", Decimal("0.300"), _second_opinion(session, description, [], nodes)
    qualifier = _QUALIFIER.search(text)
    cut = qualifier.start() if qualifier else len(text)
    head = {k for _, _, hits in scored for k in hits if _keyword_pattern(k).search(text[:cut])}
    scored.sort(key=lambda x: (-x[0], -any(k in head for k in x[2]), -max((_specificity(k) for k in x[2]), default=0),
                               _TAXONOMY_ORDER.get(x[1], len(TAXONOMY)), x[1]))
    best, runner_up = scored[0], scored[1] if len(scored) > 1 else None
    margin = best[0] - (runner_up[0] if runner_up else 0)
    confidence = min(Decimal("0.97"), Decimal("0.45") + Decimal(str(round(0.12 * best[0] + 0.05 * margin, 3))))
    if not best[2]:  # supplier prior only, no textual evidence
        confidence = min(confidence, Decimal("0.650"))
    alternatives = [{"category": c, "score": s, "evidence": h} for s, c, h in scored[:3]]
    if confidence < Decimal("0.65"):
        alternatives = _second_opinion(session, description, alternatives, nodes)
    return best[1], confidence.quantize(Decimal("0.001")), alternatives


def _second_opinion(session: Session, description: str, alternatives: list, nodes: Optional[list]) -> list:
    """TD 13.3: when the keyword classifier is unsure and the LLM gateway is configured, the model's choice among the taxonomy
    categories is appended to the steward's alternatives as ``source: LLM``. It never changes the proposed category or the auto-apply
    decision; with no gateway this returns ``alternatives`` untouched."""
    from app.pic.services import ai_assist

    suggestion = ai_assist.classification_second_opinion(session, description, nodes if nodes is not None else _nodes(session))
    return alternatives + [suggestion] if suggestion else alternatives


def classify_line(session: Session, line: SpendLine, nodes: Optional[list] = None) -> Optional[str]:
    """Spend Classification Agent (L3): applies confident results, routes the rest to the steward queue."""
    if line.classification_confidence is not None and line.classification_confidence >= Decimal("1.000"):
        return None  # classified from the material master
    if session.execute(select(ClassificationReview.id).where(ClassificationReview.spend_line_id == line.id)).first():
        return None
    threshold = Decimal(str(_rule(session).body["classificationThreshold"]))
    category, confidence, alternatives = classify_text(session, line.description or line.material_group, line.supplier_id, nodes)
    allowed, reason = agents.guard(session, "SPEND_CLASSIFICATION", required_level="L3", scope="spend:read")
    auto = allowed and confidence >= threshold
    ref = agents.log_run(session, "SPEND_CLASSIFICATION", object_type="SPEND_LINE", object_id=line.id, object_ref=line.invoice_ref,
                         inputs={"description": line.description, "materialGroup": line.material_group},
                         evidence=[a["category"] for a in alternatives], output={"category": category, "confidence": str(confidence)},
                         confidence=float(confidence), action_taken="EXECUTED" if auto else "DRAFTED",
                         denial_reason=None if allowed else reason)
    if auto:
        line.category, line.classification_confidence = category, confidence
        _apply_addressable(session, line)
        return "AUTO"
    session.add(ClassificationReview(tenant_id=line.tenant_id, spend_line_id=line.id, invoice_ref=line.invoice_ref,
                                     description=(line.description or line.material_group)[:300], proposed_category=category,
                                     confidence=confidence, alternatives=alternatives, agent_run_ref=ref, created_by=line.created_by))
    line.classification_confidence = confidence
    if line.category != "UNCLASSIFIED" and line.category not in {n.code for n in (nodes if nodes is not None else _nodes(session))}:
        # A free-text line's provisional category is its raw material group (e.g. SVC-TOOLING), not a taxonomy category:
        # it stays unclassified until the steward decides, instead of turning into a taxonomy node at the next refresh.
        line.category = "UNCLASSIFIED"
    return "REVIEW"


def _apply_addressable(session: Session, line: SpendLine) -> None:
    node = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == line.category)).scalar_one_or_none()
    root = node
    while root is not None and root.parent_code:
        root = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == root.parent_code)).scalar_one_or_none()
    line.addressable = bool(root.addressable if root else True) and line.category != "IC-TRANSFER"


def decide_review(session: Session, review: ClassificationReview, category: str, comment: Optional[str] = None) -> ClassificationReview:
    p = principal(session)
    if not set(p.roles) & {"CATEGORY_MANAGER", "MDM_STEWARD", "PROCUREMENT_HEAD"}:
        raise Problem(403, "FORBIDDEN", "Spend classification is reviewed by a category manager or data steward", rule_ref="M01")
    if review.status != "OPEN":
        raise Problem(409, "ILLEGAL_TRANSITION", f"Review for {review.invoice_ref} is already {review.status}")
    if not session.execute(select(TaxonomyNode.id).where(TaxonomyNode.code == category, TaxonomyNode.level == 3)).first():
        raise Problem(422, "UNKNOWN_CATEGORY", f"{category} is not a taxonomy category")
    line = session.get(SpendLine, review.spend_line_id)
    before = line.category
    line.category, line.classification_confidence = category, Decimal("1.000")
    _apply_addressable(session, line)
    review.status = "ACCEPTED" if category == review.proposed_category else "RECLASSIFIED"
    review.decided_category, review.decided_by, review.decided_at = category, p.user_id, clock.now()
    agents.feedback(session, review.agent_run_ref, "ACCEPTED" if review.status == "ACCEPTED" else "REJECTED")
    audit.record(session, "SPEND_LINE", line.id, "CLASSIFIED", object_ref=line.invoice_ref, before={"category": before},
                 after={"category": category, "review": review.status}, reason=comment, ai_ref=review.agent_run_ref)
    return review


# ---------------------------------------------------------------- maverick rules
def _owner(session: Session, role: str, category: str) -> Optional[uuid.UUID]:
    if role == "CATEGORY_MANAGER":
        plan = session.execute(select(CategoryPlan.owner_id).where(CategoryPlan.category == category)).scalar()
        if plan:
            return plan
    return session.execute(select(AppUser.id).where(AppUser.roles.any(role), AppUser.active.is_(True)).order_by(AppUser.email)).scalar()


def evaluate_line(session: Session, line: SpendLine, active: Optional[dict] = None) -> list[str]:
    """Apply the tenant's maverick rules; extra flags are written back so the cube's maverick share agrees."""
    body = _rule(session).body
    flags = set(line.maverick_flags or [])
    po_line = session.execute(select(PoLine).where(PoLine.id == line.po_line_id)).scalar_one_or_none() if line.po_line_id else None
    if po_line and po_line.item_type == "FREE_TEXT" and session.execute(select(CatalogueItem.id).where(
            CatalogueItem.material_group == po_line.material_group, CatalogueItem.active.is_(True))).first():
        flags.add("NON_CATALOGUE")
    if line.addressable and line.amount_minor > int(body["oneTimeVendorLimitMinor"]) and line.category not in ("UNCLASSIFIED",):
        qualified = session.execute(select(SupplierCategoryStatus.id).where(
            SupplierCategoryStatus.supplier_id == line.supplier_id, SupplierCategoryStatus.category == line.category,
            SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")))).first()
        if not qualified:
            flags.add("ONE_TIME_VENDOR")
    line.maverick_flags = sorted(flags)
    active = active if active is not None else {r.code: r for r in session.execute(select(MaverickRule).where(MaverickRule.active.is_(True))).scalars()}
    created = []
    for code in line.maverick_flags:
        rule = active.get(code)
        if rule is None or session.execute(select(MaverickHit.id).where(MaverickHit.rule_code == code, MaverickHit.spend_line_id == line.id)).first():
            continue
        hit = MaverickHit(tenant_id=line.tenant_id, number=next_number(session, "MAVERICK_HIT"), rule_code=code, spend_line_id=line.id,
                          invoice_ref=line.invoice_ref, po_ref=line.po_ref, supplier_id=line.supplier_id, category=line.category,
                          amount_minor=line.amount_minor, owner_role=rule.owner_role, owner_id=_owner(session, rule.owner_role, line.category),
                          created_by=line.created_by)
        session.add(hit)
        created.append(code)
    session.flush()
    return created


def dispose(session: Session, hit: MaverickHit, disposition: str, comment: str) -> MaverickHit:
    p = principal(session)
    if disposition not in DISPOSITIONS:
        raise Problem(422, "INVALID_DISPOSITION", f"Use one of {', '.join(DISPOSITIONS)}")
    if not comment or len(comment.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "Every maverick disposition needs a comment", rule_ref="M01")
    if hit.owner_id != p.user_id and not set(p.roles) & (DISPOSERS - {"CATEGORY_MANAGER"}) and hit.owner_role not in p.roles:
        raise Problem(403, "FORBIDDEN", f"{hit.number} is owned by {hit.owner_role.replace('_', ' ').lower()}", rule_ref="M01")
    if hit.status != "OPEN":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{hit.number} is already {hit.status}")
    hit.status = "RECOVERY_OPEN" if disposition == "RECOVERY" else "DISPOSED"
    hit.disposition, hit.comment, hit.disposed_by, hit.disposed_at = disposition, comment, p.user_id, clock.now()
    audit.record(session, "MAVERICK_HIT", hit.id, "DISPOSED", object_ref=hit.number, after={"disposition": disposition, "rule": hit.rule_code},
                 reason=comment)
    return hit


def refresh(session: Session, tenant_id: uuid.UUID) -> dict:
    """Classify and evaluate every spend line that has not been processed yet (idempotent)."""
    ensure_taxonomy(session, tenant_id)
    nodes = _nodes(session)
    active = {r.code: r for r in session.execute(select(MaverickRule).where(MaverickRule.active.is_(True))).scalars()}
    out = {"auto": 0, "review": 0, "hits": 0}
    for line in session.execute(select(SpendLine).order_by(SpendLine.period, SpendLine.invoice_ref)).scalars():
        result = classify_line(session, line, nodes)
        if result:
            out["auto" if result == "AUTO" else "review"] += 1
        out["hits"] += len(evaluate_line(session, line, active))
    return out


def after_spend_line(session: Session, line: SpendLine) -> None:
    session.flush()
    classify_line(session, line)
    evaluate_line(session, line)


# ---------------------------------------------------------------- read models
def _months_back(today: date, n: int) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _window(session: Session, months: int = 12) -> list[str]:
    """The last `months` complete months before today (or ending at the latest posted period if that is earlier)."""
    latest = spend_cube.latest_period(session)
    first_of_month = clock.today().replace(day=1)
    previous = first_of_month - timedelta(days=1)
    anchor = f"{previous.year:04d}-{previous.month:02d}"
    if latest and latest < anchor:
        anchor = latest
    return _months_back(date(int(anchor[:4]), int(anchor[5:]), 1), months)


def _pct(num, den) -> str:
    return str((Decimal(num) * 100 / den).quantize(Decimal("0.1"))) if den else "0"


# The cube engine (summary tables, refresh, filters) lives in services/spend_cube.py; these are its public entry points.
refresh_spend_views = spend_cube.refresh_spend_views
cube = spend_cube.cube
commitments = spend_cube.commitments
CubeFilter = spend_cube.CubeFilter
CUBE_DIMENSIONS = spend_cube.ALL_DIMENSIONS


def _in_window(periods: list[str]):
    return SpendCubeSummary.period.between(periods[0], periods[-1])


def portfolio(session: Session, period_from: str, period_to: str) -> dict:
    """Spend totals and shares between two periods (inclusive) from the cube summary: total, addressable, under management,
    contracted, maverick, auto-classified lines, counts and price variance (group currency)."""
    C = SpendCubeSummary
    group = C.amount_group_minor
    qualified = exists().where(SupplierCategoryStatus.supplier_id == C.supplier_id, SupplierCategoryStatus.category == C.category,
                               SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")))
    # Under management: contract or catalogue price, or bought without maverick flags from a qualified supplier
    # in a category that has an approved category plan.
    managed_categories = list(session.execute(select(CategoryPlan.category).where(CategoryPlan.status == "APPROVED")).scalars())
    managed_clause = C.contracted.is_(True) | (C.maverick.is_(False) & C.category.in_(managed_categories or [""]) & qualified)
    addr = C.addressable.is_(True)
    t = session.execute(select(
        func.coalesce(func.sum(group), 0), func.coalesce(func.sum(case((addr, group), else_=0)), 0),
        func.coalesce(func.sum(case((addr & managed_clause, group), else_=0)), 0),
        func.coalesce(func.sum(case((addr & C.contracted.is_(True), group), else_=0)), 0),
        func.coalesce(func.sum(case((addr & C.maverick.is_(True), group), else_=0)), 0),
        func.coalesce(func.sum(C.auto_classified_lines), 0), func.coalesce(func.sum(C.invoices), 0), func.coalesce(func.sum(C.pos), 0),
        func.coalesce(func.sum(C.price_variance_group_minor), 0), func.coalesce(func.sum(C.price_variance_last_group_minor), 0),
        func.coalesce(func.sum(C.fx_missing_lines), 0), func.coalesce(func.sum(C.lines), 0),
    ).where(C.period.between(period_from, period_to))).one()
    keys = ("totalMinor", "addressableMinor", "managedMinor", "contractedMinor", "maverickMinor", "autoClassifiedLines", "invoices", "pos",
            "priceVarianceMinor", "priceVarianceLastMinor", "fxMissingLines", "lines")
    return {k: int(v) for k, v in zip(keys, t)}


def overview(session: Session) -> dict:
    """SPD-01: trailing-12-month totals, shares, top movers and the opportunity list, from the cube summary (SQL aggregates)."""
    freshness = spend_cube.ensure_fresh(session)
    periods = _window(session, 12)
    C = SpendCubeSummary
    group = C.amount_group_minor
    p = portfolio(session, periods[0], periods[-1])
    total, addr_total, auto = p["totalMinor"], p["addressableMinor"], p["autoClassifiedLines"]
    decided = {k: v for k, v in session.execute(select(ClassificationReview.status, func.count()).group_by(ClassificationReview.status)).all()}
    accuracy_den = auto + decided.get("ACCEPTED", 0) + decided.get("RECLASSIFIED", 0)
    recent, prior = periods[-3:], periods[-6:-3]
    moved = session.execute(select(
        C.category, func.coalesce(func.sum(case((C.period.in_(recent), group), else_=0)), 0),
        func.coalesce(func.sum(case((C.period.in_(prior), group), else_=0)), 0)).where(C.period.in_(recent + prior)).group_by(C.category)).all()
    top_movers = sorted(({"category": c, "last3Minor": int(a), "prior3Minor": int(b), "changePct": _pct(a - b, b) if b else None}
                         for c, a, b in moved if a or b), key=lambda x: -abs(x["last3Minor"] - x["prior3Minor"]))[:6]
    spend_cube.ensure_commitments_fresh(session)
    committed = session.execute(select(func.coalesce(func.sum(SpendCommitmentSummary.committed_group_minor), 0))).scalar() if session.execute(
        select(SpendViewState.id).where(SpendViewState.view_name == "spend_commitment_summary")).first() else None
    opps = opportunities(session, periods)
    return {"periods": [periods[0], periods[-1]], "totalMinor": total, "addressableMinor": addr_total, "addressablePct": _pct(addr_total, total),
            "underManagementPct": _pct(p["managedMinor"], addr_total), "contractedPct": _pct(p["contractedMinor"], addr_total),
            "maverickPct": _pct(p["maverickMinor"], addr_total),
            "classificationAccuracyPct": _pct(auto + decided.get("ACCEPTED", 0), accuracy_den) if accuracy_den else None,
            "openReviews": decided.get("OPEN", 0),
            "openMaverickHits": session.execute(select(func.count()).select_from(MaverickHit).where(MaverickHit.status == "OPEN")).scalar(),
            "topMovers": top_movers, "opportunities": opps,
            "priceVarianceMinor": p["priceVarianceMinor"], "priceVarianceLastMinor": p["priceVarianceLastMinor"], "invoices": p["invoices"],
            "pos": p["pos"], "lines": p["lines"], "openCommitmentsMinor": int(committed) if committed is not None else None,
            "aggregationOpportunityMinor": sum(o.get("indicativeSavingMinor", 0) for o in opps if o["kind"] == "CONSOLIDATION"),
            "fxMissingLines": p["fxMissingLines"], "groupCurrency": spend_cube._group_currency(session), "freshness": freshness}


def opportunities(session: Session, periods: list[str]) -> list[dict]:
    """Contract-coverage, aggregation (many suppliers / plants for one category) and price-variance opportunities, from the cube."""
    C = SpendCubeSummary
    group = C.amount_group_minor
    body = _rule(session).body
    min_suppliers, saving_pct = int(body.get("aggregationMinSuppliers", 4)), Decimal(str(body.get("aggregationSavingPct", "3")))
    rows = session.execute(select(
        C.category, func.sum(group), func.coalesce(func.sum(case((C.contracted.is_(False), group), else_=0)), 0),
        func.count(func.distinct(C.supplier_id)), func.count(func.distinct(C.plant)), func.coalesce(func.sum(C.price_variance_group_minor), 0))
        .where(_in_window(periods), C.addressable.is_(True), C.category != "UNCLASSIFIED").group_by(C.category)).all()
    by_supplier: dict[str, list[int]] = defaultdict(list)
    for category, amount in session.execute(select(C.category, func.sum(group)).where(
            _in_window(periods), C.addressable.is_(True), C.category != "UNCLASSIFIED").group_by(C.category, C.supplier_id)):
        by_supplier[category].append(int(amount or 0))
    out = []
    for category, spend_, off, suppliers, plants, variance in rows:
        spend_, off, variance = int(spend_ or 0), int(off or 0), int(variance or 0)
        if off > spend_ * 0.4 and spend_ > 50 * 100_000 * 100:
            out.append({"category": category, "kind": "CONTRACT_COVERAGE", "valueMinor": off,
                        "text": f"{_pct(off, spend_)}% of spend is not on contract; run a sourcing event", "deepLink": "/pic/sourcing/new"})
        if suppliers >= min_suppliers or (plants >= 2 and suppliers >= 2):
            ranked = sorted(by_supplier[category], reverse=True)
            tail = sum(ranked[3:]) if len(ranked) > 3 else sum(ranked[1:])
            where = f"{suppliers} suppliers" + (f" across {plants} plants" if plants > 1 else "")
            out.append({"category": category, "kind": "CONSOLIDATION", "valueMinor": spend_,
                        "indicativeSavingMinor": int(Decimal(tail) * saving_pct / 100), "suppliers": suppliers, "plants": plants,
                        "text": f"{where} share this category; consolidate volume (tail spend {_pct(tail, spend_)}%)",
                        "deepLink": "/pic/spend?tab=suppliers"})
        if variance > 0:
            out.append({"category": category, "kind": "PRICE_VARIANCE", "valueMinor": variance,
                        "text": "Invoiced above contract or standard price; recover or renegotiate", "deepLink": "/pic/spend?tab=compliance"})
    return sorted(out, key=lambda o: -o["valueMinor"])[:10]


def treemap(session: Session) -> dict:
    """SPD-02: segment → family → category with spend and drill to supplier."""
    periods = _window(session, 12)
    C = SpendCubeSummary
    nodes = {n.code: n for n in session.execute(select(TaxonomyNode)).scalars()}
    suppliers = {s.id: (s.code, s.legal_name) for s in session.execute(select(Supplier)).scalars()}
    rows = session.execute(select(C.category, C.supplier_id, func.sum(C.amount_group_minor), func.sum(C.lines))
                           .where(_in_window(periods)).group_by(C.category, C.supplier_id)).all()
    tree: dict = {}
    for category, supplier_id, amount, count in rows:
        node = nodes.get(category)
        family = nodes.get(node.parent_code) if node and node.parent_code else None
        segment = nodes.get(family.parent_code) if family and family.parent_code else family
        seg_key = segment.code if segment else (family.code if family else "UNCLASSIFIED")
        fam_key = family.code if family and family is not segment else seg_key
        seg = tree.setdefault(seg_key, {"code": seg_key, "name": nodes[seg_key].name if seg_key in nodes else seg_key, "valueMinor": 0, "children": {}})
        fam = seg["children"].setdefault(fam_key, {"code": fam_key, "name": nodes[fam_key].name if fam_key in nodes else fam_key, "valueMinor": 0, "children": {}})
        cat = fam["children"].setdefault(category, {"code": category, "name": node.name if node else category, "valueMinor": 0, "suppliers": []})
        code, name = suppliers.get(supplier_id, ("?", "Unknown supplier"))
        cat["suppliers"].append({"supplier": code, "name": name, "valueMinor": int(amount), "lines": int(count)})
        for level in (seg, fam, cat):
            level["valueMinor"] += int(amount)

    def flatten(level):
        if "children" in level:
            level["children"] = sorted((flatten(c) for c in level["children"].values()), key=lambda c: -c["valueMinor"])
        else:
            level["suppliers"].sort(key=lambda s: -s["valueMinor"])
        return level
    return {"periods": [periods[0], periods[-1]], "segments": sorted((flatten(s) for s in tree.values()), key=lambda s: -s["valueMinor"])}


def _norm_name(name: str) -> str:
    name = re.sub(r"\b(pvt|private|ltd|limited|llp|inc|llc|plc|co|company|corp|corporation|the)\b\.?", " ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _duplicate_clusters(master: dict, spend_by_supplier: dict) -> list[dict]:
    """Same PAN, or similar legal names: names are compared in sorted order inside a sliding window (similar names sort next to
    each other), so the scan stays linear in the number of suppliers instead of comparing every pair."""
    items = sorted(((s, _norm_name(s.legal_name)) for s in master.values()), key=lambda x: (x[1], x[0].code))
    parent: dict = {s.id: s.id for s, _ in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_pan: dict = defaultdict(list)
    for s, _ in items:
        if s.pan_hash:
            by_pan[s.pan_hash].append(s)
    for group in by_pan.values():
        for other in group[1:]:
            parent[find(other.id)] = find(group[0].id)
    window = 25
    for i, (a, na) in enumerate(items):
        for b, nb in items[i + 1:i + 1 + window]:
            if na and nb and find(a.id) != find(b.id) and SequenceMatcher(None, na, nb).ratio() >= 0.86:
                parent[find(b.id)] = find(a.id)
    groups: dict = defaultdict(list)
    for s, _ in items:
        groups[find(s.id)].append(s)
    clusters = []
    for group in groups.values():
        if len(group) > 1:
            first = group[0]
            clusters.append({"suppliers": [{"code": g.code, "name": g.legal_name, "spendMinor": spend_by_supplier.get(g.id, 0)} for g in group],
                             "reason": "same PAN" if any(g.pan_hash and g.pan_hash == first.pan_hash for g in group[1:]) else "similar legal name"})
    return sorted(clusters, key=lambda c: c["suppliers"][0]["code"])


def suppliers_view(session: Session, limit: int = 200) -> dict:
    """SPD-03: supplier ranking, HHI per category and duplicate-supplier clusters (parent roll-up and currency normalisation:
    amounts are in the group currency; ``parent`` is the corporate parent when the supplier has one)."""
    periods = _window(session, 12)
    C = SpendCubeSummary
    master = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    rows = session.execute(select(C.supplier_id, C.category, func.sum(C.amount_group_minor))
                           .where(_in_window(periods), C.addressable.is_(True)).group_by(C.supplier_id, C.category)).all()
    total = sum(int(r[2]) for r in rows) or 1
    by_supplier, by_cat = defaultdict(int), defaultdict(dict)
    for supplier_id, category, amount in rows:
        by_supplier[supplier_id] += int(amount)
        by_cat[category][supplier_id] = by_cat[category].get(supplier_id, 0) + int(amount)
    categories_of = defaultdict(list)
    for category, m in by_cat.items():
        for sid in m:
            categories_of[sid].append(category)
    ranked = sorted(by_supplier.items(), key=lambda x: -x[1])
    ranking = [{"supplier": master[s].code if s in master else "?", "name": master[s].legal_name if s in master else "Unknown",
                "riskTier": master[s].risk_tier if s in master else None, "spendMinor": v, "sharePct": _pct(v, total),
                "parent": master[master[s].parent_supplier_id].code if s in master and master[s].parent_supplier_id in master else None,
                "categories": sorted(categories_of[s])} for s, v in ranked[:limit]]
    concentration = []
    for category, shares in by_cat.items():
        cat_total = sum(shares.values())
        hhi = sum((Decimal(v) * 100 / cat_total) ** 2 for v in shares.values()) if cat_total else Decimal(0)
        top = max(shares.items(), key=lambda x: x[1])
        concentration.append({"category": category, "spendMinor": cat_total, "suppliers": len(shares), "hhi": int(hhi),
                              "level": "HIGH" if hhi > 2500 else "MODERATE" if hhi > 1500 else "LOW",
                              "topSupplier": master[top[0]].code if top[0] in master else "?", "topSharePct": _pct(top[1], cat_total)})
    return {"periods": [periods[0], periods[-1]], "totalMinor": total, "ranking": ranking, "suppliersRanked": len(ranked),
            "concentration": sorted(concentration, key=lambda c: -c["spendMinor"]),
            "duplicateClusters": _duplicate_clusters(master, by_supplier)}


def compliance(session: Session) -> dict:
    """SPD-05: contracted vs non-contracted by category, off-contract lines and price delta vs contract."""
    periods = _window(session, 12)
    C = SpendCubeSummary
    group = C.amount_group_minor
    rows = session.execute(select(
        C.category, func.coalesce(func.sum(case((C.contracted.is_(True), group), else_=0)), 0),
        func.coalesce(func.sum(case((C.contracted.is_(False), group), else_=0)), 0), func.coalesce(func.sum(C.price_variance_group_minor), 0),
        func.coalesce(func.sum(C.price_variance_last_group_minor), 0))
        .where(_in_window(periods), C.addressable.is_(True)).group_by(C.category)).all()
    master = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    off_lines = session.execute(select(SpendLine).where(
        SpendLine.period.between(periods[0], periods[-1]), SpendLine.addressable.is_(True),
        text("spend_line.maverick_flags ?| array['OFF_CONTRACT','OFF_CONTRACT_PRICE']")).order_by(SpendLine.amount_minor.desc()).limit(100)).scalars().all()
    off_agg = {c: (n, int(v or 0)) for c, n, v in session.execute(select(
        SpendLine.category, func.count(), func.sum(SpendLine.price_variance_minor)).where(
        SpendLine.period.between(periods[0], periods[-1]), SpendLine.addressable.is_(True),
        text("spend_line.maverick_flags ?| array['OFF_CONTRACT','OFF_CONTRACT_PRICE']")).group_by(SpendLine.category)).all()}
    categories = [{"category": c, "contractedMinor": int(a), "nonContractedMinor": int(b), "priceVarianceMinor": int(v), "priceVarianceLastMinor": int(vl),
                   "offContractLines": off_agg.get(c, (0, 0))[0], "coveragePct": _pct(int(a), int(a) + int(b))} for c, a, b, v, vl in rows]
    off = [{"invoice": l.invoice_ref, "po": l.po_ref, "supplier": master.get(l.supplier_id), "category": l.category, "period": l.period,
            "amountMinor": l.amount_minor, "priceVarianceMinor": l.price_variance_minor or 0, "flags": l.maverick_flags} for l in off_lines]
    return {"periods": [periods[0], periods[-1]], "categories": sorted(categories, key=lambda r: -(r["contractedMinor"] + r["nonContractedMinor"])),
            "offContract": off, "leakageMinor": sum(v for _, v in off_agg.values())}


def forecast(session: Session, category: Optional[str] = None, plant: Optional[str] = None, horizon: int = 6) -> dict:
    """SPD-09: Holt linear smoothing on monthly spend with an 80% band that widens with the horizon."""
    periods = _window(session, 24)
    C = SpendCubeSummary
    query = select(C.category, C.period, func.sum(C.amount_group_minor)).where(C.period.in_(periods))
    if category:
        query = query.where(C.category == category)
    if plant:
        query = query.where(C.plant == plant)
    series = defaultdict(lambda: {p: 0 for p in periods})
    for cat, period, amount in session.execute(query.group_by(C.category, C.period)).all():
        series[cat][period] = int(amount)
    last = date(int(periods[-1][:4]), int(periods[-1][5:]), 1)
    future = _months_back(date(last.year + (last.month + horizon - 1) // 12, (last.month + horizon - 1) % 12 + 1, 1), horizon)
    out = []
    for cat, values in sorted(series.items(), key=lambda kv: -sum(kv[1].values())):
        ys = [values[p] for p in periods]
        if sum(1 for y in ys if y) < 3:
            continue
        level, trend, alpha, beta = ys[0], 0.0, 0.4, 0.2
        residuals = []
        for y in ys[1:]:
            predicted = level + trend
            residuals.append(y - predicted)
            prev = level
            level = alpha * y + (1 - alpha) * (level + trend)
            trend = beta * (level - prev) + (1 - beta) * trend
        sigma = math.sqrt(sum(r * r for r in residuals) / max(1, len(residuals) - 1))
        points = [{"period": p, "actualMinor": values[p]} for p in periods[-12:]]
        for h, p in enumerate(future, start=1):
            mid = max(0.0, level + h * trend)
            band = 1.2816 * sigma * math.sqrt(h)
            points.append({"period": p, "forecastMinor": int(mid), "lowMinor": int(max(0.0, mid - band)), "highMinor": int(mid + band)})
        out.append({"category": cat, "method": "Holt linear (α 0.4, β 0.2), 80% band", "next12Minor": int(max(0.0, sum(level + h * trend for h in range(1, 13)))),
                    "points": points})
    return {"history": [periods[0], periods[-1]], "horizon": future, "series": out}


# ---------------------------------------------------------------- category strategy (SPD-07)
def _supply_risk(session: Session, category: str, shares: dict) -> tuple[Decimal, dict]:
    """0–10: criticality (direct vs indirect), concentration (HHI), single qualified source, worst supplier tier and
    the supplier twin's late-delivery probability. Every factor is returned as evidence."""
    node = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == category)).scalar_one_or_none()
    root = node
    while root is not None and root.parent_code:
        root = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == root.parent_code)).scalar_one_or_none()
    direct = root is None or root.code == "DIRECT"
    statuses = session.execute(select(SupplierCategoryStatus.status).where(SupplierCategoryStatus.category == category)).scalars().all()
    qualified = sum(1 for s in statuses if s in ("QUALIFIED", "PREFERRED"))
    total = sum(shares.values()) or 1
    hhi = sum((Decimal(v) * 100 / total) ** 2 for v in shares.values())
    tiers = [s.risk_tier for s in session.execute(select(Supplier).where(Supplier.id.in_(list(shares)))).scalars() if s.risk_tier]
    twins = session.execute(select(TwinSnapshot.late_delivery_prob).where(TwinSnapshot.category == category)).scalars().all()
    factors = {
        "criticality": Decimal(2) if direct else Decimal("0.5"),
        "concentration": (hhi / 10000 * (Decimal("2.5") if direct else Decimal("1.5"))).quantize(Decimal("0.01")),
        "singleSource": Decimal(2) if direct and qualified <= 1 else Decimal(0),
        "supplierTier": Decimal("1.5") if "HIGH" in tiers else Decimal("0.5") if "MEDIUM" in tiers else Decimal(0),
        "lateDelivery": (Decimal(str(max(twins))) * 6).quantize(Decimal("0.01")) if twins else Decimal(0),
    }
    risk = min(Decimal(10), sum(factors.values())).quantize(Decimal("0.01"))
    return risk, {"direct": direct, "qualifiedSuppliers": qualified, "hhi": int(hhi), "riskTiers": tiers,
                  "maxLateProb": str(max(twins)) if twins else None, "factors": {k: str(v) for k, v in factors.items()}}


def generate_plans(session: Session, fiscal_year: str, owner_id: uuid.UUID) -> list[CategoryPlan]:
    periods = _window(session, 12)
    rows = session.execute(select(SpendCubeSummary.category, SpendCubeSummary.supplier_id, func.sum(SpendCubeSummary.amount_group_minor)).where(
        SpendCubeSummary.period.in_(periods), SpendCubeSummary.addressable.is_(True), SpendCubeSummary.category != "UNCLASSIFIED")
        .group_by(SpendCubeSummary.category, SpendCubeSummary.supplier_id)).all()
    by_cat = defaultdict(dict)
    for category, supplier_id, amount in rows:
        by_cat[category][supplier_id] = int(amount)
    total = sum(sum(v.values()) for v in by_cat.values()) or 1
    largest = max((sum(v.values()) for v in by_cat.values()), default=1)
    projection = {s["category"]: s["next12Minor"] for s in forecast(session)["series"]}
    out = []
    for category, shares in by_cat.items():
        spend = sum(shares.values())
        impact = (Decimal(math.sqrt(spend / largest)) * 10).quantize(Decimal("0.01"))
        risk, evidence = _supply_risk(session, category, shares)
        quadrant = ("STRATEGIC" if risk >= 4 else "LEVERAGE") if impact >= 5 else ("BOTTLENECK" if risk >= 4 else "NON_CRITICAL")
        plan = session.execute(select(CategoryPlan).where(CategoryPlan.category == category, CategoryPlan.fiscal_year == fiscal_year)).scalar_one_or_none()
        if plan is not None and plan.status == "APPROVED":
            continue
        # Budget from the spend forecast; fall back to trailing spend when the forecast window is thin (e.g. right after go-live).
        projected = projection.get(category, 0)
        budget, basis = (projected, "spend forecast (next 12 months)") if projected >= spend / 2 else (spend, "trailing 12-month spend")
        values = dict(spend_minor=spend, profit_impact=impact, supply_risk=risk, kraljic=quadrant,
                      evidence={**evidence, "spendSharePct": _pct(spend, total), "window": [periods[0], periods[-1]], "budgetBasis": basis},
                      levers=LEVERS[quadrant], waves=WAVES[quadrant], budget_minor=budget,
                      savings_target_minor=int(Decimal(budget) * TARGET_PCT[quadrant] / 100))
        if plan is None:
            plan = CategoryPlan(tenant_id=session.info["principal"].tenant_id, number=next_number(session, "CATEGORY_PLAN"), category=category,
                                fiscal_year=fiscal_year, owner_id=owner_id, created_by=owner_id, **values)
            session.add(plan)
        else:
            for k, v in values.items():
                setattr(plan, k, v)
        out.append(plan)
    session.flush()
    for plan in out:
        audit.record(session, "CATEGORY_PLAN", plan.id, "GENERATED", object_ref=plan.number,
                     after={"category": plan.category, "kraljic": plan.kraljic, "impact": plan.profit_impact, "risk": plan.supply_risk})
    return out


def approve_plan(session: Session, plan: CategoryPlan, comment: Optional[str]) -> CategoryPlan:
    p = principal(session)
    if not set(p.roles) & {"PROCUREMENT_HEAD", "CPO"}:
        raise Problem(403, "FORBIDDEN", "Category plans are approved by the procurement head or CPO", rule_ref="M01")
    if plan.owner_id == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The plan owner cannot approve their own category plan", rule_ref="M01")
    if plan.status != "DRAFT":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{plan.number} is {plan.status}")
    plan.status, plan.approved_by, plan.approved_at = "APPROVED", p.user_id, clock.now()
    audit.record(session, "CATEGORY_PLAN", plan.id, "APPROVED", object_ref=plan.number, reason=comment,
                 after={"budgetMinor": plan.budget_minor, "savingsTargetMinor": plan.savings_target_minor})
    return plan


def get_plan(session: Session, ref: str) -> CategoryPlan:
    plan = session.execute(select(CategoryPlan).where((CategoryPlan.number == ref) | (CategoryPlan.category == ref))
                           .order_by(CategoryPlan.fiscal_year.desc())).scalars().first()
    if plan is None:
        raise not_found("Category plan", ref)
    return plan
