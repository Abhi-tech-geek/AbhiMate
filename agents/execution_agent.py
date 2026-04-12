import json
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

class ExecutionAgent:
    def __init__(self, input_path: str = "output/test_cases.json", output_path: str = "output/execution_results.json"):
        self.input_path = input_path
        self.output_path = output_path

    def execute(self):
        print("Executing tests via Selenium WebDriver...")
        
        if not os.path.exists(self.input_path):
            print(f"Error: Could not find {self.input_path}")
            return None

        with open(self.input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        test_cases = data.get("test_cases", [])
        if not test_cases:
            print("No test cases found to execute.")
            return None

        # Setup Selenium Chrome driver once
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless') # Uncomment for headless
        options.add_argument('--disable-gpu')
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.implicitly_wait(10) # Added implicit wait to reduce NoSuchElement exceptions

        for i, tc in enumerate(test_cases):
            tc_id = tc.get("id", f"TC_Unknown_{i}")
            print(f" -> Running [{tc_id}] {tc.get('type')} - {tc.get('description')[:30]}...")
            
            action_code = tc.get("selenium_action", "")
            if not action_code:
                tc["status"] = "Skipped"
                tc["error"] = "No Selenium action provided."
                continue
            
            try:
                from selenium.webdriver.common.by import By
                from selenium.webdriver.common.keys import Keys
                # Provide a local execution context containing the 'driver' object
                exec_globals = {"driver": driver, "time": time, "By": By, "Keys": Keys}
                exec(action_code, exec_globals)
                
                tc["status"] = "Pass"
                tc["error"] = None
            except Exception as e:
                tc["status"] = "Fail"
                tc["error"] = f"{type(e).__name__}: {str(e)}"
                
                out_dir = os.path.dirname(self.output_path) or "output"
                os.makedirs(out_dir, exist_ok=True)
                screenshot_path = os.path.join(out_dir, f"failure_{tc_id}.png")
                try:
                    driver.save_screenshot(screenshot_path)
                    tc["screenshot"] = screenshot_path
                except Exception:
                    pass

        driver.quit()
        
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        
        print(f"-> Successfully saved execution results to {self.output_path}")
        return data
