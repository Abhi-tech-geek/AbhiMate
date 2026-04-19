import os
from groq import Groq

class MultiLanguageAgent:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)

    def adapt_prompt_for_locale(self, raw_input: str, target_locale: str = "en-US") -> str:
        """Translates inputs into standard English before testing, while preserving intended locale for the output."""
        if not self.api_key:
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
                model="llama3-8b-8192", 
                temperature=0.1
            )
            return chat_completion.choices[0].message.content.strip()
        except:
            return raw_input
