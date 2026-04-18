from utils.models import TestCase, ExecutionMetrics
from utils.automation_drivers import WebSeleniumDriver
from typing import List, Tuple
import os

class AutomationExecutorAgent:
    def __init__(self, mode="web"):
        self.mode = mode

    def execute(self, test_cases: List[TestCase], session_id: str) -> Tuple[List[TestCase], ExecutionMetrics]:
        print(f"-> Executing {len(test_cases)} tests in {self.mode} environment...")
        
        metrics = ExecutionMetrics(total=len(test_cases))
        
        if self.mode == "web":
            driver_instance = WebSeleniumDriver()
        else:
            raise NotImplementedError("Android/API not yet implemented.")
            
        driver_instance.start()
        context = driver_instance.get_context()
        
        out_dir = f"output/screenshots/{session_id}"
        os.makedirs(out_dir, exist_ok=True)
        
        for tc in test_cases:
            if not tc.selenium_action:
                tc.status = "Skipped"
                tc.error = "No executable action provided."
                metrics.skipped += 1
                continue
                
            try:
                # Provide strict context to block unsafe globals
                exec(tc.selenium_action, {}, context)
                tc.status = "Pass"
                tc.error = None
                metrics.passed += 1
            except Exception as e:
                tc.status = "Fail"
                tc.error = f"{type(e).__name__}: {str(e)}"
                metrics.failed += 1
                
                # Take screenshot
                ss_path = os.path.join(out_dir, f"failure_{tc.id}.png")
                driver_instance.take_screenshot(ss_path)
                tc.screenshot = ss_path

        driver_instance.quit()
        return test_cases, metrics
