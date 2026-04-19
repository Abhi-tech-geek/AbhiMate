import os
import time

class ReportingAgent:
    def __init__(self):
        pass

    def generate_report(self, test_cases, metrics, insights):
        """Constructs a consolidated final test execution report."""
        report = {
            "timestamp": time.time(),
            "metrics": metrics,
            "executive_summary": insights.get("summary", "No AI analysis provided."),
            "bug_report": [],
            "error_report": []
        }
        
        for tc in test_cases:
            if tc.status == "Fail":
                report["error_report"].append({"id": tc.id, "error": tc.error})
                report["bug_report"].append({"id": tc.id, "suggested_fix": tc.bug_insight})
                
        return report
