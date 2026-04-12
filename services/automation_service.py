import json
import os
import time
import asyncio
import textwrap
from playwright.async_api import async_playwright

class AutomationService:
    def __init__(self, test_cases_path: str = "output/test_cases.json"):
        self.test_cases_path = test_cases_path

    async def run_tests(self):
        """
        Reads test cases, executes async Playwright code for each, updates their status, 
        and saves it back to the JSON file.
        """
        if not os.path.exists(self.test_cases_path):
            print(f"Error: Could not find {self.test_cases_path}")
            return

        with open(self.test_cases_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        test_cases = data.get("test_cases", [])
        if not test_cases:
            print("No test cases found to execute.")
            return

        print("\n========================================")
        print("      STARTING AUTOMATED EXECUTION      ")
        print("========================================")
        print("Launching Chromium Browser...\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, slow_mo=500)
            context = await browser.new_context()

            passed = 0
            failed = 0

            for tc in test_cases:
                page = await context.new_page()
                print(f"Running [{tc.get('id', 'N/A')}] {tc.get('type', '')} - {tc.get('description', '')[:50]}")
                
                playwright_action = tc.get("playwright_action", "")
                if not playwright_action:
                    print("  -> SKIPPED (No Playwright action defined)")
                    tc["status"] = "Skipped"
                    await page.close()
                    continue
                
                # We need to wrap the generated async code inside an async function to execute it cleanly
                indented_code = textwrap.indent(playwright_action, "    ")
                wrapper_code = f"async def __execute_ai_test(page):\n{indented_code}"
                
                try:
                    exec_globals = {"time": time}
                    exec(wrapper_code, exec_globals)
                    await exec_globals["__execute_ai_test"](page)
                    
                    tc["status"] = "Pass"
                    print("  -> PASS")
                    passed += 1
                except Exception as e:
                    tc["status"] = "Fail"
                    print(f"  -> FAIL: {str(e)}")
                    failed += 1
                    
                    screenshot_path = os.path.join("output", f"failure_{tc.get('id', 'unknown')}.png")
                    try:
                        await page.screenshot(path=screenshot_path)
                        print(f"     Screenshot saved to {screenshot_path}")
                    except Exception as s_err:
                        print(f"     Could not take screenshot: {str(s_err)}")
                
                await page.close()

            await browser.close()

        print("\n========================================")
        print(f"  EXECUTION COMPLETE: {passed} Passed, {failed} Failed  ")
        print("========================================")

        with open(self.test_cases_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print("Updated status saved to output folder.")
