"""D8 volume generator smoke test: a small-scale run into a scratch database next to the test database (never the test
database itself, never Neon), plus the URL guards. The generator runs in a subprocess so it gets its own DATABASE_URL."""
import json
import os
import subprocess
import sys

from sqlalchemy.engine import make_url

from app.pic.config import BACKEND_DIR
from app.pic.tools import volume_gen


def _run(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    return subprocess.run([sys.executable, "-m", "app.pic.tools.volume_gen", *args], cwd=BACKEND_DIR, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout)


def test_volumes_scale_to_the_nfr():
    full = volume_gen.volumes(1.0, 1)
    assert full == {"materials": 50_000, "suppliers": 2_000, "purchase_orders": 2_500_000, "invoices": 5_000_000, "spend_lines": 50_000_000}
    small = volume_gen.volumes(0.001, 1)
    assert small["materials"] == 50 and small["invoices"] == 5_000 and small["spend_lines"] == 50_000


def test_refuses_neon_and_non_scratch_databases():
    neon = _run("--database-url", "postgresql://u:p@ep-example-123.eu-central-1.aws.neon.tech/neondb", "--scale", "0.001", timeout=120)
    assert neon.returncode == 2 and "Neon" in neon.stderr
    plain = _run("--database-url", "postgresql://postgres@127.0.0.1:54329/production_like", "--scale", "0.001", timeout=120)
    assert plain.returncode == 2 and "scratch" in plain.stderr


def test_small_scale_run(database):
    test_url = make_url(os.environ["DATABASE_URL"])
    scratch = test_url.set(database=f"{test_url.database}_scratch_volume").render_as_string(hide_password=False)
    assert "neon.tech" not in scratch
    result = _run("--database-url", scratch, "--scale", "0.0002", "--reset", "--measure")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    copied, vol = summary["copied"], summary["volumes"]
    assert summary["status"] == "PASS"
    assert copied["invoice"] == vol["invoices"] == 1_000 and copied["purchase_order"] == vol["purchase_orders"]
    assert copied["spend_line"] == vol["spend_lines"] == 10_000 and copied["invoice_line"] >= vol["invoices"]
    assert summary["mrp_masters"]["materials"] == vol["materials"] == 10
    cube = {tuple(r["dimensions"]): r for r in summary["spend_cube"]}
    assert cube[("category",)]["lines"] == 10_000 and all(r["pass"] for r in summary["spend_cube"])
