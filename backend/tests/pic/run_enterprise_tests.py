import hashlib
import json
import tempfile
from pathlib import Path
import sys

# Ensure backend directory is in path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.pic.tools import erp_mock
from tests.pic import test_enterprise_mock_datasets as t

print("--> Testing D11 Reference Data Integrity...")
t.test_d11_reference_datasets_integrity()
t.test_d11_feed_simulator_dry_run()
print("    PASS: D11 Reference Data & Live Feeds verified.")

print("--> Testing D10 Deterministic Byte-for-Byte Generation of KAC Mock...")
with tempfile.TemporaryDirectory() as tmp_dir:
    manifest = erp_mock.generate(Path(tmp_dir) / "KAC", months=24)
    committed = json.loads((erp_mock.OUT_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert {k: v["sha256"] for k, v in manifest["files"].items()} == {k: v["sha256"] for k, v in committed["files"].items()}
print("    PASS: KAC ERP Mock files are 100% byte-for-byte SHA256 deterministic.")

print("--> Testing D10 ERP Cutover & GL Tie-Out Validation...")
t.test_d10_erp_cutover_validation()
print("    PASS: D10 9 Migration Objects & GL ACDOCA tie-out verified.")

print("--> Testing D8 Volume Scaling & Offline Export Generator...")
with tempfile.TemporaryDirectory() as tmp_dir:
    t.test_d8_volume_scaling_and_offline_export(Path(tmp_dir))
print("    PASS: D8 NFR streaming export and SQL script verified.")

print("\nSUCCESS: ALL ENTERPRISE MOCK DATASET VERIFICATIONS PASSED!")
