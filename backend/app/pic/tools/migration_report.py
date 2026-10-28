"""Render the legacy-migration reconciliation report (docs/PIC_Legacy_Migration_Report.md)."""
from collections import defaultdict

SEVERITY = ["Critical", "High", "Medium", "Low"]
EXPLAIN = {
    "OVERPAID_PO": "More invoices were paid against the PO than its value.",
    "PAID_BEFORE_APPROVAL": "An invoice was paid while its PO was still waiting for approval.",
    "PAID_WITHOUT_RECEIPT": "An invoice was paid with no goods receipt (no 3-way match).",
    "PAID_DISPUTED_INVOICE": "An invoice was paid while marked as disputed.",
    "CLOSED_WITHOUT_RECEIPT": "The PO is closed and paid in the legacy system but nothing was received.",
    "QUOTE_PO_MISMATCH": "The PO value differs from the approved quotation.",
    "GR_VALUE_MISMATCH": "The goods receipt value does not equal quantity × PO price.",
    "STOCK_LEDGER_BREAK": "A stock transaction's running balance does not follow from the previous one.",
    "STOCK_LEDGER_GAP": "Stock transactions do not add up to the on-hand quantity.",
    "SUPPLIER_COMPLIANCE_FLAG": "The legacy supplier profile is flagged for compliance.",
    "UNCLASSIFIED_SPEND": "The legacy request has no item or category, so the spend could not be classified.",
    "TEST_DATA": "Rows that look like test or dummy data.",
}


def amount(minor: int) -> str:
    return f"{minor / 100:,.2f}"


def render(snapshot: dict, reports: list[dict]) -> str:
    out = []
    w = out.append
    counts = snapshot["counts"]
    w("# Legacy Data Migration Report")
    w("")
    w("Migration of the legacy `supplier_twin` database (Docker Desktop container `supplier_twin_db`, PostgreSQL 15) into the "
      "Procurement Intelligence Cloud, following Delivery Plan §15 (\"current demo data\").")
    w("")
    w("| Item | Value |")
    w("|---|---|")
    w(f"| Source | {snapshot['source'].get('kind')} `{snapshot['source'].get('container', snapshot['source'].get('host', ''))}` "
      f"database `{snapshot['source'].get('database', '')}` (Alembic `{snapshot.get('alembicVersion')}`) |")
    w(f"| Snapshot | `backend/data/legacy/supplier_twin.json`, extracted {snapshot['extractedAt']}, SHA-256 `{snapshot['sha256'][:16]}…` |")
    w(f"| Rows extracted | {sum(counts.values())} in {len(counts)} tables |")
    fx = {r.get("fx") for r in reports if "fx" in r} or {"1"}
    w(f"| Amount conversion | legacy amount × {', '.join(sorted(fx))} → INR paise (the legacy schema has no currency column) |")
    w("")
    w("## What was loaded where")
    w("")
    w("1. **Verbatim copy.** All 15 legacy tables were copied unchanged into the `public` schema, with their legacy ids. A new legacy "
      "migration (`e3c1f2a4b5d6`) first adds 9 columns that the Docker database has but the legacy Alembic chain was missing "
      "(inventory category, unit, thresholds, location and status; stock-transaction notes, performed-by and balance).")
    w("2. **Migration into PIC.** Each legacy buyer became a PIC tenant. Masters, open documents and paid history were loaded with "
      "their legacy ids and audited as `MIGRATED`. Lineage links connect requisition → sourcing event → PO → ASN → goods receipt → "
      "invoice → payment.")
    w("3. **Live continuation.** The open items then ran through the same services the API uses, so the PIC rules were applied to the "
      "legacy data: supplier screening and requalification, PO validation and approval routing, invoice capture with duplicate "
      "check and 3-way match, promotion of a repeatedly bought free-text item to a material request, and an MRP run on the "
      "migrated stock.")
    w("")
    w("| Legacy table | Rows | PIC target |")
    w("|---|---:|---|")
    targets = {
        "tenants": "tenant (buyers) · supplier (suppliers)", "users": "app_user (buyer users, supplier portal users)",
        "supplier_profiles": "supplier.screening, supplier_category_status, qualification",
        "order_requests": "requisition + pr_line", "quotations": "PO price source; bid + bid_line when a request was quoted more than once",
        "negotiation_messages": "– (empty)", "purchase_orders": "purchase_order + po_line (legacy number kept)",
        "po_approvals": "audit trail of the PO (LEGACY_APPROVAL_*)", "contracts": "– (empty)", "advance_ship_notices": "asn + asn_line",
        "goods_receipts": "goods_receipt + gr_line", "sales_invoices": "invoice + invoice_line (paid: history; pending: live capture)",
        "payments": "payment", "inventory_items": "material + stock (buyer); catalogue_item (supplier finished goods)",
        "stock_transactions": "stock_movement (+ opening balance 561)",
    }
    for table, rows in counts.items():
        w(f"| `{table}` | {rows} | {targets.get(table, '')} |")
    for report in reports:
        w("")
        if "skipped" in report:
            w(f"## Tenant {report['tenant']}: {report['name']}")
            w("")
            w(f"Skipped: {report['skipped']}.")
            continue
        _tenant(w, report)
    w("")
    w("## Decisions and actions for the business")
    w("")
    w("1. **Currency.** The legacy schema stores amounts without a currency, and the legacy screens labelled prices in USD. The load "
      "kept the amounts at face value. If they are USD, re-run the load with `--fx-rate <cutover rate>`.")
    w("2. **Overpayments.** Recover or confirm the excess payments listed under `OVERPAID_PO` and `PAID_BEFORE_APPROVAL` before go-live. "
      "In PIC, the pending duplicates are held with a payment block.")
    w("3. **Bank details.** The legacy system never stored supplier bank accounts. Each migrated supplier has an inactive placeholder "
      "that carries the paid history. New payments stay blocked until the supplier completes the MDM-04 bank change "
      "(two finance approvers, call-back, cooling-off).")
    w("4. **Test data.** The rows under `TEST_DATA` were migrated so that the books reconcile. Decide whether to reverse them in PIC or "
      "purge them from the source before the final cutover.")
    w("5. **Classification.** `UNCLASSIFIED` spend needs a category before it counts towards category strategies and savings.")
    w("")
    w("Regenerate this report with `python -m app.pic.tools.neon_setup` (it is rewritten whenever a legacy tenant is migrated).")
    w("")
    return "\n".join(out)


def _tenant(w, report: dict) -> None:
    w(f"## Tenant {report['tenant']}: {report['name']}")
    w("")
    w(f"Legacy tenant id `{report['legacyId']}`. Sign in with organisation **{report['tenant']}**. Internal users are "
      f"`<role>@{report['tenant'].lower()}.example` (for example `buyer@`, `ap.clerk@`, `finance.controller@`). Legacy buyer and "
      "supplier users keep their legacy e-mail addresses.")
    w("")
    w("### Reconciliation")
    w("")
    w("| Object | Legacy | PIC | Result |")
    w("|---|---:|---:|---|")
    for c in report["counts"]:
        w(f"| {c['object']} | {c['legacy']} | {c['pic']} | {'✔ match' if c['ok'] else '✘ differs'} |")
    for c in report["values"]:
        w(f"| {c['object']} | {amount(c['legacyMinor'])} | {amount(c['picMinor'])} | {'✔ match' if c['ok'] else '✘ differs'} |")
    live = report["live"]
    w("")
    w("### Live continuation (PIC rules applied to the legacy data)")
    w("")
    if live.get("screening"):
        w(f"- **F8 screening:** {', '.join(live['screening'])}.")
    if live.get("requalification"):
        w(f"- **F8 requalification opened** for compliance-flagged suppliers: {', '.join(live['requalification'])}.")
    if live.get("poApproval"):
        w(f"- **F5 approval routing:** {'; '.join(live['poApproval'])}.")
    if live.get("sourcingEvents"):
        w(f"- **F3 sourcing history:** {'; '.join(live['sourcingEvents'])}.")
    if live.get("invoices"):
        by_result = defaultdict(list)
        for inv in live["invoices"]:
            by_result[", ".join(inv["exceptions"]) or inv["status"]].append(f"{inv['invoice']} ({inv['po']})")
        for result, items in by_result.items():
            w(f"- **F7 pending invoices → {result}:** {', '.join(items)}.")
    if live.get("materialRequests"):
        w(f"- **F9 material governance:** {'; '.join(live['materialRequests'])}.")
    if live.get("mrp"):
        mrp = live["mrp"]
        forecast = ", ".join(f"{k} {v}" for k, v in mrp.get("forecast", {}).items()) or "none"
        w(f"- **F1 MRP {mrp['run']}:** {mrp['materialsPlanned']} materials planned, {mrp['plannedOrders']} planned order(s), "
          f"{mrp['exceptions']} exception(s). The consumption forecast comes from legacy goods issues in the last 30 days, "
          f"excluding test postings: {forecast}."
          + (f" Converted: {mrp['converted']}." if mrp.get("converted") else ""))
    if live.get("intelligence"):
        intel = live["intelligence"]
        sp = intel.get("spend", {})
        w(f"- **M01 spend governance:** {sp.get('auto', 0)} line(s) auto-classified by the Spend Classification Agent, "
          f"{sp.get('review', 0)} sent to steward review, {sp.get('hits', 0)} maverick hit(s) opened with an owner; "
          f"category plans: {', '.join(intel.get('plans') or []) or 'none'}.")
        w(f"- **M02 / M06 / M05 agents:** {intel.get('forecasts', 0)} forecast period(s), {intel.get('demandSensing', 0)} Demand Sensing "
          f"recommendation(s), {intel.get('riskSignals', 0)} supplier risk signal(s), {intel.get('sourcingAdvice', 0)} sourcing recommendation(s).")
    if report.get("openTasks") or report.get("openInvoiceExceptions") or report.get("mrpExceptions"):
        w("")
        w("Open work created in the worklists: "
          + "; ".join([f"{k} tasks {v}" for k, v in report.get("openTasks", {}).items()]
                      + [f"invoice exceptions {k} {v}" for k, v in report.get("openInvoiceExceptions", {}).items()]
                      + [f"MRP {k} {v}" for k, v in report.get("mrpExceptions", {}).items()]) + ".")
    if report.get("maverickSpendMinor"):
        w("")
        w("Spend carrying maverick flags (paid history): "
          + ", ".join(f"{k} {amount(v)}" for k, v in report["maverickSpendMinor"].items()) + ".")
    findings = report["findings"]
    w("")
    w(f"### Findings on the legacy data ({len(findings)})")
    w("")
    w("| Severity | Finding | Detail | References |")
    w("|---|---|---|---|")
    order = {s: i for i, s in enumerate(SEVERITY)}
    for f in sorted(findings, key=lambda f: (order.get(f["severity"], 9), f["code"])):
        detail = f["detail"].replace("|", "/")
        w(f"| {f['severity']} | `{f['code']}` | {detail} | {', '.join(f'`{r}`' for r in f['refs'])} |")
    codes = sorted({f["code"] for f in findings}, key=lambda c: min(order.get(f["severity"], 9) for f in findings if f["code"] == c))
    if codes:
        w("")
        for code in codes:
            w(f"- `{code}`: {EXPLAIN.get(code, '')}")
