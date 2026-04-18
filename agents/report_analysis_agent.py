from utils.models import TestCase, AnalysisReport, ExecutionMetrics
from utils.llm_node import LLMNode
from typing import List

class ReportAndAnalysisAgent:
    def __init__(self):
        self.llm = LLMNode()

    def analyze(self, test_cases: List[TestCase], metrics: ExecutionMetrics) -> AnalysisReport:
        print("-> Performing AI-driven failure analysis and reporting...")
        
        failed_cases = [tc for tc in test_cases if tc.status == "Fail"]
        
        # Phase 1: Deep dive analysis for failed cases
        if failed_cases:
            system_message = "You are a Senior QA Automation Architect. Analyze failures and output short actionable insights."
            for tc in failed_cases:
                prompt = f"""
Test Case: {tc.id} - {tc.description}
Expected: {tc.expected}
Error: {tc.error}

Provide a 1-2 sentence root cause explanation prioritizing whether this is a flaky UI wait issue, an env issue, or a genuine bug.
Return valid JSON: {{"bug_insight": "..."}}
"""
                try:
                    res = self.llm.query_json(system_message, prompt)
                    tc.bug_insight = res.get("bug_insight", "Failed to analyze error.")
                except Exception:
                    tc.bug_insight = "LLM Parsing Failed during insight generation."

        # Phase 2: Executive Summary
        summary_payload = {
            "metrics": metrics.model_dump(),
            "failures": [{"id": tc.id, "error": tc.error, "insight": tc.bug_insight} for tc in failed_cases]
        }
        
        exec_system = "You are a QA Director reporting to stakeholders."
        exec_prompt = f"""
Summarize this test run:
{summary_payload}

Return JSON: {{"executive_summary": "1-paragraph human-readable summary"}}
"""
        executive_summary = "No summary generated."
        if metrics.total > 0:
            try:
                res = self.llm.query_json(exec_system, exec_prompt)
                executive_summary = res.get("executive_summary", executive_summary)
            except Exception:
                pass
                
        return AnalysisReport(
            metrics=metrics,
            executive_summary=executive_summary,
            test_cases=test_cases
        )
