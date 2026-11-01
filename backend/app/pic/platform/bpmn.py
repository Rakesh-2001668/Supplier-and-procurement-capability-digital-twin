"""Process definition JSON <-> BPMN 2.0 XML (item 49, FE-5).

The designer stores definitions as JSON (steps, flows, lanes). ``to_xml`` renders one as a BPMN 2.0 collaboration with one pool,
one lane per swimlane and a diagram interchange (BPMNDI) layout, which the bpmn-js viewer in the admin workflow designer and on the
object pages draws; the live token position is added in the browser from the process instance's path. ``from_xml`` reads BPMN
(from this module, or from a modeller using the same element conventions) back into the definition JSON, so an exported diagram
can be imported again. PIC attributes (task kind, screen, roles, SLA) travel in the ``pic:`` namespace.
"""
import re
from typing import Optional
from xml.etree import ElementTree as ET

from app.pic.platform.errors import Problem

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"
PIC = "https://alphahelion.io/schema/pic-bpmn"

TAGS = {"event": None, "user": "userTask", "system": "serviceTask", "gateway": "exclusiveGateway"}
REVERSE = {"userTask": "user", "serviceTask": "system", "exclusiveGateway": "gateway", "startEvent": "event", "endEvent": "event",
           "intermediateThrowEvent": "event", "intermediateCatchEvent": "event", "task": "system", "manualTask": "user",
           "scriptTask": "system", "businessRuleTask": "system", "sendTask": "system", "receiveTask": "system"}
COL, LANE_H, POOL_X, POOL_Y, LABEL_W = 170, 150, 40, 40, 30


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _layout(steps: list, flows: list) -> dict:
    """Column of each step: longest path from the start over forward edges (back edges found by DFS are ignored)."""
    ids = [s["id"] for s in steps]
    out: dict = {i: [] for i in ids}
    incoming = {i: 0 for i in ids}
    for f in flows:
        if f["from"] in out and f["to"] in out:
            out[f["from"]].append(f["to"])
            incoming[f["to"]] += 1
    forward: dict = {i: [] for i in ids}
    state: dict = {}

    def visit(node):  # iterative DFS; an edge to a node still on the stack is a back edge
        stack = [(node, iter(out[node]))]
        state[node] = 1
        while stack:
            current, it = stack[-1]
            for nxt in it:
                if state.get(nxt) == 1:
                    continue
                forward[current].append(nxt)
                if nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, iter(out[nxt])))
                    break
            else:
                state[current] = 2
                stack.pop()

    for start in [i for i in ids if incoming[i] == 0] + ids:
        if start not in state:
            visit(start)
    level = {i: 0 for i in ids}
    changed = True
    rounds = 0
    while changed and rounds <= len(ids) + 1:
        changed = False
        rounds += 1
        for a, targets in forward.items():
            for b in targets:
                if level[b] < level[a] + 1:
                    level[b] = level[a] + 1
                    changed = True
    return level


def _size(kind: str) -> tuple:
    return {"event": (36, 36), "gateway": (50, 50)}.get(kind, (110, 70))


def to_xml(key: str, name: str, definition: dict) -> str:
    steps, flows = definition.get("steps") or [], definition.get("flows") or []
    lanes = list(definition.get("lanes") or [])
    for s in steps:
        if s["lane"] not in lanes:
            lanes.append(s["lane"])
    by_id = {s["id"]: s for s in steps}
    incoming = {i: 0 for i in by_id}
    outgoing = {i: 0 for i in by_id}
    for f in flows:
        if f["from"] in by_id and f["to"] in by_id:
            outgoing[f["from"]] += 1
            incoming[f["to"]] += 1
    ET.register_namespace("bpmn", BPMN)
    ET.register_namespace("bpmndi", BPMNDI)
    ET.register_namespace("dc", DC)
    ET.register_namespace("di", DI)
    ET.register_namespace("pic", PIC)
    root = ET.Element(_q(BPMN, "definitions"), {"id": "Definitions_1", "targetNamespace": "https://alphahelion.io/pic/process"})
    process_id = "Process_" + re.sub(r"[^A-Za-z0-9_]", "_", key)
    collab = ET.SubElement(root, _q(BPMN, "collaboration"), {"id": "Collaboration_1"})
    ET.SubElement(collab, _q(BPMN, "participant"), {"id": "Participant_1", "name": name, "processRef": process_id})
    process = ET.SubElement(root, _q(BPMN, "process"), {"id": process_id, "name": name, "isExecutable": "false"})
    lane_set = ET.SubElement(process, _q(BPMN, "laneSet"), {"id": "LaneSet_1"})
    for index, lane in enumerate(lanes):
        element = ET.SubElement(lane_set, _q(BPMN, "lane"), {"id": f"Lane_{index}", "name": lane})
        for s in steps:
            if s["lane"] == lane:
                ET.SubElement(element, _q(BPMN, "flowNodeRef")).text = s["id"]
    for s in steps:
        kind = s["type"]
        if kind == "event":
            tag = "startEvent" if incoming[s["id"]] == 0 else "endEvent" if outgoing[s["id"]] == 0 else "intermediateThrowEvent"
        else:
            tag = TAGS[kind]
        attrs = {"id": s["id"], "name": s["name"]}
        if s.get("screen"):
            attrs[_q(PIC, "screen")] = str(s["screen"])
        if s.get("taskKind"):
            attrs[_q(PIC, "taskKind")] = s["taskKind"]
        if s.get("roles"):
            attrs[_q(PIC, "roles")] = ",".join(s["roles"])
        if s.get("slaBusinessDays"):
            attrs[_q(PIC, "sla")] = str(s["slaBusinessDays"])
        ET.SubElement(process, _q(BPMN, tag), attrs)
    flow_ids = []
    for index, f in enumerate(flows):
        if f["from"] not in by_id or f["to"] not in by_id:
            continue
        fid = f"Flow_{index + 1}"
        flow_ids.append((fid, f))
        attrs = {"id": fid, "sourceRef": f["from"], "targetRef": f["to"]}
        if f.get("label"):
            attrs["name"] = f["label"]
        ET.SubElement(process, _q(BPMN, "sequenceFlow"), attrs)

    # ---- diagram interchange
    level = _layout(steps, flows)
    width = POOL_X + LABEL_W + (max(level.values(), default=0) + 1) * COL + 60
    height = len(lanes) * LANE_H
    diagram = ET.SubElement(root, _q(BPMNDI, "BPMNDiagram"), {"id": "Diagram_1"})
    plane = ET.SubElement(diagram, _q(BPMNDI, "BPMNPlane"), {"id": "Plane_1", "bpmnElement": "Collaboration_1"})

    def shape(element_id: str, x: int, y: int, w: int, h: int, **extra):
        node = ET.SubElement(plane, _q(BPMNDI, "BPMNShape"), {"id": f"{element_id}_di", "bpmnElement": element_id, **extra})
        ET.SubElement(node, _q(DC, "Bounds"), {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})

    shape("Participant_1", POOL_X, POOL_Y, width - POOL_X, height, isHorizontal="true")
    for index in range(len(lanes)):
        shape(f"Lane_{index}", POOL_X + LABEL_W, POOL_Y + index * LANE_H, width - POOL_X - LABEL_W, LANE_H, isHorizontal="true")
    bounds = {}
    for s in steps:
        w, h = _size(s["type"])
        x = POOL_X + LABEL_W + 40 + level[s["id"]] * COL
        y = POOL_Y + lanes.index(s["lane"]) * LANE_H + (LANE_H - h) // 2
        bounds[s["id"]] = (x, y, w, h)
        shape(s["id"], x, y, w, h, **({"isMarkerVisible": "true"} if s["type"] == "gateway" else {}))
    for fid, f in flow_ids:
        sx, sy, sw, sh = bounds[f["from"]]
        tx, ty, tw, th = bounds[f["to"]]
        start, end = (sx + sw, sy + sh // 2), (tx, ty + th // 2)
        if tx > sx + sw:
            mid = (sx + sw + tx) // 2
            points = [start, (mid, start[1]), (mid, end[1]), end] if start[1] != end[1] else [start, end]
        else:  # back edge or same column: leave from the bottom, return to the bottom of the target
            low = max(sy + sh, ty + th) + 24
            points = [(sx + sw // 2, sy + sh), (sx + sw // 2, low), (tx + tw // 2, low), (tx + tw // 2, ty + th)]
        edge = ET.SubElement(plane, _q(BPMNDI, "BPMNEdge"), {"id": f"{fid}_di", "bpmnElement": fid})
        for px, py in points:
            ET.SubElement(edge, _q(DI, "waypoint"), {"x": str(px), "y": str(py)})
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def from_xml(xml: str) -> dict:
    """The definition JSON of a BPMN document: steps (type from the element), lanes, flows and the pic: attributes."""
    if not isinstance(xml, str) or not xml.strip():
        raise Problem(422, "BPMN_INVALID", "The BPMN document is empty")
    if len(xml) > 2_000_000:
        raise Problem(413, "PAYLOAD_TOO_LARGE", "The BPMN document is larger than 2 MB")
    if re.search(r"<!(DOCTYPE|ENTITY)", xml, re.I):
        raise Problem(422, "BPMN_INVALID", "DOCTYPE and ENTITY declarations are not allowed in BPMN documents")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise Problem(422, "BPMN_INVALID", f"The BPMN document is not well-formed XML: {exc}")
    process = root.find(_q(BPMN, "process"))
    if process is None:
        raise Problem(422, "BPMN_INVALID", "No bpmn:process in the document")
    lane_of: dict = {}
    lanes = []
    for lane in process.iter(_q(BPMN, "lane")):
        lanes.append(lane.get("name") or lane.get("id"))
        for ref in lane.findall(_q(BPMN, "flowNodeRef")):
            lane_of[(ref.text or "").strip()] = lanes[-1]
    steps, flows = [], []
    for child in process:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in REVERSE:
            step = {"id": child.get("id"), "type": REVERSE[tag], "lane": lane_of.get(child.get("id"), lanes[0] if lanes else "Process"),
                    "name": child.get("name") or child.get("id"), "screen": child.get(_q(PIC, "screen"))}
            if child.get(_q(PIC, "taskKind")):
                step["taskKind"] = child.get(_q(PIC, "taskKind"))
            if child.get(_q(PIC, "roles")):
                step["roles"] = [r for r in child.get(_q(PIC, "roles")).split(",") if r]
            if child.get(_q(PIC, "sla")):
                try:
                    step["slaBusinessDays"] = int(child.get(_q(PIC, "sla")))
                except ValueError:
                    raise Problem(422, "BPMN_INVALID", f"pic:sla of {step['id']} is not a number")
            steps.append(step)
        elif tag == "sequenceFlow":
            flow = {"from": child.get("sourceRef"), "to": child.get("targetRef")}
            if child.get("name"):
                flow["label"] = child.get("name")
            flows.append(flow)
    if not steps:
        raise Problem(422, "BPMN_INVALID", "The process has no tasks, events or gateways")
    return {"steps": steps, "flows": flows, "lanes": list(dict.fromkeys(lanes or [s["lane"] for s in steps]))}
