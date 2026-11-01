"""Coverage gate (TD §17): report line coverage per package of app/pic and fail when the total or a package drops below the
thresholds in backend/coverage-thresholds.json (set from a measured baseline; raise them as coverage grows, never lower them).

    python .github/scripts/coverage_gate.py backend/coverage.json backend/coverage-thresholds.json
"""
import json
import sys
from collections import defaultdict
from pathlib import PurePosixPath


def package_of(path: str) -> str:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if "pic" in parts:
        rest = parts[parts.index("pic") + 1:]
        return rest[0] if len(rest) > 1 else "(root)"
    return "(other)"


def main(coverage_file: str, thresholds_file: str) -> int:
    data = json.load(open(coverage_file, encoding="utf-8"))
    limits = json.load(open(thresholds_file, encoding="utf-8"))
    covered, total = defaultdict(int), defaultdict(int)
    for path, info in data["files"].items():
        package = package_of(path)
        covered[package] += info["summary"]["covered_lines"]
        total[package] += info["summary"]["num_statements"]
    failures = []
    print(f"{'package':14} {'lines':>8} {'covered':>8} {'percent':>8} {'minimum':>8}")
    for package in sorted(total):
        percent = 100 * covered[package] / total[package] if total[package] else 100.0
        minimum = limits.get("packages", {}).get(package)
        print(f"{package:14} {total[package]:8} {covered[package]:8} {percent:7.1f}% {('%.1f%%' % minimum) if minimum is not None else '-':>8}")
        if minimum is not None and percent + 0.05 < minimum:
            failures.append(f"package {package}: {percent:.1f}% < {minimum}%")
    all_total, all_covered = sum(total.values()), sum(covered.values())
    overall = 100 * all_covered / all_total if all_total else 100.0
    print(f"{'TOTAL':14} {all_total:8} {all_covered:8} {overall:7.1f}% {limits.get('total', 0):7.1f}%")
    if overall + 0.05 < limits.get("total", 0):
        failures.append(f"total: {overall:.1f}% < {limits['total']}%")
    for failure in failures:
        print(f"::error::coverage below threshold: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
