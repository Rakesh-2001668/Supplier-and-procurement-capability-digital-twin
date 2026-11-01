"""TD §12.4 clause extraction when contracts are migrated (pending workflow 27).

A rule-based extractor reads the text of a signed contract (plain text, or text taken from a PDF), splits it into clauses by heading, assigns
each clause to the playbook's clause library by heading and body keywords, reads the commercial attributes (payment days, liability cap,
notice period, governing law, validity dates) and classifies each clause against the CLM playbook (STANDARD, FALLBACK or NON_STANDARD).
Every item carries a confidence; a person reviews the extraction (accept, edit, reject) before the clauses are written to the contract.
The migration loader (tools/erp_load) calls ``from_migration``: items at or above the auto-apply confidence are written straight away,
the rest wait for review. No language model is involved; the optional LLM gateway can later propose items the same way.
"""
import hashlib
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import Clause, ClauseExtraction, Contract
from app.pic.platform import audit, clock, rules
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found
from app.pic.platform.serialize import row
from app.pic.services.common import principal

VERSION = "clause-rules-1.0"
AUTO_APPLY_DEFAULT = Decimal("0.85")
MAX_TEXT = 400_000
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# code -> (title words that identify the clause, body phrases that support it)
LIBRARY: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "PAYMENT": (("payment", "invoicing", "fees and payment", "price and payment"), ("within", "days of", "invoice", "payable", "net 30", "net 45", "net 60")),
    "PRICE_INDEX": (("price adjustment", "price variation", "indexation", "escalation", "index"), ("lme", "index", "escalat", "price variation", "reset")),
    "PRICE": (("price", "prices", "pricing", "rates", "charges"), ("unit price", "fixed for", "rate card", "price list")),
    "DELIVERY": (("delivery", "shipment", "dispatch", "supply schedule"), ("deliver", "lead time", "incoterm", "schedule line", "tolerance")),
    "QUALITY": (("quality", "specification", "inspection", "ppap"), ("specification", "inspection", "conform", "certificate", "ppap", "iatf", "defect")),
    "WARRANTY": (("warranty", "defects liability", "guarantee"), ("warrant", "defect", "replace", "repair")),
    "LIABILITY": (("liability", "limitation of liability"), ("liable", "cap", "aggregate", "consequential", "indirect loss")),
    "INDEMNITY": (("indemnity", "indemnification"), ("indemnif", "hold harmless", "third-party claim")),
    "TERMINATION": (("termination", "term and termination", "cancellation"), ("terminate", "notice", "breach", "insolvency")),
    "CONFIDENTIALITY": (("confidentiality", "non-disclosure", "confidential information"), ("confidential", "disclose", "trade secret")),
    "GOVERNING_LAW": (("governing law", "applicable law", "jurisdiction"), ("laws of", "governed by", "courts at", "courts of", "exclusive jurisdiction")),
    "DISPUTES": (("dispute resolution", "arbitration", "disputes"), ("arbitrat", "arbitrator", "seat", "conciliation")),
    "FORCE_MAJEURE": (("force majeure",), ("beyond the reasonable control", "act of god", "force majeure")),
    "IP": (("intellectual property", "ownership of work"), ("intellectual property", "patent", "copyright", "licence", "license")),
    "INSURANCE": (("insurance",), ("insure", "insurance", "policy", "cover")),
    "AUDIT": (("audit", "audit rights", "records"), ("audit", "inspect the records", "books and records")),
    "DATA_PROTECTION": (("data protection", "personal data", "privacy"), ("personal data", "data protection", "processing", "dpdp")),
    "SLA": (("service levels", "service level agreement", "sla"), ("service level", "response time", "service credit", "resolution time")),
    "SUBCONTRACTING": (("subcontracting", "sub-contracting"), ("subcontract", "sub-contract", "sub-supplier")),
    "ASSIGNMENT": (("assignment",), ("assign", "novate", "transfer its rights")),
    "ANTI_BRIBERY": (("anti-bribery", "anti-corruption", "code of conduct", "ethics"), ("bribe", "corrupt", "gift", "code of conduct")),
    "NOTICES": (("notices",), ("notice shall be", "in writing to", "registered post")),
}
SEAT_JURISDICTION = {"mumbai": "IN-MH", "new delhi": "IN-DL", "delhi": "IN-DL", "bengaluru": "IN-KA", "bangalore": "IN-KA", "chennai": "IN-TN",
                     "ahmedabad": "IN-GJ", "kolkata": "IN-WB", "hyderabad": "IN-TG", "gurugram": "IN-HR", "gurgaon": "IN-HR",
                     "singapore": "SG", "london": "GB"}
HEADING_NUMBERED = re.compile(r"^\s*(?:clause\s+|article\s+|section\s+)?(\d{1,2}(?:\.\d{1,2})*)[.):\-–]?\s+(\S.{1,100})$", re.I)
HEADING_WORD = re.compile(r"^\s*(?:article|clause|section)\s+([IVXLC]+|\d+)[.:\-–]?\s*(.{0,100})$", re.I)
NUMBER_WORDS = {"thirty": 30, "forty-five": 45, "forty five": 45, "sixty": 60, "ninety": 90, "fifteen": 15, "seven": 7, "ten": 10, "twenty": 20,
                "one hundred and twenty": 120, "one hundred twenty": 120}


# ---------------------------------------------------------------- text in
def text_from_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # optional dependency: PDF text extraction
    except ImportError:
        raise Problem(501, "PDF_EXTRACTION_UNAVAILABLE", "PDF text extraction is not installed on this server; send the contract text instead "
                      "(copy it from the PDF or run it through the OCR service)", rule_ref="TD-12.4")
    import io

    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _is_heading(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped or len(stripped) > 110 or stripped.endswith((".", ";", ",")) and not HEADING_NUMBERED.match(stripped):
        return None
    m = HEADING_WORD.match(stripped)
    if m:
        return (m.group(2) or stripped).strip(" .:-–")
    m = HEADING_NUMBERED.match(stripped)
    if m:
        title = m.group(2).strip()
        # "1. The supplier shall ..." is a numbered sentence, not a heading: headings are short and carry no verb-ending full stop
        if len(title.split()) <= 9 and not title.endswith((".", ";", ",")):
            return title.strip(" .:-–")
        return None
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 4 and stripped.upper() == stripped and len(stripped.split()) <= 8:
        return stripped.title()
    return None


def split_clauses(text: str) -> list[dict]:
    """Blocks of the document: heading (or None), the text, the line span."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks, current = [], None
    for number, line in enumerate(lines):
        heading = _is_heading(line)
        if heading:
            if current:
                blocks.append(current)
            current = {"heading": heading, "lines": [], "start": number}
        elif current is None:
            if line.strip():
                current = {"heading": None, "lines": [line], "start": number}
        else:
            current["lines"].append(line)
    if current:
        blocks.append(current)
    if len(blocks) <= 1 and "\n\n" in text:  # no headings: paragraphs are the blocks
        blocks = [{"heading": None, "lines": para.split("\n"), "start": 0} for para in re.split(r"\n\s*\n", text) if para.strip()]
    out = []
    for block in blocks:
        body = "\n".join(l.rstrip() for l in block["lines"]).strip()
        if len(body) < 12 and not block["heading"]:
            continue
        out.append({"heading": block["heading"], "text": body, "start": block["start"]})
    return out


# ---------------------------------------------------------------- classification
def classify_block(heading: Optional[str], body: str) -> tuple[Optional[str], Decimal, list]:
    """(clause code, confidence, alternatives). Heading words are strong evidence, body phrases support it."""
    h, b = (heading or "").lower(), body.lower()
    scored = []
    for code, (title_words, phrases) in LIBRARY.items():
        title_hit = any(w in h for w in title_words) if h else False
        hits = sum(1 for p in phrases if p in b)
        if not title_hit and hits == 0:
            continue
        score = (0.55 if title_hit else 0.2) + min(hits, 4) * (0.1 if title_hit else 0.12)
        if title_hit and h.strip() in title_words:
            score += 0.1  # the heading is exactly the library title
        scored.append((min(score, 0.98), code))
    if not scored:
        return None, Decimal(0), []
    scored.sort(reverse=True)
    best = scored[0]
    return best[1], Decimal(str(round(best[0], 2))), [{"code": c, "confidence": round(s, 2)} for s, c in scored[1:4]]


def _days(text: str) -> Optional[int]:
    m = re.search(r"(\d{1,3})\s*(?:\([a-z\- ]+\)\s*)?(?:calendar\s+|working\s+|business\s+)?days", text, re.I)
    if m:
        return int(m.group(1))
    for word, value in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b\s*(?:\(\d+\)\s*)?days", text, re.I):
            return value
    return None


def parse_date(text: str) -> Optional[date]:
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:day of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _safe_date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text)
    if m and m.group(1)[:3].lower() in MONTHS:
        return _safe_date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", text)  # day first, as written in India
    if m:
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def clause_attributes(code: Optional[str], body: str) -> dict:
    """Commercial attributes read from the clause text."""
    out: dict = {}
    if code == "PAYMENT":
        discount = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:cash\s+)?discount[^.]{0,60}?within\s+(\d{1,3})\s+days", body, re.I)
        days = None
        net = re.search(r"\bnet\s*(\d{1,3})\b|\bN(\d{2,3})\b", body, re.I)
        if net:
            days = int(net.group(1) or net.group(2))
        else:
            within = re.search(r"(?:within|after)\s+(\d{1,3})\s*(?:\([a-z\- ]+\)\s*)?(?:calendar\s+)?days", body, re.I)
            days = int(within.group(1)) if within else _days(body)
        if days is not None:
            out["paymentDays"] = days
            out["paymentTerms"] = f"{discount.group(1)}/{discount.group(2)} N{days}" if discount else f"N{days}"
    elif code == "LIABILITY":
        if re.search(r"\bunlimited\b|without (?:any )?limit", body, re.I):
            out["liabilityUnlimited"] = True
        cap = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s*cent|percent)\s+of\s+(?:the\s+)?(?:annual\s+|total\s+|aggregate\s+)?(?:contract\s+)?(?:value|price|fees|charges)", body, re.I)
        if cap:
            out["liabilityCapPct"] = float(cap.group(1))
        amount = re.search(r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|crores?|million)?", body, re.I)
        if amount and "liabilityCapPct" not in out:
            value = Decimal(amount.group(1).replace(",", ""))
            factor = {"lakh": 100_000, "lakhs": 100_000, "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000}.get((amount.group(2) or "").lower(), 1)
            out["liabilityCapAmountMinor"] = int(value * factor * 100)
    elif code == "TERMINATION":
        notice = re.search(r"(\d{1,3})\s*(?:\([a-z\- ]+\)\s*)?days['’]?\s+(?:prior\s+)?(?:written\s+)?notice|notice\s+of\s+(?:not\s+less\s+than\s+)?(\d{1,3})\s+days", body, re.I)
        if notice:
            out["noticeDays"] = int(notice.group(1) or notice.group(2))
        else:
            days = _days(body)
            if days is not None and re.search(r"notice", body, re.I):
                out["noticeDays"] = days
    elif code in ("GOVERNING_LAW", "DISPUTES"):
        law = re.search(r"laws?\s+of\s+(India|Singapore|England(?:\s+and\s+Wales)?)", body, re.I)
        if law:
            out["governingLaw"] = law.group(1).title()
        seat = re.search(r"(?:seat|venue|courts?)\s+(?:and\s+venue\s+)?(?:of arbitration\s+)?(?:shall\s+be|is|will\s+be|at|of|in)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)", body)
        if seat:
            out["seat"] = seat.group(1)
            code_j = SEAT_JURISDICTION.get(seat.group(1).lower().strip())
            if code_j:
                out["jurisdiction"] = code_j
        if re.search(r"Arbitration and Conciliation Act", body, re.I):
            out["arbitrationAct"] = "Arbitration and Conciliation Act, 1996"
    elif code == "DELIVERY":
        tol = re.search(r"\+\s*(\d+(?:\.\d+)?)\s*%\s*/?\s*[-–]\s*(\d+(?:\.\d+)?)\s*%", body)
        if tol:
            out["overTolerancePct"], out["underTolerancePct"] = float(tol.group(1)), float(tol.group(2))
    return out


def document_attributes(text: str) -> dict:
    """Facts about the whole contract: validity, auto-renewal, value, parties."""
    out: dict = {}
    start = re.search(r"(?:effective|commenc\w+|start\w*)\s+(?:date\s+)?(?:from|on|of|is)?\s*[:\-]?\s*([^\n.;]{6,40})", text, re.I)
    end = re.search(r"(?:expir\w+|valid\s+until|valid\s+till|end\s+date|ends?\s+on|terminates?\s+on|until)\s+(?:on\s+)?[:\-]?\s*([^\n.;]{6,40})", text, re.I)
    if start and parse_date(start.group(1)):
        out["validFrom"] = parse_date(start.group(1)).isoformat()
    if end and parse_date(end.group(1)):
        out["validTo"] = parse_date(end.group(1)).isoformat()
    if re.search(r"automatically\s+(?:renew|extend)|auto-?renew", text, re.I):
        out["autoRenewal"] = True
    value = re.search(r"(?:total\s+)?(?:contract|order|agreement)\s+value[^\n]{0,40}?(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|crores?)?", text, re.I)
    if value:
        factor = {"lakh": 100_000, "lakhs": 100_000, "crore": 10_000_000, "crores": 10_000_000}.get((value.group(2) or "").lower(), 1)
        out["contractValueMinor"] = int(Decimal(value.group(1).replace(",", "")) * factor * 100)
    parties = re.search(r"between\s+(.{3,120}?)\s*(?:\(|,)\s*(?:hereinafter|the\s+[\"“]?buyer)[^\n]*?\band\s+(.{3,120}?)\s*(?:\(|,)\s*(?:hereinafter|the\s+[\"“]?(?:supplier|seller))", text, re.I | re.S)
    if parties:
        out["parties"] = [" ".join(parties.group(1).split()), " ".join(parties.group(2).split())]
    return out


def position_of(code: Optional[str], attrs: dict) -> tuple[str, str]:
    """Playbook position of the clause as written: STANDARD, FALLBACK (an approved fallback) or NON_STANDARD (routes through Legal)."""
    if code == "LIABILITY":
        if attrs.get("liabilityUnlimited"):
            return "NON_STANDARD", "liability is unlimited"
        cap = attrs.get("liabilityCapPct")
        if cap is None:
            return "NON_STANDARD", ("liability is capped in money terms, not as a share of the contract value; Legal reviews"
                                    if "liabilityCapAmountMinor" in attrs else "no liability cap found; Legal reviews")
        if cap == 100:
            return "STANDARD", "liability capped at 100% of the contract value"
        if 50 <= cap < 100:
            return "FALLBACK", f"liability capped at {cap:g}% (playbook fallback is 50%)"
        return "NON_STANDARD", f"liability cap {cap:g}% is outside the playbook (100%, fallback 50%)"
    if code == "PAYMENT":
        days = attrs.get("paymentDays")
        if days is None:
            return "NON_STANDARD", "payment period not found"
        if days >= 60:
            return "STANDARD", f"payment in {days} days"
        if days >= 45:
            return "FALLBACK", f"payment in {days} days (playbook fallback: 45 days minimum)"
        return "NON_STANDARD", f"payment in {days} days is below the 45-day fallback"
    if code == "TERMINATION":
        days = attrs.get("noticeDays")
        if days is None:
            return "NON_STANDARD", "notice period not found"
        if days >= 60:
            return "STANDARD", f"{days} days' notice"
        if days >= 30:
            return "FALLBACK", f"{days} days' notice (below the 60-90 day standard)"
        return "NON_STANDARD", f"{days} days' notice is below 30 days"
    if code in ("GOVERNING_LAW", "DISPUTES"):
        if attrs.get("governingLaw", "").lower() in ("india",) or attrs.get("jurisdiction", "").startswith("IN"):
            return "STANDARD", "Indian law and seat"
        if attrs.get("governingLaw") or attrs.get("jurisdiction"):
            return "FALLBACK", "foreign governing law or seat; Legal confirms"
        return "STANDARD", ""
    if code == "INDEMNITY":
        return "FALLBACK", "indemnities are reviewed by Legal against the playbook"
    return "STANDARD", ""


# ---------------------------------------------------------------- extraction
def extract(text: str, playbook_body: Optional[dict] = None) -> dict:
    """Pure function: contract text → items, unmatched blocks and document attributes (no database)."""
    if not (text or "").strip():
        raise Problem(422, "TEXT_REQUIRED", "Give the contract text", rule_ref="TD-12.4")
    if len(text) > MAX_TEXT:
        raise Problem(413, "TEXT_TOO_LARGE", f"The contract text is longer than {MAX_TEXT:,} characters; extract it in parts", rule_ref="TD-12.4")
    risk_of = (playbook_body or {}).get("positionRisk") or {"STANDARD": 0, "FALLBACK": 30, "NON_STANDARD": 70}
    titles = {}
    for group in ((playbook_body or {}).get("templates") or {}).values():
        for t in group:
            titles.setdefault(t["code"], t["title"])
    items, unmatched, used = [], [], {}
    for block in split_clauses(text):
        code, confidence, alternatives = classify_block(block["heading"], block["text"])
        if code is None or confidence < Decimal("0.45"):
            unmatched.append({"heading": block["heading"], "text": block["text"][:2000], "line": block["start"] + 1,
                              "suggestions": [code] if code else [], "confidence": float(confidence)})
            continue
        attrs = clause_attributes(code, block["text"])
        position, why = position_of(code, attrs)
        if code in used:  # a second block for a code that is already taken: keep the better one, list the other as unmatched
            other = items[used[code]]
            if confidence > Decimal(str(other["confidence"])):
                unmatched.append({"heading": other["heading"], "text": other["text"][:2000], "line": other["line"], "suggestions": [code],
                                  "confidence": other["confidence"], "note": "duplicate of a better match"})
                items[used[code]] = None
            else:
                unmatched.append({"heading": block["heading"], "text": block["text"][:2000], "line": block["start"] + 1, "suggestions": [code],
                                  "confidence": float(confidence), "note": "duplicate of a better match"})
                continue
        item = {"seq": len(items) + 1, "code": code, "title": titles.get(code) or (block["heading"] or code.replace("_", " ").title())[:200],
                "heading": block["heading"], "text": block["text"], "line": block["start"] + 1, "confidence": float(confidence),
                "alternatives": alternatives, "attributes": attrs, "position": position, "positionReason": why,
                "risk": int(risk_of.get(position, 0)), "decision": "PENDING"}
        used[code] = len(items)
        items.append(item)
    items = [i for i in items if i is not None]
    for number, item in enumerate(items, start=1):
        item["seq"] = number
    return {"items": items, "unmatched": unmatched, "attributes": document_attributes(text), "version": VERSION}


def discrepancies(contract: Optional[Contract], result: dict) -> list[dict]:
    """Differences between what the document says and what the migrated contract record holds."""
    if contract is None:
        return []
    out = []
    by_code = {i["code"]: i for i in result["items"]}
    doc = result["attributes"]
    pay = (by_code.get("PAYMENT") or {}).get("attributes", {}).get("paymentTerms")
    if pay and pay.replace(" ", "") != (contract.payment_terms or "").replace(" ", ""):
        out.append({"field": "paymentTerms", "document": pay, "contract": contract.payment_terms})
    if doc.get("validTo") and doc["validTo"] != contract.valid_to.isoformat():
        out.append({"field": "validTo", "document": doc["validTo"], "contract": contract.valid_to.isoformat()})
    if doc.get("validFrom") and doc["validFrom"] != contract.valid_from.isoformat():
        out.append({"field": "validFrom", "document": doc["validFrom"], "contract": contract.valid_from.isoformat()})
    if doc.get("contractValueMinor") and contract.target_value_minor and doc["contractValueMinor"] != contract.target_value_minor:
        out.append({"field": "contractValueMinor", "document": doc["contractValueMinor"], "contract": contract.target_value_minor})
    return out


def _rule(session: Session) -> dict:
    try:
        return rules.resolve(session, "CLAUSE-EXTRACTION").body
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        return {"autoApplyAbove": str(AUTO_APPLY_DEFAULT)}


def create_extraction(session: Session, *, contract_ref: str, text: str, source_name: str) -> ClauseExtraction:
    """Extract and store for review. The same text for the same contract returns the existing extraction (idempotent)."""
    p = principal(session)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = session.execute(select(ClauseExtraction).where(ClauseExtraction.source_hash == digest,
                                                              ClauseExtraction.contract_ref == contract_ref)).scalar_one_or_none()
    if existing is not None:
        return existing
    contract = session.execute(select(Contract).where(Contract.number == contract_ref)).scalar_one_or_none()
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    result = extract(text, playbook.body)
    found = discrepancies(contract, result)
    entry = ClauseExtraction(
        tenant_id=current_tenant(session), number=next_number(session, "CLAUSE_EXTRACTION"), source_name=(source_name or "contract text")[:200],
        source_hash=digest, contract_ref=contract_ref, contract_id=contract.id if contract else None, status="EXTRACTED", items=result["items"],
        attributes={**result["attributes"], "discrepancies": found}, unmatched=result["unmatched"], extractor_version=VERSION, created_by=p.user_id)
    session.add(entry)
    session.flush()
    audit.record(session, "CLAUSE_EXTRACTION", entry.id, "EXTRACTED", object_ref=entry.number,
                 after={"contract": contract_ref, "items": len(entry.items), "unmatched": len(entry.unmatched),
                        "lowConfidence": sum(1 for i in entry.items if i["confidence"] < 0.7), "discrepancies": len(found), "version": VERSION},
                 rule_set_version=playbook.ref)
    return entry


def review(session: Session, extraction: ClauseExtraction, decisions: list[dict]) -> ClauseExtraction:
    """Accept, edit or reject items. ACCEPT keeps the extracted clause; EDIT replaces its text, code and/or position; REJECT drops it."""
    p = principal(session)
    if "CONTRACT_MANAGER" not in p.roles and "LEGAL" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Clause extractions are reviewed by the contract manager or Legal", rule_ref="TD-12.4")
    if extraction.status in ("APPLIED", "REJECTED"):
        raise illegal_transition("Clause extraction", extraction.number, extraction.status, "review")
    positions = ("STANDARD", "FALLBACK", "NON_STANDARD")
    items = [dict(i) for i in extraction.items]
    by_seq = {i["seq"]: i for i in items}
    for decision in decisions:
        item = by_seq.get(int(decision.get("seq", 0)))
        if item is None:
            raise Problem(422, "INVALID_DECISION", f"Item {decision.get('seq')} is not in {extraction.number}", rule_ref="TD-12.4")
        action = str(decision.get("action", "")).upper()
        if action not in ("ACCEPT", "EDIT", "REJECT"):
            raise Problem(422, "INVALID_DECISION", "action must be ACCEPT, EDIT or REJECT", rule_ref="TD-12.4")
        if action == "EDIT":
            if decision.get("text") is not None:
                if not str(decision["text"]).strip():
                    raise Problem(422, "INVALID_DECISION", "The edited clause text cannot be empty", rule_ref="TD-12.4")
                item["text"] = str(decision["text"]).strip()
            if decision.get("code"):
                code = str(decision["code"]).upper()
                if code not in LIBRARY and code != item["code"]:
                    raise Problem(422, "INVALID_DECISION", f"{code} is not a clause code of the library", rule_ref="TD-12.4")
                item["code"] = code
            if decision.get("position"):
                if decision["position"] not in positions:
                    raise Problem(422, "INVALID_DECISION", f"position must be one of {', '.join(positions)}", rule_ref="TD-12.4")
                item["position"] = decision["position"]
            item["edited"] = True
        item["decision"] = "REJECTED" if action == "REJECT" else "ACCEPTED"
        item["reviewedBy"], item["reviewNote"] = p.email, decision.get("note")
    codes = [i["code"] for i in items if i["decision"] == "ACCEPTED"]
    if len(codes) != len(set(codes)):
        raise Problem(422, "DUPLICATE_CODE", "Two accepted items share a clause code; reject or recode one", rule_ref="TD-12.4")
    extraction.items = items
    if all(i["decision"] != "PENDING" for i in items):
        extraction.status, extraction.reviewed_by, extraction.reviewed_at = "REVIEWED", p.user_id, clock.now()
    audit.record(session, "CLAUSE_EXTRACTION", extraction.id, "REVIEWED" if extraction.status == "REVIEWED" else "REVIEW_PROGRESS",
                 object_ref=extraction.number, after={"accepted": sum(1 for i in items if i["decision"] == "ACCEPTED"),
                                                      "rejected": sum(1 for i in items if i["decision"] == "REJECTED"),
                                                      "pending": sum(1 for i in items if i["decision"] == "PENDING")})
    return extraction


def _write_clause(session: Session, contract: Contract, item: dict, risk_of: dict, source: str) -> str:
    clause = session.execute(select(Clause).where(Clause.contract_id == contract.id, Clause.code == item["code"])).scalar_one_or_none()
    before = {"text": clause.text, "position": clause.position} if clause else None
    if clause is None:
        clause = Clause(tenant_id=contract.tenant_id, contract_id=contract.id, code=item["code"], title=item["title"][:200], text=item["text"],
                        position=item["position"], risk_score=int(risk_of.get(item["position"], 0)), created_by=principal(session).user_id)
        session.add(clause)
        action = "added"
    else:
        clause.text, clause.position, clause.risk_score = item["text"], item["position"], int(risk_of.get(item["position"], 0))
        action = "replaced"
    session.flush()
    audit.record(session, "CONTRACT", contract.id, "CLAUSE_EXTRACTED", object_ref=contract.number, before=before,
                 after={"clause": item["code"], "position": item["position"], "confidence": item["confidence"], "action": action, "source": source})
    return action


def apply(session: Session, extraction: ClauseExtraction) -> dict:
    """Write the accepted items to the contract (existing clauses of the same code are replaced and the old text stays in the audit trail)."""
    p = principal(session)
    if "CONTRACT_MANAGER" not in p.roles and "LEGAL" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Clause extractions are applied by the contract manager or Legal", rule_ref="TD-12.4")
    if extraction.status != "REVIEWED":
        raise illegal_transition("Clause extraction", extraction.number, extraction.status, "apply")
    contract = session.get(Contract, extraction.contract_id) if extraction.contract_id else session.execute(
        select(Contract).where(Contract.number == extraction.contract_ref)).scalar_one_or_none()
    if contract is None:
        raise not_found("Contract", extraction.contract_ref)
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    added = replaced = 0
    for item in extraction.items:
        if item["decision"] == "ACCEPTED":
            if _write_clause(session, contract, item, playbook.body["positionRisk"], extraction.number) == "added":
                added += 1
            else:
                replaced += 1
    extraction.contract_id, extraction.status, extraction.applied_at = contract.id, "APPLIED", clock.now()
    audit.record(session, "CLAUSE_EXTRACTION", extraction.id, "APPLIED", object_ref=extraction.number,
                 after={"contract": contract.number, "added": added, "replaced": replaced}, rule_set_version=playbook.ref)
    return {"extraction": extraction.number, "contract": contract.number, "added": added, "replaced": replaced}


def reject(session: Session, extraction: ClauseExtraction, reason: str) -> ClauseExtraction:
    if extraction.status in ("APPLIED", "REJECTED"):
        raise illegal_transition("Clause extraction", extraction.number, extraction.status, "reject")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for rejecting the extraction", rule_ref="TD-12.4")
    extraction.status = "REJECTED"
    audit.record(session, "CLAUSE_EXTRACTION", extraction.id, "REJECTED", object_ref=extraction.number, reason=reason)
    return extraction


def from_migration(session: Session, contract: Contract, text: str, source_name: str) -> dict:
    """Called by the contract loader for a migrated contract: extract, write the items at or above the auto-apply confidence as clauses
    (position classified against the playbook) and keep the rest in a pending extraction for review. Idempotent per text and contract."""
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    threshold = Decimal(str(_rule(session).get("autoApplyAbove", AUTO_APPLY_DEFAULT)))
    extraction = create_extraction(session, contract_ref=contract.number, text=text, source_name=source_name)
    if extraction.status != "EXTRACTED" or (extraction.attributes or {}).get("migration"):
        return {"extraction": extraction.number, "applied": 0, "pending": sum(1 for i in extraction.items if i["decision"] == "PENDING"), "existing": True}
    items, applied = [dict(i) for i in extraction.items], 0
    for item in items:
        if Decimal(str(item["confidence"])) >= threshold and item["position"] != "NON_STANDARD":
            _write_clause(session, contract, item, playbook.body["positionRisk"], extraction.number)
            item["decision"], item["reviewedBy"], item["reviewNote"] = "ACCEPTED", "migration", f"auto-applied at confidence >= {threshold}"
            applied += 1
    extraction.items = items
    extraction.attributes = {**(extraction.attributes or {}), "migration": {"applied": applied, "threshold": str(threshold)}}
    pending = sum(1 for i in items if i["decision"] == "PENDING")
    if pending == 0:
        extraction.status, extraction.applied_at = "APPLIED", clock.now()
    return {"extraction": extraction.number, "applied": applied, "pending": pending, "unmatched": len(extraction.unmatched),
            "discrepancies": len((extraction.attributes or {}).get("discrepancies") or [])}


def view(session: Session, extraction: ClauseExtraction) -> dict:
    return row(extraction, extra={"summary": {
        "items": len(extraction.items), "pending": sum(1 for i in extraction.items if i["decision"] == "PENDING"),
        "accepted": sum(1 for i in extraction.items if i["decision"] == "ACCEPTED"),
        "lowConfidence": sum(1 for i in extraction.items if i["confidence"] < 0.7),
        "nonStandard": sum(1 for i in extraction.items if i["position"] == "NON_STANDARD")}})
