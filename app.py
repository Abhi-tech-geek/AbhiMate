import os
import json
import uuid
import glob
from flask import Flask, render_template, request, jsonify
from agents.test_generator_agent import TestGeneratorAgent
from agents.execution_agent import ExecutionAgent
from agents.bug_analyzer_agent import BugAnalyzerAgent
from agents.reporting_agent import ReportingAgent

app = Flask(__name__)

SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    """Returns a list of all chat sessions"""
    sessions = []
    for filepath in glob.glob(os.path.join(SESSION_DIR, "*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append({
                    "id": data.get("session_id"),
                    "feature": data.get("feature", "Unknown Feature"),
                    "timestamp": os.path.getctime(filepath)
                })
        except Exception:
            pass
    # Sort newest first
    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return jsonify(sessions)

@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    """Fetch session details"""
    path = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        return jsonify({"error": "Session not found"}), 404
    
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

@app.route("/api/global_metrics", methods=["GET"])
def get_global_metrics():
    """Aggregates all execution data globally from sessions"""
    total_tests = 0
    total_passed = 0
    total_failed = 0
    reports = []
    
    for filepath in glob.glob(os.path.join(SESSION_DIR, "*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # Check if it was executed and has metrics
                if data.get("state") == "EXECUTED" and "metrics" in data:
                    metrics = data["metrics"]
                    total_tests += metrics.get("total", 0)
                    total_passed += metrics.get("passed", 0)
                    total_failed += metrics.get("failed", 0)
                    
                    reports.append({
                        "session_id": data.get("session_id"),
                        "feature": data.get("feature"),
                        "passed": metrics.get("passed", 0),
                        "failed": metrics.get("failed", 0),
                        "summary": data.get("executive_summary", "No summary.")
                    })
        except Exception:
            pass

    return jsonify({
        "aggregated_metrics": {
            "total_tests": total_tests,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "pass_rate": round((total_passed / total_tests * 100), 2) if total_tests > 0 else 0
        },
        "historical_reports": reports
    })

@app.route("/api/generate", methods=["POST"])
def generate_tests():
    data = request.json
    feature = data.get("feature", "")
    
    if not feature:
        return jsonify({"error": "Feature description is required."}), 400

    session_id = str(uuid.uuid4())
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")

    try:
        # Phase 1: Generation
        generator = TestGeneratorAgent()
        # It normally outputs to {"test_cases": ...}
        # We will wrap it with session metadata
        result = generator.generate(feature, output_path=session_file)
        
        # Inject metadata into the file
        with open(session_file, "r", encoding="utf-8") as f:
            full_data = json.load(f)
            
        full_data["session_id"] = session_id
        full_data["feature"] = feature
        full_data["state"] = "GENERATED" # Or EXECUTED
        
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(full_data, f, indent=4)
            
        return jsonify({
            "message": "Test Cases Generated Successfully",
            "session_id": session_id,
            "feature": feature,
            "test_cases": full_data.get("test_cases", [])
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/execute/<session_id>", methods=["POST"])
def execute_session(session_id):
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(session_file):
        return jsonify({"error": "Session not found"}), 404
        
    try:
        # Phase 2: Execution (in-place modification of session_file)
        executor = ExecutionAgent(input_path=session_file, output_path=session_file)
        executor.execute()
        
        # Phase 3: Analysis
        analyzer = BugAnalyzerAgent(input_path=session_file)
        analyzer.analyze()
        
        # Phase 4: Reporting
        reporter = ReportingAgent(input_path=session_file, output_path=session_file)
        final_report = reporter.report()
        
        # Mark state as EXECUTED
        with open(session_file, "r", encoding="utf-8") as f:
            full_data = json.load(f)
            
        full_data["state"] = "EXECUTED"
        # Overwrite the file with the final merged state
        # The ReportingAgent creates {"metrics": ..., "executive_summary": ..., "test_cases": ...}
        # Let's restore the metadata
        final_report["session_id"] = session_id
        final_report["feature"] = full_data.get("feature", "")
        final_report["state"] = "EXECUTED"
        
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=4)
        
        return jsonify({
            "message": "Full Automation Pipeline Complete",
            "session_id": session_id,
            "test_cases": final_report.get("test_cases", []),
            "metrics": final_report.get("metrics"),
            "executive_summary": final_report.get("executive_summary")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
