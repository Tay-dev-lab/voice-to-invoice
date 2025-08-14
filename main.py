from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid
import shutil
import os

from whisper_gpt import OpenAIWhisperGPT
from session_store import get_session, advance_step
from step_handlers import get_prompt_for_step

app = FastAPI()

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tay-dev-lab.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/step")
async def step_handler(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    authorization: str = Header(None)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")
    
    api_key = authorization.split("Bearer ")[1]
    temp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.webm")

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        llm = OpenAIWhisperGPT(api_key)
        transcript = await llm.transcribe(temp_path)

        session = get_session(session_id)
        step = session["step"]
        prompt = get_prompt_for_step(step, transcript)
        result = await llm.chat(prompt)

        # Save data based on step
        if step == "invoice_type":
            session["invoice_type"] = result.strip()
        elif step == "client_info":
            session["client"] = result
        elif step.startswith("item_"):
            session["current_item"][step.replace("item_", "")] = result
        elif step == "add_another":
            if "add" in result.lower():
                session["items"].append(session["current_item"])
                session["current_item"] = {}
                session["step"] = "item_description"  # loop back
            else:
                session["items"].append(session["current_item"])
                session["step"] = "done"

        if session["step"] != "done":
            advance_step(session)

        next_prompt = get_prompt_for_step(session["step"], "")
        return {
            "transcription": transcript,
            "result": result,
            "next_prompt": next_prompt if session["step"] != "done" else "Generating invoice..."
        }

    finally:
        os.remove(temp_path)