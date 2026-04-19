import os
from groq import Groq

class RootCauseAnalyzerAgent:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key)

    def analyze_failure(self, test_id: str, error_stacktrace: str) -> str:
        """Deeply analyzes execution failures to pinpoint root causes and suggest Dev/UX fixes."""
        if not self.api_key:
            return "Analysis blocked: API key missing."
            
        try:
            prompt = f"""You are the RootCauseAnalyzerAgent, a senior QA debugging engineer.
            Test Case [{test_id}] failed during execution.
            
            Stacktrace log:
            {error_stacktrace}
            
            Provide a short, 1-2 sentence root cause explanation and a likely fix to hand back to the developer."""

            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-70b-8192",
                temperature=0.2
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            return f"Analyzer error: {str(e)}"
