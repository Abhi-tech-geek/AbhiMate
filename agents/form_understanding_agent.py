import os
import json
from groq import Groq

class FormUnderstandingAgent:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)

    def analyze_dom(self, url: str, dom_context: dict) -> dict:
        """Analyzes a DOM structure and extracts key forms, input fields, and action buttons."""
        try:
            # Flatten context for LLM limit
            str_context = json.dumps(dom_context)[:10000]
            
            prompt = f"""You are the FormUnderstandingAgent. Analyze this DOM map for {url}.
            Identify critical input fields (like username, password, search bots) and primary action buttons (login, submit, search).
            Return a JSON object detailing exactly what a user would interact with to test this page.
            
            DOM Map snippet:
            {str_context}
            
            Return ONLY raw valid JSON."""

            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-70b-8192",
                temperature=0.1
            )
            
            res = chat_completion.choices[0].message.content
            # Cleanup Markdown blocks if any
            res = res.replace("```json", "").replace("```", "").strip()
            return json.loads(res)
        except Exception as e:
            return {"error": f"Form analysis failed: {str(e)}"}
