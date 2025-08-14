from pydantic import BaseModel
from typing import Optional, Literal
from datetime import date

class Invoice(BaseModel):
    client_name: str
    amount: float
    due_date: date
    vat_rate: float
    discount: Optional[float]
    cis_required: bool
    invoice_type: Literal["deposit", "works_completed"]
