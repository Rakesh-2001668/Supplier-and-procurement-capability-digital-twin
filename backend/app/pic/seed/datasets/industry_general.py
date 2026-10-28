"""D7 general enterprise demo tenant GEN: laptop punch-out order ₹78,500, single approval (blueprint §23 / §23.1).

Brindavan Business Services Pvt Ltd (fictional shared-services company, Bengaluru HQ and a Hyderabad office) buys only
indirect spend. Everything runs through the domain services on the tenant's own timeline Oct 2026 – Mar 2027:

  bootstrap    tenant GEN from the GENERAL industry template (EXPENSE: receipt-less below ₹1 L, desktop receipt above),
               company code 1000 (GSTIN 29…, Karnataka), sites BLR1 Whitefield (29) and HYD1 HITEC City (36), cost centres
               1100 admin & facilities / 1200 IT end-user computing / 1300 Hyderabad office, budgets (initial load),
               taxonomy extension for office supplies, furniture and IT hardware
  F8           three suppliers onboarded: Lakeview IT Solutions (punch-out reseller), Deccan Office Supplies (catalogue),
               Cauvery Facility Management (housekeeping)
  M04 punch-out  cXML session against the built-in punch-out simulator (services/punchout.py, url "builtin"): catalogue page,
               checkout, PunchOutOrderMessage returned through the public return path, cart converted to a CATALOGUE
               requisition: laptop ₹78,500 → DMN-01 band ₹25k–2 L → one approval (IT cost-centre owner) → touchless PO →
               receipt-less (2-way, below ₹1 L) → e-invoice → posted → paid; a second punch-out (2 monitors, ₹23,800) is
               auto-approved under ₹25,000
  catalogue    monthly office-supplies orders from the internal catalogue (auto-approved, touchless, 2-way) and 12 office
               chairs for Hyderabad (₹1,62,000: one approval, desktop receipt by the requester, 3-way match)
  F9 + F4      housekeeping service master (SAC 998533) → value contract ₹1,68,000/month → PO for Nov–Mar → monthly service
               entries approved by the facilities manager → invoices matched against the service entries
  F7           monthly payment runs (N30)
"""
import html
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import (
    CatalogueItem, Contract, ContractLine, Invoice, InvoiceException, Material, Payment, PoLine, PunchoutSession, PurchaseOrder,
    Requisition, ServiceEntry, SpendLine, Supplier, Task, TaxonomyNode,
)
from app.pic.platform import audit, clock
from app.pic.platform.auth import Principal
from app.pic.platform.money import fmt_inr, line_amount
from app.pic.seed import reference
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets.industry_logistics import (
    create_users, days, gstin, load_budgets, new_tenant, onboard, post_invoice, relay, run_timeline, service_master,
)

KEY = "industry-general"
VERSION = "1"
TITLE = "D7 general enterprise demo tenant GEN: laptop punch-out order ₹78,500, single approval"
TENANTS = ('GEN',)
CREATES_TENANT = True
READY = True

TENANT = ("GEN", "Brindavan Business Services Pvt Ltd")
DOMAIN = "brindavan-services.example"
COMPANY_PAN = "AAHCB5532N"

USERS = [
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("ananya.rao", "Ananya Rao", ["REQUESTER", "RECEIVER"], {"cost_objects": ["COST_CENTER:1200"], "plants": ["BLR1"]}),
    ("office.admin", "Shalini Gowda", ["REQUESTER", "RECEIVER"], {"cost_objects": ["COST_CENTER:1100"], "plants": ["BLR1"]}),
    ("hyd.admin", "Karthik Reddy", ["REQUESTER", "RECEIVER"], {"cost_objects": ["COST_CENTER:1300"], "plants": ["HYD1"]}),
    ("it.manager", "Vivek Hegde", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:1200"], "plants": ["BLR1"]}),
    ("admin.manager", "Lavanya Murthy", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:1100", "COST_CENTER:1300"],
                                                                "plants": ["BLR1", "HYD1"]}),
    ("coo", "Rajesh Kulkarni", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:1100", "COST_CENTER:1200", "COST_CENTER:1300"],
                                               "plants": ["BLR1", "HYD1"]}),
    ("buyer", "Nikhil Shetty", ["BUYER"], {"plants": ["BLR1", "HYD1"]}),
    ("buyer.lead", "Pooja Nair", ["BUYER"], {"plants": ["BLR1", "HYD1"]}),
    ("category.manager", "Sandeep Rao", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("contract.manager", "Meera Iyengar", ["CONTRACT_MANAGER"], {}),
    ("procurement.head", "Arvind Bhat", ["PROCUREMENT_HEAD"], {}),
    ("supplier.manager", "Divya Prakash", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("finance.controller", "Ramya Krishnan", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Mohan Das", ["FINANCE_CONTROLLER"], {}),
    ("mdm.purchasing", "Tejas Kamath", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "Nisha Menon", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "Prakash Hiremath", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "Asha Kulkarni", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("facilities.manager", "Imran Pasha", ["SERVICE_OWNER"], {"cost_objects": ["COST_CENTER:1100"], "plants": ["BLR1"]}),
    ("ap.clerk", "Sunita Joshi", ["AP_CLERK"], {}),
]
ROLE_USER = {
    "COST_OBJECT_OWNER": ["it.manager", "admin.manager"], "DEPT_HEAD": "coo", "BUYER": "buyer.lead", "CATEGORY_MANAGER": "category.manager",
    "CONTRACT_MANAGER": "contract.manager", "PROCUREMENT_HEAD": "procurement.head",
    "FINANCE_CONTROLLER": ["finance.controller", "finance.controller2"], "SERVICE_OWNER": "facilities.manager",
    "MDM_STEWARD": ["mdm.purchasing", "mdm.quality", "mdm.finance", "mdm.plant"],
}

LVIT = {
    "code": "LVIT01", "name": "Lakeview IT Solutions Pvt Ltd", "gstin": gstin("29", "AAECL6610P"), "ifsc": "HDFC0001953", "account": "50200041187762",
    "terms": "N30", "categories": ["IT-HARDWARE"], "segment": "LEVERAGE", "user": "orders@lakeview-it.example",
    "user_name": "Lakeview IT Solutions – order desk",
    "address": {"line1": "3rd Floor, 80 Feet Road, Koramangala 4th Block", "city": "Bengaluru", "state_code": "29", "pin": "560034", "country": "IN"},
    "certificates": [{"type": "ISO9001", "number": "QMS-LVIT-2291", "issued_on": "2025-02-01", "expires_on": "2028-01-31"},
                     {"type": "OEM_AUTHORISATION", "number": "AUTH-RESELLER-LVIT-2026", "issued_on": "2026-04-01", "expires_on": "2027-12-31"}],
    "questionnaire": {"role": "authorised reseller", "punchout": "cXML 1.2", "warranty": "on-site, next business day"},
    "scores": (82, 80), "qualification_note": "Authorised reseller; punch-out catalogue with contracted corporate prices",
}
DOS = {
    "code": "DOS02", "name": "Deccan Office Supplies Pvt Ltd", "gstin": gstin("29", "AADCD3907R"), "ifsc": "KKBK0008067", "account": "8612447301",
    "terms": "N30", "categories": ["OFFICE-SUPPLIES", "OFFICE-FURNITURE"], "segment": "ROUTINE", "user": "sales@deccanofficesupplies.example",
    "user_name": "Deccan Office Supplies – key accounts",
    "address": {"line1": "No. 44, 2nd Stage, Peenya Industrial Area", "city": "Bengaluru", "state_code": "29", "pin": "560058", "country": "IN"},
    "certificates": [{"type": "ISO9001", "number": "QMS-DOS-7750", "issued_on": "2024-11-01", "expires_on": "2027-10-31"}],
    "questionnaire": {"delivery": "next day within Bengaluru, 3 days to Hyderabad", "catalogue": "annual price list"},
    "scores": (78, 79), "qualification_note": "Catalogue supplier for stationery, consumables and office furniture",
}
CFM = {
    "code": "CFM03", "name": "Cauvery Facility Management Pvt Ltd", "gstin": gstin("29", "AAICC8143E"), "ifsc": "CNRB0002714", "account": "2714201004583",
    "terms": "N30", "categories": ["FACILITIES"], "segment": "ROUTINE", "user": "billing@cauveryfm.example",
    "user_name": "Cauvery Facility Management – billing",
    "address": {"line1": "No. 1102, 24th Main, HSR Layout Sector 1", "city": "Bengaluru", "state_code": "29", "pin": "560102", "country": "IN"},
    "certificates": [{"type": "ISO9001", "number": "QMS-CFM-3318", "issued_on": "2025-08-01", "expires_on": "2028-07-31"},
                     {"type": "LABOUR_LICENCE", "number": "CLRA-KA-BLR-2026-04417", "issued_on": "2026-01-01", "expires_on": "2027-12-31"}],
    "questionnaire": {"staff": "PF/ESI registered", "training": "monthly hygiene training", "supervision": "on-site supervisor"},
    "scores": (80, 81), "qualification_note": "Contract-labour licence, PF/ESI compliance and site audit verified",
}

# Supplier catalogues: (supplier, part no, description, material group, category, unit, price ₹, HSN, GST %). Lakeview's rows
# are what its punch-out catalogue (the built-in simulator) shows; Deccan's are the internal catalogue for guided buying.
CATALOGUE = [
    ("LVIT01", "LV-NB14-U5-16-512", "14-inch business laptop – Intel Core Ultra 5, 16 GB RAM, 512 GB SSD, Windows 11 Pro, 3-year on-site warranty",
     "IT-NOTEBOOK", "IT-HARDWARE", "EA", 78_500, "84713010", 18),
    ("LVIT01", "LV-MON24-FHD", "24-inch full-HD IPS monitor, height-adjustable stand, HDMI and DisplayPort", "IT-MONITOR", "IT-HARDWARE",
     "EA", 11_900, "85285200", 18),
    ("DOS02", "DOS-TNR-BLK-A4", "Toner cartridge, black, for A4 mono laser printer (1,600 pages)", "OFF-SUPPLIES", "OFFICE-SUPPLIES",
     "EA", 3_250, "844399", 18),
    ("DOS02", "DOS-PEN-BL50", "Ball pen, blue, 0.7 mm (box of 50)", "OFF-SUPPLIES", "OFFICE-SUPPLIES", "BOX", 450, "960810", 18),
    ("DOS02", "DOS-WBM-10", "Whiteboard marker, assorted colours (pack of 10)", "OFF-SUPPLIES", "OFFICE-SUPPLIES", "PAC", 380, "96082000", 18),
    ("DOS02", "DOS-CHR-MESH", "Ergonomic mesh office chair, lumbar support, adjustable arms", "OFF-FURNITURE", "OFFICE-FURNITURE",
     "EA", 13_500, "94013900", 18),
]
TAXONOMY = [
    ("IND-OFFICE", "INDIRECT", 2, "Office and workplace", []),
    ("OFFICE-SUPPLIES", "IND-OFFICE", 3, "Office supplies and stationery", ["toner", "cartridge", "stationery", "ball pen", "marker", "stapler"]),
    ("OFFICE-FURNITURE", "IND-OFFICE", 3, "Office furniture", ["chair", "desk", "workstation", "furniture", "cabinet"]),
    ("IND-IT", "INDIRECT", 2, "IT and end-user computing", []),
    ("IT-HARDWARE", "IND-IT", 3, "End-user computing hardware", ["laptop", "notebook", "monitor", "docking", "desktop computer"]),
]
# Monthly office-supplies orders (internal catalogue, cost centre 1100): order date, need date, (part, qty).
SUPPLY_ORDERS = [
    (date(2026, 11, 16), [("DOS-TNR-BLK-A4", 3), ("DOS-PEN-BL50", 4), ("DOS-WBM-10", 5)]),
    (date(2026, 12, 14), [("DOS-TNR-BLK-A4", 4), ("DOS-PEN-BL50", 2), ("DOS-WBM-10", 4)]),
    (date(2027, 1, 18), [("DOS-TNR-BLK-A4", 3), ("DOS-PEN-BL50", 6), ("DOS-WBM-10", 6)]),
    (date(2027, 2, 15), [("DOS-TNR-BLK-A4", 5), ("DOS-WBM-10", 3)]),
    (date(2027, 3, 15), [("DOS-TNR-BLK-A4", 4), ("DOS-PEN-BL50", 4), ("DOS-WBM-10", 5)]),
]
HOUSEKEEPING_MONTHLY = 168_000   # ₹ per month: 6 housekeepers × 26 days incl. consumables
SERVICE_MONTHS = [(date(2026, 11, 1), date(2026, 11, 30)), (date(2026, 12, 1), date(2026, 12, 31)), (date(2027, 1, 1), date(2027, 1, 30)),
                  (date(2027, 2, 1), date(2027, 2, 27)), (date(2027, 3, 1), date(2027, 3, 31))]
PAYMENT_RUNS = [date(2026, 12, 15), date(2027, 1, 15), date(2027, 2, 15), date(2027, 3, 15)]


def _configure(sc: Scenario, suppliers: dict) -> None:
    """Taxonomy extension (ADM-02), supplier catalogues (initial load) and Lakeview's punch-out endpoint (M04)."""
    from app.pic.services import punchout
    when = at(date(2026, 10, 10), 10)
    with sc.act("admin", when) as s:
        have = set(s.execute(select(TaxonomyNode.code)).scalars())
        for code, parent, level, name, keywords in TAXONOMY:
            if code not in have:
                s.add(TaxonomyNode(tenant_id=sc.tenant_id, code=code, parent_code=parent, level=level, name=name, keywords=keywords,
                                   addressable=True))
        s.flush()
        audit.record(s, "TAXONOMY", uuid.uuid5(uuid.NAMESPACE_URL, "GEN-taxonomy"), "EXTENDED", object_ref="spend taxonomy",
                     after={"nodes": [t[0] for t in TAXONOMY]}, reason="General enterprise template: office, furniture and IT hardware")
        for supplier, part, description, group, category, uom, price, hsn, gst in CATALOGUE:
            s.add(CatalogueItem(tenant_id=sc.tenant_id, supplier_id=suppliers[supplier], supplier_part_no=part, description=description,
                                material_group=group, category=category, uom=uom, price_minor=price * 100, gst_rate=Decimal(gst), hsn_code=hsn))
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, "GEN-catalogues"), "INITIAL_LOAD", object_ref="supplier catalogues",
                     after={"items": [c[1] for c in CATALOGUE]}, actor="migration")
    with sc.act("supplier.manager", at(date(2026, 10, 10), 11)) as s:
        punchout.configure(s, s.get(Supplier, suppliers["LVIT01"]), protocol="CXML", url=punchout.BUILTIN, identity="LAKEVIEW-IT-CXML",
                           shared_secret="lakeview-demo-secret-2026")
    sc.note("Taxonomy extended (office supplies, furniture, IT hardware); catalogues loaded; Lakeview cXML punch-out configured (built-in simulator)")


def _punch_out(sc: Scenario, picks: dict, at_time, *, purpose_code: str, purpose_text: str, need_date: date) -> dict:
    """M04 end to end with the built-in supplier: setup → catalogue page → checkout → cart return → requisition."""
    from app.pic.services import punchout, requisition
    from app.pic.services.common import supplier_by_code
    with sc.act("ananya.rao", at_time) as s:
        started = punchout.start(s, supplier_by_code(s, "LVIT01"))
        cookie = started["buyer_cookie"]
        items = {c.supplier_part_no: str(c.id) for c in s.execute(select(CatalogueItem).where(CatalogueItem.supplier_id == supplier_by_code(s, "LVIT01").id)).scalars()}
    clock.set_pinned(at_time + timedelta(minutes=4))
    with tenant_tx(sc.tenant_id) as s:   # the simulated supplier's pages (public, no user session)
        page = punchout.simulator_catalogue(s, cookie, {})
        if "online catalogue" not in page:
            raise RuntimeError("The built-in punch-out catalogue page did not render")
        checkout = punchout.simulator_checkout(s, {"cookie": cookie, **{f"qty_{items[part]}": str(qty) for part, qty in picks.items()}})
    document = html.unescape(re.search(r'name="cxml-urlencoded" value="([^"]*)"', checkout).group(1))
    cookie_back, protocol, cart, raw = punchout.decode_return({"cxml-urlencoded": document}, None)
    with tenant_tx(sc.tenant_id) as s:   # the public return endpoint acts as the PUNCHOUT_RETURN gateway
        s.info["principal"] = Principal(user_id=uuid.UUID(int=0), tenant_id=sc.tenant_id, tenant_code=sc.tenant_code,
                                        email="punchout_return@gateway.pic", name="PUNCHOUT_RETURN", roles=[], scopes=set(),
                                        agent_code="PUNCHOUT_RETURN")
        punchout.receive(s, cookie_back, protocol, cart, raw)
    with sc.act("ananya.rao", at_time + timedelta(minutes=8)) as s:
        ps = punchout.get(s, cookie)
        pr = punchout.convert(s, ps, plant="BLR1", purpose_code=purpose_code, purpose_text=purpose_text, need_date=need_date,
                              purchase_type="EXPENSE", account_assignment_type="COST_CENTER", account_assignment_code="1200")
        submitted = requisition.submit(s, pr)
        return {"requisition": pr.number, "requisitionId": pr.id, "chain": submitted["chain"], "status": pr.status,
                "session": punchout.view(s, ps)["number"], "totalMinor": pr.total_minor}


def _laptop(sc: Scenario, state: dict):
    from app.pic.services import order, payables
    t = at(date(2026, 11, 9), 10)
    yield t
    cart = _punch_out(sc, {"LV-NB14-U5-16-512": 1}, t, purpose_code="NEW_JOINER", need_date=date(2026, 11, 16),
                      purpose_text="Laptop for new joiner – finance analyst, Bengaluru HQ (joining 16 Nov)")
    t = at(date(2026, 11, 9), 15)
    yield t
    approvals = sc.approve_all(cart["requisitionId"], t, "Standard laptop for a new joiner; within the IT budget")
    t = at(date(2026, 11, 10), 10)
    yield t
    with sc.act("buyer", t) as s:
        po = order.create_from_requisition(s, requisition=cart["requisition"], lines=[10], supplier_code="LVIT01")[0]
        po_id, po_no, touchless = po.id, po.number, po.touchless
    relay(sc, at(date(2026, 11, 10), 10, 30))
    t = at(date(2026, 11, 10), 16)
    yield t
    with sc.act(LVIT["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Ships from Bengaluru stock; delivery 12 Nov with asset tag")
    t = at(date(2026, 11, 13), 11)
    yield t
    with sc.act(LVIT["user"], t) as s:
        invoice = payables.capture(s, supplier="LVIT01", supplier_invoice_no="LVIT/26-27/2214", invoice_date=date(2026, 11, 13), channel="E_INVOICE",
                                   irn=payables.expected_irn(LVIT["gstin"], "2026-27", "INV", "LVIT/26-27/2214"),
                                   lines=[{"po": po_no, "po_line": 10, "qty": "1", "unit_price": "78500.00", "gst_rate": "18", "hsn": "84713010",
                                           "description": "Business laptop 14-inch Core Ultra 5 16/512, S/N LV5X-26-118204"}])
        invoice_id, status, match_type = invoice.id, invoice.status, invoice.match_type
    t = at(date(2026, 11, 16), 11)
    yield t
    post_invoice(sc, invoice_id, t, "LVIT01")
    relay(sc, at(date(2026, 11, 16), 12))
    state["laptop"] = {**{k: v for k, v in cart.items() if k != "requisitionId"}, "approvals": approvals, "po": po_no, "touchless": touchless,
                       "invoice": "LVIT/26-27/2214", "invoiceStatus": status, "matchType": match_type}
    sc.note(f"M04 punch-out {cart['session']} → {cart['requisition']} laptop {fmt_inr(cart['totalMinor'])}: route "
            f"{' → '.join(cart['chain'])} ({approvals} approval) → {po_no} touchless={touchless} → LVIT/26-27/2214 {match_type} {status} → posted")


def _monitors(sc: Scenario, state: dict):
    from app.pic.services import order, payables
    t = at(date(2027, 1, 20), 10)
    yield t
    cart = _punch_out(sc, {"LV-MON24-FHD": 2}, t, purpose_code="WORKPLACE", need_date=date(2027, 1, 27),
                      purpose_text="Second monitors for two finance analysts (month-end close)")
    t = at(date(2027, 1, 20), 14)
    yield t
    with sc.act("buyer", t) as s:
        po = order.create_from_requisition(s, requisition=cart["requisition"], lines=[10], supplier_code="LVIT01")[0]
        po_id, po_no = po.id, po.number
    relay(sc, at(date(2027, 1, 20), 14, 30))
    t = at(date(2027, 1, 20), 17)
    yield t
    with sc.act(LVIT["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED")
    t = at(date(2027, 1, 23), 11)
    yield t
    with sc.act(LVIT["user"], t) as s:
        invoice = payables.capture(s, supplier="LVIT01", supplier_invoice_no="LVIT/26-27/2731", invoice_date=date(2027, 1, 23), channel="E_INVOICE",
                                   irn=payables.expected_irn(LVIT["gstin"], "2026-27", "INV", "LVIT/26-27/2731"),
                                   lines=[{"po": po_no, "po_line": 10, "qty": "2", "unit_price": "11900.00", "gst_rate": "18", "hsn": "85285200"}])
        invoice_id = invoice.id
    t = at(date(2027, 1, 25), 11)
    yield t
    post_invoice(sc, invoice_id, t, "LVIT01")
    relay(sc, at(date(2027, 1, 25), 12))
    state["monitors"] = {"requisition": cart["requisition"], "status": cart["status"], "chain": cart["chain"], "po": po_no}
    sc.note(f"M04 punch-out {cart['session']} → {cart['requisition']} 2 monitors {fmt_inr(cart['totalMinor'])}: catalogue below ₹25,000 → "
            f"auto-approved by DMN-01 (status {cart['status']}, no approval task) → {po_no} → LVIT/26-27/2731 posted")


def _supplies(sc: Scenario, state: dict, n: int, ordered: date, picks: list):
    from app.pic.services import order, payables, requisition
    t = at(ordered, 10)
    yield t
    with sc.act("office.admin", t) as s:
        items = {c.supplier_part_no: c for c in s.execute(select(CatalogueItem)).scalars()}
        requisition.search(s, "toner cartridge", "BLR1")
        pr = requisition.create(s, origin="CATALOGUE", purpose_code="OFFICE_CONSUMABLES", plant="BLR1",
                                purpose_text=f"Monthly stationery and printer consumables – Bengaluru HQ ({ordered:%b %Y})",
                                lines=[{"item_type": "CATALOGUE", "purchase_type": "EXPENSE", "catalogue_item_id": str(items[part].id), "qty": str(qty),
                                        "account_assignment_type": "COST_CENTER", "account_assignment_code": "1100",
                                        "need_date": (ordered + days(3)).isoformat()} for part, qty in picks])
        result = requisition.submit(s, pr)
        pr_no, pr_status = pr.number, pr.status
        prices = {part: items[part] for part, _ in picks}
    t = at(ordered, 14)
    yield t
    with sc.act("buyer", t) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10 * (i + 1) for i in range(len(picks))], supplier_code="DOS02")[0]
        po_id, po_no, touchless = po.id, po.number, po.touchless
    relay(sc, at(ordered, 14, 30))
    t = at(ordered, 17)
    yield t
    with sc.act(DOS["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED")
    invoice_no = f"DOS/26-27/{5100 + n * 37}"
    invoice_day = ordered + days(3)
    t = at(invoice_day, 12)
    yield t
    with sc.act(DOS["user"], t) as s:
        invoice = payables.capture(s, supplier="DOS02", supplier_invoice_no=invoice_no, invoice_date=invoice_day, channel="PORTAL",
                                   lines=[{"po": po_no, "po_line": 10 * (i + 1), "qty": str(qty), "unit_price": f"{prices[part].price_minor / 100:.2f}",
                                           "gst_rate": f"{prices[part].gst_rate:.0f}", "hsn": prices[part].hsn_code} for i, (part, qty) in enumerate(picks)])
        invoice_id, status = invoice.id, invoice.status
    t = at(invoice_day + days(1), 11)
    yield t
    post_invoice(sc, invoice_id, t, "DOS02")
    relay(sc, at(invoice_day + days(1), 12))
    state["supplies"].append({"requisition": pr_no, "status": pr_status, "chain": result["chain"], "po": po_no, "touchless": touchless,
                              "invoice": invoice_no, "invoiceStatus": status})


def _chairs(sc: Scenario, state: dict):
    """₹1,62,000 EXPENSE above the ₹1 L receipt-less threshold: one approval, desktop receipt by the requester, 3-way match."""
    from app.pic.services import order, payables, receiving, requisition
    t = at(date(2026, 12, 7), 10)
    yield t
    with sc.act("hyd.admin", t) as s:
        chair = s.execute(select(CatalogueItem).where(CatalogueItem.supplier_part_no == "DOS-CHR-MESH")).scalar_one()
        pr = requisition.create(s, origin="CATALOGUE", purpose_code="WORKPLACE", plant="HYD1",
                                purpose_text="Seating for 12 new workstations, Hyderabad office (finance shared services expansion)",
                                lines=[{"item_type": "CATALOGUE", "purchase_type": "EXPENSE", "catalogue_item_id": str(chair.id), "qty": "12",
                                        "account_assignment_type": "COST_CENTER", "account_assignment_code": "1300", "need_date": "2026-12-16"}])
        result = requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    t = at(date(2026, 12, 7), 16)
    yield t
    approvals = sc.approve_all(pr_id, t, "Budgeted Hyderabad expansion; catalogue price")
    t = at(date(2026, 12, 8), 10)
    yield t
    with sc.act("buyer", t) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="DOS02")[0]
        po_id, po_no = po.id, po.number
    relay(sc, at(date(2026, 12, 8), 10, 30))
    t = at(date(2026, 12, 8), 15)
    yield t
    with sc.act(DOS["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Dispatch from Bengaluru 13 Dec; delivery Hyderabad 16 Dec")
    t = at(date(2026, 12, 16), 16)
    yield t
    with sc.act("hyd.admin", t) as s:   # desktop receipt by the requester
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), delivery_note="DOS/DC/2612/0311", posting_date=date(2026, 12, 16),
                               lines=[{"line": 10, "qty": "12"}])
        gr_no = gr.number
    t = at(date(2026, 12, 17), 12)
    yield t
    with sc.act(DOS["user"], t) as s:
        invoice = payables.capture(s, supplier="DOS02", supplier_invoice_no="DOS/26-27/5390", invoice_date=date(2026, 12, 17), channel="PORTAL",
                                   lines=[{"po": po_no, "po_line": 10, "qty": "12", "unit_price": "13500.00", "gst_rate": "18", "hsn": "94013900"}])
        invoice_id, status, match_type = invoice.id, invoice.status, invoice.match_type
    t = at(date(2026, 12, 18), 11)
    yield t
    post_invoice(sc, invoice_id, t, "DOS02")
    relay(sc, at(date(2026, 12, 18), 12))
    state["chairs"] = {"requisition": pr_no, "chain": result["chain"], "approvals": approvals, "po": po_no, "gr": gr_no, "matchType": match_type,
                       "invoiceStatus": status}
    sc.note(f"Catalogue {pr_no} 12 chairs ₹1,62,000 (route {' → '.join(result['chain'])}) → {po_no} → desktop receipt {gr_no} by the requester "
            f"→ DOS/26-27/5390 {match_type} {status} → posted")


def _housekeeping(sc: Scenario, state: dict, suppliers: dict):
    from app.pic.services import contract as contract_svc
    from app.pic.services import order, payables, receiving, requisition
    t = at(date(2026, 10, 12), 10)
    yield t
    mrq_no, material_no = service_master(sc, "category.manager", t, description="Housekeeping services - office premises, monthly",
                                         material_group="FAC-HOUSEKEEP", category="FACILITIES", uom="MON", sac="998533",
                                         attributes={"scope": "office housekeeping", "basis": "monthly fixed fee"})
    t = at(date(2026, 10, 14), 11)
    yield t
    with sc.act("category.manager", t) as s:
        material = s.execute(select(Material).where(Material.number == material_no)).scalar_one()
        contract = contract_svc.create_draft(
            s, type="VALUE_CONTRACT", title="Housekeeping services – Bengaluru HQ Whitefield – Cauvery Facility Management",
            supplier_id=suppliers["CFM03"], company_code="1000", valid_from=date(2026, 11, 1), valid_to=date(2027, 10, 31), payment_terms="N30",
            incoterms=None, owner_id=s.info["principal"].user_id, tolerances={"over_pct": "0", "under_pct": "0", "price_pct": "0"},
            lines=[{"material_id": material.id, "plant": "BLR1", "uom": "MON", "target_qty": "12", "unit_price_minor": HOUSEKEEPING_MONTHLY * 100,
                    "description": "Housekeeping – Bengaluru HQ (6 housekeepers, 26 days/month, consumables included)"}],
            trigger="3-quote policy: Cauvery FM lowest of three quotes")
        contract_id, contract_no = contract.id, contract.number
        line_id = s.execute(select(ContractLine.id).where(ContractLine.contract_id == contract_id)).scalar_one()
    t = at(date(2026, 10, 15), 10)
    yield t
    with sc.act("contract.manager", t) as s:
        contract_svc.ai_review(s, s.get(Contract, contract_id))
        contract_svc.submit(s, s.get(Contract, contract_id))
    t = at(date(2026, 10, 16), 11)
    yield t
    sc.approve_all(contract_id, t, "Standard clauses; value below ₹1 Cr")
    t = at(date(2026, 10, 19), 10)
    yield t
    with sc.act("contract.manager", t) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Meera Iyengar, Contract Manager")
    with sc.act(CFM["user"], at(date(2026, 10, 19), 15)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", "S. Nagaraj, Managing Director – Cauvery Facility Management")
    t = at(date(2026, 10, 20), 10)
    yield t
    with sc.act("contract.manager", t) as s:
        contract_svc.activate(s, s.get(Contract, contract_id))
    relay(sc, at(date(2026, 10, 20), 11))
    t = at(date(2026, 10, 26), 10)
    yield t
    with sc.act("office.admin", t) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="FACILITY_SERVICES", plant="BLR1",
                                purpose_text="Housekeeping Bengaluru HQ, Nov 2026 – Mar 2027 (call-off on the housekeeping contract)",
                                lines=[{"item_type": "CONTRACT", "purchase_type": "SERVICE", "material": material_no, "contract_line_id": str(line_id),
                                        "qty": "5", "account_assignment_type": "COST_CENTER", "account_assignment_code": "1100",
                                        "need_date": "2027-03-31"}])
        result = requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    t = at(date(2026, 10, 27), 11)
    yield t
    approvals = sc.approve_all(pr_id, t, "Within the facilities budget")
    t = at(date(2026, 10, 28), 10)
    yield t
    with sc.act("buyer", t) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10], contract_ref=contract_no, need_date=date(2026, 11, 1))[0]
        po_id, po_no, touchless = po.id, po.number, po.touchless
    relay(sc, at(date(2026, 10, 28), 10, 30))
    t = at(date(2026, 10, 28), 16)
    yield t
    with sc.act(CFM["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Team of 6 deployed from 1 Nov; supervisor Mr. Raju")
    state["housekeeping"] = {"serviceMaster": material_no, "materialRequest": mrq_no, "contract": contract_no, "requisition": pr_no,
                             "chain": result["chain"], "approvals": approvals, "po": po_no, "touchless": touchless, "invoices": []}
    sc.note(f"F9 {mrq_no} → {material_no} (SAC 998533); F4 {contract_no} ₹1,68,000/month active from 1 Nov; {pr_no} "
            f"(route {' → '.join(result['chain'])}) → {po_no} Nov–Mar touchless={touchless}")
    for i, (start, end) in enumerate(SERVICE_MONTHS, start=1):
        t = at(end, 15)
        yield t
        with sc.act(CFM["user"], t) as s:
            ses = receiving.create_ses(s, s.get(PurchaseOrder, po_id), method="UNIT_RATE", period_from=start, period_to=end,
                                       lines=[{"line": 10, "qty": "1",
                                               "description": f"Housekeeping {start:%b %Y} – 6 staff, attendance register countersigned by admin"}])
            receiving.submit_ses(s, ses)
            ses_id = ses.id
        t = at(end, 17)
        yield t
        sc.approve_all(ses_id, t, f"Attendance and checklist audit for {start:%b %Y} verified")
        invoice_no = f"CFM/26-27/{1100 + i:04d}"
        t = at(end, 18)
        yield t
        with sc.act(CFM["user"], t) as s:
            invoice = payables.capture(s, supplier="CFM03", supplier_invoice_no=invoice_no, invoice_date=end, channel="PORTAL",
                                       lines=[{"po": po_no, "po_line": 10, "qty": "1", "unit_price": f"{HOUSEKEEPING_MONTHLY}.00", "gst_rate": "18",
                                               "hsn": "998533", "description": f"Housekeeping services {start:%B %Y}"}])
            invoice_id = invoice.id
        t = at(end, 19)
        yield t
        post_invoice(sc, invoice_id, t, "CFM03")
        relay(sc, at(end, 19, 30))
        state["housekeeping"]["invoices"].append(invoice_no)


def _payment_run(sc: Scenario, state: dict, run_day: date):
    from app.pic.services import payables
    t = at(run_day, 10)
    yield t
    with sc.act("finance.controller", t) as s:
        run = payables.payment_run(s, run_day)
    relay(sc, at(run_day, 11))
    state["runs"].append(run)
    sc.note(f"F7 payment run {run['run']} ({run_day}): {len(run['paid'])} invoice(s) paid, {fmt_inr(sum(p['amountMinor'] for p in run['paid']))}")


def apply(tenant_code: str, password: str) -> dict:
    if tenant_code != TENANT[0]:
        raise ValueError(f"{KEY} creates tenant {TENANT[0]} only")
    clock.set_pinned(at(date(2026, 10, 1), 9))
    tenant_id = new_tenant(*TENANT, "GENERAL", company_gstin=gstin("29", COMPANY_PAN),
                           plants=[("BLR1", "Bengaluru HQ – Whitefield", "29"), ("HYD1", "Hyderabad office – HITEC City", "36")],
                           cost_objects=[("COST_CENTER", "1100", "Administration & facilities – Bengaluru"),
                                         ("COST_CENTER", "1200", "IT end-user computing"), ("COST_CENTER", "1300", "Hyderabad office")],
                           holidays=[date(2026, 10, 2), date(2026, 11, 1), date(2026, 12, 25), date(2027, 1, 26)])
    sc = Scenario(tenant_id, TENANT[0], DOMAIN, ROLE_USER)
    create_users(sc, USERS, password)
    load_budgets(sc, [("COST_CENTER", "1100", "SOFT", 30 * reference.L), ("COST_CENTER", "1200", "SOFT", 45 * reference.L),
                      ("COST_CENTER", "1300", "SOFT", 8 * reference.L)], at(date(2026, 10, 1), 9, 15), "budgets")
    sc.note("Tenant GEN from the GENERAL template: EXPENSE receipt-less below ₹1 L (2-way), desktop receipt above (3-way)")
    suppliers = {spec["code"]: onboard(sc, spec, password, day)
                 for spec, day in ((LVIT, date(2026, 10, 5)), (DOS, date(2026, 10, 6)), (CFM, date(2026, 10, 7)))}
    _configure(sc, suppliers)

    state = {"supplies": [], "runs": []}
    processes = [_housekeeping(sc, state, suppliers), _laptop(sc, state), _monitors(sc, state), _chairs(sc, state)]
    processes += [_supplies(sc, state, n, ordered, picks) for n, (ordered, picks) in enumerate(SUPPLY_ORDERS, start=1)]
    processes += [_payment_run(sc, state, run_day) for run_day in PAYMENT_RUNS]
    run_timeline(processes)
    relay(sc, at(date(2027, 3, 31), 20))

    # ------------------------------------------------------------ summary and KPIs (BP §23: catalogue adoption, PR cycle time, maverick)
    with tenant_tx(tenant_id) as s:
        counts = {
            "suppliers": s.execute(select(func.count()).select_from(Supplier)).scalar(),
            "catalogueItems": s.execute(select(func.count()).select_from(CatalogueItem)).scalar(),
            "punchoutSessions": s.execute(select(func.count()).select_from(PunchoutSession)).scalar(),
            "requisitions": s.execute(select(func.count()).select_from(Requisition)).scalar(),
            "contracts": s.execute(select(func.count()).select_from(Contract)).scalar(),
            "purchaseOrders": s.execute(select(func.count()).select_from(PurchaseOrder)).scalar(),
            "serviceEntries": s.execute(select(func.count()).select_from(ServiceEntry)).scalar(),
            "invoices": s.execute(select(func.count()).select_from(Invoice)).scalar(),
            "invoiceExceptions": s.execute(select(func.count()).select_from(InvoiceException)).scalar(),
            "payments": s.execute(select(func.count()).select_from(Payment)).scalar(),
            "spendLines": s.execute(select(func.count()).select_from(SpendLine)).scalar(),
            "openTasks": s.execute(select(func.count()).select_from(Task).where(Task.status == "OPEN")).scalar(),
        }
        po_lines = s.execute(select(PoLine)).scalars().all()
        catalogue_value = sum(l.net_minor for l in po_lines if l.item_type == "CATALOGUE")
        guided_value = sum(l.net_minor for l in po_lines if l.item_type in ("CATALOGUE", "CONTRACT"))
        total_value = sum(l.net_minor for l in po_lines)
        cycle = [(pr.approved_at - pr.submitted_at).total_seconds() / 3600 for pr in s.execute(select(Requisition)).scalars()
                 if pr.approved_at and pr.submitted_at]
        spend = s.execute(select(SpendLine)).scalars().all()
        maverick = sum(l.amount_minor for l in spend if l.maverick_flags)
        spend_total = sum(l.amount_minor for l in spend)
    kpis = {"catalogueAdoptionPct": f"{Decimal(catalogue_value) * 100 / total_value:.1f}" if total_value else "0",
            "guidedBuyingPct": f"{Decimal(guided_value) * 100 / total_value:.1f}" if total_value else "0",
            "prCycleTimeHoursAvg": f"{sum(cycle) / len(cycle):.1f}" if cycle else None,
            "maverickPct": f"{Decimal(maverick) * 100 / spend_total:.1f}" if spend_total else "0",
            "spendMinor": spend_total, "poValueMinor": total_value, "laptopNetMinor": line_amount(1, 7_850_000)}
    sc.note(f"KPIs: catalogue adoption {kpis['catalogueAdoptionPct']} % of PO value (catalogue + contract "
            f"{kpis['guidedBuyingPct']} %), PR cycle time {kpis['prCycleTimeHoursAvg']} h, "
            f"maverick {kpis['maverickPct']} %; spend {fmt_inr(spend_total)} over {counts['spendLines']} lines; {len(state['runs'])} payment runs")
    clock.set_pinned(None)
    return {"notes": sc.log, "counts": {**counts, "kpis": kpis, "laptop": state.get("laptop"), "monitors": state.get("monitors"),
                                        "chairs": state.get("chairs"), "housekeeping": state.get("housekeeping"),
                                        "supplyOrders": [o["requisition"] for o in state["supplies"]],
                                        "paymentRuns": [r["run"] for r in state["runs"]], "paid": sum(len(r["paid"]) for r in state["runs"])}}
