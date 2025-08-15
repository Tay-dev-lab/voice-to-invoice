import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import ValidationError

from database import db
from models import InvoiceData, LineItem

logger = logging.getLogger(__name__)

# Define the step flow for invoice creation
STEP_FLOW = [
    "start",
    "client_info",
    "payment_terms",
    "item_1",
    "item_2",
    "item_3",
    "done"
]

def get_session(session_id: str) -> Dict[str, Any]:
    """Get or create a session"""
    session = db.get_session(session_id)
    if not session:
        session = db.create_session(session_id, {
            "step": "start",
            "items": [],
            "client_info": None,
            "payment_terms": None,
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
        "items": [],
        "client_info": None,
        "payment_terms": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id
    }
    db.update_session(session_id, initial_data)
    logger.info(f"Reset session: {session_id}")
    return initial_data

def advance_step(session: Dict[str, Any]) -> str:
    """Advance to the next step in the flow"""
    current_step = session.get("step", "start")
    
    # Handle dynamic item steps
    if current_step.startswith("item_"):
        current_item_num = int(current_step.split("_")[1])
        next_item_num = current_item_num + 1
        
        # Check if we should continue with items or finish
        if len(session.get("items", [])) >= 30 or next_item_num > 10:
            session["step"] = "done"
        else:
            session["step"] = f"item_{next_item_num}"
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
    prompts = {
        "start": "Welcome! Let's create your invoice. Please tell me your client's name and address.",
        
        "client_info": f"""Extract the client information from: "{transcript}"
        Return as JSON with structure:
        {{
            "client_name": "string",
            "client_address": "string",
            "client_email": "string (optional)",
            "client_phone": "string (optional)"
        }}""" if transcript else "Please provide your client's name and address.",
        
        "payment_terms": f"""Extract payment terms from: "{transcript}"
        Return as JSON with structure:
        {{
            "payment_due_days": integer (e.g., 30 for "Net 30"),
            "late_fee_percentage": float (optional),
            "notes": "string (optional)"
        }}""" if transcript else "What are your payment terms? (e.g., 'Net 30 days')",
        
        "done": "Invoice information complete! You can now generate your PDF."
    }
    
    # Handle dynamic item steps
    if step.startswith("item_"):
        item_num = step.split("_")[1]
        if transcript:
            return f"""Extract line item #{item_num} from: "{transcript}"
            Return as JSON with structure:
            {{
                "description": "string",
                "quantity": float,
                "unit_price": float,
                "unit": "string (e.g., 'hours', 'units', 'each')"
            }}"""
        else:
            if item_num == "1":
                return "Now let's add items to your invoice. Please describe the first item, including description, quantity, and price."
            else:
                return f"Please describe item #{item_num}, or say 'done' if you've finished adding items."
    
    return prompts.get(step, "Please continue with the next step.")

def store_step_result(session: Dict[str, Any], step: str, result: str) -> None:
    """Store and validate step result"""
    try:
        # Parse the GPT response as JSON
        parsed_result = json.loads(result)
        
        if step == "client_info":
            # Validate client info
            if not parsed_result.get("client_name") or not parsed_result.get("client_address"):
                raise ValidationError("Client name and address are required")
            session["client_info"] = parsed_result
            
        elif step == "payment_terms":
            # Validate payment terms
            if "payment_due_days" not in parsed_result:
                parsed_result["payment_due_days"] = 30  # Default to Net 30
            session["payment_terms"] = parsed_result
            
        elif step.startswith("item_"):
            # Validate line item
            item = LineItem(
                description=parsed_result.get("description", ""),
                quantity=float(parsed_result.get("quantity", 1)),
                unit_price=float(parsed_result.get("unit_price", 0)),
                unit=parsed_result.get("unit", "each")
            )
            
            if not session.get("items"):
                session["items"] = []
            session["items"].append(item.dict())
            
        # Save updated session
        save_session(session.get("session_id", ""), session)
        logger.info(f"Stored result for step {step}")
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {str(e)}")
        raise ValidationError(f"Invalid response format: {str(e)}")
    except Exception as e:
        logger.error(f"Error storing step result: {str(e)}")
        raise ValidationError(f"Failed to process response: {str(e)}")

def get_invoice_data(session_id: str) -> Optional[InvoiceData]:
    """Get complete invoice data from session"""
    session = get_session(session_id)
    
    if session.get("step") != "done":
        return None
    
    try:
        # Build invoice data
        invoice_data = InvoiceData(
            invoice_number=f"INV-{session_id[:8].upper()}",
            invoice_date=datetime.now(timezone.utc).isoformat(),
            client_name=session["client_info"]["client_name"],
            client_address=session["client_info"]["client_address"],
            client_email=session["client_info"].get("client_email"),
            client_phone=session["client_info"].get("client_phone"),
            payment_due_days=session["payment_terms"]["payment_due_days"],
            late_fee_percentage=session["payment_terms"].get("late_fee_percentage"),
            items=[LineItem(**item) for item in session.get("items", [])]
        )
        
        return invoice_data
        
    except Exception as e:
        logger.error(f"Error building invoice data: {str(e)}")
        return None