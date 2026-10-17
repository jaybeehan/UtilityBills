"""Shared Playwright login + capture logic for both utility portals.

Capture mode logs in, opens each portal's known billing pages, then follows
visible bill/usage/history links up to two levels deep. It saves every page
(HTML + screenshot) and every data response the site loads in the background
(JSON, GWT-RPC, PDFs). Those files are what the parsers get written against.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

log = logging.getLogger(__name__)

KEYWORDS = re.compile(r"bill|usage|consum|histor|statement|invoice|transaction|account|"
                      r"utility|meter|summary|detail|view", re.I)
# Pages that are never useful.
SKIP = re.compile(r"privacy|terms|help|faq|contact|requirement|forgot|register|property tax|"
                  r"message|notification|profile|search", re.I)
# Never click anything that could change the account or move money.
UNSAFE = re.compile(r"pay|cancel|close|delete|remove|log ?out|log ?off|sign ?out|submit|change|"
                    r"update|add|enrol|enroll|switch|renew|paperless|autopay|pre-?auth|"
                    r"unlink|edit|save|request|rate plan", re.I)
NAV_SEL = ("a, button, [role=tab], [role=menuitem], [role=link], .gwt-MenuItem, "
           ".gwt-TabBarItem, .gwt-TabLayoutPanelTab, .gwt-Anchor, .gwt-Hyperlink")
MAX_PAGES = 20
MAX_PDF_BYTES = 5_000_000


class Portal:
    name = "portal"
    login_url = ""
    user_sel = ""
    pass_sel = ""
    submit_sel = ""
    env_prefix = ""
    start_urls: tuple[str, ...] = ()   # known billing pages to open right after login

    def __init__(self, data_dir: Path):
        p = self.env_prefix
        self.username = os.environ[f"{p}_USERNAME"]
        self.password = os.environ[f"{p}_PASSWORD"]
        self.login_url = os.getenv(f"{p}_LOGIN_URL", self.login_url)
        self.user_sel = os.getenv(f"{p}_USER_SELECTOR", self.user_sel)
        self.pass_sel = os.getenv(f"{p}_PASS_SELECTOR", self.pass_sel)
        self.submit_sel = os.getenv(f"{p}_SUBMIT_SELECTOR", self.submit_sel)
        self.capture_dir = data_dir / "capture" / self.name
        self._resp_count = 0
        self._shots = 0

    # --- browser ---------------------------------------------------------
    def _open(self, pw) -> tuple[Browser, BrowserContext, Page]:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"),
            locale="en-CA", timezone_id="America/Edmonton", accept_downloads=True)
        return browser, ctx, ctx.new_page()

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
        page.locator(self.submit_sel).first.click(timeout=15_000)
        # Wait for the login form to go away; some sites take several seconds.
        try:
            page.locator(self.pass_sel).first.wait_for(state="hidden", timeout=45_000)
        except Exception:
            raise RuntimeError(f"{self.name}: still on the login form 45 s after submitting; "
                               "check the username/password") from None
        self._settle(page, 20)
        log.info("%s: logged in, now at %s", self.name, page.url)

    # --- capture mode ----------------------------------------------------
    def capture(self) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser, ctx, page = self._open(pw)
            ctx.on("response", self._save_response)
            try:
                log.info("%s: opening login page", self.name)
                page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
                self._settle(page)
                self._snapshot(page, "login")
                try:
                    self.login(page, already_open=True)
                finally:
                    self._snapshot(page, "after-login")
                page = self._crawl(ctx, page)
            finally:
                browser.close()
        log.info("%s: capture saved to %s", self.name, self.capture_dir)

    def _targets(self, page: Page) -> list[str]:
        out = []
        loc = page.locator(NAV_SEL)
        for i in range(min(loc.count(), 400)):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                text = " ".join((el.inner_text(timeout=1000) or "").split())
            except Exception:
                continue
            if (text and len(text) < 60 and KEYWORDS.search(text)
                    and not SKIP.search(text) and not UNSAFE.search(text)):
                out.append(text)
        return list(dict.fromkeys(out))

    def _click_text(self, ctx: BrowserContext, page: Page, text: str) -> Page | None:
        """Click the first visible nav element with exactly this text; follow popups."""
        pattern = re.compile(r"^\s*" + re.escape(text) + r"\s*$")
        loc = page.locator(NAV_SEL).filter(has_text=pattern)
        for i in range(min(loc.count(), 20)):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                before = len(ctx.pages)
                el.click(timeout=5000)
            except Exception:
                continue
            page.wait_for_timeout(1500)
            if len(ctx.pages) > before:
                page = ctx.pages[-1]
                log.info("%s: link opened a new window", self.name)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:
                pass
            self._settle(page)
            return page
        return None

    def _crawl(self, ctx: BrowserContext, page: Page) -> Page:
        for url in self.start_urls:
            log.info("%s: opening %s", self.name, url)
            try:
                before = len(ctx.pages)
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1500)
                if len(ctx.pages) > before:
                    page = ctx.pages[-1]
                self._settle(page)
                self._snapshot(page, "start")
            except Exception as e:
                log.warning("%s: could not open %s: %s", self.name, url, e)

        log.info("%s: looking for bill and usage pages", self.name)
        done: set[str] = set()
        queue = [(t, page.url, 1) for t in self._targets(page)]
        while queue and self._shots < MAX_PAGES:
            text, source_url, depth = queue.pop(0)
            if text in done:
                continue
            done.add(text)
            new_page = self._click_text(ctx, page, text)
            if new_page is None and page.url != source_url:
                try:
                    page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
                    self._settle(page)
                    new_page = self._click_text(ctx, page, text)
                except Exception:
                    new_page = None
            if new_page is None:
                log.info("%s: couldn't click %r", self.name, text)
                continue
            page = new_page
            log.info("%s: opened %r", self.name, text)
            self._snapshot(page, re.sub(r"[^a-z0-9]+", "-", text.lower())[:30])
            if depth < 3:
                queue += [(t, page.url, depth + 1) for t in self._targets(page) if t not in done]
        return page

    def _snapshot(self, page: Page, label: str) -> None:
        self._shots += 1
        label = f"{self._shots:02d}-{label}"
        log.info("%s: saving page %s", self.name, label)
        try:
            (self.capture_dir / f"{label}.html").write_text(page.content(), encoding="utf-8")
        except Exception as e:
            log.warning("%s: could not save %s: %s", self.name, label, e)
        try:
            page.screenshot(path=str(self.capture_dir / f"{label}.png"), full_page=True, timeout=30_000)
        except Exception as e:
            log.warning("%s: screenshot of %s failed: %s", self.name, label, e)
        for i, frame in enumerate(page.frames[1:], 1):
            try:
                html = frame.content()
                if len(html) > 200:
                    (self.capture_dir / f"{label}.frame{i}.html").write_text(html, encoding="utf-8")
            except Exception:
                pass

    def _save_response(self, response) -> None:
        ctype = (response.headers.get("content-type") or "").lower()
        try:
            if "json" in ctype:
                kind, body = "json", json.dumps(response.json(), indent=2)
            elif "gwt-rpc" in ctype or response.url.endswith(".rpc") or "/rpc" in response.url:
                kind, body = "rpc.txt", response.text()
            elif "pdf" in ctype:
                data = response.body()
                if len(data) > MAX_PDF_BYTES:
                    return
                self._resp_count += 1
                (self.capture_dir / f"data-{self._resp_count:03d}.pdf").write_bytes(data)
                return
            else:
                return
        except Exception:
            return
        self._resp_count += 1
        out = self.capture_dir / f"data-{self._resp_count:03d}.{kind}"
        out.write_text(f"URL: {response.url}\nSTATUS: {response.status}\n\n{body}", encoding="utf-8")

    # --- sync mode -------------------------------------------------------
    def fetch_bills(self):
        with sync_playwright() as pw:
            browser, _ctx, page = self._open(pw)
            try:
                self.login(page)
                return self.read_bills(page)
            finally:
                browser.close()

    def read_bills(self, page: Page):
        raise NotImplementedError(
            f"{self.name}: bill reader not written yet; run capture mode and send the files")
