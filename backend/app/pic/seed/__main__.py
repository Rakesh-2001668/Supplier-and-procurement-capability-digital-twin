"""Seed the PIC schema with the Axion Mobility signature case.

    python -m app.pic.seed            # uses PIC_SEED_PASSWORD from .env, or generates one
"""
import logging
import os
import secrets
import sys

import app.pic.services  # noqa: F401
from app.pic.seed import axion


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    password = os.environ.get("PIC_SEED_PASSWORD")
    if not password:
        from app.pic.config import BACKEND_DIR
        env = BACKEND_DIR / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("PIC_SEED_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    steps = axion.run(password)
    print("\nAxion Mobility signature case seeded:")
    for step in steps:
        print(" -", step)
    if generated:
        print(f"\nDemo users (…@axion.example) share the generated password: {password}\nStore it now; it is not saved anywhere.")


if __name__ == "__main__":
    sys.exit(main())
