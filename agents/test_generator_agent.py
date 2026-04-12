import json
import os
from services.llm_service import LLMService

class TestGeneratorAgent:
    def __init__(self):
        self.llm = LLMService()

    def generate(self, feature: str, output_path: str = "output/test_cases.json"):
        print("Generating test cases via Groq API...")
        
        system_message = "You are an expert QA Automation Engineer."
        
        prompt = f"""
Generate exhaustive, professional, and highly detailed software test cases for the following feature.

Feature: {feature}

You must write at least 4 test cases covering Positive, Negative, and Edge scenarios.
CRITICAL: Do NOT just write short steps. Write "pure pure steps" (extremely thorough, meticulously detailed step-by-step instructions from a user's perspective, mapping out exactly what to do).
Also ensure your Selenium Python code uses sophisticated strategies (Explicit Waits, robust XPATH/CSS locators) and is perfectly functional to match your exhaustive steps!
Ensure all 5 required JSON keys are perfectly formulated.

You MUST output the response ONLY as a valid JSON object without markdown formatting.
The JSON object must contain a single key "test_cases" which is an array of objects.

Each test case object MUST have exactly these keys:
"id": (string) Test case ID (e.g., "TC001")
"type": (string) "Positive", "Negative", or "Edge"
"description": (string) Brief description of the test
"steps": (array of strings) Sequential text steps
"selenium_action": (string) Raw Python code using Selenium. Assume 'driver' is already initialized (e.g. driver.get('https://google.com')). Combine all steps into one executable block. CRITICAL: Provide a standard, properly escaped JSON string (\n for newlines, \" for quotes). Do NOT use Python triple quotes (\"\"\") inside the JSON!
"expected": (string) The expected result
        """
        
        result = self.llm.prompt_json(system_message, prompt)
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)
        
        print(f"-> Successfully saved test cases to {output_path}")
        return result
