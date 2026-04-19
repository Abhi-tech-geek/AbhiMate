class PerformanceTestingAgent:
    def __init__(self):
        self.metrics_log = []

    def evaluate_performance(self, execution_times: list):
        """Analyzes execution times of test cases to detect performance regressions."""
        if not execution_times:
            return {"status": "Skipped", "insight": "No performance data collected."}
            
        avg_time = sum(execution_times) / len(execution_times)
        
        if avg_time > 5.0:
            status = "Warning"
            insight = f"Average interaction time is highly degraded ({round(avg_time, 2)}s). High risk of timeouts in production."
        elif avg_time > 2.0:
            status = "Moderate"
            insight = f"Interaction times are acceptable but slightly slow ({round(avg_time, 2)}s)."
        else:
            status = "Pass"
            insight = f"Fast execution detected ({round(avg_time, 2)}s). System is highly responsive."
            
        return {
            "average_time_seconds": round(avg_time, 2),
            "status": status,
            "insight": insight
        }
