"""Shared Playwright login + capture logic for both utility portals.

Capture mode logs in, then saves every page it visits (HTML + screenshot) and
every JSON response the site loads in the background. Those files are what the
parsers in echo.py / lacombe.py get written against.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

log = logging.getLogger(__name__)

KEYWORDS = re.compile(r"bill|usage|consum|histor|statement|invoice|transaction", re.I)
# Never click anything that could change the account or move money.
UNSAFE = re.compile(r"pay|cancel|close|delete|remove|log ?out|sign ?out|submit|change|update|"
                    r"add|enrol|enroll|switch|renew|paperless|autopay|pre-?auth", re.I)
MAX_PAGES = 12


class Portal:
    name = "portal"
    login_url = ""
    user_sel = ""
    pass_sel = ""
    submit_sel = ""
    env_prefix = ""

    def __init__(self, data_dir: Path):
        p = self.env_prefix
        self.username = os.environ[f"{p}_USERNAME"]
        self.password = os.environ[f"{p}_PASSWORD"]
        self.login_url = os.getenv(f"{p}_LOGIN_URL", self.login_url)
        self.user_sel = os.getenv(f"{p}_USER_SELECTOR", self.user_sel)
        self.pass_sel = os.getenv(f"{p}_PASS_SELECTOR", self.pass_sel)
        self.submit_sel = os.getenv(f"{p}_SUBMIT_SELECTOR", self.submit_sel)
        self.capture_dir = data_dir / "capture" / self.name
        self._json_count = 0

    # --- browser ---------------------------------------------------------
    def _open(self, pw) -> tuple[Browser, Page]:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"),
            locale="en-CA", timezone_id="America/Edmonton")
        return browser, ctx.new_page()

    @staticmethod
    def _settle(page: Page, seconds: int = 15) -> None:
        """Wait for the page to quiet down, but don't fail on sites that never go idle."""
        try:
            page.wait_for_load_state("networkidle", timeout=seconds * 1000)
        except Exception:
            pass

    def login(self, page: Page, already_open: bool = False) -> None:
        if not already_open:
            log.info("%s: opening login page", self.name)
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
            self._settle(page)
        log.info("%s: looking for the login form", self.name)
        page.locator(self.pass_sel).first.wait_for(state="visible", timeout=30_000)
        page.locator(self.user_sel).first.fill(self.username)
        page.locator(self.pass_sel).first.fill(self.password)
        log.info("%s: submitting login", self.name)
        page.locator(self.submit_sel).first.click()
        self._settle(page, 20)
        if page.locator(self.pass_sel).count() and page.locator(self.pass_sel).first.is_visible():
            raise RuntimeError(f"{self.name}: still on the login form after submitting; "
                               "check the username/password or the selectors in .env")
        log.info("%s: logged in, now at %s", self.name, page.url)

    # --- capture mode ----------------------------------------------------
    def capture(self) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser, page = self._open(pw)
            page.on("response", self._save_json)
            try:
                log.info("%s: opening login page", self.name)
                page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
                self._settle(page)
                self._snapshot(page, "00-login")
                try:
                    self.login(page, already_open=True)
                finally:
                    self._snapshot(page, "01-after-login")
                log.info("%s: looking for bill and usage pages", self.name)
                self._crawl(page)
            finally:
                browser.close()
        log.info("%s: capture saved to %s", self.name, self.capture_dir)

    def _crawl(self, page: Page) -> None:
        seen, n = {page.url}, 2
        links = page.locator("a, button, [role=tab], [role=menuitem]")
        targets = []
        for i in range(min(links.count(), 300)):
            el = links.nth(i)
            try:
                text = (el.inner_text(timeout=1000) or "").strip()
            except Exception:
                continue
            if text and KEYWORDS.search(text) and not UNSAFE.search(text) and len(text) < 60:
                targets.append(text)
        for text in dict.fromkeys(targets):
            if n >= MAX_PAGES:
                break
            try:
                page.get_by_text(text, exact=True).first.click(timeout=5000)
                self._settle(page)
            except Exception as e:
                log.debug("skip %r: %s", text, e)
                continue
            seen.add(page.url)
            self._snapshot(page, f"{n:02d}-{re.sub(r'[^a-z0-9]+', '-', text.lower())[:30]}")
            n += 1

    def _snapshot(self, page: Page, label: str) -> None:
        log.info("%s: saving page %s", self.name, label)
        (self.capture_dir / f"{label}.html").write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(self.capture_dir / f"{label}.png"), full_page=True, timeout=30_000)
        except Exception as e:
            log.warning("%s: screenshot of %s failed: %s", self.name, label, e)
        for i, frame in enumerate(page.frames[1:], 1):
            try:
                (self.capture_dir / f"{label}.frame{i}.html").write_text(frame.content(), encoding="utf-8")
            except Exception:
                pass

    def _save_json(self, response) -> None:
        if "json" not in (response.headers.get("content-type") or ""):
            return
        try:
            body = response.json()
        except Exception:
            return
        self._json_count += 1
        out = self.capture_dir / f"api-{self._json_count:03d}.json"
        out.write_text(json.dumps({"url": response.url, "status": response.status, "body": body},
                                  indent=2), encoding="utf-8")

    # --- sync mode -------------------------------------------------------
    def fetch_bills(self):
        with sync_playwright() as pw:
            browser, page = self._open(pw)
            try:
                self.login(page)
                return self.read_bills(page)
            finally:
                browser.close()

    def read_bills(self, page: Page):
        raise NotImplementedError(
            f"{self.name}: bill parser not written yet; run capture mode and send the files")
