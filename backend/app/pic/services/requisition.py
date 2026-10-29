"""F2 Guided buying → requisition (M04)."""
import difflib
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Budget, BudgetCommitment, CatalogueItem, Contract, ContractLine, CostObject, Material, PrLine, Requisition, Task,
)
from app.pic.platform import audit, clock, outbox, rules, workflow
from app.pic.platform.core import StateMachine, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, line_amount
from app.pic.services import mdm, source
from app.pic.services.common import material_by_number, principal

PROCESS = "pic.requisition"
NEEDS_ACCOUNT = ("NON_STOCK", "SERVICE", "EXPENSE", "ASSET")
NEEDS_MATERIAL = ("CONSIGNMENT", "SUBCONTRACTING", "STOCK")  # P08: stock and special stocks are kept per material master
CAPEX_ACCOUNTS = ("ASSET", "WBS")
COST_OBJECT_ROLES = ("COST_OBJECT_OWNER", "DEPT_HEAD")  # one task per distinct cost object when a PR spans several


def unstructured(line) -> bool:
    """A line with no material master, catalogue item or contract line: free text or a free service (quote policy, F2-04)."""
    return not (line.material_id or line.catalogue_item_id or line.contract_line_id)


def quote_count(line) -> int:
    """Quotes that count for the quote policy: one per distinct supplier with a recorded reference (see ``_quote_refs``)."""
    return len({q["supplier"].strip().upper() for q in (line.source_determination or {}).get("quotes") or []})


def _quote_refs(raw) -> list[dict]:
    """Quote references on a line. There is no document store for quote files yet, so every quote is recorded by
    supplier, the supplier's quote reference and its date; a bare "quotes attached" number does not count."""
    refs = []
    for index, quote in enumerate(raw or [], start=1):
        quote = dict(quote or {})
        supplier, reference = str(quote.get("supplier") or "").strip(), str(quote.get("reference") or "").strip()
        try:
            quoted_on = quote["date"] if isinstance(quote.get("date"), date) else date.fromisoformat(str(quote.get("date")))
        except (TypeError, ValueError):
            quoted_on = None
        if not supplier or not reference or quoted_on is None:
            raise rule_violation(f"quote {index}: give the supplier, the supplier's quote reference and the quote date", "QUOTE-POLICY")
        if quoted_on > clock.today():
            raise rule_violation(f"quote {index}: the quote date {quoted_on.isoformat()} is in the future", "QUOTE-POLICY")
        refs.append({"supplier": supplier[:80], "reference": reference[:80], "date": quoted_on.isoformat()})
    return refs

SM = StateMachine("REQUISITION", {
    ("DRAFT", "submit"): "SUBMITTED",
    ("RETURNED", "submit"): "SUBMITTED",
    ("SUBMITTED", "route"): "IN_APPROVAL",
    ("SUBMITTED", "auto_approve"): "APPROVED",
    ("IN_APPROVAL", "approve"): "APPROVED",
    ("IN_APPROVAL", "reject"): "REJECTED",
    ("IN_APPROVAL", "return"): "RETURNED",
    ("APPROVED", "reapprove"): "IN_APPROVAL",
    ("APPROVED", "order_partially"): "PARTIALLY_ORDERED",
    ("APPROVED", "order"): "ORDERED",
    ("PARTIALLY_ORDERED", "order_partially"): "PARTIALLY_ORDERED",
    ("PARTIALLY_ORDERED", "order"): "ORDERED",
    ("ORDERED", "close"): "CLOSED",
    ("DRAFT", "cancel"): "CANCELLED",
    ("RETURNED", "cancel"): "CANCELLED",
    ("APPROVED", "cancel"): "CANCELLED",
    ("IN_APPROVAL", "cancel"): "CANCELLED",  # the requester withdraws it from approval (open tasks are cancelled)
    # A cancelled purchase order gives its quantity back to the requisition (order.cancel).
    ("ORDERED", "reopen"): "APPROVED",
    ("PARTIALLY_ORDERED", "reopen"): "APPROVED",
    ("ORDERED", "reopen_partially"): "PARTIALLY_ORDERED",
})


# ---------------------------------------------------------------- REQ-01 guided buying search (P03)
def search(session: Session, query: str, plant: Optional[str] = None) -> dict:
    """Search order enforced: contract item → catalogue item → material master → free text."""
    q = query.lower().strip()

    def score(text: str) -> float:
        text = text.lower()
        return 1.0 if q in text else difflib.SequenceMatcher(None, q, text).ratio()

    today = clock.today()
    contract_hits = []
    for line, contract in session.execute(select(ContractLine, Contract).join(Contract, Contract.id == ContractLine.contract_id)
                                          .where(Contract.status.in_(("ACTIVE", "EXPIRING")), Contract.valid_to >= today)).all():
        s = score(line.description)
        if s >= 0.6 and (plant is None or line.plant == plant):
            # Price valid today, or the first published period if the contract starts later.
            validity = source.contract_price(session, line.id, max(today, contract.valid_from))
            material = session.get(Material, line.material_id) if line.material_id else None
            contract_hits.append({"channel": "CONTRACT", "contract": contract.number, "line": line.line_no, "contractLineId": str(line.id),
                                  "material": material.number if material else None,
                                  "materialGroup": material.material_group if material else None, "uom": line.uom,
                                  "description": line.description, "validFrom": contract.valid_from.isoformat(),
                                  "unitPriceMinor": validity.unit_price_minor if validity else None, "score": round(s, 2)})
    catalogue_hits = [
        {"channel": "CATALOGUE", "id": str(c.id), "supplierPartNo": c.supplier_part_no, "description": c.description,
         "unitPriceMinor": c.price_minor, "uom": c.uom, "score": round(score(c.description), 2)}
        for c in session.execute(select(CatalogueItem).where(CatalogueItem.active.is_(True))).scalars() if score(c.description) >= 0.6
    ]
    material_hits = [
        {"channel": "MATERIAL", "material": m.number, "description": m.description, "uom": m.base_uom, "score": round(score(m.description), 2)}
        for m in session.execute(select(Material).where(Material.status == "ACTIVE")).scalars() if score(m.description) >= 0.6
    ]
    channels = [("CONTRACT", contract_hits), ("CATALOGUE", catalogue_hits), ("MATERIAL", material_hits)]
    recommended = next((name for name, hits in channels if hits), "FREE_TEXT")
    return {
        "query": query, "searchOrder": ["CONTRACT", "CATALOGUE", "MATERIAL", "FREE_TEXT"], "recommendedChannel": recommended,
        "results": {name.lower(): sorted(hits, key=lambda h: -h["score"]) for name, hits in channels},
        "freeTextAllowed": recommended == "FREE_TEXT",
        "hint": None if recommended == "FREE_TEXT" else f"Use the {recommended.lower()} result before adding free text (P03)",
    }


# ---------------------------------------------------------------- create
def create(session: Session, *, origin: str, lines: list[dict], plant: str, purpose_code: Optional[str] = None,
           purpose_text: Optional[str] = None, origin_ref: Optional[str] = None, company_code: str = "1000") -> Requisition:
    p = principal(session)
    if origin == "MRP" and not (p.is_agent or "MRP_CONTROLLER" in p.roles):
        raise Problem(403, "FORBIDDEN", "Only MRP conversion creates MRP-origin requisitions", rule_ref="P02")
    if not lines:
        raise rule_violation("A requisition needs at least one line", "REQ-02")
    pr = Requisition(tenant_id=current_tenant(session), number=next_number(session, "REQUISITION"), origin=origin,
                     origin_ref=origin_ref, purpose_code=purpose_code, purpose_text=purpose_text, requester_id=p.user_id,
                     company_code=company_code, plant=plant, status="DRAFT", created_by=p.user_id)
    session.add(pr)
    session.flush()
    instance = workflow.start(session, PROCESS, "REQUISITION", pr.id, pr.number, {"origin": origin})
    total = 0
    channels = set()
    reusable_lines = []
    for index, data in enumerate(lines, start=1):
        line = _build_line(session, pr, index * 10, data)
        session.add(line)
        total += line_amount(line.qty, line.price_est_minor)
        channels.add(line.item_type)
        if unstructured(line) and line.reusable:
            reusable_lines.append((line, data))
    pr.total_minor = total
    session.flush()
    workflow.step(session, instance, "F2-02", outcome="channels: " + ", ".join(sorted(channels)))
    found = channels & {"CONTRACT", "CATALOGUE"}
    other = "material master" if "MATERIAL" in channels else "free text"
    workflow.step(session, instance, "F2-03", outcome="yes: " + ", ".join(sorted(found)) if found else f"no → {other}")
    free = [l for l in _lines(session, pr) if unstructured(l)]
    if free:
        kinds = ", ".join(sorted({l.item_type.lower().replace("_", " ") for l in free}))
        workflow.step(session, instance, "F2-04", outcome=f"{len(free)} {kinds} line(s) without material, catalogue or contract: "
                                                          "material group, account assignment and quote policy")
        workflow.step(session, instance, "F2-05", outcome="yes" if reusable_lines else "no")
    for line, data in reusable_lines:
        mdm.create_request(session, description=line.description, type="NON_STOCK" if line.purchase_type != "STOCK" else "STOCK",
                           material_group=line.material_group, category=line.category or line.material_group,
                           base_uom=line.uom, mpn=data.get("mpn"), attributes=data.get("attributes"), source_pr=line)
        workflow.step(session, instance, "F2-06", outcome=f"MDM request started for line {line.line_no}; PR does not wait")
    audit.record(session, "REQUISITION", pr.id, "CREATED", object_ref=pr.number,
                 after={"origin": origin, "lines": len(lines), "totalMinor": total})
    return pr


def _build_line(session: Session, pr: Requisition, line_no: int, data: dict) -> PrLine:
    item_type = data.get("item_type", "FREE_TEXT").upper()
    purchase_type = data.get("purchase_type", "NON_STOCK").upper()
    material = material_by_number(session, data["material"]) if data.get("material") else None
    catalogue = None
    # A line from a returned punch-out cart carries the supplier's live price and part number (M04).
    punchout = data.get("punchout")
    if item_type == "CATALOGUE":
        if data.get("catalogue_item_id"):
            catalogue = session.get(CatalogueItem, uuid.UUID(str(data["catalogue_item_id"])))
            if catalogue is None:
                raise Problem(404, "NOT_FOUND", "Catalogue item not found")
        elif not punchout:
            raise rule_violation("Catalogue lines need a catalogue item from the guided-buying search or a punch-out cart", "P03")
    if item_type == "FREE_TEXT" and material is not None:
        raise rule_violation("Free-text lines cannot reference a material master", "P04")
    if item_type in ("MATERIAL", "CONTRACT") and material is None:
        raise rule_violation("Material and contract lines need a material number", "P03")
    contract_line = None
    if item_type == "CONTRACT":
        if not data.get("contract_line_id"):
            raise rule_violation("Contract lines need the contract line from the guided-buying search", "P03")
        try:
            contract_line = session.get(ContractLine, uuid.UUID(str(data["contract_line_id"])))
        except ValueError:
            contract_line = None
        if contract_line is None or contract_line.material_id != material.id:
            raise rule_violation("The contract line does not match the material", "P03")
        validity = source.contract_price(session, contract_line.id, max(clock.today(), session.get(Contract, contract_line.contract_id).valid_from))
        if validity is not None:
            data = {**data, "price_est_minor": validity.unit_price_minor}
    description = data.get("description") or (material.description if material else catalogue.description if catalogue else None)
    material_group = data.get("material_group") or (material.material_group if material else catalogue.material_group if catalogue else None)
    if not description or not material_group:
        raise rule_violation("Every line needs a description and a material group", "P04")
    price = data.get("price_est_minor")
    if catalogue is not None and not punchout:
        price = catalogue.price_minor
    if price is None:
        raise rule_violation("Every line needs an estimated price", "REQ-02")
    # A negative quantity or price would net down the requisition value and dodge the approval band and the budget.
    try:
        qty = D(data["qty"])
    except (ArithmeticError, TypeError, ValueError):
        raise rule_violation(f"line {line_no}: the quantity '{data.get('qty')}' is not a number", "REQ-02")
    if not qty.is_finite() or qty <= 0:
        raise rule_violation(f"line {line_no}: the quantity must be greater than zero", "REQ-02")
    if int(price) < 0:
        raise rule_violation(f"line {line_no}: the estimated price cannot be negative", "REQ-02")
    quotes = _quote_refs(data.get("quotes"))
    declared = int(data.get("quotes_attached", 0) or 0)
    if declared < 0:
        raise rule_violation(f"line {line_no}: quotes attached cannot be negative", "QUOTE-POLICY")
    if declared > len(quotes):
        raise rule_violation(f"line {line_no}: {declared} quote(s) declared but {len(quotes)} quote reference(s) given; record each quote "
                             "with the supplier, its quote reference and date", "QUOTE-POLICY")
    determination = dict(data.get("source_determination") or {})
    if quotes:
        determination["quotes"] = quotes
    return PrLine(
        tenant_id=pr.tenant_id, requisition_id=pr.id, line_no=line_no, item_type=item_type, purchase_type=purchase_type,
        material_id=material.id if material else None, catalogue_item_id=catalogue.id if catalogue else None,
        contract_line_id=contract_line.id if contract_line else None,
        description=description, material_group=material_group,
        category=data.get("category") or (material.category if material else catalogue.category if catalogue else material_group),
        qty=qty, uom=data.get("uom") or (material.base_uom if material else catalogue.uom if catalogue else "EA"),
        price_est_minor=int(price), account_assignment_type=data.get("account_assignment_type"),
        account_assignment_code=data.get("account_assignment_code"),
        need_date=data["need_date"] if isinstance(data["need_date"], date) else date.fromisoformat(str(data["need_date"])),
        plant=data.get("plant", pr.plant), storage_location=data.get("storage_location"),
        quotes_attached=len({q["supplier"].upper() for q in quotes}), reusable=bool(data.get("reusable", False)),
        planned_order_id=data.get("planned_order_id"), source_determination=determination,
        preferred_supplier_id=data.get("preferred_supplier_id"), created_by=pr.created_by,
    )


def _lines(session: Session, pr: Requisition) -> list[PrLine]:
    return session.execute(select(PrLine).where(PrLine.requisition_id == pr.id).order_by(PrLine.line_no)).scalars().all()


def add_lines(session: Session, pr: Requisition, lines: list[dict], source: str) -> list[PrLine]:
    """Append lines (e.g. a returned punch-out cart) to a draft or returned requisition; checks run again on submit."""
    if pr.status not in ("DRAFT", "RETURNED"):
        raise illegal_transition("Requisition", pr.number, pr.status, "add lines")
    if principal(session).user_id != pr.requester_id:
        raise Problem(403, "FORBIDDEN", "Only the requester can add lines to this requisition")
    line_no = max((l.line_no for l in _lines(session, pr)), default=0)
    added = []
    for data in lines:
        line_no += 10
        line = _build_line(session, pr, line_no, data)
        session.add(line)
        added.append(line)
    session.flush()
    pr.total_minor = sum(line_amount(l.qty, l.price_est_minor) for l in _lines(session, pr))
    audit.record(session, "REQUISITION", pr.id, "LINES_ADDED", object_ref=pr.number,
                 after={"lines": [l.line_no for l in added], "source": source, "totalMinor": pr.total_minor})
    instance = workflow.find(session, "REQUISITION", pr.id, PROCESS)
    if instance is not None and instance.status == "RUNNING":
        workflow.step(session, instance, "F2-02", outcome=f"{len(added)} line(s) added from {source}")
    return added


# ---------------------------------------------------------------- submit: policy, budget, approval route
def submit(session: Session, pr: Requisition, justification: Optional[str] = None, request_sourcing: bool = False) -> dict:
    if not SM.can(pr.status, "submit"):
        raise illegal_transition("Requisition", pr.number, pr.status, "submit")
    lines = _lines(session, pr)
    if not lines:
        raise rule_violation("A requisition needs at least one line before submission", "REQ-02")
    if not pr.purpose_code:
        raise rule_violation("A purpose code is mandatory before submission", "P01")
    hints, violations = [], []
    quote_rule = rules.resolve(session, "QUOTE-POLICY", company_code=pr.company_code)
    for line in lines:
        if line.qty <= 0 or line.price_est_minor < 0:
            violations.append(f"line {line.line_no}: quantity must be greater than zero and the price cannot be negative")
        if line.purchase_type in NEEDS_ACCOUNT and not line.account_assignment_code:
            violations.append(f"line {line.line_no}: {line.purchase_type.lower()} purchases need an account assignment")
        # BP §22: capital assets are assigned to an asset or a WBS element (capex); consignment and subcontracting need a material.
        if line.purchase_type == "ASSET" and line.account_assignment_code and line.account_assignment_type not in CAPEX_ACCOUNTS:
            violations.append(f"line {line.line_no}: capital assets are assigned to an asset or a WBS element (capex), "
                              f"not {(line.account_assignment_type or 'none').lower().replace('_', ' ')}")
        if line.purchase_type in NEEDS_MATERIAL and not line.material_id:
            violations.append(f"line {line.line_no}: {line.purchase_type.lower()} purchases need a material master")
        if unstructured(line):  # free text and free services alike (no material, catalogue or contract price)
            required = quotes_required(quote_rule, line_amount(line.qty, line.price_est_minor))
            if quote_count(line) < required:
                if required == 3 and request_sourcing:
                    line.sourcing_status = "SOURCING_REQUIRED"
                    hints.append(f"line {line.line_no}: sourcing event required instead of three quotes")
                else:
                    violations.append(f"line {line.line_no}: {required} quote(s) from different suppliers, each with its reference "
                                      f"and date, required for a {line.item_type.lower().replace('_', ' ')} line of this value")
    if violations:
        raise rule_violation("; ".join(violations), "P01/P08/" + quote_rule.ref, violations=violations)

    category_result, category_rules = category_budget_check(session, pr, lines, justification)
    budget_rule = rules.resolve(session, "BUDGET", company_code=pr.company_code)
    budget_result = _budget_check(session, pr, lines, budget_rule, justification)
    route_rule, chain = _route(session, pr, lines)
    pr.rule_set_version = rules.refs(route_rule, quote_rule, budget_rule)
    for extra in category_rules:  # the full list stays in budget_result; the column holds 80 characters
        if extra.ref not in pr.rule_set_version and len(pr.rule_set_version) + len(extra.ref) + 1 <= 80:
            pr.rule_set_version += ";" + extra.ref
    budget_result = {**budget_result, "categoryBudget": category_result}
    pr.budget_result = budget_result
    if category_result["checks"]:
        audit.record(session, "REQUISITION", pr.id, "CATEGORY_BUDGET_CHECKED", object_ref=pr.number, after=category_result,
                     reason=justification if category_result["outcome"] == "EXCEEDED_JUSTIFIED" else None,
                     rule_set_version=";".join(sorted({r.ref for r in category_rules})))
    pr.policy_hints = hints
    pr.approval_chain = chain
    pr.submitted_at = clock.now()
    SM.apply(session, pr, "submit", rule_set_version=pr.rule_set_version)
    outbox.emit(session, "requisition.submitted", "REQUISITION", pr.id, pr.number,
                {"origin": pr.origin, "totalMinor": pr.total_minor, "chain": chain})
    instance = workflow.find(session, "REQUISITION", pr.id, PROCESS)
    workflow.step(session, instance, "F2-07", outcome=f"budget {budget_result['outcome']}; route {' → '.join(chain) or 'auto'}")
    if not chain:
        SM.apply(session, pr, "auto_approve", reason="policy-compliant catalogue/contract purchase below band",
                 rule_set_version=route_rule.ref)
        workflow.step(session, instance, "F2-08", outcome="auto-approved (DMN-01)")
        _approved(session, pr, instance)
        return {"status": pr.status, "chain": chain, "categoryBudget": category_result}
    SM.apply(session, pr, "route", rule_set_version=route_rule.ref)
    _start_route(session, pr, instance, lines, chain, route_rule)
    return {"status": pr.status, "chain": chain, "categoryBudget": category_result}


def quotes_required(rule, value_minor: int) -> int:
    """BP §10.2 default quote policy: "< 25,000 none; 25,000 – 2 L one quote or catalogue; > 2 L three quotes or sourcing
    event". Below ``noQuoteBelow`` none; up to and including ``oneQuoteBelow`` (₹2 L) one; strictly above it three
    (exactly ₹2 L needs one quote, as in the blueprint wording and sourcing_strategy)."""
    return 0 if value_minor < rule.body["noQuoteBelow"] else 1 if value_minor <= rule.body["oneQuoteBelow"] else 3


def _route(session: Session, pr: Requisition, lines: list[PrLine]):
    """DMN-01 for the whole requisition (submit and re-approval after a change alike): value = requisition total, rule
    scope = company code, plant, dominant category by value and purchase type (ASSET if any line is an asset, else the
    dominant purchase type by value) — the same scope the ADM-03 policy simulator resolves with."""
    by_category: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for line in lines:
        value = line_amount(line.qty, line.price_est_minor)
        category = line.category or line.material_group
        by_category[category] = by_category.get(category, 0) + value
        by_type[line.purchase_type] = by_type.get(line.purchase_type, 0) + value
    category = max(sorted(by_category), key=lambda k: by_category[k])
    purchase_type = "ASSET" if "ASSET" in by_type else max(sorted(by_type), key=lambda k: by_type[k])
    channel = "CATALOGUE" if all(l.item_type == "CATALOGUE" for l in lines) else (
        "CONTRACT" if all(l.item_type == "CONTRACT" for l in lines) else "OTHER")
    account_type = "ASSET" if any(l.account_assignment_type == "ASSET" for l in lines) else lines[0].account_assignment_type
    route_rule = rules.resolve(session, "DMN-01", company_code=pr.company_code, plant=pr.plant, category=category,
                               purchase_type=purchase_type)
    return route_rule, rules.requisition_chain(route_rule, pr.total_minor, channel, account_type, purchase_type)


def _cost_objects(lines: list[PrLine]) -> list[str]:
    objects = []
    for line in lines:
        if line.account_assignment_type and line.account_assignment_code:
            key = f"{line.account_assignment_type}:{line.account_assignment_code}"
            if key not in objects:
                objects.append(key)
    return objects


def _stages(lines: list[PrLine], chain: list[str]) -> list[dict]:
    """Approval stages for a chain. With one cost object (or none) the chain runs as one sequential group, as before.
    A requisition charged to several cost objects gets, for each cost-object role in the chain (owner, department head),
    a parallel stage with one task per distinct cost object — all must approve — and the other roles run sequentially
    between those stages in chain order."""
    objects = _cost_objects(lines)
    if len(objects) <= 1:
        return [{"mode": "SEQUENTIAL", "chain": chain}]
    stages, rest = [], []
    for role in chain:
        if role in COST_OBJECT_ROLES:
            if rest:
                stages.append({"mode": "SEQUENTIAL", "chain": rest})
                rest = []
            stages.append({"mode": "PARALLEL", "chain": [role] * len(objects), "costObjects": objects})
        else:
            rest.append(role)
    if rest:
        stages.append({"mode": "SEQUENTIAL", "chain": rest})
    return stages


def _start_route(session: Session, pr: Requisition, instance, lines: list[PrLine], chain: list[str], route_rule) -> None:
    stages = _stages(lines, chain)
    for stage in stages:
        stage.update(rule=route_rule.ref, sla=int(route_rule.body.get("slaBusinessDays", 2)))
    _start_stage(session, pr, instance, lines, stages[0], [])
    instance.variables = {**(instance.variables or {}), "reqStages": stages[1:]}


def _start_stage(session: Session, pr: Requisition, instance, lines: list[PrLine], stage: dict, exclude: list) -> None:
    parallel = stage["mode"] == "PARALLEL"
    tasks = workflow.start_approval(
        session, instance, "REQ_APPROVAL", object_type="REQUISITION", object_id=pr.id, object_ref=pr.number, chain=stage["chain"],
        mode=stage["mode"], step_id="F2-08", initiator_id=pr.requester_id, scopes={} if parallel else _scopes(lines, stage["chain"]),
        sla_business_days=stage["sla"], rule_set_version=stage["rule"], exclude=exclude,
        evidence={"totalMinor": pr.total_minor, "budget": pr.budget_result},
    )
    if parallel:  # each parallel task is bound to one cost object (as the F9 steward tasks are bound to a domain)
        for task, cost_object in zip(tasks, stage["costObjects"]):
            task.candidate_scope = {"cost_object": cost_object}
            task.name = f"{task.name} · {cost_object.replace(':', ' ')}"[:200]
        session.flush()


def _next_stage(session: Session, pr: Requisition, instance) -> bool:
    """Open the next approval stage of a multi-cost-object requisition; False when every stage is approved."""
    pending = list((instance.variables or {}).get("reqStages") or []) if instance is not None else []
    if not pending:
        return False
    approvers = [t.completed_by for t in session.execute(select(Task).where(
        Task.object_id == pr.id, Task.kind == "REQ_APPROVAL", Task.instance_id == instance.id, Task.decision == "APPROVE")).scalars()
        if t.completed_by]
    _start_stage(session, pr, instance, _lines(session, pr), pending[0], approvers)
    instance.variables = {**(instance.variables or {}), "reqStages": pending[1:]}
    return True


def _scopes(lines: list[PrLine], chain: list[str]) -> dict:
    accounted = next((l for l in lines if l.account_assignment_code), None)
    scope = ({"cost_object": f"{accounted.account_assignment_type}:{accounted.account_assignment_code}"}
             if accounted else {"plant": lines[0].plant})
    return {role: scope for role in chain if role in ("COST_OBJECT_OWNER", "DEPT_HEAD")}


def _budget_check(session: Session, pr: Requisition, lines: list[PrLine], rule, justification: Optional[str]) -> dict:
    fiscal_year = clock.fiscal_year(clock.today())
    totals: dict[tuple[str, str], int] = {}
    for line in lines:
        if line.account_assignment_type and line.account_assignment_code:
            key = (line.account_assignment_type, line.account_assignment_code)
            totals[key] = totals.get(key, 0) + line_amount(line.qty, line.price_est_minor)
    if not totals:
        return {"outcome": "not applicable (inventory purchase)", "checks": []}
    checks = []
    for (obj_type, code), amount in totals.items():
        budget = session.execute(select(Budget).where(Budget.cost_object_type == obj_type, Budget.cost_object_code == code,
                                                      Budget.fiscal_year == fiscal_year).with_for_update()).scalar_one_or_none()
        if budget is None:
            raise rule_violation(f"No {fiscal_year} budget for {obj_type} {code}", rule.ref)
        available = budget.amount_minor - budget.committed_minor - budget.consumed_minor
        hard = obj_type in rule.body["hardFor"]
        ok = amount <= available
        if not ok and hard:
            raise Problem(422, "BUDGET_EXCEEDED", f"{obj_type} {code}: hard stop, available {available} < {amount}", rule_ref=rule.ref)
        if not ok and not justification:
            raise Problem(422, "BUDGET_JUSTIFICATION_REQUIRED", f"{obj_type} {code}: soft stop, add a justification", rule_ref=rule.ref)
        budget.committed_minor += amount
        session.add(BudgetCommitment(tenant_id=pr.tenant_id, budget_id=budget.id, object_type="REQUISITION", object_id=pr.id,
                                     object_ref=pr.number, amount_minor=amount, status="OPEN",
                                     justification=None if ok else justification, created_by=pr.requester_id))
        checks.append({"costObject": f"{obj_type}:{code}", "amountMinor": amount, "availableMinor": available,
                       "control": "HARD" if hard else "SOFT", "result": "OK" if ok else "SOFT_STOP_JUSTIFIED"})
    return {"outcome": "OK" if all(c["result"] == "OK" for c in checks) else "SOFT_STOP_JUSTIFIED", "checks": checks}


# ---------------------------------------------------------------- §24.1 / M01 category-plan budget
CATEGORY_MEASURE = (
    "committed = net value of purchase-order lines (any status except DRAFT and CANCELLED) on POs created in the fiscal year, "
    "plus the not-yet-ordered value of requisition lines that are SUBMITTED, IN_APPROVAL, APPROVED or PARTIALLY_ORDERED and were "
    "submitted in the fiscal year; a line's category is its requisition-line category (else material category, else material group)"
)
_RESULT_ORDER = {"OK": 0, "WARNING": 1, "EXCEEDED_JUSTIFIED": 2}


def _fiscal_bounds(fiscal_year: str):
    start = int(fiscal_year[:4])
    return clock.at_ist(date(start, 4, 1), 0, 0), clock.at_ist(date(start + 1, 4, 1), 0, 0)


def category_committed(session: Session, categories: set[str], fiscal_year: str,
                       exclude_pr: Optional[uuid.UUID] = None) -> dict[str, int]:
    """Committed spend per category for a fiscal year (see CATEGORY_MEASURE)."""
    from app.pic.models import PoLine, PurchaseOrder

    start, end = _fiscal_bounds(fiscal_year)
    committed = {c: 0 for c in categories}
    material_category = {m.id: m.category for m in session.execute(select(Material)).scalars()}

    def category_of(line: PrLine) -> str:
        return line.category or material_category.get(line.material_id) or line.material_group

    for line, pr in session.execute(
            select(PrLine, Requisition).join(Requisition, Requisition.id == PrLine.requisition_id).where(
                Requisition.status.in_(("SUBMITTED", "IN_APPROVAL", "APPROVED", "PARTIALLY_ORDERED")),
                Requisition.submitted_at >= start, Requisition.submitted_at < end)).all():
        if pr.id == exclude_pr:
            continue
        category = category_of(line)
        if category in committed and line.qty > line.ordered_qty:
            committed[category] += line_amount(line.qty - line.ordered_qty, line.price_est_minor)
    pos = session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PurchaseOrder.status.notin_(("DRAFT", "CANCELLED")), PurchaseOrder.created_at >= start, PurchaseOrder.created_at < end)).all()
    sources = {(l.requisition_id, l.line_no): category_of(l) for l in session.execute(select(PrLine).where(
        PrLine.requisition_id.in_({po_line.requisition_id for po_line, _ in pos if po_line.requisition_id}))).scalars()} if pos else {}
    for po_line, _ in pos:
        category = (sources.get((po_line.requisition_id, po_line.pr_line_no)) if po_line.requisition_id else None) \
            or material_category.get(po_line.material_id) or po_line.material_group
        if category in committed:
            committed[category] += po_line.net_minor
    return committed


def category_budget_check(session: Session, pr: Requisition, lines: list[PrLine], justification: Optional[str]) -> tuple[dict, list]:
    """Compare committed spend + this requisition with each APPROVED category plan's budget (rule CATEGORY-BUDGET).
    SOFT: warning from warnAtPct, justification required above 100%. HARD: blocked above 100%."""
    from app.pic.models import CategoryPlan

    fiscal_year = clock.fiscal_year(clock.today())
    amounts: dict[str, int] = {}
    for line in lines:
        category = line.category or line.material_group
        amounts[category] = amounts.get(category, 0) + line_amount(line.qty, line.price_est_minor)
    # Lock the plan rows (in a fixed order) before reading the committed spend, so concurrent submits against the same
    # category plan are serialised and a HARD budget cannot be overrun by two requisitions read side by side.
    plans = {plan.category: plan for plan in session.execute(select(CategoryPlan).where(
        CategoryPlan.category.in_(list(amounts)), CategoryPlan.fiscal_year == fiscal_year, CategoryPlan.status == "APPROVED",
        CategoryPlan.budget_minor.is_not(None)).order_by(CategoryPlan.category, CategoryPlan.id).with_for_update()).scalars()}
    result = {"outcome": "NOT_APPLICABLE", "fiscalYear": fiscal_year, "measure": CATEGORY_MEASURE, "checks": [], "warnings": []}
    if not plans:
        return result, []
    committed = category_committed(session, set(plans), fiscal_year, exclude_pr=pr.id)
    used_rules = []
    for category, plan in sorted(plans.items()):
        rule = rules.resolve(session, "CATEGORY-BUDGET", company_code=pr.company_code, category=category)
        used_rules.append(rule)
        mode = str(rule.body.get("mode", "SOFT")).upper()
        warn_at = Decimal(str(rule.body.get("warnAtPct", 90)))
        projected = committed[category] + amounts[category]
        used_pct = (Decimal(projected) * 100 / Decimal(plan.budget_minor)).quantize(Decimal("0.1")) if plan.budget_minor > 0 else Decimal(999)
        status = "EXCEEDED" if used_pct > 100 else "WARNING" if used_pct >= warn_at else "OK"
        check = {"category": category, "plan": plan.number, "budgetMinor": plan.budget_minor, "committedMinor": committed[category],
                 "requisitionMinor": amounts[category], "projectedMinor": projected, "availableMinor": plan.budget_minor - committed[category],
                 "usedPct": str(used_pct), "warnAtPct": str(warn_at), "mode": mode, "result": status, "ruleSetVersion": rule.ref}
        if status == "EXCEEDED":
            message = (f"{category}: this requisition takes the {fiscal_year} category budget ({plan.number}) to {used_pct}% "
                       f"(committed {committed[category]} + this requisition {amounts[category]} of {plan.budget_minor} paise)")
            if mode == "HARD":
                raise Problem(422, "CATEGORY_BUDGET_EXCEEDED", f"{message}; hard stop", rule_ref=rule.ref, categoryBudget=check)
            if not (justification or "").strip():
                raise Problem(422, "CATEGORY_BUDGET_JUSTIFICATION_REQUIRED", f"{message}; add a justification", rule_ref=rule.ref,
                              categoryBudget=check)
            check["result"] = "EXCEEDED_JUSTIFIED"
            check["justification"] = justification.strip()
            result["warnings"].append(f"{message}; justified")
        elif status == "WARNING":
            result["warnings"].append(f"{category}: {used_pct}% of the {fiscal_year} category budget ({plan.number}) is committed "
                                      f"with this requisition (warning from {warn_at}%)")
        result["checks"].append(check)
    result["outcome"] = max((c["result"] for c in result["checks"]), key=lambda r: _RESULT_ORDER[r])
    return result, used_rules


def _release_budget(session: Session, pr: Requisition) -> None:
    for commitment in session.execute(select(BudgetCommitment).where(BudgetCommitment.object_id == pr.id,
                                                                     BudgetCommitment.status == "OPEN")).scalars():
        budget = session.get(Budget, commitment.budget_id)
        budget.committed_minor -= commitment.amount_minor
        commitment.status = "RELEASED"


@workflow.on_task("REQ_APPROVAL")
def _decided(session: Session, task: Task, outcome: str) -> None:
    pr = session.get(Requisition, task.object_id)
    instance = workflow.find(session, "REQUISITION", pr.id, PROCESS)
    if outcome == "APPROVED":
        if _next_stage(session, pr, instance):  # a multi-cost-object requisition has more approval stages
            return
        SM.apply(session, pr, "approve", rule_set_version=task.rule_set_version)
        _approved(session, pr, instance)
        return
    if instance is not None and (instance.variables or {}).get("reqStages"):
        instance.variables = {**instance.variables, "reqStages": []}
    if outcome == "REJECTED":
        SM.apply(session, pr, "reject", reason=task.comment)
        _release_budget(session, pr)
        workflow.end(session, instance, "F2-09", outcome=f"rejected: {task.comment}")
    else:
        SM.apply(session, pr, "return", reason=task.comment)
        _release_budget(session, pr)
        workflow.wait(session, instance, "F2-02", outcome=f"returned to requester: {task.comment}")


def _approved(session: Session, pr: Requisition, instance) -> None:
    from app.pic.services import planning

    pr.approved_at = clock.now()
    lines = _lines(session, pr)
    pr.approved_snapshot = {str(l.line_no): {"value": line_amount(l.qty, l.price_est_minor), "account": l.account_assignment_code,
                                             "accountType": l.account_assignment_type,
                                             "supplier": str(l.preferred_supplier_id) if l.preferred_supplier_id else None}
                            for l in lines}
    for line in lines:
        if line.material_id:
            material = session.get(Material, line.material_id)
            determination = source.determine(session, material, line.plant, line.need_date, line.qty)
            line.source_determination = determination.as_dict()
            if line.sourcing_status == "OPEN":
                line.sourcing_status = "SOURCED" if determination.method != "NONE" else "OPEN"
    outbox.emit(session, "requisition.approved", "REQUISITION", pr.id, pr.number,
                {"origin": pr.origin, "totalMinor": pr.total_minor, "lines": [l.line_no for l in lines]})
    workflow.end(session, instance, "F2-09", outcome="approved PR to buyer workbench")
    planning.on_requisition_approved(session, pr)


# ---------------------------------------------------------------- change after approval
def change_line(session: Session, pr: Requisition, line_no: int, changes: dict) -> dict:
    """Restart approval only when value, account assignment or supplier changes (§10.4)."""
    if pr.status not in ("APPROVED", "DRAFT", "RETURNED"):
        raise illegal_transition("Requisition", pr.number, pr.status, "change")
    p = principal(session)
    # DRAFT / RETURNED: the requester's own document. APPROVED: the requester or a buyer (re-approval rules apply).
    if p.user_id != pr.requester_id and not (pr.status == "APPROVED" and "BUYER" in p.roles):
        raise Problem(403, "FORBIDDEN", "Only the requester can change this requisition" +
                      (" (or a buyer once it is approved)" if pr.status == "APPROVED" else ""))
    line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == line_no)).scalar_one_or_none()
    if line is None:
        raise Problem(404, "NOT_FOUND", f"Requisition {pr.number} has no line {line_no}")
    justification = (changes.get("justification") or "").strip() or None
    before = {"qty": str(line.qty), "price": line.price_est_minor, "account": line.account_assignment_code,
              "accountType": line.account_assignment_type,
              "supplier": str(line.preferred_supplier_id) if line.preferred_supplier_id else None, "need_date": line.need_date.isoformat()}
    for field in ("qty", "price_est_minor", "account_assignment_code", "account_assignment_type", "need_date", "description",
                  "preferred_supplier_id"):
        if field in changes:
            value = changes[field]
            if field == "qty":
                try:
                    value = D(value)
                except (ArithmeticError, TypeError, ValueError):
                    raise rule_violation(f"line {line_no}: the quantity '{value}' is not a number", "REQ-02")
                if not value.is_finite() or value <= 0:
                    raise rule_violation(f"line {line_no}: the quantity must be greater than zero", "REQ-02")
                if value < (line.ordered_qty or 0):
                    raise rule_violation(f"line {line_no}: {line.ordered_qty} is already ordered; the quantity cannot go below it", "REQ-02")
            if field == "price_est_minor" and (value is None or int(value) < 0):
                raise rule_violation(f"line {line_no}: the estimated price cannot be negative", "REQ-02")
            if field == "need_date" and not isinstance(value, date):
                value = date.fromisoformat(str(value))
            setattr(line, field, value)
    lines = _lines(session, pr)
    pr.total_minor = sum(line_amount(l.qty, l.price_est_minor) for l in lines)
    restart = False
    if pr.status == "APPROVED":
        snap = (pr.approved_snapshot or {}).get(str(line_no), {})
        restart = (line_amount(line.qty, line.price_est_minor) != snap.get("value")
                   or line.account_assignment_code != snap.get("account")
                   or ("accountType" in snap and line.account_assignment_type != snap.get("accountType"))
                   or (str(line.preferred_supplier_id) if line.preferred_supplier_id else None) != snap.get("supplier"))
    audit.record(session, "REQUISITION", pr.id, "LINE_CHANGED", object_ref=pr.number, before=before,
                 after={k: str(v) for k, v in changes.items() if k != "justification"},
                 reason=("re-approval required" if restart else "no re-approval needed") + (f"; justification: {justification}" if justification else ""))
    if restart:
        SM.apply(session, pr, "reapprove", reason="value, account or supplier changed after approval")
        # The budget commitments follow the changed value: release the old ones and book the new ones with the same
        # soft/hard rules (a soft stop takes the change's justification); the category plan is checked again as well.
        _release_budget(session, pr)
        category_result, _ = category_budget_check(session, pr, lines, justification)
        rebooked = _budget_check(session, pr, lines, rules.resolve(session, "BUDGET", company_code=pr.company_code), justification)
        pr.budget_result = {**rebooked, "categoryBudget": category_result, "rebookedOnChange": True}
        # The same DMN-01 aggregation as on submit (whole requisition, full rule scope); a changed approved
        # requisition always goes to at least the cost-object owner.
        rule, chain = _route(session, pr, lines)
        chain = chain or ["COST_OBJECT_OWNER"]
        pr.approval_chain = chain
        instance = workflow.start(session, PROCESS, "REQUISITION", pr.id, pr.number, {"reapproval": True})
        _start_route(session, pr, instance, lines, chain, rule)
    return {"status": pr.status, "reapproval": restart}


# ---------------------------------------------------------------- cancel / withdraw
def cancel(session: Session, pr: Requisition, reason: str) -> Requisition:
    """Withdraw a requisition: the requester while DRAFT, RETURNED, IN_APPROVAL or APPROVED (not yet ordered), a buyer once APPROVED.
    Releases the budget commitments, cancels the open approval tasks and their timers and ends the process."""
    from app.pic.models import PoLine, PurchaseOrder, Timer

    reason = (reason or "").strip()
    if not reason:
        raise rule_violation("A reason is required to cancel a requisition", "REQ-02")
    if not SM.can(pr.status, "cancel"):
        raise illegal_transition("Requisition", pr.number, pr.status, "cancel")
    p = principal(session)
    if p.user_id != pr.requester_id and not (pr.status == "APPROVED" and "BUYER" in p.roles):
        raise Problem(403, "FORBIDDEN", "Only the requester can cancel this requisition" +
                      (" (or a buyer once it is approved)" if pr.status == "APPROVED" else ""))
    ordered = session.execute(select(PurchaseOrder.number).join(PoLine, PoLine.po_id == PurchaseOrder.id).where(
        PoLine.requisition_id == pr.id, PurchaseOrder.status != "CANCELLED")).scalars().first()
    if ordered:
        raise Problem(409, "REQUISITION_ORDERED", f"{pr.number} is on purchase order {ordered}; cancel the purchase order first",
                      rule_ref="REQ-02")
    lines = _lines(session, pr)
    if any(l.ordered_qty > 0 for l in lines):
        raise Problem(409, "REQUISITION_ORDERED", f"{pr.number} is partly ordered; cancel the purchase order first", rule_ref="REQ-02")
    if any(l.sourcing_status == "IN_SOURCING" for l in lines):
        raise Problem(409, "REQUISITION_IN_SOURCING", f"{pr.number} is bundled into a sourcing event; remove it there first",
                      rule_ref="REQ-02")
    before = pr.status
    _release_budget(session, pr)
    cancelled = 0
    for task in session.execute(select(Task).where(Task.object_id == pr.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
        cancelled += 1
        for timer in session.execute(select(Timer).where(Timer.object_id == task.id, Timer.fired_at.is_(None))).scalars():
            timer.fired_at = clock.now()
            timer.payload = {**(timer.payload or {}), "cancelled": True}
    for timer in session.execute(select(Timer).where(Timer.object_id == pr.id, Timer.fired_at.is_(None))).scalars():
        timer.fired_at = clock.now()
        timer.payload = {**(timer.payload or {}), "cancelled": True}
    instance = workflow.find(session, "REQUISITION", pr.id, PROCESS)
    if instance is not None:
        if (instance.variables or {}).get("reqStages"):
            instance.variables = {**instance.variables, "reqStages": []}
        if instance.status == "RUNNING":
            workflow.end(session, instance, "F2-09", outcome=f"cancelled by {p.actor}: {reason}", status="CANCELLED")
    SM.apply(session, pr, "cancel", reason=reason, extra_after={"tasksCancelled": cancelled, "cancelledBy": p.actor})
    outbox.emit(session, "requisition.cancelled", "REQUISITION", pr.id, pr.number, {"reason": reason, "previousStatus": before})
    return pr


def buyer_queue(session: Session, origin: Optional[str] = None) -> list[dict]:
    """REQ-04: approved PR lines waiting for sourcing or a PO, MRP and manual in one queue."""
    query = select(PrLine, Requisition).join(Requisition, Requisition.id == PrLine.requisition_id).where(
        Requisition.status.in_(("APPROVED", "PARTIALLY_ORDERED")), PrLine.qty > PrLine.ordered_qty)
    if origin:
        query = query.where(Requisition.origin == origin.upper())
    materials = {m.id: m.number for m in session.execute(select(Material)).scalars()}
    return [{"requisition": pr.number, "line": l.line_no, "origin": pr.origin, "description": l.description, "itemType": l.item_type,
             "purchaseType": l.purchase_type, "material": materials.get(l.material_id), "category": l.category,
             "priceEstMinor": l.price_est_minor,
             "qty": str(l.qty - l.ordered_qty), "uom": l.uom, "needDate": l.need_date.isoformat(), "plant": l.plant,
             "sourcingStatus": l.sourcing_status, "source": l.source_determination}
            for l, pr in session.execute(query.order_by(PrLine.need_date)).all()]


def mark_ordered(session: Session, pr: Requisition, line: PrLine, qty: Decimal) -> None:
    line.ordered_qty += qty
    line.sourcing_status = "ORDERED" if line.ordered_qty >= line.qty else line.sourcing_status
    lines = _lines(session, pr)
    command = "order" if all(l.ordered_qty >= l.qty for l in lines) else "order_partially"
    if SM.can(pr.status, command):
        SM.apply(session, pr, command)
