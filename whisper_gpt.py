import openai
from typing import Tuple
from models import Invoice
from dotenv import load_dotenv
import os

load_dotenv()

def set_openai_key(api_key: str):
    openai.api_key = api_key or os.getenv("OPENAI_API_KEY")

async def transcribe_audio(file_path: str) -> str:
    with open(file_path, "rb") as audio_file:
        transcript = openai.Audio.transcribe("whisper-1", audio_file)
    return transcript["text"]

async def extract_invoice_data(transcribed_text: str) -> Invoice:
    prompt = f"""
You are an invoicing assistant. Given the following transcribed voice note, extract the invoice information in structured JSON format.

Voice note:
\"\"\"
{transcribed_text}
\"\"\"

Return a JSON object like this:

{{
  "client_name": "...",
  "amount": 0.0,
  "due_date": "YYYY-MM-DD",
  "vat_rate": 20.0,
  "discount": 0.0,
  "cis_required": true,
  "invoice_type": "deposit"  // or "works_completed"
}}
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format="json"
    )

    return Invoice.parse_obj(response.choices[0].message.content)
