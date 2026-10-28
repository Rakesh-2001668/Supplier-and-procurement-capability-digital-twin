"""Fail CI on HIGH or CRITICAL Python dependency vulnerabilities, with a justified ignore list.

    pip-audit -r backend/requirements.txt -f json -o pip-audit.json || true
    python .github/scripts/pip_audit_gate.py pip-audit.json backend/pip-audit-ignore.txt

pip-audit reports vulnerability ids without a severity, so each id (and its aliases) is looked up in OSV
(https://api.osv.dev/v1/vulns/<id>): GitHub-reviewed advisories carry database_specific.severity, otherwise the CVSS v3/v4
base score is used. An id whose severity cannot be determined is treated as HIGH (fail closed).

Ignore file: one entry per line, `<ID> | <justification> | <review-by YYYY-MM-DD>`; blank lines and # comments are skipped.
Entries without a justification, or past their review date, are rejected so the list cannot rot silently.
Standard library only.
"""
import datetime
import json
import math
import re
import sys
import urllib.request

BLOCKING = {"HIGH", "CRITICAL"}


def load_ignores(path: str) -> dict[str, str]:
    ignores, problems = {}, []
    today = datetime.date.today()
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return {}
    for number, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip() if line.lstrip().startswith("#") else line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not parts[1]:
            problems.append(f"{path}:{number}: expected '<ID> | <justification> | <review-by YYYY-MM-DD>'")
            continue
        try:
            review = datetime.date.fromisoformat(parts[2])
        except ValueError:
            problems.append(f"{path}:{number}: review-by date must be YYYY-MM-DD")
            continue
        if review < today:
            problems.append(f"{path}:{number}: ignore for {parts[0]} expired on {review}; re-assess it")
            continue
        ignores[parts[0]] = parts[1]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(2)
    return ignores


def _cvss3_score(vector: str) -> float:
    """CVSS v3.x base score from a vector string (FIRST specification)."""
    m = dict(part.split(":") for part in vector.split("/")[1:] if ":" in part)
    av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[m["AV"]]
    ac = {"L": 0.77, "H": 0.44}[m["AC"]]
    changed = m["S"] == "C"
    pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[m["PR"]]
    ui = {"N": 0.85, "R": 0.62}[m["UI"]]
    cia = {"H": 0.56, "L": 0.22, "N": 0.0}
    iss = 1 - (1 - cia[m["C"]]) * (1 - cia[m["I"]]) * (1 - cia[m["A"]])
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    exploit = 8.22 * av * ac * pr * ui
    raw = min(1.08 * (impact + exploit), 10) if changed else min(impact + exploit, 10)
    return math.ceil(raw * 10) / 10


def severity(vuln_id: str) -> str:
    try:
        with urllib.request.urlopen(f"https://api.osv.dev/v1/vulns/{vuln_id}", timeout=20) as response:
            data = json.load(response)
    except Exception as exc:  # network or unknown id: fail closed
        print(f"  could not look up {vuln_id} in OSV ({exc}); treating as HIGH", file=sys.stderr)
        return "HIGH"
    label = (data.get("database_specific") or {}).get("severity")
    if isinstance(label, str) and label.upper() in {"LOW", "MODERATE", "MEDIUM", "HIGH", "CRITICAL"}:
        return {"MODERATE": "MEDIUM"}.get(label.upper(), label.upper())
    scores = []
    for item in data.get("severity") or []:
        vector = item.get("score", "")
        if item.get("type") == "CVSS_V3" and vector.startswith("CVSS:3"):
            try:
                scores.append(_cvss3_score(vector))
            except (KeyError, ValueError):
                pass
    if scores:
        score = max(scores)
        return "CRITICAL" if score >= 9 else "HIGH" if score >= 7 else "MEDIUM" if score >= 4 else "LOW"
    return "HIGH"


def main(report_path: str, ignore_path: str) -> int:
    ignores = load_ignores(ignore_path)
    report = json.load(open(report_path, encoding="utf-8"))
    dependencies = report.get("dependencies", report if isinstance(report, list) else [])
    blocking, reported = [], 0
    for dep in dependencies:
        for vuln in dep.get("vulns", []):
            reported += 1
            ids = [vuln["id"], *vuln.get("aliases", [])]
            ignored = next((i for i in ids if i in ignores), None)
            ghsa = next((i for i in ids if i.startswith("GHSA-")), vuln["id"])
            level = severity(ghsa)
            line = f"{dep['name']}=={dep.get('version')} {vuln['id']} ({', '.join(ids[1:]) or '-'}) {level}; fixed in {', '.join(vuln.get('fix_versions', [])) or 'n/a'}"
            if ignored:
                print(f"IGNORED  {line} — {ignores[ignored]}")
            elif level in BLOCKING:
                print(f"BLOCKING {line}")
                blocking.append(line)
            else:
                print(f"report   {line}")
    print(f"{reported} known vulnerabilities, {len(blocking)} blocking (HIGH/CRITICAL, not ignored)")
    return 1 if blocking else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
