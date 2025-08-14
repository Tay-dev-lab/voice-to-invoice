from fastapi import FastAPI, File, UploadFile, Header, HTTPException
from whisper_gpt import transcribe_audio, extract_invoice_data, set_openai_key
import uuid
import os
import shutil
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Replace this with your actual GitHub Pages domain
origins = [
    "https://Tay-dev-lab.github.io",  # your GitHub Pages root
    "https://Tay-dev-lab.github.io/voice-to-invoice",  # full path for subfolder use
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # use ["*"] for development only!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/transcribe")
async def transcribe_and_extract(
    file: UploadFile = File(...),
    authorization: str = Header(None)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")

    api_key = authorization.split("Bearer ")[1]
    set_openai_key(api_key)

    temp_filename = f"{uuid.uuid4()}.webm"
    temp_path = os.path.join(UPLOAD_DIR, temp_filename)

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        transcribed_text = await transcribe_audio(temp_path)
        invoice_data = await extract_invoice_data(transcribed_text)
        return invoice_data.dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.remove(temp_path)
