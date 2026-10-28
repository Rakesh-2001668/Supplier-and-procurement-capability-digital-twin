"""Operations: privacy requests (DPDP) and approval-matrix simulation (ADM-03).

Probes and metrics (/healthz, /readyz, /metrics) are served by platform/http.py outside /v1.
"""
import uuid
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.pic.api.deps import uow
from app.pic.platform.auth import Principal, require
from app.pic.services import policy_sim, privacy

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- DPDP privacy requests (tenant administrator)
@router.get("/admin/privacy/users/{user_id}/export", tags=["Privacy"])
def export_personal_data(user_id: uuid.UUID, p: Principal = Depends(require("admin:audit"))):
    """Everything PIC holds about one user: profile, roles, MFA factor metadata, notifications, audit events where the user acted
    or was the subject, tasks completed and document counts. The export itself is audited."""
    with uow(p) as s:
        return privacy.export(s, user_id)


class EraseIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000, description="Request reference and reason, e.g. 'DPDP-2026-014: employee left'")


@router.post("/admin/privacy/users/{user_id}/erase", tags=["Privacy"])
def erase_personal_data(user_id: uuid.UUID, body: EraseIn, p: Principal = Depends(require("admin:audit"))):
    """Pseudonymise name and e-mail, strip contact attributes, deactivate, destroy password and MFA factors, delete notifications.
    Refused while the user can still work open tasks. The audit trail is not modified; the erasure is appended to it."""
    with uow(p) as s:
        return privacy.erase(s, user_id, body.reason)


@router.get("/admin/privacy/retention", tags=["Privacy"])
def retention_report(p: Principal = Depends(require("admin:audit"))):
    """Personal-data categories, purpose, lawful basis, configured retention (rule set PRIVACY-RETENTION) and data residency."""
    with uow(p) as s:
        return privacy.retention(s)


# ---------------------------------------------------------------- ADM-03 approval-matrix simulation
class SimScope(BaseModel):
    companyCode: Optional[str] = None  # noqa: N815
    plant: Optional[str] = None
    category: Optional[str] = None
    purchaseType: Optional[str] = None  # noqa: N815


class SimulateIn(BaseModel):
    key: Literal["DMN-01", "PO-APPROVAL", "AWARD-APPROVAL", "CONTRACT-APPROVAL", "CONTRACT-AMENDMENT", "DMN-02", "DMN-03"]
    inputs: dict = Field(default_factory=dict)
    on: Optional[date] = Field(default=None, description="Business date the rule version is resolved for (default today)")
    scope: Optional[SimScope] = None
    draftBody: Optional[dict] = Field(default=None, description="Compare mode: evaluate this unsaved body next to the resolved version")  # noqa: N815


@router.post("/admin/rules/simulate", tags=["Administration"])
def simulate_rule(body: SimulateIn, p: Principal = Depends(require("admin:rules"))):
    """Resolve the effective rule version for the scope and date, and return the approver chain or decision with the reasons,
    using the same decision functions as the services. Nothing is saved."""
    with uow(p) as s:
        return policy_sim.simulate(s, body.key, body.inputs, body.on, body.scope.model_dump() if body.scope else None, body.draftBody)
