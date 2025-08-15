import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from database import db
from models import Invoice, InvoiceDetails, ClientInfo, InvoiceItem

logger = logging.getLogger(__name__)

# Custom exception for input validation errors
class InputValidationError(Exception):
    """Custom exception for input validation errors with user-friendly messages"""
    pass

# Define the step flow for invoice creation
STEP_FLOW = [
    "welcome",           # Step 1: Welcome screen with button
    "client_info",       # Step 2: Get recipient name and address
    "invoice_details",   # Step 3: Invoice type and due date
    "item_1",           # Step 4: First item details
    "item_2",           # Step 5+: Additional items (up to 30)
    # ... dynamically continues to item_30
    "done"
]

def get_session(session_id: str) -> Dict[str, Any]:
    """Get or create a session"""
    session = db.get_session(session_id)
    if not session:
        session = db.create_session(session_id, {
            "step": "welcome",
            "client_info": None,
            "invoice_details": None,
            "items": [],
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
        "step": "welcome",
        "client_info": None,
        "invoice_details": None,
        "items": [],
        "reference_number": f"INV-{session_id[:8].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id
    }
    db.update_session(session_id, initial_data)
    logger.info(f"Reset session: {session_id}")
    return initial_data

def advance_step(session: Dict[str, Any]) -> str:
    """Advance to the next step in the flow"""
    current_step = session.get("step", "welcome")
    
    if current_step == "welcome":
        session["step"] = "client_info"
    elif current_step == "client_info":
        session["step"] = "invoice_details"
    elif current_step == "invoice_details":
        session["step"] = "item_1"
    elif current_step.startswith("item_"):
        # Extract item number and increment
        current_num = int(current_step.split("_")[1])
        if current_num >= 30:
            session["step"] = "done"
        else:
            session["step"] = f"item_{current_num + 1}"
    else:
        session["step"] = "done"
    
    save_session(session["session_id"], session)
    return session["step"]

def step_prompt(step: str, transcript: str = None) -> str:
    """Generate appropriate prompt for each step"""
    
    if transcript:
        # GPT prompts for processing transcribed text
        if step == "client_info":
            return f"""Extract the client's name and address from: "{transcript}"

Return ONLY raw JSON, no markdown formatting or explanations:
{{"name": "string", "address": "string"}}"""
            
        elif step == "invoice_details":
            return f"""Extract invoice type and payment due date from: "{transcript}"
            The invoice type should be either "deposit" or "works_completed".
            Parse any date mentioned (e.g., "30 days", "end of month", specific date).
            
Return ONLY raw JSON, no markdown formatting or explanations:
{{"type": "deposit", "due_date": "YYYY-MM-DD"}}"""
            
        elif step.startswith("item_"):
            item_num = step.split("_")[1]
            return f"""Extract invoice item #{item_num} details from: "{transcript}"
            Parse the description, value, and any applicable rates mentioned.
            If rates are not mentioned, assume they are 0.
            If you cannot determine the value, use 0.
            If you cannot determine the description, use empty string "".
            
Return ONLY raw JSON, no markdown formatting or explanations:
{{"description": "string", "value": 0.0, "vat_rate": 0.0, "cis_rate": 0.0, "retention_rate": 0.0, "discount_rate": 0.0}}"""
    
    # User-facing prompts
    if step == "welcome":
        return "Would you like to create an invoice?"
    elif step == "client_info":
        return "What is the recipient's name and address?"
    elif step == "invoice_details":
        return "Do you require a works invoice or a deposit invoice, and when is it due to be paid?"
    elif step.startswith("item_"):
        item_num = step.split("_")[1]
        if item_num == "1":
            return "Describe Item 1 of the invoice including the value, the rate of VAT (if any), the rate of CIS (if any), retention deduction (if any), and discount (if any)"
        else:
            return f"Describe Item {item_num} of the invoice including the value, the rate of VAT (if any), the rate of CIS (if any), retention deduction (if any), and discount (if any)"
    elif step == "done":
        return "Invoice information complete! Click 'Create Invoice PDF' to generate your invoice."
    else:
        return "Please continue with the next step."

def clean_json_response(response: str) -> str:
    """Clean GPT response to extract JSON, handling various formats"""
    response = response.strip()
    
    # Remove markdown code blocks if present
    if response.startswith('```'):
        lines = response.split('\n')
        if lines[0].startswith('```') and lines[-1] == '```':
            response = '\n'.join(lines[1:-1])
    
    # Remove any leading/trailing whitespace
    response = response.strip()
    
    # If it starts with 'json' (from ```json), remove it
    if response.startswith('json'):
        response = response[4:].strip()
    
    return response

def store_step_result(session: Dict[str, Any], step: str, result: str) -> None:
    """Store and validate step result"""
    try:
        # Clean the GPT response first
        cleaned_result = clean_json_response(result)
        
        if step == "client_info":
            # Parse ClientInfo from GPT response
            try:
                client_data = json.loads(cleaned_result)
            except json.JSONDecodeError:
                # Try to extract name and address using regex as fallback
                import re
                name_match = re.search(r'"name"\s*:\s*"([^"]+)"', cleaned_result)
                address_match = re.search(r'"address"\s*:\s*"([^"]+)"', cleaned_result)
                
                if name_match and address_match:
                    client_data = {
                        "name": name_match.group(1),
                        "address": address_match.group(1)
                    }
                else:
                    raise json.JSONDecodeError("Could not parse client info", cleaned_result, 0)
            
            # Detailed validation with specific error messages
            if not client_data.get("name"):
                raise InputValidationError(
                    "Client name is missing. Please say the full name clearly. "
                    "Example: 'John Smith' or 'ABC Company Ltd'"
                )
            if not client_data.get("address"):
                raise InputValidationError(
                    "Client address is missing. Please provide the complete address. "
                    "Example: '123 Main Street, London, SW1A 1AA'"
                )
            
            # Create ClientInfo instance to validate
            client = ClientInfo(
                name=client_data["name"],
                address=client_data["address"]
            )
            session["client_info"] = client.model_dump(mode='json')
            
        elif step == "invoice_details":
            # Parse InvoiceDetails from GPT response
            try:
                details_data = json.loads(cleaned_result)
            except json.JSONDecodeError:
                # Fallback parsing for common variations
                import re
                type_match = re.search(r'"type"\s*:\s*"(deposit|works_completed)"', cleaned_result)
                date_match = re.search(r'"due_date"\s*:\s*"([^"]+)"', cleaned_result)
                
                if type_match:
                    details_data = {
                        "type": type_match.group(1),
                        "due_date": date_match.group(1) if date_match else None
                    }
                else:
                    raise json.JSONDecodeError("Could not parse invoice details", cleaned_result, 0)
            
            # Validate that we have required fields before processing
            if not details_data.get("type"):
                raise InputValidationError(
                    "Invoice type is missing. Please clearly state whether this is a "
                    "'deposit invoice' or 'works completed invoice'."
                )
            
            invoice_type = details_data.get("type")
            if invoice_type not in ["deposit", "works_completed"]:
                raise InputValidationError(
                    f"Invalid invoice type '{invoice_type}'. Please say either "
                    "'deposit invoice' or 'works completed invoice'."
                )
            
            # Parse and validate the due date
            if not details_data.get("due_date"):
                raise InputValidationError(
                    "Payment due date is missing. Please specify when payment is due. "
                    "Examples: 'in 30 days', 'end of month', 'November 15th'"
                )
            
            try:
                due_date = datetime.fromisoformat(details_data["due_date"]).date()
            except:
                raise InputValidationError(
                    f"Invalid date format '{details_data.get('due_date')}'. "
                    "Please specify a clear due date like '30 days' or 'end of month'."
                )
            
            # Create InvoiceDetails instance
            details = InvoiceDetails(
                type=invoice_type,
                due_date=due_date
            )
            session["invoice_details"] = details.model_dump(mode='json')
            
        elif step.startswith("item_"):
            # Parse InvoiceItem from GPT response
            try:
                item_data = json.loads(cleaned_result)
            except json.JSONDecodeError:
                # Fallback parsing for item data
                import re
                desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', cleaned_result)
                value_match = re.search(r'"value"\s*:\s*([\d.]+)', cleaned_result)
                
                if desc_match and value_match:
                    item_data = {
                        "description": desc_match.group(1),
                        "value": float(value_match.group(1))
                    }
                    # Try to extract optional rates
                    vat_match = re.search(r'"vat_rate"\s*:\s*([\d.]+)', cleaned_result)
                    if vat_match:
                        item_data["vat_rate"] = float(vat_match.group(1))
                else:
                    # If we can't parse, provide helpful error message
                    raise InputValidationError(
                        "I couldn't understand the item details. Please clearly state: "
                        "1) What the item is (description), "
                        "2) The amount/value in pounds. "
                        "Example: 'Website development for £1500'"
                    )
            
            # Create InvoiceItem instance with defaults for missing fields
            item = InvoiceItem(
                description=item_data.get("description", ""),
                value=float(item_data.get("value", 0)),
                vat_rate=float(item_data.get("vat_rate", 0.0)),
                cis_rate=float(item_data.get("cis_rate", 0.0)),
                retention_rate=float(item_data.get("retention_rate", 0.0)),
                discount_rate=float(item_data.get("discount_rate", 0.0))
            )
            
            # Validate that we have at least description and value
            if not item.description:
                raise InputValidationError(
                    "Item description is missing. Please describe what work or product this is for. "
                    "Example: 'Website development for homepage redesign'"
                )
            if item.value <= 0:
                raise InputValidationError(
                    f"Item value must be a positive amount. You said: {item.value}. "
                    "Please state the amount clearly. Example: 'One thousand five hundred pounds' or '1500 pounds'"
                )
            
            # Add to items list
            if not session.get("items"):
                session["items"] = []
            session["items"].append(item.model_dump(mode='json'))
            logger.info(f"Added item {len(session['items'])}: {item.description}")
        
        # Save updated session
        save_session(session.get("session_id", ""), session)
        logger.info(f"Stored result for step {step}")
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response for step {step}: {str(e)}")
        # Provide step-specific error messages
        if step == "client_info":
            raise InputValidationError(
                "I couldn't understand the client information. "
                "Please clearly state the client's name and full address."
            )
        elif step == "invoice_details":
            raise InputValidationError(
                "I couldn't understand the invoice details. "
                "Please clearly state whether this is a deposit or works completed invoice, "
                "and when payment is due (e.g., '30 days' or 'end of month')."
            )
        elif step.startswith("item_"):
            raise InputValidationError(
                "I couldn't understand the item details. "
                "Please clearly state what the item is and its value in pounds."
            )
        else:
            raise InputValidationError(f"I couldn't understand your response. Please try again.")
    except Exception as e:
        logger.error(f"Error storing step result for {step}: {str(e)}")
        raise InputValidationError(f"Failed to process response: {str(e)}")

def can_generate_invoice(session: Dict[str, Any]) -> bool:
    """Check if session has enough data to generate an invoice"""
    return (
        session.get("client_info") is not None and
        session.get("invoice_details") is not None and
        len(session.get("items", [])) > 0
    )

def get_invoice_data(session_id: str) -> Optional[Invoice]:
    """Get complete invoice data from session"""
    session = get_session(session_id)
    
    if not can_generate_invoice(session):
        logger.warning(f"Session {session_id} doesn't have enough data to generate invoice")
        return None
    
    try:
        # Parse the stored due_date
        invoice_details = session["invoice_details"]
        if isinstance(invoice_details["due_date"], str):
            due_date = datetime.fromisoformat(invoice_details["due_date"]).date()
        else:
            due_date = invoice_details["due_date"]
        
        # Build invoice using existing models
        invoice = Invoice(
            reference_number=session["reference_number"],
            client=ClientInfo(**session["client_info"]),
            details=InvoiceDetails(
                type=invoice_details["type"],
                due_date=due_date
            ),
            items=[InvoiceItem(**item) for item in session.get("items", [])]
        )
        
        logger.info(f"Built invoice data for session {session_id}")
        return invoice
        
    except Exception as e:
        logger.error(f"Error building invoice data: {str(e)}")
        return None