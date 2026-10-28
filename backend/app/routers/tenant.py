from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import uuid

from app.core.database import get_db
from app.core import security
from app.models.tenant import Tenant, User, TenantType
from pydantic import BaseModel

router = APIRouter()

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    company_name: str
    account_type: str # "buyer" or "supplier"

@router.post("/register")
def register_user(req: RegisterRequest, db: Session = Depends(get_db)):
    # Check if user exists
    user = db.query(User).filter(User.email == req.email).first()
    if user:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    # Create Tenant
    tenant_id = str(uuid.uuid4())
    t_type = TenantType.BUYER if req.account_type.lower() == 'buyer' else TenantType.SUPPLIER
    new_tenant = Tenant(id=tenant_id, name=req.company_name, type=t_type)
    db.add(new_tenant)
    
    # Create User
    user_id = str(uuid.uuid4())
    hashed_password = security.get_password_hash(req.password)
    new_user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=req.email,
        full_name=req.full_name,
        role="Admin",
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    
    # Generate Token
    access_token = security.create_access_token(subject=new_user.id)
    return {"access_token": access_token, "token_type": "bearer", "tenant_id": tenant_id, "role": req.account_type.lower()}


@router.post("/login")
def login(db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not user.hashed_password:
        # Mock backdoor for existing seed users without passwords
        if user and form_data.password == "password":
            pass
        else:
            if not user or not security.verify_password(form_data.password, user.hashed_password):
                raise HTTPException(status_code=400, detail="Incorrect email or password")
            
    access_token = security.create_access_token(subject=user.id)
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    role = "buyer" if tenant.type == TenantType.BUYER else "supplier"
    
    return {"access_token": access_token, "token_type": "bearer", "tenant_id": user.tenant_id, "role": role}

