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
        
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
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
