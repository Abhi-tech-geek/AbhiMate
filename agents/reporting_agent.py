import json
import os
from services.llm_service import LLMService

class ReportingAgent:
    def __init__(self, input_path: str = "output/execution_results.json", output_path: str = "output/final_report.json"):
        self.input_path = input_path
        self.output_path = output_path
        self.llm = LLMService()

    def report(self):
        print("Generating final report...")
        
        if not os.path.exists(self.input_path):
            print(f"Error: Could not find {self.input_path}")
            return None

        with open(self.input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        test_cases = data.get("test_cases", [])
        
        total = len(test_cases)
        passed = sum(1 for tc in test_cases if tc.get("status") == "Pass")
        failed = sum(1 for tc in test_cases if tc.get("status") == "Fail")
        skipped = total - passed - failed
        
        # Prepare a lightweight summary to send to LLM
        summary_payload = {
            "metrics": {"total": total, "passed": passed, "failed": failed, "skipped": skipped},
            "failures": [{"id": tc.get("id"), "error": tc.get("error"), "insight": tc.get("bug_insight")} for tc in test_cases if tc.get("status") == "Fail"]
        }
        
        system_message = "You are a QA Director. Summarize the test execution results for the executive team."
        prompt = f"""
Here are the raw metrics and failure insights from the latest automated test run:
{json.dumps(summary_payload, indent=2)}

Please write a brief, human-readable summary of the test execution. Mention the pass/fail rates and summarize any major bugs found.
Return ONLY a valid JSON object with the key "executive_summary" containing your string response.
        """
        
        executive_summary = "No summary generated."
        if total > 0:
            try:
                res = self.llm.prompt_json(system_message, prompt)
                executive_summary = res.get("executive_summary", executive_summary)
            except Exception as e:
                executive_summary = f"Could not generate summary: {str(e)}"
        
        final_report = {
            "metrics": summary_payload["metrics"],
            "executive_summary": executive_summary,
            "test_cases": test_cases
        }
        
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=4)
            
        print(f"-> Successfully saved final report to {self.output_path}")
        
        # Print a nice console output
        print("\n========================================")
        print("         FINAL QA REPORT                ")
        print("========================================")
        print(f"Total Tests: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
        print("-" * 40)
        print("Executive Summary:")
        print(executive_summary)
        print("========================================\n")
        
        return final_report
