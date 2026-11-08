"""D20 material master governance cases on the Axion tenant (August 2027, flow fixes A8 / A9).

The pack adds a material of its own through the F9 workflow and then exercises the change governance of an existing material, so there
is a demo case on every screen of the material master (MDM-02 steward workbench):

  F9      hydraulic hose assembly through the four data stewards; a STOCK material, so it is created plannable (MRP type PD, rule
          MATERIAL-DEFAULTS) instead of ND
  MCR 1   the MRP controller changes the planning data (safety stock 50, planned delivery 7 days, PERIOD lot size): routed to the PLANT
          steward, approved -> APPLIED, material version 2, ERP material master updated (MAT|<number>|2)
  MCR 2   the requester corrects the HSN code: FINANCE owns it and PURCHASING must also approve (stock material) -> left IN_APPROVAL in
          the two stewards' inboxes
  MRQ     a second request for the same hose is blocked as a duplicate and the requester withdraws it (WITHDRAWN, steward tasks none)

Nothing of the signature case or of the other packs is touched: the material is new and is looked up by its description.
"""
from datetime import date, datetime

from sqlalchemy import select

from app.pic.models import Material, MaterialChangeRequest, MaterialRequest
from app.pic.platform import clock
from app.pic.seed import axion
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION, Scenario, at
from app.pic.seed.datasets.purchase_types import material_via_f9, tenant_id_of

KEY = "axn-material-governance"
VERSION = "1"
TITLE = "D20 material master governance: change requests (applied and in approval), a withdrawn duplicate request (AXN, August 2027)"
TENANTS = ('AXN',)
CREATES_TENANT = False
READY = True
REQUIRES = {SIGNATURE_KEY: SIGNATURE_VERSION}

HOSE = "Hydraulic hose assembly 1/2 in two-wire braid 600 mm JIC female both ends"


def _aug(day: int, hour: int = 10) -> datetime:
    return at(date(2027, 8, day), hour)


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import material_changes, mdm

    sc = Scenario(tenant_id_of(tenant_code), tenant_code, axion.DOMAIN)
    notes, counts = [], {}
    number = material_via_f9(sc, "requester", _aug(2, 9), description=HOSE, type="STOCK", material_group="HYDRAULICS", category="MRO",
                             base_uom="EA", hsn_code="40093100", mpn="HH-08-2W-600-JIC", attributes={"size": "1/2 in", "length_mm": 600})
    with sc.act("mrp.controller", _aug(3, 10)) as s:
        material = s.execute(select(Material).where(Material.number == number).with_for_update()).scalar_one()
        notes.append(f"F9 {number} {HOSE}: created with MRP type {material.mrp_type} (stock material default)")
        planning = material_changes.request_change(s, material, {"safety_stock": 50, "planned_delivery_days": 7, "lot_size_policy": "PERIOD"},
                                                   "Planning data for the new hose: two weeks of consumption as buffer, weekly lots")
        planning_no, planning_id = planning.number, planning.id
    with sc.act("mdm.plant", _aug(3, 15)) as s:
        material_changes.decide(s, s.get(MaterialChangeRequest, planning_id), "APPROVE", "Planning data checked against the consumption history")
    with sc.act("requester", _aug(4, 11)) as s:
        material = s.execute(select(Material).where(Material.number == number).with_for_update()).scalar_one()
        pending = material_changes.request_change(s, material, {"hsn_code": "40094100"},
                                                  "HSN correction: hose assemblies with fittings are classified under 4009 41")
        pending_no = pending.number
    with sc.act("requester", _aug(5, 10)) as s:
        duplicate = mdm.create_request(s, description=HOSE, type="STOCK", material_group="HYDRAULICS", category="MRO", base_uom="EA",
                                       hsn_code="40093100", mpn="HH-08-2W-600-JIC")
        duplicate_no, duplicate_status = duplicate.number, duplicate.status
        if duplicate.status in mdm.WITHDRAWABLE:
            mdm.withdraw(s, duplicate, f"Raised twice: {number} already exists and is used instead")
    with sc.act("requester", _aug(5, 11)) as s:
        applied = s.get(MaterialChangeRequest, planning_id)
        material = s.execute(select(Material).where(Material.number == number)).scalar_one()
        withdrawn = s.execute(select(MaterialRequest.status).where(MaterialRequest.number == duplicate_no)).scalar()
        notes.append(f"{planning_no} planning data (safety stock, lead time, PERIOD lot size): {applied.status}, {number} version {material.version}")
        notes.append(f"{pending_no} HSN correction: IN_APPROVAL with the FINANCE and PURCHASING stewards")
        notes.append(f"{duplicate_no} second request for the hose: {duplicate_status} -> {withdrawn}")
    clock.set_pinned(None)
    counts.update({"materials": 1, "changeRequests": 2, "withdrawnRequests": 1 if withdrawn == "WITHDRAWN" else 0})
    return {"notes": notes, "counts": counts, "material": number, "changeRequests": [planning_no, pending_no], "withdrawn": duplicate_no}
