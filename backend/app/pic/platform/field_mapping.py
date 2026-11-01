"""Configurable ERP field mappings (item 50, TD §12): per tenant and target system, versioned rules that reshape the outbound
payload before the connector sees it.

The services build one canonical payload per message type (``integration.enqueue``). A tenant whose ERP expects other field names,
formats or codes publishes a mapping for (target system, message type); ``integration.process`` applies the ACTIVE version right
before the connector call and stores what was sent (``integration_message.outbound_payload`` and ``mapping_version``). The
canonical ``payload`` is never modified, so business logic that reads it keeps working and a message can be re-sent under a newer
mapping. Without an active mapping the payload is sent exactly as built: the defaults are today's payloads.

Rules run in order on a deep copy. Paths are dotted (``supplier.code``); ``lines[].qty`` addresses every element of a list.

    rename    {"op": "rename", "from": "grossMinor", "to": "GrossAmount"}
    copy      {"op": "copy", "from": "invoiceNo", "to": "Reference"}
    constant  {"op": "constant", "to": "SourceSystem", "value": "PIC"}
    drop      {"op": "drop", "field": "internalNote"}
    format    {"op": "format", "field": "invoiceDate", "kind": "date", "pattern": "%d.%m.%Y"}
              kinds: upper, lower, trim, date (strftime, input ISO date), minor_to_major (decimals), pad_left (width, char),
                     truncate (length), prefix (text), suffix (text), replace (old, new), number (decimals), string
    lookup    {"op": "lookup", "field": "currency", "table": {"INR": "INR01"}, "default": null, "to": "CurrencyCode"}
              (a value missing from the table keeps its value unless ``default`` is set; ``required: true`` fails the message)
"""
import copy
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import IntegrationFieldMapping

OPS = {"rename", "copy", "constant", "drop", "format", "lookup"}
KINDS = {"upper", "lower", "trim", "date", "minor_to_major", "pad_left", "truncate", "prefix", "suffix", "replace", "number", "string"}
PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[\])?)*$")
MAX_RULES = 200


class MappingError(ValueError):
    """A rule cannot be applied to the payload (a required value is missing or has the wrong shape)."""


# ---------------------------------------------------------------- paths
def _segments(path: str) -> list:
    return [(seg[:-2], True) if seg.endswith("[]") else (seg, False) for seg in path.split(".")]


def _walk(node: Any, segs: list):
    """Yield (container, key) for every location the path addresses; container is a dict and key a field name."""
    if not segs:
        return
    name, many = segs[0]
    if not isinstance(node, dict):
        return
    if len(segs) == 1 and not many:
        yield node, name
        return
    child = node.get(name)
    if many:
        for item in child if isinstance(child, list) else []:
            if len(segs) == 1:
                continue
            yield from _walk(item, segs[1:])
    else:
        yield from _walk(child, segs[1:])


def _get(payload: Any, path: str) -> list:
    return [container[key] for container, key in _walk(payload, _segments(path)) if key in container]


def _set(payload: Any, path: str, value: Any, *, create: bool = False) -> int:
    segs = _segments(path)
    count = 0
    for container, key in _walk(payload, segs):
        container[key] = value
        count += 1
    if not count and create and len(segs) == 1 and not segs[0][1]:
        payload[segs[0][0]] = value
        count = 1
    return count


# ---------------------------------------------------------------- transforms
def _format(value: Any, rule: dict) -> Any:
    kind = rule["kind"]
    if value is None:
        return None
    if kind == "upper":
        return str(value).upper()
    if kind == "lower":
        return str(value).lower()
    if kind == "trim":
        return str(value).strip()
    if kind == "string":
        return str(value)
    if kind == "date":
        try:
            parsed = value if isinstance(value, (date, datetime)) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise MappingError(f"{value!r} is not an ISO date")
        return parsed.strftime(rule.get("pattern", "%Y-%m-%d"))
    if kind in ("minor_to_major", "number"):
        try:
            number = Decimal(str(value))
        except Exception:  # noqa: BLE001
            raise MappingError(f"{value!r} is not a number")
        decimals = int(rule.get("decimals", 2))
        if kind == "minor_to_major":
            number = number / (Decimal(10) ** decimals)
        return f"{number:.{decimals}f}"
    if kind == "pad_left":
        return str(value).rjust(int(rule["width"]), str(rule.get("char", "0"))[:1] or "0")
    if kind == "truncate":
        return str(value)[: int(rule["length"])]
    if kind == "prefix":
        return f"{rule['text']}{value}"
    if kind == "suffix":
        return f"{value}{rule['text']}"
    if kind == "replace":
        return str(value).replace(str(rule["old"]), str(rule.get("new", "")))
    raise MappingError(f"unknown format kind {kind}")


# ---------------------------------------------------------------- engine
def validate(rules: Any) -> list:
    """Structural problems of a rule list (empty: valid). Does not need a payload."""
    problems = []
    if not isinstance(rules, list):
        return [{"rule": None, "message": "rules must be a list"}]
    if len(rules) > MAX_RULES:
        problems.append({"rule": None, "message": f"at most {MAX_RULES} rules"})
    for index, rule in enumerate(rules[:MAX_RULES]):
        def bad(message: str) -> None:
            problems.append({"rule": index, "message": message})
        if not isinstance(rule, dict) or rule.get("op") not in OPS:
            bad(f"op must be one of {', '.join(sorted(OPS))}")
            continue
        op = rule["op"]
        needs = {"rename": ("from", "to"), "copy": ("from", "to"), "constant": ("to", "value"), "drop": ("field",),
                 "format": ("field", "kind"), "lookup": ("field", "table")}[op]
        for name in needs:
            if name not in rule or rule[name] is None and name != "value":
                bad(f"{op} needs '{name}'")
        for name in ("from", "to", "field"):
            if name in rule and isinstance(rule[name], str) and not PATH.match(rule[name]):
                bad(f"'{name}' is not a valid path: {rule[name]!r}")
            elif name in rule and not isinstance(rule[name], str):
                bad(f"'{name}' must be text")
        if (op == "rename" or (op == "copy" and "[]" in str(rule.get("from")))) and isinstance(rule.get("to"), str) and "." in rule["to"]:
            bad(f"{op} keeps the parent object: 'to' is a plain field name")
        if op == "format":
            if rule.get("kind") not in KINDS:
                bad(f"kind must be one of {', '.join(sorted(KINDS))}")
            elif rule["kind"] == "date":
                try:
                    datetime(2026, 1, 31).strftime(rule.get("pattern", "%Y-%m-%d"))
                except (ValueError, TypeError):
                    bad("pattern is not a valid strftime pattern")
            for needed, kinds in (("width", ("pad_left",)), ("length", ("truncate",)), ("text", ("prefix", "suffix")), ("old", ("replace",))):
                if rule.get("kind") in kinds and needed not in rule:
                    bad(f"kind {rule['kind']} needs '{needed}'")
        if op == "lookup" and not isinstance(rule.get("table"), dict):
            bad("table must be an object of value -> code")
    return problems


def apply(rules: list, payload: dict) -> dict:
    """The outbound payload: ``payload`` (untouched) with ``rules`` applied. Raises MappingError."""
    out = copy.deepcopy(payload)
    for index, rule in enumerate(rules or []):
        op = rule.get("op")
        try:
            if op == "rename":
                for container, key in list(_walk(out, _segments(rule["from"]))):
                    if key in container:
                        container[rule["to"]] = container.pop(key)
            elif op == "copy":
                if "[]" in rule["from"]:
                    _copy_many(out, rule)  # every list element gets the copy next to the original
                else:
                    values = _get(out, rule["from"])
                    if values:
                        _set(out, rule["to"], values[0], create=True)
            elif op == "constant":
                _set(out, rule["to"], rule["value"], create=True)
            elif op == "drop":
                for container, key in list(_walk(out, _segments(rule["field"]))):
                    container.pop(key, None)
            elif op == "format":
                for container, key in list(_walk(out, _segments(rule["field"]))):
                    if key in container:
                        container[key] = _format(container[key], rule)
            elif op == "lookup":
                table = rule["table"]
                for container, key in list(_walk(out, _segments(rule["field"]))):
                    if key not in container:
                        continue
                    value = container[key]
                    lookup_key = str(value)
                    if lookup_key in table:
                        mapped = table[lookup_key]
                    elif rule.get("required"):
                        raise MappingError(f"no mapping for {value!r}")
                    elif "default" in rule:
                        mapped = rule["default"]
                    else:
                        mapped = value
                    if rule.get("to"):
                        container[rule["to"]] = mapped
                    else:
                        container[key] = mapped
        except MappingError as exc:
            raise MappingError(f"rule {index} ({op}): {exc}")
        except (KeyError, TypeError, ValueError) as exc:
            raise MappingError(f"rule {index} ({op}): {type(exc).__name__}: {exc}")
    return out


def _copy_many(out: dict, rule: dict) -> None:
    for container, key in list(_walk(out, _segments(rule["from"]))):
        if key in container:
            container[rule["to"]] = container[key]


def diff(before: Any, after: Any, path: str = "") -> list:
    """Flat list of what a mapping changed: [{path, change: added|removed|changed, before, after}]."""
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            here = f"{path}.{key}" if path else key
            if key not in after:
                changes.append({"path": here, "change": "removed", "before": before[key], "after": None})
            elif key not in before:
                changes.append({"path": here, "change": "added", "before": None, "after": after[key]})
            else:
                changes += diff(before[key], after[key], here)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (b, a) in enumerate(zip(before, after)):
            changes += diff(b, a, f"{path}[{index}]")
    elif before != after:
        changes.append({"path": path, "change": "changed", "before": before, "after": after})
    return changes


def preview(rules: list, sample: dict) -> dict:
    """Admin 'test with a sample payload': the mapped payload and the list of changes, or the problems found."""
    problems = validate(rules)
    if problems:
        return {"valid": False, "problems": problems, "outbound": None, "changes": []}
    try:
        outbound = apply(rules, sample)
    except MappingError as exc:
        return {"valid": False, "problems": [{"rule": None, "message": str(exc)}], "outbound": None, "changes": []}
    return {"valid": True, "problems": [], "outbound": outbound, "changes": diff(sample, outbound)}


# ---------------------------------------------------------------- database access
def active_for(session: Session, target_system: str, message_type: str) -> Optional[IntegrationFieldMapping]:
    return session.execute(select(IntegrationFieldMapping).where(
        IntegrationFieldMapping.target_system == target_system, IntegrationFieldMapping.message_type == message_type,
        IntegrationFieldMapping.status == "ACTIVE")).scalar_one_or_none()


def outbound_for(session: Session, target_system: str, message_type: str, payload: dict) -> tuple[Optional[dict], Optional[int]]:
    """(mapped payload, mapping version), or (None, None) when the tenant has no active mapping for this message."""
    mapping = active_for(session, target_system, message_type)
    if mapping is None or not mapping.rules:
        return None, None
    return apply(mapping.rules, payload), mapping.version
