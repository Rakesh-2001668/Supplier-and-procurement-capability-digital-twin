from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class TenantBaseSchema(BaseSchema):
    tenant_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
