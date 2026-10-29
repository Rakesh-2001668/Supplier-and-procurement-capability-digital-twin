"""Dataset-pack framework: prerequisites are checked before a pack writes anything."""
from app.pic.seed import datasets
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION


def test_signature_case_marker_is_recorded_by_the_seed():
    row = datasets.loaded("AXN", SIGNATURE_KEY)
    assert row is not None and row.version == SIGNATURE_VERSION
    assert datasets._unmet("AXN", {SIGNATURE_KEY: SIGNATURE_VERSION}) == []


def test_unmet_prerequisites_name_the_missing_or_outdated_dataset():
    missing = datasets._unmet("AXN", {"no-such-dataset": "1"})
    assert len(missing) == 1 and "no-such-dataset" in missing[0] and "older release" in missing[0]
    outdated = datasets._unmet("AXN", {SIGNATURE_KEY: "1999.01.01"})
    assert len(outdated) == 1 and f"found {SIGNATURE_VERSION}" in outdated[0]


def test_axn_packs_require_the_current_signature_case():
    for name in ("branches", "module_cases", "purchase_types", "ai_eval"):
        assert datasets.load(name).REQUIRES == {SIGNATURE_KEY: SIGNATURE_VERSION}, name
