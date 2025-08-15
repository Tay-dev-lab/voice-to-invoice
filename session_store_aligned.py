import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from database import db
from models import Invoice, InvoiceDetails, ClientInfo, InvoiceItem
from step_handlers import get_prompt_for_step

logger = logging.getLogger(__name__)

# Define the complete step flow for invoice creation
STEP_FLOW = [
    "start",
    "invoice_type",      # deposit or works_completed
    "client_info",       # name and address
    "item_description",  # description of first item
    "item_value",        # value of item
    "item_vat",          # VAT rate
    "item_cis",          # CIS rate
    "item_retention",    # Retention rate
    "item_discount",     # Discount rate
    "add_another",       # add another item or submit
    "done"
]

def get_session(session_id: str) -> Dict[str, Any]:
    """Get or create a session"""
    session = db.get_session(session_id)
    if not session:
        session = db.create_session(session_id, {
            "step": "start",
            "invoice_type": None,
            "client_info": None,
            "items": [],
            "current_item": {},
            "reference_number": f"INV-{session_id[:8].upper()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id
        })
    return session

def save_session(session_id: str, session_data: Dict[str, Any]) -> bool:
    """Save session data to database"""
    return db.update_session(session_id, session_data)

def reset_session(session_id: str) -> Dict[str, Any]:
    """Reset a session to initial state"""
    initial_data = {
        "step": "start",
        "invoice_type": None,
        "client_info": None,
        "items": [],
        "current_item": {},
        "reference_number": f"INV-{session_id[:8].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id
    }
    db.update_session(session_id, initial_data)
    logger.info(f"Reset session: {session_id}")
    return initial_data

def advance_step(session: Dict[str, Any]) -> str:
    """Advance to the next step in the flow"""
    current_step = session.get("step", "start")
    
    # Special handling for add_another step
    if current_step == "add_another":
        last_response = session.get("last_add_another_response", "")
        if last_response == "add":
            # Go back to item_description for a new item
            session["step"] = "item_description"
            session["current_item"] = {}  # Reset current item
        else:
            # Done adding items
            session["step"] = "done"
    else:
        # Follow the predefined flow
        try:
            current_index = STEP_FLOW.index(current_step)
            if current_index < len(STEP_FLOW) - 1:
                session["step"] = STEP_FLOW[current_index + 1]
        except ValueError:
            logger.warning(f"Unknown step: {current_step}")
            session["step"] = "done"
    
    return session["step"]

def step_prompt(step: str, transcript: str = None) -> str:
    """Generate appropriate prompt for each step"""
    if transcript:
        # Use the existing step_handlers function for GPT prompts
        return get_prompt_for_step(step, transcript)
    
    # User-facing prompts
    prompts = {
        "start": "Welcome! Let's create your invoice. Click 'Start Invoice' to begin.",
        "invoice_type": "What type of invoice is this? Say 'deposit invoice' or 'works completed invoice'.",
        "client_info": "Please provide the client's name and address.",
        "item_description": "Please describe the invoice item or service.",
        "item_value": "What is the value or price for this item?",
        "item_vat": "Is VAT applicable? If yes, what's the VAT rate? (Say 'no VAT' or '20 percent VAT')",
        "item_cis": "Is CIS applicable? If yes, what rate? (Say 'no CIS' or the CIS rate)",
        "item_retention": "Is there any retention? If yes, what percentage? (Say 'no retention' or the retention rate)",
        "item_discount": "Any discount to apply? (Say 'no discount' or the discount percentage)",
        "add_another": "Would you like to add another item or generate the invoice? (Say 'add another' or 'generate invoice')",
        "done": "Invoice information complete! Click 'Generate PDF' to create your invoice."
    }
    
    return prompts.get(step, "Please continue with the next step.")

def store_step_result(session: Dict[str, Any], step: str, result: str) -> None:
    """Store and validate step result"""
    try:
        if step == "invoice_type":
            # Expecting: 'deposit' or 'works_completed'
            invoice_type = result.strip().lower()
            if invoice_type not in ["deposit", "works_completed"]:
                raise ValidationError(f"Invalid invoice type: {invoice_type}")
            session["invoice_type"] = invoice_type
            
        elif step == "client_info":
            # Expecting JSON: {"name": "...", "address": "..."}
            client_data = json.loads(result)
            if not client_data.get("name") or not client_data.get("address"):
                raise ValidationError("Client name and address are required")
            session["client_info"] = client_data
            
        elif step == "item_description":
            # Plain text description
            description = result.strip()
            if not description:
                raise ValidationError("Item description is required")
            session["current_item"]["description"] = description
            
        elif step == "item_value":
            # Numeric value
            try:
                value = float(result.strip())
                session["current_item"]["value"] = value
            except ValueError:
                raise ValidationError(f"Invalid value: {result}")
            
        elif step == "item_vat":
            # Expecting JSON: {"vat_rate": 20.0} or {"vat_rate": 0.0}
            vat_data = json.loads(result)
            session["current_item"]["vat_rate"] = vat_data.get("vat_rate", 0.0)
            
        elif step == "item_cis":
            # Expecting JSON: {"cis_rate": 20.0} or {"cis_rate": 0.0}
            cis_data = json.loads(result)
            session["current_item"]["cis_rate"] = cis_data.get("cis_rate", 0.0)
            
        elif step == "item_retention":
            # Expecting JSON: {"retention_rate": 5.0} or {"retention_rate": 0.0}
            retention_data = json.loads(result)
            session["current_item"]["retention_rate"] = retention_data.get("retention_rate", 0.0)
            
        elif step == "item_discount":
            # Expecting JSON: {"discount_rate": 10.0} or {"discount_rate": 0.0}
            discount_data = json.loads(result)
            session["current_item"]["discount_rate"] = discount_data.get("discount_rate", 0.0)
            
            # After discount, we have a complete item - add it to items list
            if session.get("current_item"):
                item = InvoiceItem(
                    description=session["current_item"]["description"],
                    value=session["current_item"]["value"],
                    vat_rate=session["current_item"].get("vat_rate", 0.0),
                    cis_rate=session["current_item"].get("cis_rate", 0.0),
                    retention_rate=session["current_item"].get("retention_rate", 0.0),
                    discount_rate=session["current_item"].get("discount_rate", 0.0)
                )
                session["items"].append(item.dict())
                logger.info(f"Added item to invoice: {item.description}")
            
        elif step == "add_another":
            # Expecting: 'add' or 'submit'
            response = result.strip().lower()
            if response not in ["add", "submit"]:
                raise ValidationError(f"Invalid response: {response}")
            session["last_add_another_response"] = response
        
        # Save updated session
        save_session(session.get("session_id", ""), session)
        logger.info(f"Stored result for step {step}")
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response for step {step}: {str(e)}")
        raise ValidationError(f"Invalid response format: {str(e)}")
    except Exception as e:
        logger.error(f"Error storing step result for {step}: {str(e)}")
        raise ValidationError(f"Failed to process response: {str(e)}")

def get_invoice_data(session_id: str) -> Optional[Invoice]:
    """Get complete invoice data from session"""
    session = get_session(session_id)
    
    if session.get("step") != "done":
        logger.warning(f"Session {session_id} not complete. Current step: {session.get('step')}")
        return None
    
    try:
        # Calculate due date (30 days from now by default)
        due_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()
        
        # Build invoice data using existing models
        invoice = Invoice(
            reference_number=session["reference_number"],
            client=ClientInfo(
                name=session["client_info"]["name"],
                address=session["client_info"]["address"]
            ),
            details=InvoiceDetails(
                type=session["invoice_type"],
                due_date=due_date
            ),
            items=[InvoiceItem(**item) for item in session.get("items", [])]
        )
        
        logger.info(f"Built invoice data for session {session_id}")
        return invoice
        
    except Exception as e:
        logger.error(f"Error building invoice data: {str(e)}")
        return None