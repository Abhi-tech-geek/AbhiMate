from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

class TestCase(BaseModel):
    id: str = Field(..., description="Unique test case ID, e.g., TC001")
    type: Literal["Positive", "Negative", "Edge"] = Field(..., description="The nature of the test case")
    description: str = Field(..., description="Brief summary of what the test case covers")
    steps: List[str] = Field(..., description="Sequential steps to execute the test")
    selenium_action: str = Field(..., description="Raw executable Python Selenium code snippet")
    expected: str = Field(..., description="Expected outcome of the test case")
    status: Optional[str] = Field("Un-Run", description="Execution status: Pass, Fail, Skipped, or Un-Run")
    error: Optional[str] = Field(None, description="Exception string if the test fails")
    screenshot: Optional[str] = Field(None, description="Path to screenshot on failure")
    bug_insight: Optional[str] = Field(None, description="AI-generated insight into the failure")

class ExecutionMetrics(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0

class AnalysisReport(BaseModel):
    metrics: ExecutionMetrics = Field(default_factory=ExecutionMetrics)
    executive_summary: str = Field(..., description="High-level summary of the execution run")
    test_cases: List[TestCase] = Field(default_factory=list, description="The test cases attached to this report")

class TestSession(BaseModel):
    session_id: str
    feature: str
    state: Literal["GENERATED", "EXECUTED", "ARCHIVED"] = "GENERATED"
    timestamp: float
    test_cases: List[TestCase] = Field(default_factory=list)
    report: Optional[AnalysisReport] = None
