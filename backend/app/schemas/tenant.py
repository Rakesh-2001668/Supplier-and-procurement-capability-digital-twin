from pydantic import BaseModel
from .base import BaseSchema, TenantBaseSchema
from enum import Enum

class TenantType(str, Enum):
    BUYER = "BUYER"
    SUPPLIER = "SUPPLIER"

class TenantSchema(BaseSchema):
    id: str
    type: TenantType
    name: str

class UserSchema(TenantBaseSchema):
    id: str
    email: str
    full_name: str
    role: str
