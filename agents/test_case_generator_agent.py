from utils.llm_node import LLMNode
from utils.models import TestCase
from typing import List
import json

class TestCaseGeneratorAgent:
    def __init__(self):
        self.llm = LLMNode()

    def generate(self, feature: str) -> List[TestCase]:
        print("-> Generating test cases via LLM...")
        
        system_message = "You are an expert QA Automation Engineer."
        
        prompt = f"""
Generate exhaustive, professional, and highly detailed software test cases for the following feature.

Feature: {feature}

You must write exactly 5 test cases covering Positive, Negative, and Edge scenarios.
Write extremely thorough step-by-step instructions from a user's perspective.
Provide executable Python Selenium code block (store in selenium_action) assuming 'driver' is already initialized.

Format Requirements:
Output valid JSON containing a single key "test_cases" which maps to an array.
Each object must precisely match this schema:
{{
    "id": "string (e.g. TC001)",
    "type": "Positive | Negative | Edge",
    "description": "string",
    "steps": ["string", "string"],
    "selenium_action": "string (Python code snippet)",
    "expected": "string"
}}
"""
        
        result_dict = self.llm.query_json(system_message, prompt)
        raw_cases = result_dict.get("test_cases", [])
        
        # Validate against Pydantic model
        validated_cases = []
        for index, rc in enumerate(raw_cases):
            # Enforce required keys
            try:
                tc = TestCase(**rc)
                validated_cases.append(tc)
            except Exception as e:
                print(f"Validation failed for case index {index}: {e}")
                
        return validated_cases

    def generate_from_url_dom(self, url: str, dom_data: dict) -> List[TestCase]:
        print(f"-> Generating tests dynamically for URL: {url}...")
        
        system_message = "You are an expert QA Automation Engineer."
        
        prompt = f"""
I have extracted the Document Object Model (DOM) from the target URL: {url}.
The page title is: {dom_data.get('title', 'Unknown')}
Here are all the interactable HTML elements natively mapped:
{json.dumps(dom_data.get('interactable_elements', []), indent=2)}

Your task is to write exhaustive automation test cases strictly mapping to these EXACT elements.
Use the verified HTML 'id', 'name', or 'type' inside your Selenium locators (e.g., By.ID, By.NAME).
Do not hallucinate locators not present in the DOM map above!
The 'driver' is already initialized and already sitting on the URL {url}.

Write 3 to 5 test cases focusing on core interactions.

Format Requirements:
Output valid JSON containing a single key "test_cases" which maps to an array.
Each object must precisely match this schema:
{{
    "id": "string",
    "type": "Positive | Negative | Edge",
    "description": "string",
    "steps": ["string", "string"],
    "selenium_action": "string (Python code snippet)",
    "expected": "string"
}}
"""
        result_dict = self.llm.query_json(system_message, prompt)
        raw_cases = result_dict.get("test_cases", [])
        
        validated_cases = []
        for index, rc in enumerate(raw_cases):
            try:
                tc = TestCase(**rc)
                validated_cases.append(tc)
            except Exception as e:
                print(f"Validation failed for case index {index}: {e}")
                
        return validated_cases
