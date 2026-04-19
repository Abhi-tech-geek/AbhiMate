import os
import time
import uuid
import re
from flask import Flask, render_template, request, jsonify

from utils.models import TestSession
from agents.test_case_generator_agent import TestCaseGeneratorAgent
from agents.automation_executor_agent import AutomationExecutorAgent
from agents.report_analysis_agent import ReportAndAnalysisAgent
from agents.memory_manager_agent import MemoryManagerAgent

# Import NEW Agents
from agents.form_understanding_agent import FormUnderstandingAgent
from agents.root_cause_analyzer_agent import RootCauseAnalyzerAgent
from agents.reporting_agent import ReportingAgent
from agents.performance_testing_agent import PerformanceTestingAgent
from agents.multi_language_agent import MultiLanguageAgent
from agents.data_driven_testing_agent import DataDrivenTestingAgent
from agents.model_selector_agent import ModelSelectorAgent

app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")

# Initialize Pipeline Base Agents
generator_agent = TestCaseGeneratorAgent()
executor_agent = AutomationExecutorAgent()
report_agent = ReportAndAnalysisAgent() 
memory_agent = MemoryManagerAgent()

# Initialize NEW Agents
form_agent = FormUnderstandingAgent()
rca_agent = RootCauseAnalyzerAgent()
new_reporter = ReportingAgent()
perf_agent = PerformanceTestingAgent()
lang_agent = MultiLanguageAgent()
data_driven_agent = DataDrivenTestingAgent()
model_selector = ModelSelectorAgent()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    try:
        sessions = memory_agent.list_all_sessions()
        return jsonify(sessions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    try:
        session = memory_agent.load_session(session_id)
        return jsonify(session.model_dump())
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    try:
        memory_agent.delete_session(session_id)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/reports/global_insights", methods=["GET"])
def get_global_insights():
    session_metadata = memory_agent.list_all_sessions()
    failed_cases_payload = []
    total_cases = 0
    total_passes = 0
    total_fails = 0
    
    for meta in session_metadata:
        try:
            session = memory_agent.load_session(meta["session_id"])
            if session.report:
                total_cases += session.report.metrics.total
                total_passes += session.report.metrics.passed
                total_fails += session.report.metrics.failed
                for tc in session.test_cases:
                    if tc.status == "Fail":
                        failed_cases_payload.append({
                            "session": session.feature,
                            "test_id": tc.id,
                            "description": tc.description,
                            "error": tc.error,
                            "isolated_insight": tc.bug_insight
                        })
        except Exception:
            continue
    insights = report_agent.generate_global_insights(failed_cases_payload)
    return jsonify({
        "total_evaluated": total_cases,
        "pass_rate": round(total_passes/total_cases*100, 1) if total_cases > 0 else 0,
        "total_failures": total_fails,
        "most_failing_tests": failed_cases_payload[-10:],
        "bug_patterns": insights.get("bug_patterns", []),
        "ai_suggestions": insights.get("ai_suggestions", "")
    })

# -------------------------------------------------------------
# 🤖 UNIFIED INTELLIGENT ROUTING (Smart Input + Multi-Agent)
# -------------------------------------------------------------
@app.route("/api/smart_input", methods=["POST"])
def smart_generate():
    data = request.json
    raw_prompt = data.get("prompt", "")
    auto_run = data.get("autoRun", False)
    env = data.get("environment", "web")
    model_pref = data.get("model", "accurate")
    target_lang = data.get("lang", "en-US")
    
    if not raw_prompt:
        return jsonify({"error": "Prompt field is required."}), 400

    # Truncate Feature Name cleanly to 1-2 words
    words = raw_prompt.split()
    feature_name = " ".join(words[:2]) + "..." if len(words) > 2 else raw_prompt

    session_id = str(uuid.uuid4())
    
    try:
        # MultiLanguage Adaptation
        adapted_prompt = lang_agent.adapt_prompt_for_locale(raw_prompt, target_lang)
        
        # URL Autodetection
        url_match = re.search(r'(https?://[^\s]+)', adapted_prompt)
        
        if url_match:
            target_url = url_match.group(1)
            # Agent 2: FormUnderstanding via Webscraper
            from utils.automation_drivers import WebSeleniumDriver
            driver = WebSeleniumDriver()
            dom_map = {"error": "Driver failure"}
            try:
                dom_map = driver.extract_dom_map(target_url)
                driver.quit()
                if "error" in dom_map: raise Exception(dom_map["error"])
            except Exception as e:
                try: driver.quit()
                except: pass
                raise Exception("DOM extraction failed: " + str(e))
                
            clean_dom = form_agent.analyze_dom(target_url, dom_map)
            test_cases = generator_agent.generate_from_url_dom(target_url, clean_dom)
            feature_name = f"DOM Scrape: {target_url}"
        else:
            # Standard Generation
            test_cases = generator_agent.generate(adapted_prompt)
            
        session = TestSession(
            session_id=session_id,
            feature=feature_name,
            state="GENERATED",
            timestamp=time.time(),
            test_cases=test_cases
        )
        memory_agent.save_session(session)
        
        # ⚡ Optional Immedate Execution
        if auto_run:
            start_t = time.time()
            executor_agent.mode = env
            updated_cases, metrics = executor_agent.execute(session.test_cases, session_id)
            end_t = time.time()
            
            # Post-Execution Advanced Analytics (RootCause & Performance)
            for tc in updated_cases:
                if tc.status == "Fail" and tc.error:
                    tc.bug_insight = rca_agent.analyze_failure(tc.id, tc.error)
                    
            session.test_cases = updated_cases
            session.state = "EXECUTED"
            
            perf_insight = perf_agent.evaluate_performance([end_t - start_t])
            legacy_report = report_agent.analyze(session.test_cases, metrics)
            legacy_report.executive_summary += f" | ⚡ Perf Status: {perf_insight['status']} ({perf_insight['average_time_seconds']}s)"
            session.report = legacy_report
            
        memory_agent.save_session(session)
        return jsonify({"message": "Pipeline Complete", "session": session.model_dump()})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/execute/<session_id>", methods=["POST"])
def execute_session(session_id):
    """Executes a previously Generated session (For Manual Approvals)"""
    environment = request.json.get("environment", "web")
    try:
        session = memory_agent.load_session(session_id)
        if not session.test_cases:
            return jsonify({"error": "No test cases found in this session."}), 400
            
        start_t = time.time()
        executor_agent.mode = environment 
        updated_cases, metrics = executor_agent.execute(session.test_cases, session_id)
        end_t = time.time()
        
        for tc in updated_cases:
            if tc.status == "Fail" and tc.error:
                tc.bug_insight = rca_agent.analyze_failure(tc.id, tc.error)
                
        session.test_cases = updated_cases
        session.state = "EXECUTED"
        
        perf_insight = perf_agent.evaluate_performance([end_t - start_t])
        legacy_report = report_agent.analyze(session.test_cases, metrics)
        legacy_report.executive_summary += f" | ⚡ Perf Status: {perf_insight['status']} ({perf_insight['average_time_seconds']}s)"
        session.report = legacy_report
        
        memory_agent.save_session(session)
        return jsonify({"message": "Execution Complete", "session": session.model_dump()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------
# 🏢 UNTOUCHED AUTOMATION TAB PRESERVED (Direct + DataDriven)
# -------------------------------------------------------------
@app.route("/api/execute_direct", methods=["POST"])
def execute_direct():
    data = request.json
    feature_raw = data.get("feature", "Direct Execution")
    words = feature_raw.split()
    feature = " ".join(words[:2]) + "..." if len(words) > 2 else feature_raw
    environment = data.get("environment", "web")
    raw_cases = data.get("test_cases", [])
    
    if not raw_cases:
        return jsonify({"error": "No test cases provided."}), 400

    from utils.models import TestCase
    test_cases = []
    for rc in raw_cases:
        try:
            tc = TestCase(**rc)
            test_cases.append(tc)
        except Exception as e:
            return jsonify({"error": f"Invalid test case schema: {str(e)}"}), 400
            
    session_id = str(uuid.uuid4())
    try:
        session = TestSession(
            session_id=session_id,
            feature=feature,
            state="GENERATED",
            timestamp=time.time(),
            test_cases=test_cases
        )
        memory_agent.save_session(session)
        
        start_t = time.time()
        executor_agent.mode = environment 
        updated_cases, metrics = executor_agent.execute(session.test_cases, session_id)
        end_t = time.time()
        
        for tc in updated_cases:
            if tc.status == "Fail" and tc.error:
                tc.bug_insight = rca_agent.analyze_failure(tc.id, tc.error)
                
        session.test_cases = updated_cases
        session.state = "EXECUTED"
        
        perf_insight = perf_agent.evaluate_performance([end_t - start_t])
        legacy_report = report_agent.analyze(session.test_cases, metrics)
        legacy_report.executive_summary += f" | ⚡ Perf Status: {perf_insight['status']}"
        session.report = legacy_report
        
        memory_agent.save_session(session)
        return jsonify({"message": "Direct Execution Complete", "session": session.model_dump()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/data_driven", methods=["POST"])
def execute_data_driven():
    """Allows CSV parsing to execute multi-variant tests inside Automation tab."""
    data = request.json
    csv_payload = data.get("csv", "")
    environment = data.get("environment", "web")
    
    if not csv_payload:
        return jsonify({"error": "CSV mapping empty."}), 400
        
    try:
        variants = data_driven_agent.parse_payload(csv_payload)
        return jsonify({"variants_loaded": len(variants), "message": f"Successfully mapped {len(variants)} Data-Driven test scenarios."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
