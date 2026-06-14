import os


class BaseDriver:
    def start(self):
        raise NotImplementedError
    def quit(self):
        raise NotImplementedError
    def get_context(self):
        raise NotImplementedError
    def take_screenshot(self, name: str) -> str:
        raise NotImplementedError


class WebSeleniumDriver(BaseDriver):
    def __init__(self):
        self.driver = None

    def start(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        try:
            from config import settings
        except Exception:
            class _Fallback:
                HEADLESS = False
                DRIVER_CACHE_DIR = None
            settings = _Fallback

        options = webdriver.ChromeOptions()
        if getattr(settings, "HEADLESS", False):
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Container Chrome (111+) blocks DevTools websocket from non-localhost
        # origins by default — allow it so headless launch doesn't hang.
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--window-size=1920,1080")
        # Capture browser console logs so the trace JSON can include them.
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

        # --- Cloud / container support ---------------------------------
        # When deployed (Railway/Render/Fly via the Dockerfile), Chromium and
        # its driver are installed as system packages. Point Selenium at them
        # via env vars so we skip the webdriver-manager download entirely.
        #   CHROME_BIN         -> chromium binary  (e.g. /usr/bin/chromium)
        #   CHROMEDRIVER_PATH  -> chromedriver bin (e.g. /usr/bin/chromedriver)
        chrome_bin = os.environ.get("CHROME_BIN") or os.environ.get("CHROMIUM_PATH")
        if chrome_bin:
            options.binary_location = chrome_bin

        driver_path = os.environ.get("CHROMEDRIVER_PATH")
        if driver_path:
            # System driver is present — no download needed.
            self.driver = webdriver.Chrome(
                service=Service(executable_path=driver_path),
                options=options,
            )
        else:
            cache_dir = getattr(settings, "DRIVER_CACHE_DIR", None)
            if cache_dir:
                # Do NOT set WDM_LOCAL=1 — that forces webdriver-manager to save
                # under <project>/.wdm, which Flask's debug reloader sees as a
                # source change and restarts the server mid-test.
                os.environ.setdefault("WDM_CACHE_DIR", cache_dir)
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options,
            )
        self.driver.implicitly_wait(10)
        return self

    def quit(self):
        if self.driver:
            self.driver.quit()

    def get_context(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        import time
        return {
            "driver": self.driver,
            "By": By,
            "Keys": Keys,
            "time": time
        }

    def take_screenshot(self, path: str) -> str:
        if self.driver:
            self.driver.save_screenshot(path)
            return path
        return ""

    def extract_dom_map(self, url: str) -> dict:
        if not self.driver:
            self.start()
        
        try:
            self.driver.get(url)
            import time
            time.sleep(3) # Wait for page load
            
            script = """
            return Array.from(document.querySelectorAll('input, button, a, select, textarea')).map(el => {
                let rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return null;
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    name: el.name || '',
                    type: el.type || '',
                    text: el.innerText ? el.innerText.trim() : (el.value || ''),
                    placeholder: el.placeholder || '',
                    href: el.href || ''
                };
            }).filter(e => e !== null);
            """
            elements = self.driver.execute_script(script)
            
            return {
                "url": url,
                "title": self.driver.title,
                "interactable_elements": elements
            }
        except Exception as e:
            return {"error": str(e)}
