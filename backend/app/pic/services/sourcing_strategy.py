"""Sourcing Strategy Agent (L1, blueprint §25): recommends event type, invitees and scoring weights.

Runs over approved requisition lines that have no source of supply (buyer queue, source determination
step 5). Invitees are only suppliers Qualified, Preferred or Conditional for the category (M05 rule),
ranked by the latest scorecard OTIF and the supplier twin's trust score.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import CategoryPlan, PrLine, Requisition, Scorecard, Supplier, SupplierCategoryStatus, TwinSnapshot
from app.pic.platform import agents, rules
from app.pic.platform.money import line_amount

WEIGHTS = {
    "STRATEGIC": {"PRICE": 40, "QUALITY": 30, "DELIVERY": 20, "CAPACITY": 10},
    "LEVERAGE": {"PRICE": 60, "QUALITY": 20, "DELIVERY": 20},
    "BOTTLENECK": {"PRICE": 25, "QUALITY": 25, "DELIVERY": 30, "CAPACITY": 20},
    "NON_CRITICAL": {"PRICE": 70, "DELIVERY": 30},
}


def recommend_for_line(session: Session, pr: Requisition, line: PrLine):
    category = line.category or line.material_group
    plan = session.execute(select(CategoryPlan).where(CategoryPlan.category == category).order_by(CategoryPlan.fiscal_year.desc())).scalars().first()
    quadrant = plan.kraljic if plan else ("NON_CRITICAL" if line.purchase_type in ("EXPENSE",) else "LEVERAGE")
    candidates = []
    for status, supplier in session.execute(select(SupplierCategoryStatus.status, Supplier).join(Supplier, Supplier.id == SupplierCategoryStatus.supplier_id)
                                            .where(SupplierCategoryStatus.category == category,
                                                   SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")),
                                                   Supplier.status != "BLOCKED")).all():
        card = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier.id).order_by(Scorecard.period.desc())).scalars().first()
        twin = session.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier.id, TwinSnapshot.category == category)
                               .order_by(TwinSnapshot.as_of.desc())).scalars().first()
        score = (card.otif_pct if card and card.otif_pct is not None else Decimal(85)) / 100 + (twin.trust_score if twin else Decimal("0.5"))
        candidates.append({"supplier": supplier.code, "name": supplier.legal_name, "status": status, "score": str(score.quantize(Decimal("0.01"))),
                           "waiverNeeded": status == "CONDITIONAL"})
    candidates.sort(key=lambda c: (c["waiverNeeded"], -Decimal(c["score"])))
    value = line_amount(line.qty, line.price_est_minor)
    quote_policy = rules.resolve(session, "QUOTE-POLICY").body
    if line.item_type == "SERVICE" or line.purchase_type == "SERVICE":
        event_type = "RFP"
    elif quadrant == "LEVERAGE" and len(candidates) >= 3 and value > quote_policy["oneQuoteBelow"]:
        event_type = "REVERSE_AUCTION"
    elif not candidates:
        event_type = "RFI"
    else:
        event_type = "RFQ"
    invitees = candidates[:5]
    rationale = (f"{category} is {quadrant.replace('_', '-').lower()} ({'category plan ' + plan.number if plan else 'no approved category plan'}); "
                 f"{len(candidates)} eligible supplier(s). "
                 + ("No qualified supplier exists: start with an RFI and qualification." if not candidates else
                    f"Invite {', '.join(c['supplier'] for c in invitees)}" + ("; conditional suppliers need a waiver." if any(c["waiverNeeded"] for c in invitees) else ".")))
    return agents.recommend(
        session, "SOURCING_STRATEGY", object_type="REQUISITION", object_id=pr.id, object_ref=pr.number, dedup_key=f"{pr.number}/{line.line_no}",
        title=f"{pr.number}/{line.line_no}: {event_type.replace('_', ' ').title()} for {line.description[:60]}",
        rationale=rationale,
        proposal={"eventType": event_type, "category": category, "kraljic": quadrant, "invitees": invitees, "weights": WEIGHTS[quadrant],
                  "requisition": pr.number, "line": line.line_no, "valueMinor": value},
        candidate_role="CATEGORY_MANAGER", deep_link=f"/pic/sourcing/new?requisition={pr.number}&line={line.line_no}",
        value_at_risk_minor=value, evidence=[c["supplier"] for c in invitees], confidence=0.7 if candidates else 0.5)


def recommend_all(session: Session) -> list:
    out = []
    for line, pr in session.execute(select(PrLine, Requisition).join(Requisition, Requisition.id == PrLine.requisition_id).where(
            Requisition.status.in_(("APPROVED", "PARTIALLY_ORDERED")), PrLine.sourcing_status == "OPEN")).all():
        determination = line.source_determination or {}
        if determination.get("allocations"):
            continue
        rec = recommend_for_line(session, pr, line)
        if rec is not None:
            out.append(rec)
    return out
