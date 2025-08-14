from openai import OpenAI

class OpenAIWhisperGPT:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    async def transcribe(self, file_path: str) -> str:
        with open(file_path, "rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return response.text

    async def chat(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()