"""Dataset packs on top of the Axion signature case (Remaining Work Report §4.4, D1–D11).

Every pack is a module in this package with:

    KEY: str             unique pack key, e.g. "axn-branch-cases"
    VERSION: str         bump when the pack's content changes (a loaded pack is not re-applied automatically)
    TITLE: str           one line for logs and the setup output
    TENANTS: tuple       tenant codes the pack writes to; ("*",) = every existing tenant
    CREATES_TENANT: bool True when the pack creates its tenant (industry demo tenants)
    READY: bool          False while the pack is still a stub; apply_all() skips it
    REQUIRES: dict       optional {dataset key: version} that must be loaded for the tenant first, e.g. the AXN signature
                         case of the current seed release; otherwise the pack is SKIPPED before it writes anything
    def apply(tenant_code: str, password: str) -> dict
                         creates the data for one tenant and returns a JSON summary {"notes": [...], "counts": {...}}

Packs are idempotent through pic.dataset_load (tenant, key): a pack already loaded for a tenant is skipped. They run
after the signature case on the same database (local, CI or Neon), so they must never change signature-case outcomes,
never fire timers or approve tasks that belong to other objects, and look objects up by business keys rather than by
numbers from shared number ranges.
"""
import importlib
import logging
from types import ModuleType
from typing import Iterable, Optional

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import DatasetLoad, Tenant
from app.pic.platform import clock

log = logging.getLogger(__name__)

# Packs do not depend on each other, but reference_data runs last: it covers every tenant, including the industry demo
# tenants created above, and its plant holidays must not shift the dates of the AXN cases (same order as the test suite).
PACKS = (
    "branches",              # D1  operating cases 9–n: the unexercised gateway branches of F1–F9 (AXN, April 2027)
    "module_cases",           # D1  cases for the operations modules: amendments, auctions, EDI, payment files, … (AXN, May 2027)
    "purchase_types",         # D2  expense, capital asset, consignment, subcontracting (AXN, June 2027)
    "industry_construction",  # D3  tenant CON
    "industry_it",            # D4  tenant ITS
    "industry_logistics",     # D5  tenant LOG
    "industry_healthcare",    # D6  tenant HLT
    "industry_general",       # D7  tenant GEN
    "erp_client_kac",         # D10 tenant KAC loaded from a mock SAP S/4HANA cutover extract (TD §12.4 ERP migration)
    "ai_eval",               # D9  AI evaluation sets (labelled spend, forecast actuals, duplicate pairs, Copilot questions)
    "reference_data",         # D11 HSN/SAC + GST rates, holiday calendars, UNSPSC mapping, FX rates (every tenant)
)


def load(name: str) -> ModuleType:
    if name not in PACKS:
        raise KeyError(f"Unknown dataset pack {name!r}; known: {', '.join(PACKS)}")
    return importlib.import_module(f"{__name__}.{name}")


def _tenants() -> dict[str, object]:
    with system_tx() as s:
        return {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}


def loaded(tenant_code: str, key: str) -> Optional[DatasetLoad]:
    tenant_id = _tenants().get(tenant_code)
    if tenant_id is None:
        return None
    with tenant_tx(tenant_id) as s:
        row = s.execute(select(DatasetLoad).where(DatasetLoad.key == key)).scalar_one_or_none()
        if row is not None:
            s.expunge(row)
        return row


def _unmet(tenant_code: str, requires: dict) -> list[str]:
    reasons = []
    for key, version in (requires or {}).items():
        row = loaded(tenant_code, key)
        if row is None:
            reasons.append(f"needs {key} {version}, which this database does not have (seeded by an older release: "
                           f"rebuild the tenant from the current seed)")
        elif row.version != version:
            reasons.append(f"needs {key} {version}, found {row.version} (rebuild the tenant from the current seed)")
    return reasons


def _record(tenant_code: str, pack: ModuleType, summary: dict) -> None:
    tenant_id = _tenants()[tenant_code]
    with tenant_tx(tenant_id) as s:
        s.add(DatasetLoad(tenant_id=tenant_id, key=pack.KEY, version=pack.VERSION, loaded_at=clock.now(), summary=summary or {}))


def apply_pack(name: str, password: str, tenants: Optional[Iterable[str]] = None) -> list[dict]:
    """Apply one pack to each of its tenants that does not have it yet. Returns one result per tenant."""
    pack = load(name)
    existing = _tenants()
    codes = list(tenants) if tenants else (sorted(existing) if pack.TENANTS == ("*",) else list(pack.TENANTS))
    results = []
    for code in codes:
        if code not in existing and not getattr(pack, "CREATES_TENANT", False):
            results.append({"pack": name, "tenant": code, "status": "SKIPPED", "reason": "tenant does not exist"})
            continue
        if loaded(code, pack.KEY):
            results.append({"pack": name, "tenant": code, "status": "ALREADY_LOADED"})
            continue
        unmet = _unmet(code, getattr(pack, "REQUIRES", {}))
        if unmet:
            results.append({"pack": name, "tenant": code, "status": "SKIPPED", "reason": "; ".join(unmet)})
            log.warning("dataset %s skipped for %s: %s", pack.KEY, code, "; ".join(unmet))
            continue
        try:
            summary = pack.apply(code, password) or {}
        finally:
            clock.set_pinned(None)
        _record(code, pack, summary)
        existing = _tenants()
        results.append({"pack": name, "tenant": code, "status": "LOADED", "summary": summary})
        log.info("dataset %s loaded for %s", pack.KEY, code)
    return results


def apply_all(password: str, only: Optional[Iterable[str]] = None) -> list[dict]:
    """Apply every ready pack (or the named ones) in PACKS order."""
    names = list(only) if only else [n for n in PACKS if getattr(load(n), "READY", False)]
    results = []
    for name in names:
        results.extend(apply_pack(name, password))
    return results
