from typing import Dict
from uuid import UUID

sessions: Dict[str, dict] = {}

def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "step": "invoice_type",
            "invoice_type": None,
            "client": {},
            "items": [],
            "current_item": {}
        }
    return sessions[session_id]

def advance_step(session: dict):
    step_order = [
        "invoice_type",
        "client_info",
        "item_description",
        "item_value",
        "item_vat",
        "item_cis",
        "item_retention",
        "item_discount",
        "add_another"
    ]

    current_index = step_order.index(session["step"])
    if current_index < len(step_order) - 1:
        session["step"] = step_order[current_index + 1]
    else:
        session["step"] = "done"