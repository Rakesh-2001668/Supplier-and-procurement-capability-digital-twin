"""The event catalogue (TD §11): every topic the platform emits through ``outbox.emit``, who produces and who consumes it, and the
JSON Schema of its payload (``schemas/<topic>.json``).

The catalogue is derived from the code (an AST scan of ``app/pic``), so it cannot drift from it: ``scan()`` finds the producers
(``outbox.emit`` calls with a literal or constant topic) and the consumers (``@outbox.consumer``). The schemas are files, generated
once from the payload literal at the producer and then maintained by hand; ``tests/pic/test_wave1_jobs.py`` validates the
payloads of every real event row against them, and fails for a topic without a schema (set PIC_EVENT_CATALOGUE_STRICT=0 to only
warn while a new event is being introduced).

    python -m app.pic.events.catalogue write          create missing schema files and rewrite docs/PIC_Event_Catalogue.md
    python -m app.pic.events.catalogue write --force  regenerate every schema file from the producers
"""
import ast
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from jsonschema import Draft202012Validator

PACKAGE = Path(__file__).resolve().parents[1]  # app/pic
SCHEMAS = Path(__file__).resolve().parent / "schemas"
DOC = Path(__file__).resolve().parents[4] / "docs" / "PIC_Event_Catalogue.md"

# Topics built at run time: the f-string template of the producer and the topics it yields.
DYNAMIC = {"payment_file.{status.lower()}": ["payment_file.sent", "payment_file.acknowledged", "payment_file.rejected"]}

# Events written without outbox.emit (a before_flush listener): topic -> (object type, producer, required payload keys).
MANUAL_PRODUCERS = {"agent.recommendation.created": ("RECOMMENDATION", "services/notifications.py:_recommendation_events",
                                                     ["agent", "title", "candidateRole", "objectType", "objectId", "objectRef"])}

# Events nobody consumes inside the platform, with the reason (they are read by the real-time stream and external subscribers).
STREAM_ONLY = {
    "requisition.submitted": "Approval tasks and the audit trail already carry it; subscribers use it for cycle-time metrics.",
    "punchout.cart.returned": "The requester's browser session receives the cart; nothing else reacts.",
    "supplier.invitation.sent": "The invitation e-mail is the notification; subscribers use it for onboarding funnel metrics.",
    "payment_file.sent": "Status echo of the bank file; the audit trail holds the transition.",
    "payment_file.acknowledged": "Status echo of the bank file; the audit trail holds the transition.",
    "payment_file.rejected": "Status echo of the bank file; the audit trail holds the transition.",
}


def _constants(tree: ast.AST) -> dict[str, str]:
    return {t.id: n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str) for t in n.targets if isinstance(t, ast.Name) and t.id.endswith("TOPIC")}


def _call_name(node: ast.Call) -> Optional[str]:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _types(node: ast.AST) -> Optional[set]:
    """JSON types a payload expression certainly has, or None when it cannot be told from the source."""
    if isinstance(node, ast.Constant):
        v = node.value
        return {"null"} if v is None else {"boolean"} if isinstance(v, bool) else {"integer"} if isinstance(v, int) else {"number"} if isinstance(v, float) else {"string"}
    if isinstance(node, ast.JoinedStr):
        return {"string"}
    if isinstance(node, ast.Call):
        name = _call_name(node)
        return {"str": {"string"}, "len": {"integer"}, "int": {"integer"}, "bool": {"boolean"}, "float": {"number"}, "isoformat": {"string"},
                "list": {"array"}, "dict": {"object"}}.get(name or "")
    if isinstance(node, (ast.List, ast.ListComp, ast.Tuple)):
        return {"array"}
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return {"object"}
    if isinstance(node, ast.IfExp):
        a, b = _types(node.body), _types(node.orelse)
        return a | b if a is not None and b is not None else None
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        parts = [_types(v) for v in node.values]
        return None if any(p is None for p in parts) else set().union(*parts)
    return None


def _payload_shape(node: ast.AST) -> dict:
    if not isinstance(node, ast.Dict):
        return {"properties": {}, "required": []}
    props, required = {}, []
    for key, value in zip(node.keys, node.values):
        if key is None or not isinstance(key, ast.Constant):  # {**other, ...}: the other keys are not known statically
            continue
        types = _types(value)
        props[key.value] = ({"type": sorted(types)[0] if len(types) == 1 else sorted(types)} if types else {})
        required.append(key.value)
    return {"properties": props, "required": required}


@lru_cache(maxsize=1)
def scan() -> dict[str, dict]:
    """topic -> {objectType, producers [file:line], consumers [{name, module}], payload {properties, required}}."""
    topics: dict[str, dict] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # a file being edited; the test suite imports every module, so this cannot hide a shipped error
            continue
        consts = _constants(tree)
        rel = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name == "emit" and len(node.args) >= 3:
                arg = node.args[1]
                yielded: list[str] = []
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yielded = [arg.value]
                elif isinstance(arg, ast.Name) and arg.id in consts:
                    yielded = [consts[arg.id]]
                elif isinstance(arg, ast.JoinedStr):
                    yielded = [t for template, produced in DYNAMIC.items() if template in ast.unparse(arg) for t in produced]
                object_type = node.args[2].value if isinstance(node.args[2], ast.Constant) else None
                shape = _payload_shape(node.args[5]) if len(node.args) >= 6 else {"properties": {}, "required": []}
                for topic in yielded:
                    entry = topics.setdefault(topic, {"objectType": None, "producers": [], "consumers": [], "payload": shape})
                    if not entry["producers"]:  # first producer (a consumer in an earlier file may have created the entry)
                        entry["payload"] = shape
                    else:  # several producers: the contract is what every one of them sends
                        old_props, new_props = entry["payload"]["properties"], shape["properties"]
                        merged = {k: (old_props[k] if old_props.get(k) == new_props.get(k) else {}) if k in old_props and k in new_props
                                  else (old_props.get(k) or new_props.get(k)) for k in {**old_props, **new_props}}
                        entry["payload"] = {"properties": merged, "required": [k for k in entry["payload"]["required"] if k in shape["required"]]}
                    entry["objectType"] = entry["objectType"] or object_type
                    entry["producers"].append(f"{rel}:{node.lineno}")
            elif name == "consumer" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                arg = node.args[0]
                topic = arg.value if isinstance(arg, ast.Constant) else consts.get(getattr(arg, "id", ""))
                if topic:
                    topics.setdefault(topic, {"objectType": None, "producers": [], "consumers": [], "payload": {"properties": {}, "required": []}})
                    topics[topic]["consumers"].append({"name": node.args[1].value, "module": rel})
    for topic, (object_type, where, required) in MANUAL_PRODUCERS.items():
        entry = topics.setdefault(topic, {"objectType": None, "producers": [], "consumers": [], "payload": {}})
        entry.update(objectType=object_type, payload={"properties": {k: {} for k in required}, "required": required})
        entry["producers"].append(where)
    return dict(sorted(topics.items()))


def schema_path(topic: str) -> Path:
    return SCHEMAS / f"{topic}.json"


def load_schema(topic: str) -> Optional[dict]:
    path = schema_path(topic)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build_schema(topic: str, entry: dict) -> dict:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"pic-event:{topic}", "title": topic,
            "description": f"Payload (outbox_event.payload) of {topic} on {entry.get('objectType') or 'its object'}. Produced by "
                           f"{', '.join(sorted({p.split(':')[0] for p in entry['producers']})) or 'n/a'}.",
            "type": "object", "properties": entry["payload"]["properties"], "required": entry["payload"]["required"], "additionalProperties": True}


def validate(topic: str, payload: Any) -> list[str]:
    """Validation errors of one payload against the topic's schema (empty list: valid; raises KeyError without a schema)."""
    schema = load_schema(topic)
    if schema is None:
        raise KeyError(f"no schema file for event {topic}")
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in Draft202012Validator(schema).iter_errors(payload)]


def catalogue() -> list[dict]:
    """The catalogue as served by GET /v1/admin/events/catalogue."""
    out = []
    for topic, entry in scan().items():
        schema = load_schema(topic)
        out.append({"topic": topic, "objectType": entry["objectType"], "producers": entry["producers"],
                    "consumers": [c["name"] for c in entry["consumers"]], "streamOnly": not entry["consumers"],
                    "streamOnlyReason": STREAM_ONLY.get(topic) if not entry["consumers"] else None,
                    "schema": schema})
    return out


def write(force: bool = False) -> dict:
    SCHEMAS.mkdir(parents=True, exist_ok=True)
    created = []
    for topic, entry in scan().items():
        if not entry["producers"]:
            continue
        if force or not schema_path(topic).exists():
            schema_path(topic).write_text(json.dumps(build_schema(topic, entry), indent=2, sort_keys=False) + "\n", encoding="utf-8")
            created.append(topic)
    DOC.write_text(markdown(), encoding="utf-8")
    return {"schemasWritten": created}


def markdown() -> str:
    lines = ["# PIC Event Catalogue", "",
             "Every event the platform emits through the transactional outbox (`outbox.emit`), with its producers, its consumers and the "
             "JSON Schema of its payload. Generated from the code by `python -m app.pic.events.catalogue write`; the schema files are in "
             "`backend/app/pic/events/schemas/<topic>.json` and every real event payload is validated against them in "
             "`backend/tests/pic/test_wave1_jobs.py`.", "",
             "Envelope of every event (also what an external bus receives): `eventId`, `tenantId`, `type` (the topic), `occurredAt`, `actor`, "
             "`objectRef {type, id, ref}`, `version` (payload schema version, currently 1), `traceId`, `data` (the payload below).", "",
             "Delivery: at least once, in order per tenant; consumers are idempotent (`processed_event`); a failing consumer is retried with "
             "back-off and the event is dead-lettered after 8 attempts (`outbox_event.last_error`).", "",
             "| Event | Object | Producers | Consumers | Payload (required keys) |", "|---|---|---|---|---|"]
    streamed = []
    for topic, entry in scan().items():
        if not entry["producers"]:
            continue
        producers = ", ".join(f"`{p}`" for p in entry["producers"])
        if entry["consumers"]:
            consumers = ", ".join(f"`{c['name']}`" for c in entry["consumers"])
        else:
            consumers = "stream only"
            streamed.append(topic)
        keys = ", ".join(f"`{k}`" for k in entry["payload"]["required"]) or "(see schema)"
        lines.append(f"| `{topic}` | {entry['objectType'] or ''} | {producers} | {consumers} | {keys} |")
    lines += ["", "## Events without an internal consumer", ""]
    for topic in streamed:
        lines.append(f"- `{topic}`: {STREAM_ONLY.get(topic, 'read by the real-time stream and external subscribers only.')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "write":
        print(json.dumps(write(force="--force" in sys.argv), indent=2))
    else:
        print(markdown())
