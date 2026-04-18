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
