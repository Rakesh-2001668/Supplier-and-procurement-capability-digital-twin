"""M01 spend governance: taxonomy classification, maverick rules and hits, concentration, contract compliance,
spend forecast and category strategy (blueprint §7, SPD-01..09).

Classification below the tenant threshold (default 0.80) goes to the steward queue; maverick rules are
configurable per tenant and every hit carries an owner and a disposition; intercompany spend is not addressable.
"""
import math
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import case, exists, func, select, text
from sqlalchemy.orm import Session

from app.pic.models import (
    AppUser, CatalogueItem, CategoryPlan, ClassificationReview, ContractLine, Contract, Invoice, InvoiceLine, MaverickHit, MaverickRule, PoLine,
    PurchaseOrder, SpendCommitmentSummary, SpendCubeSummary, SpendLine, SpendViewState, Supplier, SupplierCategoryStatus, Tenant, TaxonomyNode,
    TwinSnapshot,
)
from app.pic.platform import agents, audit, clock, rules
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, not_found
from app.pic.services import spend_cube, spend_scope
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
# Why a hit was accepted or dismissed (required for ACCEPTED_EXCEPTION and FALSE_POSITIVE; the free-text comment stays mandatory).
REASON_CODES = ("EMERGENCY_BREAKDOWN", "SOLE_SOURCE", "CONTRACT_NOT_LOADED", "SUPPLIER_CHANGE_PENDING", "CATALOGUE_GAP", "DATA_ERROR",
                "RULE_TOO_BROAD", "RULE_RETIRED", "OTHER")
SLA_DAYS = {"Critical": 3, "High": 5, "Medium": 10, "Low": 15}
ESCALATE_TO = {"CATEGORY_MANAGER": "PROCUREMENT_HEAD", "PROCUREMENT_HEAD": "CPO", "FINANCE_CONTROLLER": "CPO", "CPO": "CPO"}

# Governance parameters that are not in the SPEND-GOVERNANCE rule set of tenants created before the second pass fall back to these.
GOV_DEFAULTS = {
    "classificationThreshold": "0.80", "oneTimeVendorLimitMinor": 5 * 100_000 * 100, "aggregationMinSuppliers": 4, "aggregationSavingPct": "3",
    "fiscalYearStartMonth": 4,
    "fourEyesAboveMinor": 25 * 100_000 * 100,        # a reclassification of a line at or above this value (group currency) needs a second steward
    "reviewSlaDays": 5,                                # steward queue: days from creation to decision
    "bulkReclassifyMax": 500,                          # lines in one bulk reclassification
    "overInvoicedTolerancePct": "2",                   # OVER_INVOICED: invoiced above PO value by more than this
    "acceptExceptionLimitMinor": 1_000_000_000,        # an accepted maverick exception above this needs the procurement head or the CPO
    "requireReasonCode": True,                         # ACCEPTED_EXCEPTION / FALSE_POSITIVE need a reason code
    "staleFeedHours": 48, "fxMaxAgeDays": 10,          # data quality: cube older than this / FX rate older than this on the document date
    "paretoA": 80, "paretoB": 95,                      # cumulative spend % where class A / B suppliers end
    "tailSupplierSpendPct": 20,                        # the long tail: suppliers beyond (100 - this)% of cumulative spend
    "hhiHigh": 2500, "hhiModerate": 1500,
    "exportMaxRows": 50_000,
    "planMaxSavingsPct": "15",                         # a plan's savings target above this share of the category's addressable spend is refused
    "planRequiresSubmission": False,                   # True: a plan must be submitted (IN_APPROVAL) before it can be approved
    "planWaveMinDays": 7,
}

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


def gov(session: Session) -> dict:
    """The SPEND-GOVERNANCE rule body on top of the defaults (so a rule set from before the second pass keeps working)."""
    return {**GOV_DEFAULTS, **_rule(session).body}


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
    existing_rules = {r.code: r for r in session.execute(select(MaverickRule)).scalars()}
    for code, name, description, severity, owner in MAVERICK_RULES:
        rule = existing_rules.get(code)
        if rule is None:
            session.add(MaverickRule(tenant_id=tenant_id, code=code, name=name, description=description, severity=severity, owner_role=owner,
                                     sla_days=SLA_DAYS.get(severity, 10), escalate_role=ESCALATE_TO.get(owner, "CPO")))
        elif rule.escalate_role is None:
            rule.escalate_role = ESCALATE_TO.get(rule.owner_role, "CPO")
    session.flush()


def _nodes(session: Session) -> list[TaxonomyNode]:
    """The nodes a line can be classified into: categories (level 3) and, when a tenant defines them, commodities (level 4)."""
    return session.execute(select(TaxonomyNode).where(TaxonomyNode.level >= 3, TaxonomyNode.active.is_(True))).scalars().all()


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


def _line_value(line: SpendLine) -> int:
    """Value of the line in the group currency (document currency when no rate yet): the size that drives queue order and four-eyes."""
    value = line.amount_group_minor if line.amount_group_minor is not None else line.amount_minor
    return abs(int(value or 0))


def classify_line(session: Session, line: SpendLine, nodes: Optional[list] = None) -> Optional[str]:
    """Spend Classification Agent (L3): applies confident results, routes the rest to the steward queue. Credit and debit note lines
    inherit the classification of the invoice line they correct (a steward's decision on the invoice line moves them too)."""
    if line.document_type == "CREDIT_NOTE" or (line.document_type == "DEBIT_NOTE" and line.classification_confidence != Decimal("0")):
        return None  # a note line follows its invoice line; only a debit-note charge (confidence 0) is classified from its own text
    if line.classification_confidence is not None and line.classification_confidence >= Decimal("1.000"):
        return None  # classified from the material master
    if session.execute(select(ClassificationReview.id).where(ClassificationReview.spend_line_id == line.id)).first():
        return None
    settings = gov(session)
    threshold = Decimal(str(settings["classificationThreshold"]))
    category, confidence, alternatives = classify_text(session, line.description or line.material_group, line.supplier_id, nodes)
    allowed, reason = agents.guard(session, "SPEND_CLASSIFICATION", required_level="L3", scope="spend:read")
    auto = allowed and confidence >= threshold
    ref = agents.log_run(session, "SPEND_CLASSIFICATION", object_type="SPEND_LINE", object_id=line.id, object_ref=line.invoice_ref,
                         inputs={"description": line.description, "materialGroup": line.material_group},
                         evidence=[a["category"] for a in alternatives], output={"category": category, "confidence": str(confidence)},
                         confidence=float(confidence), action_taken="EXECUTED" if auto else "DRAFTED",
                         denial_reason=None if allowed else reason)
    if auto:
        _set_category(session, line, category, confidence)
        return "AUTO"
    session.add(ClassificationReview(tenant_id=line.tenant_id, spend_line_id=line.id, invoice_ref=line.invoice_ref,
                                     description=(line.description or line.material_group)[:300], proposed_category=category,
                                     confidence=confidence, alternatives=alternatives, agent_run_ref=ref, created_by=line.created_by,
                                     value_group_minor=_line_value(line), due_at=clock.now() + timedelta(days=int(settings["reviewSlaDays"]))))
    line.classification_confidence = confidence
    if line.category != "UNCLASSIFIED" and line.category not in {n.code for n in (nodes if nodes is not None else _nodes(session))}:
        # A free-text line's provisional category is its raw material group (e.g. SVC-TOOLING), not a taxonomy category:
        # it stays unclassified until the steward decides, instead of turning into a taxonomy node at the next refresh.
        line.category = "UNCLASSIFIED"
    return "REVIEW"


def _set_category(session: Session, line: SpendLine, category: str, confidence: Decimal) -> None:
    """Set the category of an invoice line and of every credit / debit note line that corrects it (their rows move with it, the cube
    re-materialises the affected periods because the lines are marked dirty), and re-derive addressability."""
    line.category, line.classification_confidence = category, confidence
    _apply_addressable(session, line)
    followers = session.execute(select(SpendLine).where(SpendLine.invoice_line_id == line.invoice_line_id, SpendLine.id != line.id)).scalars().all()
    for other in followers:
        other.category, other.classification_confidence, other.addressable = category, confidence, line.addressable


def addressable_for(session: Session, supplier: Optional[Supplier], category: str) -> bool:
    """BP 7.4: intercompany suppliers and non-addressable taxonomy segments are not addressable spend."""
    if supplier is not None and (supplier.segment or "").upper() == "INTERCOMPANY":
        return False
    if category == "IC-TRANSFER":
        return False
    cache = session.info.setdefault("spend_addressable", {})
    if category not in cache:
        node = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == category)).scalar_one_or_none()
        root, seen = node, set()
        while root is not None and root.parent_code and root.code not in seen:
            seen.add(root.code)
            root = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == root.parent_code)).scalar_one_or_none()
        cache[category] = bool(root.addressable if root else True)
    return cache[category]


def _apply_addressable(session: Session, line: SpendLine) -> None:
    line.addressable = addressable_for(session, session.get(Supplier, line.supplier_id), line.category)


def ensure_node(session: Session, tenant_id: uuid.UUID, category: str) -> None:
    """A category that comes from the material master and has no taxonomy node yet gets one under DIRECT (steward renames it later)."""
    if not category or category == "UNCLASSIFIED":
        return
    if session.execute(select(TaxonomyNode.id).where(TaxonomyNode.code == category)).first():
        return
    words = [w for w in re.split(r"[-_ ]+", category.lower()) if len(w) > 2]
    session.add(TaxonomyNode(tenant_id=tenant_id, code=category, parent_code="DIRECT", level=3, name=category.replace("-", " ").title(),
                             keywords=words, addressable=True))
    session.flush()
    session.info.pop("spend_addressable", None)


def learnable_keyword(session: Session, keyword: str, category: str) -> str:
    """A keyword a steward teaches the classifier: a whole word of 4+ letters that no other category already owns."""
    word = (keyword or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9\-]{3,39}", word):
        raise Problem(422, "INVALID_KEYWORD", "A keyword is one word of 4-40 letters or digits (a phrase is added by the taxonomy administrator)", rule_ref="M01")
    for node in session.execute(select(TaxonomyNode).where(TaxonomyNode.keywords.any(word))).scalars():
        if node.code != category:
            raise Problem(409, "KEYWORD_CONFLICT", f"'{word}' already belongs to {node.code}; two categories cannot own the same keyword", rule_ref="M01")
    return word


def _lock(session: Session, obj) -> None:
    """Row lock on the object a command changes, then the current state is read: two people deciding the same review, hit or plan at once are
    serialised, and the second one sees the first one's decision (409) instead of overwriting it."""
    session.refresh(obj, with_for_update=True)


def decide_review(session: Session, review: ClassificationReview, category: str, comment: Optional[str] = None, *,
                  learn_keyword: Optional[str] = None, reason: Optional[str] = None) -> ClassificationReview:
    """A steward accepts the agent's proposal or reclassifies. Reclassifying a line at or above ``fourEyesAboveMinor`` needs two different
    stewards who choose the same category (the first decision parks the review as PENDING_SECOND; a different category from the second
    steward reopens it). ``learn_keyword`` teaches the classifier a word for the chosen category. The cube re-materialises the periods of
    the line (and of its credit / debit notes) because the lines change."""
    p = principal(session)
    if not set(p.roles) & {"CATEGORY_MANAGER", "MDM_STEWARD", "PROCUREMENT_HEAD"}:
        raise Problem(403, "FORBIDDEN", "Spend classification is reviewed by a category manager or data steward", rule_ref="M01")
    _lock(session, review)
    if review.status not in ("OPEN", "PENDING_SECOND"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"Review for {review.invoice_ref} is already {review.status}")
    node = session.execute(select(TaxonomyNode).where(TaxonomyNode.code == category, TaxonomyNode.level >= 3, TaxonomyNode.active.is_(True))).scalar_one_or_none()
    if node is None:
        raise Problem(422, "UNKNOWN_CATEGORY", f"{category} is not a taxonomy category")
    line = session.get(SpendLine, review.spend_line_id)
    if not spend_scope.allows(session, plant=line.plant, company_code=line.company_code, category=line.category, supplier_id=line.supplier_id,
                              cost_object=line.cost_object, cost_object_type=line.cost_object_type):
        raise Problem(403, "FORBIDDEN", "This line is outside your spend scope", rule_ref="ABAC")
    settings = gov(session)
    reclass = category != review.proposed_category
    value = review.value_group_minor if review.value_group_minor is not None else _line_value(line)
    keyword = learnable_keyword(session, learn_keyword, category) if learn_keyword else None
    if reclass and value >= int(settings["fourEyesAboveMinor"]):
        if review.status == "OPEN":
            review.status, review.first_category, review.first_decided_by, review.first_decided_at = "PENDING_SECOND", category, p.user_id, clock.now()
            review.decision_reason = reason
            audit.record(session, "SPEND_LINE", line.id, "CLASSIFICATION_PROPOSED", object_ref=line.invoice_ref,
                         before={"category": line.category}, after={"category": category, "review": "PENDING_SECOND", "valueMinor": value},
                         reason=comment or reason, ai_ref=review.agent_run_ref)
            return review
        if review.first_decided_by == p.user_id:
            raise Problem(409, "SOD_CONFLICT", "A reclassification above the four-eyes value needs a second steward; you made the first decision", rule_ref="M01")
        if review.first_category != category:
            audit.record(session, "SPEND_LINE", line.id, "CLASSIFICATION_DISAGREED", object_ref=line.invoice_ref,
                         after={"first": review.first_category, "second": category}, reason=comment or reason)
            review.status, review.first_category, review.first_decided_by, review.first_decided_at = "OPEN", None, None, None
            return review
    before = line.category
    _set_category(session, line, category, Decimal("1.000"))
    review.status = "ACCEPTED" if not reclass else "RECLASSIFIED"
    review.decided_category, review.decided_by, review.decided_at = category, p.user_id, clock.now()
    review.decision_reason = reason or review.decision_reason
    if keyword:
        _teach(session, node, keyword, review)
    agents.feedback(session, review.agent_run_ref, "ACCEPTED" if review.status == "ACCEPTED" else "REJECTED")
    audit.record(session, "SPEND_LINE", line.id, "CLASSIFIED", object_ref=line.invoice_ref, before={"category": before},
                 after={"category": category, "review": review.status, **({"keyword": keyword} if keyword else {}),
                        **({"secondSteward": str(p.user_id), "firstSteward": str(review.first_decided_by)} if review.first_decided_by else {})},
                 reason=comment, ai_ref=review.agent_run_ref)
    return review


def _teach(session: Session, node: TaxonomyNode, keyword: str, review: ClassificationReview) -> None:
    if keyword not in (node.keywords or []):
        node.keywords = [*(node.keywords or []), keyword]
    review.learned_keyword = keyword
    _KEYWORD_PATTERNS.pop(keyword, None)
    audit.record(session, "TAXONOMY_NODE", node.id, "KEYWORD_LEARNED", object_ref=node.code, after={"keyword": keyword, "review": review.invoice_ref},
                 reason="taught by a steward from a reviewed line")


# ---------------------------------------------------------------- maverick rules
def _owner(session: Session, role: str, category: str) -> Optional[uuid.UUID]:
    if role == "CATEGORY_MANAGER":
        plan = session.execute(select(CategoryPlan.owner_id).where(CategoryPlan.category == category)).scalar()
        if plan:
            return plan
    return session.execute(select(AppUser.id).where(AppUser.roles.any(role), AppUser.active.is_(True)).order_by(AppUser.email)).scalar()


def _local_date(session: Session, tenant_id: uuid.UUID, moment: datetime):
    """The business date of a timestamp in the tenant's time zone (a PO created at 01:00 IST belongs to that IST day, not the UTC one)."""
    from zoneinfo import ZoneInfo
    zone = session.info.get("spend_zone")
    if zone is None:
        tenant = session.get(Tenant, tenant_id)
        zone = session.info["spend_zone"] = ZoneInfo(tenant.timezone if tenant is not None and tenant.timezone else "Asia/Kolkata")
    return moment.astimezone(zone).date()


COVERING_STATUSES = ("ACTIVE", "EXPIRING", "EXPIRED", "CLOSED")


def _po_flags(session: Session, line: SpendLine, po_line: PoLine, po: PurchaseOrder, inv_line: Optional[InvoiceLine], invoice: Optional[Invoice],
              settings: dict) -> set:
    """The document-based maverick rules of BP 7.2 plus the three payment-control rules, evaluated on the order and the invoice."""
    flags: set = set()
    invoice_date = (invoice.invoice_date if invoice is not None else line.document_date)
    po_date = _local_date(session, line.tenant_id, po.created_at)
    if invoice_date is not None and po_date > invoice_date:
        flags.add("PO_AFTER_INVOICE")
    if po_line.item_type == "FREE_TEXT" and session.execute(select(CatalogueItem.id).where(
            CatalogueItem.material_group == po_line.material_group, CatalogueItem.active.is_(True))).first():
        flags.add("NON_CATALOGUE")
    if po_line.material_id is not None and po_line.contract_line_id is None and session.execute(
            select(ContractLine.id).join(Contract, Contract.id == ContractLine.contract_id).where(
                ContractLine.material_id == po_line.material_id, (ContractLine.plant == po_line.plant) | (ContractLine.plant == ""),
                Contract.valid_from <= po_date, Contract.valid_to >= po_date, Contract.status.in_(COVERING_STATUSES))).first():
        flags.add("OFF_CONTRACT")
    if any(f.get("code") == "SPLIT_PATTERN" for f in (po.risk_factors or [])):
        flags.add("SPLIT_PO")
    if po_line.price_deviation:
        flags.add("OFF_CONTRACT_PRICE")
    # paid without proof of receipt: goods lines invoiced beyond what was received, service lines beyond the approved service entries
    if po_line.gr_required and not po_line.ses_required and Decimal(po_line.invoiced_qty or 0) > Decimal(po_line.received_qty or 0):
        flags.add("NO_GOODS_RECEIPT")
    elif po_line.ses_required and int(po_line.invoiced_minor or 0) > int(po_line.ses_approved_minor or 0):
        flags.add("NO_GOODS_RECEIPT")
    if po.released_at is None or po.status in ("DRAFT", "IN_APPROVAL"):
        flags.add("PO_NOT_APPROVED")
    tolerance = Decimal(str(settings["overInvoicedTolerancePct"]))
    if po_line.net_minor > 0 and Decimal(po_line.invoiced_minor or 0) > Decimal(po_line.net_minor) * (1 + tolerance / 100):
        flags.add("OVER_INVOICED")
    return flags


def evaluate_line(session: Session, line: SpendLine, active: Optional[dict] = None) -> list[str]:
    """Apply the tenant's maverick rules; extra flags are written back so the cube's maverick share agrees. Only rules that are active
    add a flag or a hit. Credit and debit note lines carry the flags of their invoice line but raise no hits of their own."""
    if line.document_type != "INVOICE":
        return []
    settings = gov(session)
    if active is None:   # the rules in force on the day of the document (effective-dated versions of rule set MAVERICK-RULES)
        from app.pic.services import spend_workflow
        active = {c: r for c, r in spend_workflow.effective_rules(session, line.document_date or clock.today()).items() if r.active}
    flags = set(line.maverick_flags or [])
    po_line = session.execute(select(PoLine).where(PoLine.id == line.po_line_id)).scalar_one_or_none() if line.po_line_id else None
    if po_line is not None:
        po = session.get(PurchaseOrder, po_line.po_id)
        inv_line = session.get(InvoiceLine, line.invoice_line_id)
        invoice = session.get(Invoice, inv_line.invoice_id) if inv_line is not None else None
        if po is not None:
            flags |= {f for f in _po_flags(session, line, po_line, po, inv_line, invoice, settings) if f in active}
    group_value = _line_value(line)
    if line.addressable and group_value > int(settings["oneTimeVendorLimitMinor"]) and line.category not in ("UNCLASSIFIED",) and "ONE_TIME_VENDOR" in active:
        qualified = session.execute(select(SupplierCategoryStatus.id).where(
            SupplierCategoryStatus.supplier_id == line.supplier_id, SupplierCategoryStatus.category == line.category,
            SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")))).first()
        if not qualified:
            flags.add("ONE_TIME_VENDOR")
    line.maverick_flags = sorted(flags)
    created = []
    for code in line.maverick_flags:
        rule = active.get(code)
        if rule is None or session.execute(select(MaverickHit.id).where(MaverickHit.rule_code == code, MaverickHit.spend_line_id == line.id)).first():
            continue
        session.add(MaverickHit(
            tenant_id=line.tenant_id, number=next_number(session, "MAVERICK_HIT"), rule_code=code, spend_line_id=line.id, invoice_ref=line.invoice_ref,
            po_ref=line.po_ref, supplier_id=line.supplier_id, category=line.category, amount_minor=line.amount_minor, amount_group_minor=group_value,
            owner_role=rule.owner_role, owner_id=_owner(session, rule.owner_role, line.category), created_by=line.created_by,
            due_at=clock.now() + timedelta(days=int(rule.sla_days or 10)), savings_at_risk_minor=_at_risk(code, line, po_line, _group_ccy(session))))
        created.append(code)
    session.flush()
    return created


def _group_ccy(session: Session) -> str:
    cached = session.info.get("spend_group_ccy")
    if cached is None:
        cached = session.info["spend_group_ccy"] = spend_cube._group_currency(session)
    return cached


def _at_risk(code: str, line: SpendLine, po_line: Optional[PoLine], group_ccy: str) -> int:
    """What the hit puts at risk, in the group currency: the price paid above the contract / standard price for the price rules, the
    amount invoiced above the order for OVER_INVOICED, nothing for the process rules (they are not a price)."""
    rate = Decimal(1) if line.currency == group_ccy else (line.fx_rate or Decimal(0))
    if code in ("OFF_CONTRACT", "OFF_CONTRACT_PRICE"):
        return int(Decimal(line.price_variance_minor or 0) * rate)
    if code == "OVER_INVOICED" and po_line is not None and po_line.net_minor:
        return int(Decimal(min(max(0, int(po_line.invoiced_minor) - int(po_line.net_minor)), abs(line.amount_minor))) * rate)
    return 0


def dispose(session: Session, hit: MaverickHit, disposition: str, comment: str, *, reason_code: Optional[str] = None) -> MaverickHit:
    """Decide a hit: ACCEPTED_EXCEPTION and FALSE_POSITIVE need a reason code; accepting an exception above the tenant's limit needs the
    procurement head or CPO; RECOVERY keeps the hit open until the recovery is booked (``resolve_recovery``)."""
    p = principal(session)
    if disposition not in DISPOSITIONS:
        raise Problem(422, "INVALID_DISPOSITION", f"Use one of {', '.join(DISPOSITIONS)}")
    if not comment or len(comment.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "Every maverick disposition needs a comment", rule_ref="M01")
    if hit.owner_id != p.user_id and not set(p.roles) & (DISPOSERS - {"CATEGORY_MANAGER"}) and hit.owner_role not in p.roles:
        raise Problem(403, "FORBIDDEN", f"{hit.number} is owned by {hit.owner_role.replace('_', ' ').lower()}", rule_ref="M01")
    line = session.get(SpendLine, hit.spend_line_id)
    if line is not None and not spend_scope.allows(session, plant=line.plant, company_code=line.company_code, category=line.category,
                                                   supplier_id=line.supplier_id, cost_object=line.cost_object, cost_object_type=line.cost_object_type):
        raise Problem(403, "FORBIDDEN", f"{hit.number} is outside your spend scope", rule_ref="ABAC")
    _lock(session, hit)
    if hit.status != "OPEN":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{hit.number} is already {hit.status}")
    settings = gov(session)
    if disposition in ("ACCEPTED_EXCEPTION", "FALSE_POSITIVE") and settings["requireReasonCode"]:
        if reason_code not in REASON_CODES:
            raise Problem(422, "REASON_CODE_REQUIRED", f"{disposition} needs a reason code: {', '.join(REASON_CODES)}", rule_ref="M01")
    elif reason_code is not None and reason_code not in REASON_CODES:
        raise Problem(422, "INVALID_REASON_CODE", f"Use one of {', '.join(REASON_CODES)}", rule_ref="M01")
    value = int(hit.amount_group_minor if hit.amount_group_minor is not None else hit.amount_minor)
    if disposition == "ACCEPTED_EXCEPTION" and value > int(settings["acceptExceptionLimitMinor"]) and not set(p.roles) & {"PROCUREMENT_HEAD", "CPO"}:
        raise Problem(403, "FORBIDDEN", "Accepting an exception on this amount needs the procurement head or the CPO", rule_ref="M01")
    hit.status = "RECOVERY_OPEN" if disposition == "RECOVERY" else "DISPOSED"
    hit.disposition, hit.comment, hit.disposed_by, hit.disposed_at, hit.reason_code = disposition, comment, p.user_id, clock.now(), reason_code
    audit.record(session, "MAVERICK_HIT", hit.id, "DISPOSED", object_ref=hit.number, after={"disposition": disposition, "rule": hit.rule_code,
                                                                                          "reasonCode": reason_code}, reason=comment)
    return hit


def resolve_recovery(session: Session, hit: MaverickHit, recovered_minor: int, note: str) -> MaverickHit:
    """Close a RECOVERY: the supplier credited or refunded ``recovered_minor`` (group currency); the hit becomes RESOLVED."""
    p = principal(session)
    _lock(session, hit)
    if hit.status != "RECOVERY_OPEN":
        raise Problem(409, "ILLEGAL_TRANSITION", f"{hit.number} is {hit.status}; only a hit in recovery can be resolved")
    if isinstance(recovered_minor, bool) or not isinstance(recovered_minor, int) or recovered_minor < 0:
        raise Problem(422, "INVALID_AMOUNT", "recovered_minor must be an amount of zero or more (minor units)", rule_ref="M01")
    value = int(hit.amount_group_minor if hit.amount_group_minor is not None else hit.amount_minor)
    if recovered_minor > abs(value):
        raise Problem(422, "RECOVERY_EXCEEDS_HIT", f"{hit.number} is for {value}; the recovery cannot be larger", rule_ref="M01")
    if not note or len(note.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "Say how the recovery was made (credit note, refund, set-off)", rule_ref="M01")
    if hit.owner_id != p.user_id and not set(p.roles) & {"PROCUREMENT_HEAD", "CPO", "FINANCE_CONTROLLER"} and hit.owner_role not in p.roles:
        raise Problem(403, "FORBIDDEN", f"{hit.number} is owned by {hit.owner_role.replace('_', ' ').lower()}", rule_ref="M01")
    hit.status, hit.recovered_minor, hit.resolved_at, hit.resolved_by, hit.resolution_note = "RESOLVED", recovered_minor, clock.now(), p.user_id, note
    audit.record(session, "MAVERICK_HIT", hit.id, "RECOVERY_RESOLVED", object_ref=hit.number, after={"recoveredMinor": recovered_minor}, reason=note)
    return hit


def escalate_overdue(session: Session, now=None) -> list[MaverickHit]:
    """SLA: an OPEN hit past its due date moves one escalation level up (owner role -> the rule's escalation role) and gets a new due date
    of half the SLA; at most two escalations. Returns the hits escalated now. Idempotent for a given instant."""
    from app.pic.services import spend_workflow
    now = now or clock.now()
    rules_by_code = spend_workflow.effective_rules(session)
    out = []
    for hit in session.execute(select(MaverickHit).where(MaverickHit.status == "OPEN", MaverickHit.due_at.is_not(None), MaverickHit.due_at < now,
                                                          MaverickHit.escalation_level < 2).order_by(MaverickHit.due_at)).scalars():
        rule = rules_by_code.get(hit.rule_code)
        target = (rule.escalate_role if rule and rule.escalate_role else ESCALATE_TO.get(hit.owner_role, "CPO")) if hit.escalation_level == 0 else "CPO"
        hit.escalation_level, hit.escalated_at, hit.escalated_to_role = hit.escalation_level + 1, now, target
        hit.owner_role = target
        hit.owner_id = _owner(session, target, hit.category)
        hit.due_at = now + timedelta(days=max(1, int((rule.sla_days if rule else 10) // 2)))
        audit.record(session, "MAVERICK_HIT", hit.id, "ESCALATED", object_ref=hit.number, after={"level": hit.escalation_level, "to": target}, reason="SLA missed")
        out.append(hit)
    return out


def refresh(session: Session, tenant_id: uuid.UUID) -> dict:
    """Classify and evaluate every spend line that has not been processed yet (idempotent)."""
    ensure_taxonomy(session, tenant_id)
    from app.pic.services import spend_workflow
    nodes = _nodes(session)
    active = {c: r for c, r in spend_workflow.effective_rules(session).items() if r.active}
    out = {"auto": 0, "review": 0, "hits": 0}
    for line in session.execute(select(SpendLine).where(SpendLine.document_type == "INVOICE").order_by(SpendLine.period, SpendLine.invoice_ref)).scalars():
        result = classify_line(session, line, nodes)
        if result:
            out["auto" if result == "AUTO" else "review"] += 1
        out["hits"] += len(evaluate_line(session, line, active))
    return out


def after_spend_line(session: Session, line: SpendLine) -> None:
    session.flush()
    if line.classification_confidence is not None and line.classification_confidence >= Decimal("1.000"):
        ensure_node(session, line.tenant_id, line.category)
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


_pct = spend_cube._pct   # one rounding rule (half up, one decimal) for every percentage of the module; a base of zero or less gives 0


# The cube engine (summary tables, refresh, filters) lives in services/spend_cube.py; these are its public entry points.
refresh_spend_views = spend_cube.refresh_spend_views
cube = spend_cube.cube
commitments = spend_cube.commitments
CubeFilter = spend_cube.CubeFilter
CUBE_DIMENSIONS = spend_cube.ALL_DIMENSIONS


def _in_window(periods: list[str]):
    return SpendCubeSummary.period.between(periods[0], periods[-1])


def _scoped_to_line(session: Session, query, column):
    """Keep only rows (hits, reviews) whose spend line is inside the reader's scope."""
    exists_ = spend_scope.line_exists(session, column)
    return query.where(exists_) if exists_ is not None else query


def portfolio(session: Session, period_from: str, period_to: str, plant: Optional[str] = None) -> dict:
    """Spend totals and shares between two periods (inclusive) from the cube summary: total, addressable, under management,
    contracted, maverick, auto-classified lines, counts and price variance (group currency). Restricted to the reader's scope (and the
    plant, when given): the totals are computed on the restricted rows, never trimmed afterwards."""
    C = SpendCubeSummary
    group = C.amount_group_minor
    qualified = exists().where(SupplierCategoryStatus.supplier_id == C.supplier_id, SupplierCategoryStatus.category == C.category,
                               SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")))
    # Under management: contract or catalogue price, or bought without maverick flags from a qualified supplier
    # in a category that has an approved category plan.
    managed_categories = list(session.execute(select(CategoryPlan.category).where(CategoryPlan.status == "APPROVED")).scalars())
    managed_clause = C.contracted.is_(True) | (C.maverick.is_(False) & C.category.in_(managed_categories or [""]) & qualified)
    addr = C.addressable.is_(True)
    where = [C.period.between(period_from, period_to), *spend_scope.where(session, C)]
    if plant:
        where.append(C.plant == plant)
    t = session.execute(select(
        func.coalesce(func.sum(group), 0), func.coalesce(func.sum(case((addr, group), else_=0)), 0),
        func.coalesce(func.sum(case((addr & managed_clause, group), else_=0)), 0),
        func.coalesce(func.sum(case((addr & C.contracted.is_(True), group), else_=0)), 0),
        func.coalesce(func.sum(case((addr & C.maverick.is_(True), group), else_=0)), 0),
        func.coalesce(func.sum(C.auto_classified_lines), 0), func.coalesce(func.sum(C.invoices), 0), func.coalesce(func.sum(C.pos), 0),
        func.coalesce(func.sum(C.price_variance_group_minor), 0), func.coalesce(func.sum(C.price_variance_last_group_minor), 0),
        func.coalesce(func.sum(C.fx_missing_lines), 0), func.coalesce(func.sum(C.lines), 0),
    ).where(*where)).one()
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
    decided = {k: v for k, v in session.execute(_scoped_to_line(session, select(ClassificationReview.status, func.count()).group_by(
        ClassificationReview.status), ClassificationReview.spend_line_id)).all()}
    accuracy_den = auto + decided.get("ACCEPTED", 0) + decided.get("RECLASSIFIED", 0)
    recent, prior = periods[-3:], periods[-6:-3]
    moved = session.execute(select(
        C.category, func.coalesce(func.sum(case((C.period.in_(recent), group), else_=0)), 0),
        func.coalesce(func.sum(case((C.period.in_(prior), group), else_=0)), 0)).where(
        C.period.in_(recent + prior), *spend_scope.where(session, C)).group_by(C.category)).all()
    top_movers = sorted(({"category": c, "last3Minor": int(a), "prior3Minor": int(b), "changePct": _pct(a - b, b) if b > 0 else None}
                         for c, a, b in moved if a or b), key=lambda x: (-abs(x["last3Minor"] - x["prior3Minor"]), x["category"]))[:6]
    spend_cube.ensure_commitments_fresh(session)
    committed = session.execute(select(func.coalesce(func.sum(SpendCommitmentSummary.committed_group_minor), 0)).where(
        *spend_scope.where(session, SpendCommitmentSummary))).scalar() if session.execute(
        select(SpendViewState.id).where(SpendViewState.view_name == "spend_commitment_summary")).first() else None
    opps = opportunities(session, periods)
    open_hits = session.execute(_scoped_to_line(session, select(func.count()).select_from(MaverickHit).where(MaverickHit.status == "OPEN"),
                                                MaverickHit.spend_line_id)).scalar()
    return {"periods": [periods[0], periods[-1]], "totalMinor": total, "addressableMinor": addr_total, "addressablePct": _pct(addr_total, total),
            "underManagementPct": _pct(p["managedMinor"], addr_total), "contractedPct": _pct(p["contractedMinor"], addr_total),
            "maverickPct": _pct(p["maverickMinor"], addr_total),
            "classificationAccuracyPct": _pct(auto + decided.get("ACCEPTED", 0), accuracy_den) if accuracy_den else None,
            "openReviews": decided.get("OPEN", 0) + decided.get("PENDING_SECOND", 0),
            "openMaverickHits": open_hits,
            "topMovers": top_movers, "opportunities": opps,
            "priceVarianceMinor": p["priceVarianceMinor"], "priceVarianceLastMinor": p["priceVarianceLastMinor"], "invoices": p["invoices"],
            "pos": p["pos"], "lines": p["lines"], "openCommitmentsMinor": int(committed) if committed is not None else None,
            "aggregationOpportunityMinor": sum(o.get("indicativeSavingMinor", 0) for o in opps if o["kind"] == "CONSOLIDATION"),
            "fxMissingLines": p["fxMissingLines"], "groupCurrency": spend_cube._group_currency(session), "freshness": freshness,
            "scope": spend_scope.of(session).describe() or None}


def opportunities(session: Session, periods: list[str]) -> list[dict]:
    """Contract-coverage, aggregation (many suppliers / plants for one category) and price-variance opportunities, from the cube."""
    C = SpendCubeSummary
    group = C.amount_group_minor
    settings = gov(session)
    min_suppliers, saving_pct = int(settings["aggregationMinSuppliers"]), Decimal(str(settings["aggregationSavingPct"]))
    scope = spend_scope.where(session, C)
    rows = session.execute(select(
        C.category, func.sum(group), func.coalesce(func.sum(case((C.contracted.is_(False), group), else_=0)), 0),
        func.count(func.distinct(C.parent_supplier_id)), func.count(func.distinct(C.plant)), func.coalesce(func.sum(C.price_variance_group_minor), 0))
        .where(_in_window(periods), C.addressable.is_(True), C.category != "UNCLASSIFIED", *scope).group_by(C.category)).all()
    by_supplier: dict[str, list[int]] = defaultdict(list)
    for category, amount in session.execute(select(C.category, func.sum(group)).where(
            _in_window(periods), C.addressable.is_(True), C.category != "UNCLASSIFIED", *scope).group_by(C.category, C.parent_supplier_id)):
        by_supplier[category].append(int(amount or 0))
    out = []
    for category, spend_, off, suppliers, plants, variance in rows:
        spend_, off, variance = int(spend_ or 0), int(off or 0), int(variance or 0)
        if spend_ <= 0:
            continue
        if off > spend_ * 0.4 and spend_ > 50 * 100_000 * 100:
            out.append({"category": category, "kind": "CONTRACT_COVERAGE", "valueMinor": off,
                        "text": f"{_pct(off, spend_)}% of spend is not on contract; run a sourcing event", "deepLink": "/pic/sourcing/new"})
        if suppliers >= min_suppliers or (plants >= 2 and suppliers >= 2):
            ranked = sorted(by_supplier[category], reverse=True)
            tail = sum(x for x in (ranked[3:] if len(ranked) > 3 else ranked[1:]) if x > 0)
            where = f"{suppliers} suppliers" + (f" across {plants} plants" if plants > 1 else "")
            out.append({"category": category, "kind": "CONSOLIDATION", "valueMinor": spend_,
                        "indicativeSavingMinor": int(Decimal(tail) * saving_pct / 100), "suppliers": suppliers, "plants": plants,
                        "text": f"{where} share this category; consolidate volume (tail spend {_pct(tail, spend_)}%)",
                        "deepLink": "/pic/spend?tab=suppliers"})
        if variance > 0:
            out.append({"category": category, "kind": "PRICE_VARIANCE", "valueMinor": variance,
                        "text": "Invoiced above contract or standard price; recover or renegotiate", "deepLink": "/pic/spend?tab=compliance"})
    return sorted(out, key=lambda o: (-o["valueMinor"], o["category"], o["kind"]))[:10]


def treemap(session: Session) -> dict:
    """SPD-02: taxonomy (segment -> family -> category -> commodity, as deep as the tenant defines it) with spend and drill to supplier."""
    periods = _window(session, 12)
    C = SpendCubeSummary
    nodes = {n.code: n for n in session.execute(select(TaxonomyNode)).scalars()}
    taxonomy = spend_cube._taxonomy(session)
    suppliers = {s.id: (s.code, s.legal_name) for s in session.execute(select(Supplier)).scalars()}
    rows = session.execute(select(C.category, C.supplier_id, func.sum(C.amount_group_minor), func.sum(C.lines))
                           .where(_in_window(periods), *spend_scope.where(session, C)).group_by(C.category, C.supplier_id)).all()
    root: dict = {"children": {}, "valueMinor": 0}
    for category, supplier_id, amount, count in rows:
        chain = spend_cube._chain(taxonomy, category) or [category]
        if len(chain) == 1 and chain[0] != "UNCLASSIFIED" and chain[0] not in nodes:
            chain = ["UNCLASSIFIED", category]
        level = root
        for code in chain:
            level = level["children"].setdefault(code, {"code": code, "name": nodes[code].name if code in nodes else code, "valueMinor": 0,
                                                        "children": {}, "suppliers": []})
            level["valueMinor"] += int(amount)
        code, name = suppliers.get(supplier_id, ("?", "Unknown supplier"))
        level["suppliers"].append({"supplier": code, "name": name, "valueMinor": int(amount), "lines": int(count)})

    def flatten(level):
        level["children"] = sorted((flatten(c) for c in level["children"].values()), key=lambda c: (-c["valueMinor"], c["code"]))
        level["suppliers"].sort(key=lambda x: (-x["valueMinor"], x["supplier"]))
        if not level["children"]:
            del level["children"]
        if not level["suppliers"]:
            del level["suppliers"]
        return level
    return {"periods": [periods[0], periods[-1]], "segments": sorted((flatten(c) for c in root["children"].values()),
                                                                     key=lambda c: (-c["valueMinor"], c["code"]))}


def hhi_of(shares: dict) -> Decimal:
    """Herfindahl-Hirschman index of a category on a 0-10,000 scale: the sum of squared percentage shares. Only suppliers with a positive
    net spend count (a supplier whose credits exceed its invoices has no share); an empty category has no index (0)."""
    positive = {k: v for k, v in shares.items() if v > 0}
    total = sum(positive.values())
    return sum((Decimal(v) * 100 / total) ** 2 for v in positive.values()) if total > 0 else Decimal(0)


def suppliers_view(session: Session, limit: int = 200) -> dict:
    """SPD-03: supplier ranking, HHI per category and duplicate-supplier clusters. Concentration is measured on the corporate parent (a
    group of child suppliers is one source); ``hhiChild`` is the same index on the child records. Amounts are in the group currency."""
    from app.pic.services import spend_workflow
    periods = _window(session, 12)
    C = SpendCubeSummary
    settings = gov(session)
    master = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    rows = session.execute(select(C.supplier_id, C.parent_supplier_id, C.category, func.sum(C.amount_group_minor))
                           .where(_in_window(periods), C.addressable.is_(True), *spend_scope.where(session, C))
                           .group_by(C.supplier_id, C.parent_supplier_id, C.category)).all()
    total = sum(int(r[3]) for r in rows if r[3] > 0) or 1
    by_supplier, by_cat, by_cat_child = defaultdict(int), defaultdict(dict), defaultdict(dict)
    for supplier_id, parent_id, category, amount in rows:
        by_supplier[supplier_id] += int(amount)
        by_cat[category][parent_id] = by_cat[category].get(parent_id, 0) + int(amount)
        by_cat_child[category][supplier_id] = by_cat_child[category].get(supplier_id, 0) + int(amount)
    categories_of = defaultdict(list)
    for category, m in by_cat_child.items():
        for sid in m:
            categories_of[sid].append(category)
    ranked = sorted(by_supplier.items(), key=lambda x: (-x[1], str(x[0])))
    ranking = [{"supplier": master[s].code if s in master else "?", "name": master[s].legal_name if s in master else "Unknown",
                "riskTier": master[s].risk_tier if s in master else None, "spendMinor": v, "sharePct": _pct(v, total),
                "parent": master[master[s].parent_supplier_id].code if s in master and master[s].parent_supplier_id in master else None,
                "categories": sorted(categories_of[s])} for s, v in ranked[:limit]]
    concentration = []
    for category, shares in by_cat.items():
        positive = {k: v for k, v in shares.items() if v > 0}
        cat_total = sum(positive.values())
        if cat_total <= 0:
            continue
        hhi = hhi_of(shares)
        top = max(positive.items(), key=lambda x: (x[1], str(x[0])))
        concentration.append({"category": category, "spendMinor": cat_total, "suppliers": len(positive), "hhi": int(hhi),
                              "hhiChild": int(hhi_of(by_cat_child[category])),
                              "level": "HIGH" if hhi > settings["hhiHigh"] else "MODERATE" if hhi > settings["hhiModerate"] else "LOW",
                              "topSupplier": master[top[0]].code if top[0] in master else "?", "topSharePct": _pct(top[1], cat_total)})
    return {"periods": [periods[0], periods[-1]], "totalMinor": total, "ranking": ranking, "suppliersRanked": len(ranked),
            "concentration": sorted(concentration, key=lambda c: (-c["spendMinor"], c["category"])),
            "duplicateClusters": spend_workflow.duplicate_clusters(session, by_supplier)}


def compliance(session: Session) -> dict:
    """SPD-05: contracted vs non-contracted by category, off-contract lines and price delta vs contract. Leakage is the price paid above
    the contract / standard price on off-contract and above-contract invoice lines, in the group currency."""
    periods = _window(session, 12)
    C = SpendCubeSummary
    group = C.amount_group_minor
    rows = session.execute(select(
        C.category, func.coalesce(func.sum(case((C.contracted.is_(True), group), else_=0)), 0),
        func.coalesce(func.sum(case((C.contracted.is_(False), group), else_=0)), 0), func.coalesce(func.sum(C.price_variance_group_minor), 0),
        func.coalesce(func.sum(C.price_variance_last_group_minor), 0))
        .where(_in_window(periods), C.addressable.is_(True), *spend_scope.where(session, C)).group_by(C.category)).all()
    master = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    group_ccy = spend_cube._group_currency(session)
    flagged = text("spend_line.maverick_flags ?| array['OFF_CONTRACT','OFF_CONTRACT_PRICE']")
    base = [SpendLine.period.between(periods[0], periods[-1]), SpendLine.addressable.is_(True), SpendLine.document_type == "INVOICE", flagged,
            *spend_scope.where(session, SpendLine)]
    off_lines = session.execute(select(SpendLine).where(*base).order_by(SpendLine.amount_minor.desc(), SpendLine.id).limit(100)).scalars().all()
    rate = case((SpendLine.currency == group_ccy, 1), else_=func.coalesce(SpendLine.fx_rate, 0))
    variance_group = func.coalesce(func.round(func.sum(func.coalesce(SpendLine.price_variance_minor, 0) * rate)), 0)
    off_agg = {c: (n, int(v or 0)) for c, n, v in session.execute(select(SpendLine.category, func.count(), variance_group).where(*base)
                                                                  .group_by(SpendLine.category)).all()}
    categories = [{"category": c, "contractedMinor": int(a), "nonContractedMinor": int(b), "priceVarianceMinor": int(v), "priceVarianceLastMinor": int(vl),
                   "offContractLines": off_agg.get(c, (0, 0))[0], "coveragePct": _pct(int(a), int(a) + int(b))} for c, a, b, v, vl in rows]
    off = [{"invoice": l.invoice_ref, "po": l.po_ref, "supplier": master.get(l.supplier_id), "category": l.category, "period": l.period,
            "amountMinor": l.amount_minor, "currency": l.currency, "priceVarianceMinor": l.price_variance_minor or 0, "flags": l.maverick_flags,
            "lineId": str(l.id)} for l in off_lines]
    return {"periods": [periods[0], periods[-1]], "categories": sorted(categories, key=lambda r: (-(r["contractedMinor"] + r["nonContractedMinor"]), r["category"])),
            "offContract": off, "leakageMinor": sum(v for _, v in off_agg.values()), "currency": group_ccy}


def forecast(session: Session, category: Optional[str] = None, plant: Optional[str] = None, horizon: int = 6) -> dict:
    """SPD-09 (see services/spend_forecast.py for the method, the back-test and the band)."""
    from app.pic.services import spend_forecast
    return spend_forecast.forecast(session, category, plant, horizon)


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
    hhi = hhi_of(shares)
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


def _fy_start(fiscal_year: str, start_month: int) -> date:
    return date(int(fiscal_year[:4]), start_month, 1)


def _add_months(d: date, months: int) -> date:
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def dated_waves(fiscal_year: str, start_month: int, waves: list[str], levers: list[str]) -> list[dict]:
    """The standard wave texts ("Q2: RFQ / e-auction") as dated waves of the fiscal year: a wave runs for its quarter."""
    out = []
    for position, text_ in enumerate(waves):
        quarter = int(text_[1]) if len(text_) > 2 and text_[0] == "Q" and text_[1].isdigit() else position + 1
        start = _add_months(_fy_start(fiscal_year, start_month), 3 * (quarter - 1))
        end = _add_months(start, 3) - timedelta(days=1)
        out.append({"name": text_.split(":", 1)[-1].strip(), "quarter": f"Q{quarter}", "start": start.isoformat(), "end": end.isoformat(),
                    "lever": levers[position % len(levers)] if levers else None, "milestone": text_.split(":", 1)[-1].strip()})
    return out


def split_by_lever(target: int, levers: list[str]) -> dict:
    """The savings target split evenly over the levers; the rounding remainder goes to the first lever so the parts add up exactly."""
    if not levers:
        return {}
    share, remainder = divmod(int(target), len(levers))
    return {lever: share + (remainder if i == 0 else 0) for i, lever in enumerate(levers)}


def generate_plans(session: Session, fiscal_year: str, owner_id: uuid.UUID, categories: Optional[list] = None) -> list[CategoryPlan]:
    """Draft plans for every category with addressable spend: Kraljic position from spend (profit impact) and supply risk, levers, a dated
    wave plan, a budget (the spend forecast, or the trailing spend when the forecast is thin) and a savings target by lever. A plan that
    is approved, in approval or superseded is left alone (revise it instead); a draft or rejected plan is refreshed."""
    periods = _window(session, 12)
    C = SpendCubeSummary
    rows = session.execute(select(C.category, C.supplier_id, func.sum(C.amount_group_minor)).where(
        C.period.in_(periods), C.addressable.is_(True), C.category != "UNCLASSIFIED", *spend_scope.where(session, C))
        .group_by(C.category, C.supplier_id)).all()
    by_cat = defaultdict(dict)
    for category, supplier_id, amount in rows:
        by_cat[category][supplier_id] = int(amount)
    totals = {c: sum(v.values()) for c, v in by_cat.items()}
    by_cat = {c: v for c, v in by_cat.items() if totals[c] > 0 and (categories is None or c in categories)}
    total = sum(totals[c] for c in by_cat) or 1
    largest = max((totals[c] for c in by_cat), default=1)
    from app.pic.services import spend_forecast
    projection = spend_forecast.plan_projection(session)
    settings = gov(session)
    start_month = spend_cube.fiscal_start_month(session)
    out = []
    for category, shares in by_cat.items():
        spend = totals[category]
        impact = (Decimal(math.sqrt(spend / largest)) * 10).quantize(Decimal("0.01"))
        risk, evidence = _supply_risk(session, category, shares)
        quadrant = ("STRATEGIC" if risk >= 4 else "LEVERAGE") if impact >= 5 else ("BOTTLENECK" if risk >= 4 else "NON_CRITICAL")
        plan = session.execute(select(CategoryPlan).where(CategoryPlan.category == category, CategoryPlan.fiscal_year == fiscal_year)
                               .order_by(CategoryPlan.version.desc())).scalars().first()
        if plan is not None and plan.status in ("APPROVED", "IN_APPROVAL", "SUPERSEDED"):
            continue
        # Budget from the spend forecast; fall back to trailing spend when the forecast window is thin (e.g. right after go-live).
        projected = projection.get(category, 0)
        budget, basis = (projected, "spend forecast (next 12 months)") if projected >= spend / 2 else (spend, "trailing 12-month spend")
        target = int(Decimal(budget) * TARGET_PCT[quadrant] / 100)
        cap = int(Decimal(spend) * Decimal(str(settings["planMaxSavingsPct"])) / 100)
        target = min(target, cap)
        values = dict(spend_minor=spend, profit_impact=impact, supply_risk=risk, kraljic=quadrant,
                      evidence={**evidence, "spendSharePct": _pct(spend, total), "window": [periods[0], periods[-1]], "budgetBasis": basis},
                      levers=LEVERS[quadrant], waves=WAVES[quadrant], budget_minor=budget, savings_target_minor=target, addressable_minor=spend,
                      wave_plan=dated_waves(fiscal_year, start_month, WAVES[quadrant], LEVERS[quadrant]),
                      savings_by_lever=split_by_lever(target, LEVERS[quadrant]))
        if plan is None:
            plan = CategoryPlan(tenant_id=session.info["principal"].tenant_id, number=next_number(session, "CATEGORY_PLAN"), category=category,
                                fiscal_year=fiscal_year, owner_id=owner_id, created_by=owner_id, **values)
            session.add(plan)
        else:
            for k, v in values.items():
                setattr(plan, k, v)
            if plan.status == "REJECTED":
                plan.status, plan.decision_comment = "DRAFT", None
        out.append(plan)
    session.flush()
    for plan in out:
        audit.record(session, "CATEGORY_PLAN", plan.id, "GENERATED", object_ref=plan.number,
                     after={"category": plan.category, "kraljic": plan.kraljic, "impact": plan.profit_impact, "risk": plan.supply_risk})
    return out


def approve_plan(session: Session, plan: CategoryPlan, comment: Optional[str]) -> CategoryPlan:
    """Approval by the procurement head or CPO, never the plan's owner and never the person who submitted it. A plan is validated first
    (budget, savings target against addressable spend, dated waves); the version it replaces becomes SUPERSEDED."""
    from app.pic.services import spend_workflow
    p = principal(session)
    if not set(p.roles) & {"PROCUREMENT_HEAD", "CPO"}:
        raise Problem(403, "FORBIDDEN", "Category plans are approved by the procurement head or CPO", rule_ref="M01")
    if plan.owner_id == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The plan owner cannot approve their own category plan", rule_ref="M01")
    if plan.submitted_by == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The person who submitted a category plan cannot approve it", rule_ref="M01")
    if not spend_scope.allows_category(session, plan.category):
        raise Problem(403, "FORBIDDEN", f"{plan.category} is outside your spend scope", rule_ref="ABAC")
    _lock(session, plan)
    if plan.status not in ("DRAFT", "IN_APPROVAL"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"{plan.number} is {plan.status}")
    if plan.status == "DRAFT" and gov(session)["planRequiresSubmission"]:
        raise Problem(409, "SUBMISSION_REQUIRED", f"{plan.number} must be submitted for approval first", rule_ref="M01")
    errors = spend_workflow.validate_plan(session, plan)
    if errors:
        raise Problem(422, "INVALID_PLAN", "; ".join(errors), rule_ref="M01", errors=errors)
    for older in session.execute(select(CategoryPlan).where(CategoryPlan.category == plan.category, CategoryPlan.fiscal_year == plan.fiscal_year,
                                                           CategoryPlan.id != plan.id, CategoryPlan.status == "APPROVED")).scalars():
        older.status = "SUPERSEDED"
        audit.record(session, "CATEGORY_PLAN", older.id, "SUPERSEDED", object_ref=older.number, after={"by": plan.number})
    plan.status, plan.approved_by, plan.approved_at, plan.decision_comment = "APPROVED", p.user_id, clock.now(), comment
    audit.record(session, "CATEGORY_PLAN", plan.id, "APPROVED", object_ref=plan.number, reason=comment,
                 after={"budgetMinor": plan.budget_minor, "savingsTargetMinor": plan.savings_target_minor, "version": plan.version})
    return plan


def get_plan(session: Session, ref: str) -> CategoryPlan:
    """A plan by number, or the current plan of a category (the latest version that is not superseded)."""
    plan = session.execute(select(CategoryPlan).where(CategoryPlan.number == ref)).scalars().first()
    if plan is None:
        plan = session.execute(select(CategoryPlan).where(CategoryPlan.category == ref, CategoryPlan.status != "SUPERSEDED")
                               .order_by(CategoryPlan.fiscal_year.desc(), CategoryPlan.version.desc())).scalars().first()
    if plan is None:
        raise not_found("Category plan", ref)
    if not spend_scope.allows_category(session, plan.category):
        raise not_found("Category plan", ref)
    return plan
