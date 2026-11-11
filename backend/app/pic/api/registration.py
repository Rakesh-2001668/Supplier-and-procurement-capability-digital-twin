"""Organisation registration (services/registration.py): public registration and e-mail confirmation, and the platform operator console."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.pic.platform.auth import Principal, current_principal
from app.pic.services import registration

router = APIRouter(prefix="/v1")


class RegistrationIn(BaseModel):
    kind: str = Field(description="BUYER or SUPPLIER")
    companyName: str = Field(max_length=300)
    country: str = Field(default="IN", max_length=2)
    stateCode: Optional[str] = Field(default=None, max_length=2)
    gstin: Optional[str] = Field(default=None, max_length=15)
    industryTemplate: str = Field(default="MANUFACTURING", max_length=40)
    organisationEmail: str = Field(max_length=200, description="The company's shared mailbox, e.g. purchase@company.com")
    adminName: str = Field(max_length=300)
    adminEmail: str = Field(max_length=200, description="The first administrator's personal work e-mail on the same domain")
    adminPhone: Optional[str] = Field(default=None, max_length=20)
    authorisedByName: Optional[str] = Field(default=None, max_length=300)
    authorisedByDesignation: Optional[str] = Field(default=None, max_length=200)
    expectedUsers: Optional[int] = None
    acceptTerms: bool = False


class VerifyIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ApproveIn(BaseModel):
    organisationCode: Optional[str] = Field(default=None, max_length=20)
    note: Optional[str] = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    reason: str = Field(max_length=2000)


@router.get("/public/registrations/status", tags=["Registration"])
def registration_status():
    """Public: whether organisation registration is open, which kinds, and the accepted shared mailbox names."""
    return registration.status()


@router.post("/public/registrations", status_code=202, tags=["Registration"])
def register(body: RegistrationIn, request: Request):
    """Public: register an organisation. A confirmation link goes to the shared mailbox; the answer never says whether the company is known."""
    return registration.submit(body.model_dump(), request)


@router.post("/public/registrations/verify", tags=["Registration"])
def verify(body: VerifyIn, request: Request):
    """Public: confirm the shared mailbox with the link token; the request then waits for a platform operator."""
    return registration.verify(body.token, request)


@router.get("/platform/registrations", tags=["Registration"])
def list_registrations(status: Optional[str] = Query(default=None), p: Principal = Depends(current_principal)):
    return registration.list_registrations(p, status)


@router.get("/platform/registrations/{reg_id}", tags=["Registration"])
def get_registration(reg_id: uuid.UUID, p: Principal = Depends(current_principal)):
    return registration.get(p, reg_id)


@router.post("/platform/registrations/{reg_id}/approve", tags=["Registration"])
def approve(reg_id: uuid.UUID, body: ApproveIn, p: Principal = Depends(current_principal)):
    return registration.approve(p, reg_id, body.organisationCode, body.note)


@router.post("/platform/registrations/{reg_id}/reject", tags=["Registration"])
def reject(reg_id: uuid.UUID, body: RejectIn, p: Principal = Depends(current_principal)):
    return registration.reject(p, reg_id, body.reason)
