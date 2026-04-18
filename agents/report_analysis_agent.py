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

    def generate_global_insights(self, failed_cases: List[dict]) -> dict:
        print("-> Generating Global AI Insights from all failures...")
        if not failed_cases:
            return {"bug_patterns": ["No distinct bug patterns detected."], "ai_suggestions": "System is highly stable."}
            
        system_message = "You are an AI Quality Assurance Director identifying overarching themes in failures."
        prompt = f"""
Here is a complete JSON dump of all failed test cases across all sessions:
{failed_cases}

Analyze this historical data and identify:
1. "bug_patterns": A list of the Top 3 distinct recurring failure trends (e.g. timeout on login, specific selector missing).
2. "ai_suggestions": A 2-3 sentence strategic recommendation to the engineering team.

Format Requirements:
Output valid JSON:
{{
    "bug_patterns": ["trend 1", "trend 2", "trend 3"],
    "ai_suggestions": "explanation"
}}
"""
        try:
            res = self.llm.query_json(system_message, prompt)
            return {
                "bug_patterns": res.get("bug_patterns", ["Failed to deduce patterns."]),
                "ai_suggestions": res.get("ai_suggestions", "No strategic suggestions available.")
            }
        except Exception as e:
            return {
                "bug_patterns": [f"LLM Error: {{str(e)}}"],
                "ai_suggestions": "System encountered an error parsing global insights."
            }
