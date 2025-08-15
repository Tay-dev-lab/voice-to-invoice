from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import date

class ClientInfo(BaseModel):
    name: str
    address: str

class InvoiceDetails(BaseModel):
    type: Literal["deposit", "works_completed"]
    due_date: date

class InvoiceItem(BaseModel):
    description: str
    value: float
    vat_rate: Optional[float] = 0.0
    cis_rate: Optional[float] = 0.0
    retention_rate: Optional[float] = 0.0
    discount_rate: Optional[float] = 0.0

class Invoice(BaseModel):
    reference_number: str
    client: ClientInfo
    details: InvoiceDetails
    items: List[InvoiceItem]