from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone
import logging
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import secrets

from config import config
from whisper_gpt import OpenAIWhisperGPT
from session_store import (
    get_session, advance_step, reset_session, 
    step_prompt, store_step_result, can_generate_invoice
)
from pdf_generator import generate_invoice_pdf

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Validate configuration
config.validate()

app = FastAPI(title="Voice to Invoice API")

# Configure rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS with secure settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Initialize OpenAI client with server-side API key
whisper_gpt = OpenAIWhisperGPT(config.OPENAI_API_KEY)

class SessionStart(BaseModel):
    session_id: str

class SessionReset(BaseModel):
    session_id: str

class PDFRequest(BaseModel):
    session_id: str

def validate_file_upload(file: UploadFile) -> None:
    """Validate uploaded file"""
    # Check file size (read in chunks to avoid memory issues)
    file_size = 0
    for chunk in file.file:
        file_size += len(chunk)
        if file_size > config.max_file_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {config.MAX_FILE_SIZE_MB}MB"
            )
    file.file.seek(0)  # Reset file pointer
    
    # Check content type
    allowed_types = ["audio/webm", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
        )

def generate_session_token() -> str:
    """Generate a secure session token"""
    return secrets.token_urlsafe(32)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/start")
@limiter.limit(f"{config.RATE_LIMIT_PER_MINUTE}/minute")
async def start_session(request: Request, payload: SessionStart):
    """Start a new invoice session - called when user clicks 'Create Invoice'"""
    try:
        session = get_session(payload.session_id)
        # Move from welcome to client_info when user clicks the button
        if session["step"] == "welcome":
            session["step"] = "client_info"
        session["token"] = generate_session_token()
        
        # Save the session
        from session_store import save_session
        save_session(payload.session_id, session)
        
        logger.info(f"Started session: {payload.session_id}")
        return {
            "session_token": session["token"],
            "next_prompt": step_prompt(session["step"]),
            "current_step": session["step"],
            "can_generate": can_generate_invoice(session)
        }
    except Exception as e:
        logger.error(f"Error starting session: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to start session")

@app.post("/reset")
@limiter.limit(f"{config.RATE_LIMIT_PER_MINUTE}/minute")
async def reset(request: Request, payload: SessionReset):
    """Reset a session to start over"""
    try:
        reset_session(payload.session_id)
        logger.info(f"Reset session: {payload.session_id}")
        return {
            "detail": "Session reset successfully",
            "next_prompt": step_prompt("welcome")
        }
    except Exception as e:
        logger.error(f"Error resetting session: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to reset session")

@app.post("/step")
@limiter.limit(f"{config.RATE_LIMIT_PER_MINUTE}/minute")
async def step_handler(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(...),
    session_token: str = Form(...)
):
    """Handle voice input for current step"""
    # Validate session token
    session = get_session(session_id)
    if session.get("token") != session_token:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    # Don't process if we're on welcome step
    if session["step"] == "welcome":
        raise HTTPException(status_code=400, detail="Please click 'Create Invoice' to start")
    
    # Validate file upload
    validate_file_upload(file)
    
    # Save uploaded file temporarily
    temp_path = UPLOAD_DIR / f"{uuid.uuid4()}.webm"
    
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Transcribe audio
        transcript = await whisper_gpt.transcribe(str(temp_path))
        logger.info(f"Transcribed audio for session {session_id}, step {session['step']}")
        
        # Process with GPT
        step = session["step"]
        prompt = step_prompt(step, transcript)
        result = await whisper_gpt.chat(prompt)
        
        # Store step result
        try:
            store_step_result(session, step, result)
        except ValidationError as e:
            logger.warning(f"Validation error for session {session_id}: {str(e)}")
            return {
                "transcription": transcript,
                "result": None,
                "next_prompt": f"❗ I couldn't extract the required information. Please try again.",
                "error": e.errors() if hasattr(e, 'errors') else str(e),
                "current_step": session["step"],
                "can_generate": can_generate_invoice(session),
                "items_count": len(session.get("items", []))
            }
        
        # Advance to next step
        next_step = advance_step(session)
        next_prompt = step_prompt(next_step)
        
        # Check if we can generate invoice (after first item)
        can_generate = can_generate_invoice(session)
        
        return {
            "transcription": transcript,
            "result": result,
            "next_prompt": next_prompt,
            "current_step": next_step,
            "can_generate": can_generate,
            "items_count": len(session.get("items", [])),
            "is_done": next_step == "done"
        }
        
    except Exception as e:
        logger.error(f"Error processing step for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process step")
    finally:
        # Clean up temporary file
        if temp_path.exists():
            temp_path.unlink()

@app.post("/generate")
@limiter.limit("10/hour")
async def generate_invoice(request: Request, payload: PDFRequest, session_token: str = Form(...)):
    """Generate PDF invoice from session data"""
    try:
        session = get_session(payload.session_id)
        
        # Validate session token
        if session.get("token") != session_token:
            raise HTTPException(status_code=401, detail="Invalid session token")
        
        # Check if we can generate invoice
        if not can_generate_invoice(session):
            raise HTTPException(
                status_code=400, 
                detail="Cannot generate invoice. Need at least client info, invoice details, and one item."
            )
        
        # Generate PDF
        pdf_path = await generate_invoice_pdf(session)
        logger.info(f"Generated PDF for session {payload.session_id}")
        
        # Return PDF file
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=f"invoice_{session['reference_number']}.pdf"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating PDF for session {payload.session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)