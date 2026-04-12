import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

class LLMService:
    """
    Unified service to interact with the Groq API.
    Used by all Multi-Agent components.
    """
    def __init__(self, model="llama-3.3-70b-versatile"):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key or api_key == "your_api_key_here":
            raise ValueError("GROQ_API_KEY is not set properly. Please update the .env file.")
        
        self.client = Groq(api_key=api_key)
        self.model = model

    def prompt_json(self, system_message: str, user_prompt: str) -> dict:
        """
        Forces LLM to return a valid JSON object.
        """
        response = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            model=self.model,
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content) if content else {}
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {str(e)} -> {content}")

    def prompt_text(self, system_message: str, user_prompt: str) -> str:
        """
        Returns a standard text response.
        """
        response = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            model=self.model,
            temperature=0.7
        )
        content = response.choices[0].message.content
        return content if content else ""
