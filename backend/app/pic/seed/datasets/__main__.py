"""Apply dataset packs to the database in DATABASE_URL (after the signature case is seeded).

    python -m app.pic.seed.datasets                 # every ready pack not yet loaded
    python -m app.pic.seed.datasets --only branches # one pack
    python -m app.pic.seed.datasets --list          # packs and where they are loaded

The demo-user password comes from PIC_SEED_PASSWORD (shell or backend/.env); it is required, never generated here.
"""
import argparse
import json
import logging
import os
import sys

import app.pic.services  # noqa: F401  (registers consumers, task handlers, timers)
from app.pic.seed import datasets


def _password() -> str:
    password = os.environ.get("PIC_SEED_PASSWORD")
    if not password:
        from dotenv import dotenv_values

        from app.pic.config import BACKEND_DIR
        password = dotenv_values(BACKEND_DIR / ".env").get("PIC_SEED_PASSWORD")
    if not password:
        sys.exit("PIC_SEED_PASSWORD is not set (shell or backend/.env)")
    return password


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", choices=datasets.PACKS)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for name in datasets.PACKS:
            pack = datasets.load(name)
            codes = pack.TENANTS if pack.TENANTS != ("*",) else tuple(sorted(datasets._tenants()))
            where = ", ".join(f"{c}{'✓' if datasets.loaded(c, pack.KEY) else ''}" for c in codes)
            print(f"{name:24} {'ready' if pack.READY else 'stub ':5}  {pack.KEY:28} {where}  – {pack.TITLE}")
        return
    for result in datasets.apply_all(_password(), args.only):
        line = f"{result['pack']:24} {result['tenant']:5} {result['status']}"
        if result.get("summary", {}).get("counts"):
            line += "  " + json.dumps(result["summary"]["counts"], ensure_ascii=False)
        print(line)
        for note in result.get("summary", {}).get("notes", []):
            print("   -", note)


if __name__ == "__main__":
    main()
