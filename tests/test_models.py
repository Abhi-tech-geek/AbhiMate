"""Pydantic schema validation for utils.models."""

import pytest
from pydantic import ValidationError

from utils.models import TestCase, ExecutionMetrics, AnalysisReport, TestSession


def test_testcase_round_trip(sample_test_case_dict):
    tc = TestCase(**sample_test_case_dict)
    assert tc.id == "TC001"
    assert tc.status == "Un-Run"
    assert tc.error is None
    dumped = tc.model_dump()
    assert dumped["type"] == "Positive"
    assert dumped["steps"] == ["Open page", "Click button"]


def test_testcase_rejects_invalid_type(sample_test_case_dict):
    sample_test_case_dict["type"] = "Bogus"
    with pytest.raises(ValidationError):
        TestCase(**sample_test_case_dict)


def test_testcase_requires_steps(sample_test_case_dict):
    del sample_test_case_dict["steps"]
    with pytest.raises(ValidationError):
        TestCase(**sample_test_case_dict)


def test_execution_metrics_defaults():
    m = ExecutionMetrics()
    assert m.total == 0
    assert m.passed == 0
    assert m.failed == 0
    assert m.skipped == 0


def test_test_session_roundtrip(sample_test_case_dict):
    s = TestSession(
        session_id="abc",
        feature="Login flow",
        state="GENERATED",
        timestamp=1700000000.0,
        test_cases=[TestCase(**sample_test_case_dict)],
    )
    dumped = s.model_dump()
    rebuilt = TestSession(**dumped)
    assert rebuilt.session_id == "abc"
    assert rebuilt.test_cases[0].id == "TC001"
    assert rebuilt.report is None


def test_analysis_report_default_metrics(sample_test_case_dict):
    r = AnalysisReport(
        executive_summary="All clear.",
        test_cases=[TestCase(**sample_test_case_dict)],
    )
    assert r.metrics.total == 0
    assert len(r.test_cases) == 1
