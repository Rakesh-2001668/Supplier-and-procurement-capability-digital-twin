"""Create the first GitHub issues from docs/PIC_Pending_Workflows.md and a short list of known defects.

    python .github/scripts/seed_issues.py            dry run: prints what would be created
    GITHUB_TOKEN=... python .github/scripts/seed_issues.py --create

The token needs "Issues: read and write" on this repository (a fine-grained personal access token). It is read from the
environment only and never printed. Issues whose title already exists are skipped, so the script is safe to re-run.
Run the "Sync labels" workflow first so the labels exist.
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO = "Rakesh-2001668/Supplier-and-procurement-capability-digital-twin"
DOC = Path(__file__).resolve().parents[2] / "docs" / "PIC_Pending_Workflows.md"

SECTION_LABELS = {
    "Scheduled": ["area: platform"], "Procure-to-pay": ["area: F5 orders"], "Master data": ["area: F9 master data"],
    "Sourcing": ["area: F3 sourcing"], "Supplier management": ["area: F8 suppliers"], "Spend": ["area: spend-savings"],
    "Industry": ["industry"], "Platform": ["area: platform"], "Needs the client": ["status: needs client", "area: erp-migration"],
    "Not in the specs": ["area: platform"],
}

KNOWN_BUGS = [
    ("Header always shows 'Manufacturing template'", ["type: bug", "severity: S4", "area: portal"],
     "frontend/src/components/pic/WorkspaceShell.tsx hard-codes the label for every company. Show the company's template (manufacturing, "
     "construction, IT services, logistics, healthcare, general)."),
    ("MRP at 50,000 materials takes 681 s (target 600 s)", ["type: debt", "severity: S3", "area: F1 planning", "from: spec matrix"],
     "Measured on a busy 2-CPU machine. Options: drop the per-order planned_by link row, return a run summary instead of every planned "
     "order, tune the database server. Measure again on a quiet or production-sized machine."),
    ("Idempotency-Key is honoured on only 26 of 138 POST routes", ["type: bug", "severity: S2", "area: platform", "from: spec matrix"],
     "TD section 10: every POST accepts Idempotency-Key with a 24 h replay window. Also add ETag / If-Match to the other mutable "
     "documents (only purchase orders have it)."),
    ("ABAC checks (company code, plant, value band) are not enforced on commands", ["type: bug", "severity: S2", "area: platform", "from: spec matrix"],
     "check_value_limit and check_attr exist but are never called. Only workflow task assignment applies attributes."),
    ("Spend overview loads every spend line into memory", ["type: bug", "severity: S3", "area: spend-savings", "from: spec matrix"],
     "services/spend.py overview cannot meet the 3 s target at 50 million lines. Use SQL aggregates or materialised views."),
    ("MFA enforcement is off in every company", ["type: security", "severity: S2", "area: admin-rules"],
     "Rule MFA has enforce=false in all 8 tenants. Switch it on per tenant before real users sign in (needs a decision)."),
    ("Realised savings and first-pass match rate differ from the Blueprint signature case", ["type: bug", "severity: S4", "area: spend-savings", "from: spec matrix"],
     "Blueprint: realised 0.38 Cr and first-pass 86%. The seeded data gives 0.0129 Cr and 72%. Seed enough posted invoices."),
    ("No holiday calendar for the GMC and DBY plants", ["type: bug", "severity: S4", "area: erp-migration", "from: spec matrix"],
     "The migrated plants have no holidays, so working-day calculations ignore public holidays."),
    ("Withholding tax (TDS) on open payables is rejected by the ERP loader", ["type: feature", "severity: S3", "area: erp-migration"],
     "Invoices need a withholding-tax amount field before real client payables with TDS can be loaded."),
]


def parse_pending():
    items, section = [], ""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = re.sub(r"^\d+\.\s*", "", line[3:]).strip()
        m = re.match(r"\|\s*(\d+)\s*\|(.+)\|\s*$", line)
        if m and section not in ("Totals", "Suggested order"):
            cells = [c.strip() for c in m.group(2).split("|")]
            items.append((int(m.group(1)), section, cells))
    return items


def labels_for(section: str, text: str):
    labels = ["type: feature", "from: spec matrix"]
    for key, extra in SECTION_LABELS.items():
        if section.startswith(key):
            labels += extra
    if re.search(r"\bS\b", text.split("|")[-1]):
        pass
    return labels


def build():
    issues = []
    for number, section, cells in parse_pending():
        title = cells[-4] if len(cells) >= 5 else cells[0]
        # Columns differ per table: take the first text cell as the title and keep the rest as the body.
        title = cells[0] if not re.fullmatch(r"(Manufacturing|Construction|IT services|Logistics|Healthcare|General)", cells[0]) else f"{cells[0]}: {cells[1]}"
        body = "From docs/PIC_Pending_Workflows.md item #%d (%s).\n\n%s\n\n**Acceptance criteria**\n- [ ] \n- [ ] A test covers it\n" % (
            number, section, " | ".join(cells))
        issues.append((f"[Feature] {title}", labels_for(section, " | ".join(cells)), body))
    for title, labels, body in KNOWN_BUGS:
        issues.append((f"[Bug] {title}" if "type: bug" in labels else f"[{labels[0].split(': ')[1].title()}] {title}", labels, body))
    return issues


def api(method, path, token, payload=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}", method=method,
                                 data=json.dumps(payload).encode() if payload else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "pic-seed-issues"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    issues = build()
    create = "--create" in sys.argv
    if not create:
        for title, labels, _ in issues:
            print(f"{title}   [{', '.join(labels)}]")
        print(f"\n{len(issues)} issues would be created. Re-run with --create and GITHUB_TOKEN set.")
        return
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    existing, page = set(), 1
    while True:
        batch = api("GET", f"/issues?state=all&per_page=100&page={page}", token)
        existing |= {i["title"] for i in batch if "pull_request" not in i}
        if len(batch) < 100:
            break
        page += 1
    made = skipped = 0
    for title, labels, body in issues:
        if title in existing:
            skipped += 1
            continue
        api("POST", "/issues", token, {"title": title, "body": body, "labels": labels})
        made += 1
    print(f"created {made}, skipped {skipped} that already existed")


if __name__ == "__main__":
    main()
