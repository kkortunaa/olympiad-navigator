"""All live website reads use the Selenium WebDriver requested for this project."""
import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


class SeleniumSource:
    def __init__(self, timeout=25, delay=0.3, headless=True, binary=None, driver_path=None, use_cache=False):
        self.timeout = timeout
        self.delay = delay
        self.cache = {}
        self.use_cache = use_cache
        self.cache_dir = settings.BASE_DIR.parent / '.scraper-cache'
        self.cache_dir.mkdir(exist_ok=True)
        os.environ.setdefault('SE_CACHE_PATH', str(settings.BASE_DIR.parent / '.selenium-cache'))
        os.environ.setdefault('SE_AVOID_STATS', 'true')
        options = Options()
        if headless:
            options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_experimental_option('prefs', {'profile.managed_default_content_settings.images': 2})
        options.page_load_strategy = 'eager'
        if binary:
            options.binary_location = binary
        self.options = options
        self.driver_path = driver_path
        self.driver = None
        self.page_count = 0
        self.restart()

    def restart(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = webdriver.Chrome(options=self.options, service=Service(executable_path=self.driver_path) if self.driver_path else Service())
        self.driver.set_page_load_timeout(self.timeout)
        self.page_count = 0

    def get(self, url, selector='body', timeout=None, retries=2):
        if url in self.cache:
            return self.cache[url]
        path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + '.html')
        if self.use_cache and path.exists():
            result = path.read_text(encoding='utf-8')
            self.cache[url] = result
            return result
        if self.page_count >= 75:
            self.restart()
        error = None
        for attempt in range(retries):
            try:
                if self.delay:
                    time.sleep(self.delay)
                self.page_count += 1
                self.driver.set_page_load_timeout(timeout or self.timeout)
                self.driver.get(url)
                WebDriverWait(self.driver, timeout or self.timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                # Chrome's network error document also has a body. It must never
                # count as a successful organizer read and clear a saved link.
                if (self.driver.current_url.startswith('chrome-error:')
                        or self.driver.find_elements(By.CSS_SELECTOR, 'body.neterror, #main-frame-error')):
                    raise RuntimeError('Браузер показал страницу ошибки сети вместо сайта.')
                result = self.driver.page_source
                path.write_text(result, encoding='utf-8')
                self.cache[url] = result
                return result
            except Exception as exc:
                error = exc
                if any(term in str(exc).lower() for term in ('invalid session id', 'no such window', 'chrome not reachable', 'disconnected', 'session deleted')):
                    self.restart()
                    continue
                try:
                    self.driver.execute_script('window.stop()')
                    # A timetable can finish rendering while unrelated resources still load.
                    # Recover only a confirmed target page with its required content present.
                    expected, current = urlparse(url), urlparse(self.driver.current_url)
                    same_page = (expected.hostname == current.hostname
                                 and expected.path.rstrip('/') == current.path.rstrip('/'))
                    if isinstance(exc, TimeoutException) and selector != 'body' and same_page and self.driver.find_elements(By.CSS_SELECTOR, selector):
                        result = self.driver.page_source
                        path.write_text(result, encoding='utf-8')
                        self.cache[url] = result
                        return result
                except Exception:
                    pass
        message = getattr(error, 'msg', str(error)).split('Stacktrace:')[0].strip()
        raise RuntimeError('Не удалось загрузить {}: {}'.format(url, message)) from error

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass
