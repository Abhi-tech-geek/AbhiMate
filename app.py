import os
import time
import uuid
import re
import json
import threading
from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, abort, Response, stream_with_context, redirect, url_for,
)

from utils.models import TestSession, TestCase
from utils.llm_node import LLMConfigError
from utils.auth import (
    configure_flask, login_required, current_user_id,
    hash_password, verify_password, validate_signup,
    set_session_user, clear_session_user,
)
from agents.test_case_generator_agent import TestCaseGeneratorAgent
from agents.automation_executor_agent import AutomationExecutorAgent
from agents.report_analysis_agent import ReportAndAnalysisAgent
from agents.deep_dive_agent import DeepDiveAgent, gather_deep_dive_context
from agents.memory_manager_agent import (
    MemoryManagerAgent, QuotaExceeded, NotOwner, SESSION_QUOTA_PER_USER,
)

# Import NEW Agents
from agents.form_understanding_agent import FormUnderstandingAgent
from agents.root_cause_analyzer_agent import RootCauseAnalyzerAgent
from agents.performance_testing_agent import PerformanceTestingAgent
from agents.multi_language_agent import MultiLanguageAgent
from agents.data_driven_testing_agent import DataDrivenTestingAgent
from agents.model_selector_agent import ModelSelectorAgent

app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")
configure_flask(app)

# Initialize Pipeline Base Agents
generator_agent = TestCaseGeneratorAgent()
executor_agent = AutomationExecutorAgent()
report_agent = ReportAndAnalysisAgent()
deep_dive_agent = DeepDiveAgent()
memory_agent = MemoryManagerAgent()

# Initialize NEW Agents
form_agent = FormUnderstandingAgent()
rca_agent = RootCauseAnalyzerAgent()
perf_agent = PerformanceTestingAgent()
lang_agent = MultiLanguageAgent()
data_driven_agent = DataDrivenTestingAgent()
model_selector = ModelSelectorAgent()


# ============================================================
# Phase C — Authentication routes
# ============================================================

@app.route("/")
def index():
    # Gate the SPA — anonymous users land on the auth screen.
    if current_user_id() is None:
        return redirect(url_for("auth_page"))
    return render_template("index.html")


@app.route("/signup", methods=["GET"])
@app.route("/login", methods=["GET"])
def auth_page():
    if current_user_id() is not None:
        return redirect(url_for("index"))
    initial_mode = "signup" if request.path == "/signup" else "login"
    return render_template("auth.html", initial_mode=initial_mode)


@app.route("/api/auth/signup", methods=["POST"])
def auth_signup():
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None

    err = validate_signup(email, password)
    if err:
        return jsonify({"error": err}), 400

    if memory_agent.db.get_user_by_email(email) is not None:
        return jsonify({"error": "An account with this email already exists."}), 409

    user_id = memory_agent.db.create_user(email, hash_password(password), display_name)
    set_session_user(user_id)
    memory_agent.db.update_last_login(user_id)
    return jsonify({"id": user_id, "email": email, "display_name": display_name}), 201


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = memory_agent.db.get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        # Same error message either way — don't leak which emails exist.
        return jsonify({"error": "Invalid email or password."}), 401

    set_session_user(user["id"])
    memory_agent.db.update_last_login(user["id"])
    return jsonify({
        "id": user["id"], "email": user["email"], "display_name": user.get("display_name"),
    })


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    clear_session_user()
    return jsonify({"status": "logged_out"})


# LLM-config errors anywhere in the request should surface as a friendly JSON
# response with a hint, not a 500 with a stack trace.
@app.errorhandler(LLMConfigError)
def _handle_llm_config_error(e: LLMConfigError):
    return jsonify({
        "error": e.message,
        "hint": e.hint or None,
        "code": "llm_unavailable",
    }), e.http_status


@app.route("/api/llm/ping", methods=["GET"])
@login_required
def llm_ping():
    """Cheap health check the UI uses to surface bad/expired keys early."""
    return jsonify(generator_agent.llm.ping())


@app.route("/api/locator_cache", methods=["GET"])
@login_required
def locator_cache_list():
    """Inspect the self-heal cache (Feature #9). Shows which selectors won
    after the original primary missed, host-by-host."""
    host = request.args.get("host") or None
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except (TypeError, ValueError):
        limit = 200
    rows = memory_agent.db.list_locator_cache(host=host, limit=limit)
    return jsonify({"entries": rows, "host_filter": host, "count": len(rows)})


@app.route("/api/locator_cache", methods=["DELETE"])
@login_required
def locator_cache_clear():
    """Wipe the self-heal cache (optionally for one host)."""
    host = request.args.get("host") or None
    deleted = memory_agent.db.clear_locator_cache(host=host)
    return jsonify({"deleted": deleted, "host_filter": host})


# ----- Visual baselines (Feature #4) -----------------------------------

@app.route("/api/visual/baselines", methods=["GET"])
@login_required
def visual_baselines_list():
    """List every visual baseline owned by the current user."""
    from utils.visual_store import list_baselines
    rows = list_baselines(current_user_id())
    # Strip absolute disk paths — the UI fetches images via the dedicated
    # /api/visual/image endpoint that re-resolves them safely.
    safe = [{k: v for k, v in r.items() if k != "path"} for r in rows]
    return jsonify({"baselines": safe, "count": len(safe)})


@app.route("/api/visual/baselines/<name>", methods=["DELETE"])
@login_required
def visual_baseline_delete(name):
    from utils.visual_store import delete_baseline
    try:
        ok = delete_baseline(current_user_id(), name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"deleted": ok, "name": name})


@app.route("/api/visual/baselines/<name>/promote", methods=["POST"])
@login_required
def visual_baseline_promote(name):
    """Adopt the most recent ``actual`` screenshot as the new baseline."""
    from utils.visual_store import promote_actual
    try:
        ok = promote_actual(current_user_id(), name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not ok:
        return jsonify({"error": "no actual screenshot to promote"}), 404
    return jsonify({"promoted": True, "name": name})


@app.route("/api/visual/image", methods=["GET"])
@login_required
def visual_image_serve():
    """Stream a baseline / actual / diff PNG to the caller, scoped to the
    current user (no cross-tenant access even if you guess a name)."""
    from utils.visual_store import (
        baseline_path as _bp, artifact_path as _ap,
    )
    name = (request.args.get("name") or "").strip()
    kind = (request.args.get("kind") or "baseline").strip().lower()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        if kind == "baseline":
            path = _bp(current_user_id(), name)
        elif kind in ("actual", "diff"):
            path = _ap(current_user_id(), name, kind)
        else:
            return jsonify({"error": f"unknown kind '{kind}'"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isfile(path):
        abort(404)
    rel_dir, fname = os.path.split(path)
    return send_from_directory(rel_dir, fname, mimetype="image/png")


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    uid = current_user_id()
    if uid is None:
        return jsonify({"user": None}), 200
    u = memory_agent.db.get_user_by_id(uid)
    if not u:
        clear_session_user()
        return jsonify({"user": None}), 200
    quota = memory_agent.quota_info(uid)
    return jsonify({"user": u, "quota": quota})


# Phase 2: serve failure screenshots from data/screenshots/<session>/<file>
SCREENSHOT_ROOT = os.path.abspath("data/screenshots")


@app.route("/data/screenshots/<path:subpath>")
def serve_screenshot(subpath):
    full = os.path.abspath(os.path.join(SCREENSHOT_ROOT, subpath))
    # Defense in depth — refuse anything outside the screenshots root.
    if not full.startswith(SCREENSHOT_ROOT + os.sep) and full != SCREENSHOT_ROOT:
        abort(404)
    if not os.path.isfile(full):
        abort(404)
    rel_dir, name = os.path.split(full)
    return send_from_directory(rel_dir, name)

@app.route("/api/sessions", methods=["GET"])
@login_required
def get_sessions():
    try:
        sessions = memory_agent.list_all_sessions(user_id=current_user_id())
        quota = memory_agent.quota_info(current_user_id())
        return jsonify({"sessions": sessions, "quota": quota})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/sessions/<session_id>", methods=["GET"])
@login_required
def get_session(session_id):
    try:
        session = memory_agent.load_session(session_id, user_id=current_user_id())
        return jsonify(session.model_dump())
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route("/api/sessions/<session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    try:
        memory_agent.delete_session(session_id, user_id=current_user_id())
        return jsonify({"status": "deleted", "quota": memory_agent.quota_info(current_user_id())})
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/reports/global_insights", methods=["GET"])
@login_required
def get_global_insights():
    uid = current_user_id()
    session_metadata = memory_agent.list_all_sessions(user_id=uid)
    failed_cases_payload = []
    total_cases = 0
    total_passes = 0
    total_fails = 0

    for meta in session_metadata:
        try:
            session = memory_agent.load_session(meta["session_id"], user_id=uid)
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
@login_required
def smart_generate():
    data = request.json
    raw_prompt = data.get("prompt", "")
    auto_run = data.get("autoRun", False)
    env = data.get("environment", "web")
    model_pref = data.get("model", "accurate")
    target_lang = data.get("lang", "en-US")
    # New: case count (Phase 1). Default 8 cases, clamp to 1-50.
    try:
        count = int(data.get("count", 8))
    except (TypeError, ValueError):
        count = 8
    count = max(1, min(count, 50))

    if not raw_prompt:
        return jsonify({"error": "Prompt field is required."}), 400

    # Quota gate — fail fast before burning LLM tokens.
    uid = current_user_id()
    quota = memory_agent.quota_info(uid)
    if quota["at_limit"]:
        return jsonify({
            "error": (f"Session limit reached ({SESSION_QUOTA_PER_USER}). "
                      "Delete an existing session before creating a new one."),
            "quota": quota,
        }), 409

    # Truncate Feature Name cleanly to 1-2 words
    words = raw_prompt.split()
    feature_name = " ".join(words[:2]) + "..." if len(words) > 2 else raw_prompt

    session_id = str(uuid.uuid4())
    
    try:
        # Resolve UI model preference -> concrete Groq model ID
        resolved_model = model_selector.get_model(model_pref)

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
            test_cases = generator_agent.generate_from_url_dom(
                target_url, clean_dom, model=resolved_model, count=count
            )
            feature_name = f"DOM Scrape: {target_url}"
        else:
            # Standard Generation
            test_cases = generator_agent.generate(
                adapted_prompt, model=resolved_model, count=count
            )
            
        session = TestSession(
            session_id=session_id,
            user_id=uid,
            feature=feature_name,
            state="GENERATED",
            timestamp=time.time(),
            test_cases=test_cases
        )
        memory_agent.save_session(session, user_id=uid)

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
            
        memory_agent.save_session(session, user_id=uid)
        return jsonify({"message": "Pipeline Complete", "session": session.model_dump()})

    except QuotaExceeded as qe:
        return jsonify({"error": str(qe), "quota": memory_agent.quota_info(uid)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/execute/<session_id>", methods=["POST"])
@login_required
def execute_session(session_id):
    """Executes a previously Generated session (For Manual Approvals)"""
    uid = current_user_id()
    environment = request.json.get("environment", "web")
    try:
        session = memory_agent.load_session(session_id, user_id=uid)
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

        memory_agent.save_session(session, user_id=uid)
        return jsonify({"message": "Execution Complete", "session": session.model_dump()})
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------
# 🏢 UNTOUCHED AUTOMATION TAB PRESERVED (Direct + DataDriven)
# -------------------------------------------------------------
@app.route("/api/execute_direct", methods=["POST"])
@login_required
def execute_direct():
    uid = current_user_id()
    quota = memory_agent.quota_info(uid)
    if quota["at_limit"]:
        return jsonify({
            "error": (f"Session limit reached ({SESSION_QUOTA_PER_USER}). "
                      "Delete an existing session before creating a new one."),
            "quota": quota,
        }), 409

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
            user_id=uid,
            feature=feature,
            state="GENERATED",
            timestamp=time.time(),
            test_cases=test_cases
        )
        memory_agent.save_session(session, user_id=uid)
        
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
        
        memory_agent.save_session(session, user_id=uid)
        return jsonify({"message": "Direct Execution Complete", "session": session.model_dump()})
    except QuotaExceeded as qe:
        return jsonify({"error": str(qe), "quota": memory_agent.quota_info(uid)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/data_driven", methods=["POST"])
@login_required
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

# ============================================================
# PHASE 3 — Live streaming execution + failure triage
# ============================================================

# In-memory registry of running executions, run_id -> threading.Event for cancel.
_run_registry: dict = {}
_run_registry_lock = threading.Lock()


def _register_run() -> tuple:
    run_id = str(uuid.uuid4())
    ev = threading.Event()
    with _run_registry_lock:
        _run_registry[run_id] = ev
    return run_id, ev


def _unregister_run(run_id: str) -> None:
    with _run_registry_lock:
        _run_registry.pop(run_id, None)


@app.route("/api/execute_stream/<session_id>", methods=["POST"])
@login_required
def execute_stream(session_id):
    """SSE endpoint that yields per-case lifecycle events as the executor runs."""
    uid = current_user_id()
    body = request.json or {}
    environment = body.get("environment", "web")
    device = body.get("device") or None      # per-run device override
    # Workers: 1 (default) keeps current sequential behaviour.
    # The agent clamps to [1, MAX_WORKERS], so we just trust + pass through.
    try:
        workers = int(body.get("workers") or 1)
    except (TypeError, ValueError):
        workers = 1

    try:
        session = memory_agent.load_session(session_id, user_id=uid)
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": f"Session not found: {e}"}), 404

    if not session.test_cases:
        return jsonify({"error": "No test cases in this session."}), 400

    run_id, cancel_event = _register_run()
    executor_agent.mode = environment

    def event_stream():
        try:
            yield f"data: {json.dumps({'type': 'run_id', 'run_id': run_id})}\n\n"

            updated_cases = list(session.test_cases)
            start_t = time.time()
            final_metrics = None

            for event in executor_agent.execute_streaming(
                session.test_cases, session_id, cancel_event=cancel_event,
                device=device, user_id=uid, workers=workers,
            ):
                if event.get("type") == "done":
                    final_metrics = event.get("metrics")
                    updated_cases = [TestCase(**c) for c in event.get("test_cases", [])]
                yield f"data: {json.dumps(event)}\n\n"

            end_t = time.time()

            # Failure analysis + report (mirrors /api/execute)
            for tc in updated_cases:
                if tc.status == "Fail" and tc.error and not tc.bug_insight:
                    try:
                        tc.bug_insight = rca_agent.analyze_failure(tc.id, tc.error)
                    except Exception:
                        pass

            session.test_cases = updated_cases
            session.state = "EXECUTED"

            if final_metrics is not None:
                from utils.models import ExecutionMetrics
                metrics_obj = ExecutionMetrics(**final_metrics)
                perf_insight = perf_agent.evaluate_performance([end_t - start_t])
                legacy_report = report_agent.analyze(session.test_cases, metrics_obj)
                legacy_report.executive_summary += (
                    f" | ⚡ Perf: {perf_insight['status']} ({perf_insight['average_time_seconds']}s)"
                )
                session.report = legacy_report

            memory_agent.save_session(session, user_id=uid)
            # Emit JUnit XML next to other CI artifacts.
            try:
                from utils.junit import write_session_junit
                junit_path = write_session_junit(session)
            except Exception:
                junit_path = None
            yield f"data: {json.dumps({'type': 'session_saved', 'session': session.model_dump(), 'junit_path': junit_path})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            _unregister_run(run_id)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/runs/<run_id>/cancel", methods=["POST"])
@login_required
def cancel_run(run_id):
    with _run_registry_lock:
        ev = _run_registry.get(run_id)
    if not ev:
        return jsonify({"error": "Unknown or already-completed run."}), 404
    ev.set()
    return jsonify({"status": "cancel requested", "run_id": run_id})


# ---------- Case-level mutations (Phase 3 triage) ----------

def _find_case(session, case_id):
    for tc in session.test_cases:
        if tc.id == case_id:
            return tc
    return None


@app.route("/api/cases/<session_id>/<case_id>/update", methods=["POST"])
@login_required
def update_case(session_id, case_id):
    """Persist user edits to a case (selenium_action and/or user_skipped flag)."""
    uid = current_user_id()
    data = request.json or {}
    try:
        session = memory_agent.load_session(session_id, user_id=uid)
        tc = _find_case(session, case_id)
        if not tc:
            return jsonify({"error": "case not found"}), 404
        if "selenium_action" in data:
            tc.selenium_action = data["selenium_action"]
        if "user_skipped" in data:
            tc.user_skipped = bool(data["user_skipped"])
        memory_agent.save_session(session, user_id=uid)
        return jsonify({"status": "saved", "case": tc.model_dump()})
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cases/<session_id>/<case_id>/mark_known", methods=["POST"])
@login_required
def mark_known(session_id, case_id):
    uid = current_user_id()
    flag = bool((request.json or {}).get("known", True))
    try:
        session = memory_agent.load_session(session_id, user_id=uid)
        tc = _find_case(session, case_id)
        if not tc:
            return jsonify({"error": "case not found"}), 404
        tc.known_issue = flag
        memory_agent.save_session(session, user_id=uid)
        return jsonify({"status": "ok", "known_issue": tc.known_issue})
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# Feature #6 — Screenshot → tests (vision LLM)
# ============================================================

MAX_SCREENSHOT_BYTES = 6 * 1024 * 1024     # 6 MB
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _image_to_b64(raw: bytes) -> str:
    import base64
    return base64.b64encode(raw).decode("ascii")


@app.route("/api/smart_input_image", methods=["POST"])
@login_required
def smart_input_image():
    """Vision-grounded generation: upload a screenshot, get test cases.

    Two accepted shapes:
      • multipart/form-data with ``image`` file + ``count`` + ``hint``
      • application/json with ``image_b64`` + ``mime_type`` + ``count`` + ``hint``
    """
    import base64
    uid = current_user_id()

    # ---- Quota gate (fail fast before vision-token spend) ----
    quota = memory_agent.quota_info(uid)
    if quota["at_limit"]:
        return jsonify({
            "error": f"Session limit reached ({SESSION_QUOTA_PER_USER}). "
                     "Delete an existing session before creating a new one.",
            "quota": quota,
        }), 409

    # ---- Pull the image + params from either body type ----
    hint = None
    count = 5
    image_b64 = None
    mime_type = "image/png"

    if request.files and request.files.get("image"):
        f = request.files["image"]
        raw = f.read()
        if not raw:
            return jsonify({"error": "Empty image upload."}), 400
        if len(raw) > MAX_SCREENSHOT_BYTES:
            return jsonify({"error": f"Image too large (max {MAX_SCREENSHOT_BYTES//1024//1024} MB)."}), 413
        ftype = (f.mimetype or "").lower()
        if ftype not in ALLOWED_IMAGE_MIMES:
            return jsonify({"error": f"Unsupported image type: {ftype or 'unknown'}. "
                                      "Use PNG, JPEG, or WebP."}), 415
        image_b64 = _image_to_b64(raw)
        mime_type = "image/jpeg" if ftype == "image/jpg" else ftype
        try:
            count = int(request.form.get("count", 5))
        except (TypeError, ValueError):
            count = 5
        hint = (request.form.get("hint") or "").strip() or None
    else:
        data = request.json or {}
        b64 = (data.get("image_b64") or "").strip()
        if b64.startswith("data:"):
            # Strip "data:image/png;base64,..." prefix if present.
            try:
                head, b64 = b64.split(",", 1)
                if "image/jpeg" in head: mime_type = "image/jpeg"
                elif "image/webp" in head: mime_type = "image/webp"
                else: mime_type = "image/png"
            except ValueError:
                pass
        if not b64:
            return jsonify({"error": "Provide an image file (multipart) or image_b64 (JSON)."}), 400
        try:
            decoded_len = len(base64.b64decode(b64, validate=False))
        except Exception:
            return jsonify({"error": "image_b64 is not valid base64."}), 400
        if decoded_len > MAX_SCREENSHOT_BYTES:
            return jsonify({"error": f"Image too large (max {MAX_SCREENSHOT_BYTES//1024//1024} MB)."}), 413
        image_b64 = b64
        mime_type = (data.get("mime_type") or mime_type).lower()
        if mime_type not in ALLOWED_IMAGE_MIMES:
            mime_type = "image/png"
        try:
            count = int(data.get("count", 5))
        except (TypeError, ValueError):
            count = 5
        hint = (data.get("hint") or "").strip() or None

    count = max(1, min(count, 30))

    # ---- Generate ----
    try:
        test_cases = generator_agent.generate_from_screenshot(
            image_b64=image_b64, mime_type=mime_type, count=count, hint=hint,
        )
    except LLMConfigError:
        raise          # error handler returns the friendly payload
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Vision generation failed: {e}"}), 500

    if not test_cases:
        return jsonify({"error": "Vision model returned no usable test cases."}), 502

    # ---- Persist as a new session ----
    feature_name = f"From screenshot: {(hint or 'no hint')[:48]}"
    session_id = str(uuid.uuid4())
    session = TestSession(
        session_id=session_id,
        user_id=uid,
        feature=feature_name,
        state="GENERATED",
        timestamp=time.time(),
        test_cases=test_cases,
    )
    try:
        memory_agent.save_session(session, user_id=uid)
    except QuotaExceeded as qe:
        return jsonify({"error": str(qe),
                        "quota": memory_agent.quota_info(uid)}), 409

    return jsonify({
        "message": "Screenshot interpreted and tests generated.",
        "session": session.model_dump(),
        "from_screenshot": True,
    })


# ============================================================
# Feature #11 — Bug-tracker integration (JIRA / Linear)
# ============================================================

ALLOWED_PROVIDERS = {"jira", "linear"}


@app.route("/api/tickets/credentials", methods=["GET"])
@login_required
def list_ticket_credentials():
    uid = current_user_id()
    rows = memory_agent.db.list_ticket_credentials(uid)
    return jsonify({"providers": rows})


@app.route("/api/tickets/credentials/<provider>", methods=["PUT"])
@login_required
def set_ticket_credentials(provider):
    uid = current_user_id()
    p = provider.lower().strip()
    if p not in ALLOWED_PROVIDERS:
        return jsonify({"error": f"Unknown provider: {provider}"}), 400
    data = request.json or {}
    try:
        memory_agent.db.set_ticket_credentials(
            user_id=uid, provider=p,
            base_url=(data.get("base_url") or None),
            auth_email=(data.get("auth_email") or None),
            auth_token=(data.get("auth_token") or None),
            default_project=(data.get("default_project") or None),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    rows = memory_agent.db.list_ticket_credentials(uid)
    return jsonify({"providers": rows})


@app.route("/api/tickets/credentials/<provider>", methods=["DELETE"])
@login_required
def delete_ticket_credentials(provider):
    uid = current_user_id()
    ok = memory_agent.db.delete_ticket_credentials(uid, provider)
    return jsonify({"deleted": ok})


# ============================================================
# Feature #10 — Record + replay (import recording from Chrome ext)
# ============================================================

# Recordings can include base64 screenshots in future versions; bound the
# payload now so a runaway extension can't OOM us.
MAX_RECORDING_BYTES = 512 * 1024  # 512 KB is plenty for ~200 action-plan ops


@app.route("/api/import/recording", methods=["POST"])
@login_required
def import_recording_endpoint():
    """Accept a recording JSON from the Chrome extension and persist as a session."""
    uid = current_user_id()
    # Read the raw bytes ONCE, size-check, then parse — get_data() with the
    # default cache=True lets a subsequent get_json() still see the body,
    # but for size-gating we just decode ourselves.
    raw = request.get_data() or b""
    if len(raw) > MAX_RECORDING_BYTES:
        return jsonify({
            "error": f"recording too large (>{MAX_RECORDING_BYTES // 1024} KB)",
            "code": "recording_too_large",
        }), 413

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"error": "invalid JSON body"}), 400
    if not isinstance(payload, dict):
        return jsonify({"error": "JSON body must be an object"}), 400

    from utils.recording_importer import import_recording, RecordingImportError
    try:
        session, info = import_recording(payload, user_id=uid)
    except RecordingImportError as e:
        return jsonify({"error": str(e), "code": "recording_invalid"}), 400

    try:
        memory_agent.save_session(session, user_id=uid)
    except QuotaExceeded as e:
        return jsonify({
            "error": str(e), "code": "quota_exceeded",
            "quota": memory_agent.quota_info(uid),
        }), 409

    return jsonify({
        "session_id": session.session_id,
        "feature": session.feature,
        "imported": info,
        "session": session.model_dump(),
        "quota": memory_agent.quota_info(uid),
    })


# ============================================================
# Feature #7 — Schedules + Slack notifications
# ============================================================

@app.route("/api/notifications/slack", methods=["GET"])
@login_required
def get_slack_creds():
    row = memory_agent.db.get_slack_credentials_public(current_user_id())
    return jsonify({"slack": row})


@app.route("/api/notifications/slack", methods=["PUT"])
@login_required
def set_slack_creds():
    data = request.json or {}
    try:
        memory_agent.db.set_slack_credentials(
            user_id=current_user_id(),
            webhook_url=(data.get("webhook_url") or "").strip(),
            default_channel=(data.get("default_channel") or None),
            mention_on_fail=(data.get("mention_on_fail") or None),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"slack": memory_agent.db.get_slack_credentials_public(current_user_id())})


@app.route("/api/notifications/slack", methods=["DELETE"])
@login_required
def delete_slack_creds():
    ok = memory_agent.db.delete_slack_credentials(current_user_id())
    return jsonify({"deleted": ok})


@app.route("/api/notifications/slack/test", methods=["POST"])
@login_required
def slack_test_message():
    creds = memory_agent.db.get_slack_credentials(current_user_id())
    if not creds:
        return jsonify({"error": "Slack is not configured."}), 400
    from utils.slack_notifier import post_test_message, SlackError
    try:
        post_test_message(creds["webhook_url"])
    except SlackError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True})


@app.route("/api/schedules", methods=["GET"])
@login_required
def list_schedules():
    rows = memory_agent.db.list_schedules(current_user_id())
    return jsonify({"schedules": rows})


@app.route("/api/schedules", methods=["POST"])
@login_required
def create_schedule():
    """Create/update the schedule attached to a session.

    Body: {session_id, expression, slack_notify (bool, optional)}.
    Returns the freshly-parsed schedule with ``next_run_at`` filled in.
    """
    uid = current_user_id()
    data = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    expression = (data.get("expression") or "").strip()
    slack_notify = bool(data.get("slack_notify", True))
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    # Confirm the session exists and belongs to this user before we record
    # a schedule against it (cross-user 404, not 403, to avoid leakage).
    try:
        memory_agent.load_session(session_id, user_id=uid)
    except NotOwner:
        return jsonify({"error": "Session not found"}), 404
    except Exception:
        return jsonify({"error": "Session not found"}), 404

    from utils.schedule_expr import parse, ScheduleExprError
    try:
        sched = parse(expression)
    except ScheduleExprError as e:
        return jsonify({"error": str(e)}), 400

    next_at = sched.next_after(time.time())
    sid = memory_agent.db.upsert_schedule(
        user_id=uid, session_id=session_id,
        expression=expression, next_run_at=next_at,
        enabled=True, slack_notify=slack_notify,
    )
    row = memory_agent.db.get_schedule(sid, user_id=uid)
    return jsonify({"schedule": row, "human": sched.humanize()})


@app.route("/api/schedules/<int:schedule_id>", methods=["DELETE"])
@login_required
def delete_schedule(schedule_id):
    ok = memory_agent.db.delete_schedule(schedule_id, current_user_id())
    if not ok:
        return jsonify({"error": "schedule not found"}), 404
    return jsonify({"deleted": True})


@app.route("/api/schedules/<int:schedule_id>/toggle", methods=["PUT"])
@login_required
def toggle_schedule(schedule_id):
    data = request.json or {}
    enabled = bool(data.get("enabled", True))
    ok = memory_agent.db.set_schedule_enabled(schedule_id, current_user_id(), enabled)
    if not ok:
        return jsonify({"error": "schedule not found"}), 404
    row = memory_agent.db.get_schedule(schedule_id, user_id=current_user_id())
    return jsonify({"schedule": row})


@app.route("/api/cases/<session_id>/<case_id>/create_ticket", methods=["POST"])
@login_required
def create_ticket(session_id, case_id):
    """Push a failed case to JIRA or Linear as a new issue."""
    uid = current_user_id()
    data = request.json or {}
    provider = (data.get("provider") or "").lower().strip()
    if provider not in ALLOWED_PROVIDERS:
        return jsonify({"error": "Pick a provider: jira or linear"}), 400

    creds = memory_agent.db.get_ticket_credentials(uid, provider)
    if not creds:
        return jsonify({
            "error": f"No {provider} credentials configured. "
                     f"Add them in Settings → Bug tracker integrations."
        }), 400

    try:
        session = memory_agent.load_session(session_id, user_id=uid)
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": f"Session not found: {e}"}), 404

    tc = _find_case(session, case_id)
    if not tc:
        return jsonify({"error": "case not found"}), 404

    # Optionally run a deep-dive first if the client asked for it.
    dd_report = None
    if data.get("include_deep_dive") and tc.status == "Fail":
        try:
            context = gather_deep_dive_context(session, case_id, memory_agent.db)
            dd_report = deep_dive_agent.analyze(tc.model_dump(), context)
        except Exception:
            dd_report = None

    from utils.ticket_body import compose_all
    from utils.ticket_providers import build_provider, TicketProviderError

    composed = compose_all(
        case=tc.model_dump(),
        session=session.model_dump(),
        title_override=data.get("summary_override"),
        deep_dive=dd_report,
    )

    try:
        adapter = build_provider(creds)
        result = adapter.create_issue(
            title=composed["title"],
            body_md=composed["body"],
            project_or_team=data.get("project_or_team"),
        )
    except TicketProviderError as e:
        return jsonify({
            "error": e.message,
            "status": e.status, "body": e.body,
        }), 502

    return jsonify({
        "provider": result["provider"],
        "key": result["key"],
        "url": result["url"],
        "title": composed["title"],
        "deep_dive_attached": dd_report is not None,
    })


@app.route("/api/cases/<session_id>/<case_id>/deep_dive", methods=["POST"])
@login_required
def deep_dive(session_id, case_id):
    """Feature #12 — Why did this fail? Richer than the inline RCA.

    Walks the trace file + prior session history + locator cache and asks
    the LLM for a structured multi-paragraph diagnosis.
    """
    uid = current_user_id()
    try:
        session = memory_agent.load_session(session_id, user_id=uid)
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": f"Session not found: {e}"}), 404

    tc = _find_case(session, case_id)
    if not tc:
        return jsonify({"error": "case not found"}), 404

    context = gather_deep_dive_context(session, case_id, memory_agent.db)
    report = deep_dive_agent.analyze(tc.model_dump(), context)
    return jsonify({
        "case_id": case_id,
        "session_id": session_id,
        "report": report,
        "context_used": {
            "console_log_count": len(context.get("console_logs") or []),
            "prior_run_count": len(context.get("prior_runs") or []),
            "locator_cache_count": len(context.get("locator_cache") or []),
        },
    })


@app.route("/api/suggest_fix", methods=["POST"])
@login_required
def suggest_fix():
    """LLM-suggested replacement Selenium snippet for a failed case."""
    data = request.json or {}
    test_id = data.get("test_id", "TC???")
    description = data.get("description", "")
    error = data.get("error", "")
    original_code = data.get("selenium_action", "")
    expected = data.get("expected", "")

    if not error or not original_code:
        return jsonify({"error": "test_id, error and selenium_action are required"}), 400

    system_msg = (
        "You are a senior Selenium debugger. Given a failing test, propose a corrected "
        "Python Selenium snippet. Use WebDriverWait + explicit asserts. Output JSON only."
    )
    prompt = (
        f"Test {test_id}: {description}\n"
        f"Expected: {expected}\n"
        f"Error: {error}\n\n"
        f"Original snippet (failed):\n```python\n{original_code}\n```\n\n"
        "Respond as JSON: {\"explanation\": \"...\", \"suggested_code\": \"...\"}.\n"
        "Inside suggested_code use only: driver, By, Keys, time, WebDriverWait, EC, ActionChains. "
        "Never import. Always use explicit waits and at least one assert."
    )
    try:
        result = generator_agent.llm.query_json(system_msg, prompt)
        return jsonify({
            "explanation": result.get("explanation", ""),
            "suggested_code": result.get("suggested_code", ""),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cases/<session_id>/<case_id>/retry", methods=["POST"])
@login_required
def retry_case(session_id, case_id):
    """Optionally overwrite a case's code, then re-run only that case."""
    data = request.json or {}
    new_code = data.get("selenium_action")
    environment = data.get("environment", "web")

    uid = current_user_id()
    try:
        session = memory_agent.load_session(session_id, user_id=uid)
        tc = _find_case(session, case_id)
        if not tc:
            return jsonify({"error": "case not found"}), 404
        if new_code:
            tc.selenium_action = new_code
        tc.status = "Un-Run"
        tc.error = None
        tc.screenshot = None

        executor_agent.mode = environment
        single_run, metrics = executor_agent.execute([tc], session_id)
        if single_run:
            updated = single_run[0]
            if updated.status == "Fail" and updated.error:
                updated.bug_insight = rca_agent.analyze_failure(updated.id, updated.error)
            # Swap the case back into the session by id.
            for i, existing in enumerate(session.test_cases):
                if existing.id == updated.id:
                    session.test_cases[i] = updated
                    break

        memory_agent.save_session(session, user_id=uid)
        return jsonify({"status": "retried", "case": (single_run[0].model_dump() if single_run else None)})
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# PHASE 5 — Markdown export + run diff
# ============================================================

@app.route("/api/sessions/<session_id>/export.md", methods=["GET"])
@login_required
def export_session_markdown(session_id):
    try:
        session = memory_agent.load_session(session_id, user_id=current_user_id())
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 404
    from utils.markdown_export import session_to_markdown
    md = session_to_markdown(session)
    filename = f"abhimate-{session_id[:8]}.md"
    return Response(
        md,
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/runs/diff", methods=["GET"])
@login_required
def diff_runs():
    """Compare two executed sessions case-by-case.

    Query: ?a=<session_id>&b=<session_id>
    Returns: {a: meta, b: meta, rows: [{id, description, a_status, b_status, delta}]}
    Delta values:
      - "new"        — case exists only in B
      - "removed"    — case exists only in A
      - "fixed"      — A=Fail, B=Pass
      - "regressed"  — A=Pass, B=Fail
      - "still_fail" — both Fail
      - "stable"     — same non-fail status
      - "churn"      — other status changes
    """
    a_id = request.args.get("a")
    b_id = request.args.get("b")
    if not a_id or not b_id:
        return jsonify({"error": "both ?a=<sid> and ?b=<sid> are required"}), 400

    uid = current_user_id()
    try:
        a = memory_agent.load_session(a_id, user_id=uid)
        b = memory_agent.load_session(b_id, user_id=uid)
    except NotOwner as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 404

    a_map = {tc.id: tc for tc in a.test_cases}
    b_map = {tc.id: tc for tc in b.test_cases}
    all_ids = list(a_map.keys()) + [k for k in b_map if k not in a_map]

    rows = []
    for cid in all_ids:
        ta, tb = a_map.get(cid), b_map.get(cid)
        if ta is None:
            delta = "new"
            description = tb.description
        elif tb is None:
            delta = "removed"
            description = ta.description
        else:
            sa, sb = ta.status or "Un-Run", tb.status or "Un-Run"
            if sa == sb:
                delta = "still_fail" if sa == "Fail" else "stable"
            elif sa == "Fail" and sb == "Pass":
                delta = "fixed"
            elif sa == "Pass" and sb == "Fail":
                delta = "regressed"
            else:
                delta = "churn"
            description = tb.description or ta.description
        rows.append({
            "id": cid,
            "description": description,
            "a_status": ta.status if ta else None,
            "b_status": tb.status if tb else None,
            "delta": delta,
        })

    def _meta(s):
        return {
            "session_id": s.session_id,
            "feature": s.feature,
            "state": s.state,
            "timestamp": s.timestamp,
            "metrics": s.report.metrics.model_dump() if s.report else None,
        }

    return jsonify({"a": _meta(a), "b": _meta(b), "rows": rows})


def _start_scheduler_for_runtime():
    """Boot the scheduler thread, but only in the actual server process.

    Flask's debug reloader forks: the parent watches the source tree, the
    child runs Flask. ``WERKZEUG_RUN_MAIN == 'true'`` only in the child,
    so this guard avoids two schedulers competing for the same DB rows.
    When ``debug=False`` the env var is not set at all — we treat that as
    "real run" too.
    """
    from utils.scheduler import get_or_start_scheduler
    in_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    in_production_run = "WERKZEUG_RUN_MAIN" not in os.environ
    if not (in_reloader_child or in_production_run):
        return None

    def _builder(session_id: str) -> str:
        # /#/sessions/<id> is what the SPA uses; absolute URL helps Slack.
        base = os.environ.get("ABHIMATE_PUBLIC_URL") or "http://localhost:5000"
        return f"{base.rstrip('/')}/?session={session_id}"

    return get_or_start_scheduler(
        memory_agent, executor_agent, memory_agent.db,
        tick_seconds=float(os.environ.get("ABHIMATE_SCHED_TICK", "30")),
        session_url_builder=_builder,
    )


if __name__ == "__main__":
    from config import settings
    _start_scheduler_for_runtime()
    # threaded=True so SSE streams + cancel POST can run concurrently in dev.
    # exclude_patterns: Flask's reloader otherwise restarts mid-test when the
    # webdriver-manager refreshes chromedriver under .wdm/, or when we write a
    # screenshot / trace under data/, killing in-flight Selenium runs with
    # ERR_CONNECTION_RESET. We also exclude notes/ and pycache.
    app.run(
        host=settings.HOST,
        port=settings.PORT,
        debug=settings.DEBUG,
        threaded=True,
        exclude_patterns=[
            "*/.wdm/*", "*/data/*", "*/notes/*",
            "*/__pycache__/*", "*/tests/__pycache__/*",
            "*.pyc", "*.log", "*.zip", "*.png", "*.db",
        ],
    )
