"""HTTP action handler tests — requests.request is mocked."""

from unittest.mock import patch, MagicMock

import pytest

from utils.action_engine import execute_plan, ActionContext
from utils.models import Action


def _mock_response(status=200, body=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {"Content-Type": "application/json"}
    resp.text = "{}" if body is None else str(body)
    resp.json = MagicMock(return_value=body if body is not None else {})
    return resp


def test_http_get_records_response():
    with patch("requests.request", return_value=_mock_response(200, {"ok": True})) as req:
        ctx = ActionContext()
        execute_plan([Action(op="http_get", url="https://api.example.com/ping")], ctx, retries=1)
        req.assert_called_once()
        assert ctx.last_http_response["status"] == 200
        assert ctx.last_http_response["json"] == {"ok": True}


def test_http_post_with_body_and_named_binding():
    with patch("requests.request", return_value=_mock_response(201, {"id": "abc"})) as req:
        ctx = ActionContext()
        execute_plan([
            Action(op="http_post", url="https://api/x", body={"name": "y"}, name="created"),
        ], ctx, retries=1)
        kwargs = req.call_args.kwargs
        assert kwargs["json"] == {"name": "y"}
        assert ctx.variables["created"]["status"] == 201


def test_assert_status_pass_and_fail():
    with patch("requests.request", return_value=_mock_response(404)):
        ctx = ActionContext()
        with pytest.raises(AssertionError):
            execute_plan([
                Action(op="http_get", url="https://api/x"),
                Action(op="assert_status", expected=200),
            ], ctx, retries=1)


def test_assert_json_path_dotted():
    body = {"user": {"profile": {"name": "Alice"}}}
    with patch("requests.request", return_value=_mock_response(200, body)):
        ctx = ActionContext()
        execute_plan([
            Action(op="http_get", url="https://api/x"),
            Action(op="assert_json_path", json_path="$.user.profile.name", expected="Alice"),
        ], ctx, retries=1)


def test_assert_json_path_array_index():
    body = {"items": [{"id": 1}, {"id": 99}]}
    with patch("requests.request", return_value=_mock_response(200, body)):
        ctx = ActionContext()
        execute_plan([
            Action(op="http_get", url="https://api/x"),
            Action(op="assert_json_path", json_path="$.items[1].id", expected=99),
        ], ctx, retries=1)


def test_assert_response_time_fails_when_slow():
    fake = _mock_response(200, {"ok": True})
    with patch("requests.request", return_value=fake):
        ctx = ActionContext()
        # Inject a previous slow response by hand
        ctx.last_http_response = {"status": 200, "elapsed_ms": 1500, "json": None, "headers": {}}
        with pytest.raises(AssertionError):
            execute_plan([
                Action(op="assert_response_time", expected=500),
            ], ctx, retries=1)
