import os
from groq import Groq


class MultiLanguageAgent:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)

    @staticmethod
    def _is_plain_english(text: str) -> bool:
        """Heuristic fast-path: ASCII-only input is already English-compatible."""
        try:
            text.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    def adapt_prompt_for_locale(self, raw_input: str, target_locale: str = "en-US") -> str:
        """Translate non-English / Hinglish input to English. Skips when input is
        already ASCII and target locale is English — saves a full LLM round-trip.
        """
        if not self.api_key:
            return raw_input

        if target_locale.lower().startswith("en") and self._is_plain_english(raw_input):
            return raw_input
            
        prompt = f"""You are the MultiLanguage testing agent.
        The user may provide input in English, Hindi, or Hinglish (Hindi + English).
        Translate and adapt the following testing requirement into clear, professional English.
        If the target locale ({target_locale}) requires specific currency/date formatting, note that. 
        DO NOT answer the prompt. ONLY output the translated English testing requirement.
        
        Original Input: {raw_input}
        
        Output only the translated context ready for the test generator."""

        try:
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.1
            )
            return chat_completion.choices[0].message.content.strip()
        except:
            return raw_input
