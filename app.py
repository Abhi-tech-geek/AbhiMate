import os
import time
import uuid
from flask import Flask, render_template, request, jsonify

from utils.models import TestSession
from agents.test_case_generator_agent import TestCaseGeneratorAgent
from agents.automation_executor_agent import AutomationExecutorAgent
from agents.report_analysis_agent import ReportAndAnalysisAgent
from agents.memory_manager_agent import MemoryManagerAgent

app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")

# Initialize Agents
generator_agent = TestCaseGeneratorAgent()
executor_agent = AutomationExecutorAgent()
report_agent = ReportAndAnalysisAgent()
memory_agent = MemoryManagerAgent()


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    """Returns a lightweight list of all test sessions"""
    try:
        sessions = memory_agent.list_all_sessions()
        return jsonify(sessions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    """Fetch full session details including cases and reports"""
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

@app.route("/api/generate", methods=["POST"])
def generate_tests():
    data = request.json
    feature = data.get("feature", "")
    
    if not feature:
        return jsonify({"error": "Feature description is required."}), 400

    session_id = str(uuid.uuid4())
    
    try:
        # Agent 1: Generate Test Cases
        test_cases = generator_agent.generate(feature)
        
        # Create Session Object
        session = TestSession(
            session_id=session_id,
            feature=feature,
            state="GENERATED",
            timestamp=time.time(),
            test_cases=test_cases
        )
        
        # Agent 4: Store in Memory
        memory_agent.save_session(session)
            
        return jsonify({
            "message": "Test Cases Generated Successfully",
            "session": session.model_dump()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/execute/<session_id>", methods=["POST"])
def execute_session(session_id):
    environment = request.json.get("environment", "web")
    
    try:
        # Load from DB
        session = memory_agent.load_session(session_id)
        
        if not session.test_cases:
            return jsonify({"error": "No test cases found in this session."}), 400
            
        # Agent 2: Execution
        executor_agent.mode = environment 
        updated_cases, metrics = executor_agent.execute(session.test_cases, session_id)
        
        # Update session with executed test cases
        session.test_cases = updated_cases
        session.state = "EXECUTED"
        memory_agent.save_session(session)
        
        # Agent 3: Analysis and Reporting
        report = report_agent.analyze(session.test_cases, metrics)
        session.report = report
        
        # Agent 4: Final Save to Memory
        memory_agent.save_session(session)
        
        return jsonify({
            "message": "Automation Execution Complete",
            "session": session.model_dump()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/execute_direct", methods=["POST"])
def execute_direct():
    data = request.json
    feature = data.get("feature", "Direct Automated Execution")
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
        
        executor_agent.mode = environment 
        updated_cases, metrics = executor_agent.execute(session.test_cases, session_id)
        
        session.test_cases = updated_cases
        session.state = "EXECUTED"
        memory_agent.save_session(session)
        
        report = report_agent.analyze(session.test_cases, metrics)
        session.report = report
        
        memory_agent.save_session(session)
        
        return jsonify({
            "message": "Direct Execution Complete",
            "session": session.model_dump()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/zero_touch", methods=["POST"])
def zero_touch_execute():
    data = request.json
    feature = data.get("feature", "")
    environment = data.get("environment", "web")
    
    if not feature:
        return jsonify({"error": "Feature description is required."}), 400

    session_id = str(uuid.uuid4())
    try:
        # Phase 1: Generate
        test_cases = generator_agent.generate(feature)
        session = TestSession(
            session_id=session_id,
            feature=feature,
            state="GENERATED",
            timestamp=time.time(),
            test_cases=test_cases
        )
        memory_agent.save_session(session)
        
        # Phase 2: Execute Immediately
        executor_agent.mode = environment 
        updated_cases, metrics = executor_agent.execute(session.test_cases, session_id)
        session.test_cases = updated_cases
        session.state = "EXECUTED"
        memory_agent.save_session(session)
        
        # Phase 3: Reporting
        report = report_agent.analyze(session.test_cases, metrics)
        session.report = report
        memory_agent.save_session(session)
        
        return jsonify({
            "message": "Zero-Touch Execution Complete",
            "session": session.model_dump()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
