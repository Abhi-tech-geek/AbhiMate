import json
import os
from services.llm_service import LLMService

class BugAnalyzerAgent:
    def __init__(self, input_path: str = "output/execution_results.json"):
        self.input_path = input_path
        self.llm = LLMService()

    def analyze(self):
        print("Analyzing bugs for failed test cases...")
        
        if not os.path.exists(self.input_path):
            print(f"Error: Could not find {self.input_path}")
            return None

        with open(self.input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        test_cases = data.get("test_cases", [])
        failed_cases = [tc for tc in test_cases if tc.get("status") == "Fail"]
        
        if not failed_cases:
            print("No failed test cases to analyze! Great job.")
            return data

        system_message = "You are a Senior QA Automation Architect. Analyze test failures and provide root cause insights."
        
        for i, tc in enumerate(failed_cases):
            tc_id = tc.get("id", f"Unknown_{i}")
            print(f" -> Analyzing failure in [{tc_id}]...")
            
            prompt = f"""
The following automated test case failed during execution.

Test Case ID: {tc.get('id')}
Description: {tc.get('description')}
Expected: {tc.get('expected')}
Error Encountered: {tc.get('error')}

Analyze this error and provide a short, accurate explanation of what went wrong and how a developer should fix it.
Return ONLY a valid JSON object with the key "bug_insight" containing your string explanation.
            """
            
            try:
                insight_json = self.llm.prompt_json(system_message, prompt)
                tc["bug_insight"] = insight_json.get("bug_insight", "Analysis failed.")
            except Exception as e:
                tc["bug_insight"] = f"Failed to generate insight: {str(e)}"
                
        # Update the original data dictionary (which modifies test_cases in place)
        with open(self.input_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
        print("-> Bug analysis complete.")
        return data
