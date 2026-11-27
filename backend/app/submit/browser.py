"""Submitting through the portal's own web form, the way a person would, with a real browser (Playwright).

One attempt: open the form, and on each page fill every field that is there (conditional fields appear as their
trigger is set), read each value back from the page, screenshot the page, press next. On the last page, check that
nothing is left unfilled, stop if a security check is showing, press submit, and capture the confirmation reference
and what the portal says it received.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

try:   # the API server can run without a browser: browser submissions then go to the worker
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - exercised on the deployed API, which has no Playwright
    async_playwright = None  # type: ignore[assignment]

    class PlaywrightError(Exception):  # type: ignore[no-redef]
        """Stand-in when Playwright is not installed."""

    class PlaywrightTimeout(PlaywrightError):  # type: ignore[no-redef]
        """Stand-in when Playwright is not installed."""

if TYPE_CHECKING:
    from playwright.async_api import Page

from app.forms.base import FieldSpec, FormSpec, Option
from app.submit.base import (
    HUMAN_CHECK,
    NO_CONFIRMATION,
    NOT_FOUND,
    NOT_SET,
    REJECTED,
    UNAVAILABLE,
    AttemptResult,
    Shot,
    SubmitError,
    TestModes,
)
from app.submit.locators import Resolver

MAX_PAGES = 12
SETTLE_MS = 5000
AFTER_CLICK_S = 20.0
CAPTCHA_TEXT = re.compile(r"i am not a robot|i'm not a robot|security check|verify you are (a )?human", re.I)
BUSY_TEXT = re.compile(r"could not|couldn't|went wrong|try again|unavailable|busy", re.I)


@dataclass
class _After:
    kind: str                      # confirmation | duplicate | errors | banner | moved | stuck
    ref: str = ""
    errors: list[dict[str, str]] = field(default_factory=list)


def _option(spec: FieldSpec, value: Any) -> Option:
    opt = next((o for o in spec.options if o.value == value), None)
    if opt is None:
        raise SubmitError(REJECTED, f"{spec.name} has a value that is not one of the portal's options",
                          retryable=False, field_errors=[{"field": spec.name, "message": "Not one of the options."}])
    return opt


def _date_text(iso: str, input_type: str | None, placeholder: str | None) -> str:
    if input_type == "date":
        return iso
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}" if (placeholder or "").upper().startswith("MM") else f"{d}/{m}/{y}"


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()).lower() == " ".join(b.split()).lower()


async def _shot(page: Page) -> bytes:
    return await page.screenshot(full_page=True, type="jpeg", quality=60)


async def _visible(loc: Any) -> bool:
    try:
        return await loc.count() > 0 and await loc.first.is_visible()
    except PlaywrightError:
        return False


class BrowserSubmitter:
    def __init__(self, base_url: str, headless: bool = True, action_timeout_ms: int = 8000):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout = action_timeout_ms

    async def submit(self, form: FormSpec, payload: dict[str, Any], modes: TestModes,
                     resolver: Resolver) -> AttemptResult:
        if async_playwright is None:
            raise SubmitError("BROWSER_UNAVAILABLE", "this server has no browser; web-form submissions run in the "
                              "worker", retryable=False)
        try:
            pw = await async_playwright().start()
        except PlaywrightError:
            raise SubmitError("BROWSER_UNAVAILABLE", "the browser could not start", retryable=False) from None
        try:
            try:
                browser = await pw.chromium.launch(headless=self.headless)
            except PlaywrightError:
                raise SubmitError("BROWSER_UNAVAILABLE", "Chromium is not installed for Playwright "
                                  "(run: playwright install chromium)", retryable=False) from None
            try:
                ctx = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB",
                                                timezone_id="Europe/London")
                page = await ctx.new_page()
                page.set_default_timeout(self.timeout)
                page.set_default_navigation_timeout(45_000)   # a dev server compiles a page on first visit
                shots: list[Shot] = []
                steps: list[dict[str, Any]] = []
                try:
                    result = await self._run(page, form, payload, modes, resolver, shots, steps)
                    result.shots, result.steps = shots, steps
                    return result
                except (SubmitError, PlaywrightTimeout, PlaywrightError) as exc:
                    err = exc if isinstance(exc, SubmitError) else SubmitError(
                        UNAVAILABLE, "the page stopped responding" if isinstance(exc, PlaywrightTimeout)
                        else "the browser could not work with the page", retryable=True)
                    try:
                        shots.append(Shot("when it went wrong", await _shot(page)))
                    except PlaywrightError:
                        pass
                    err.shots, err.steps = shots, steps
                    raise err from None
            finally:
                await browser.close()
        finally:
            await pw.stop()

    # ------------------------------------------------------------------ one attempt

    async def _run(self, page: Page, form: FormSpec, payload: dict[str, Any], modes: TestModes, resolver: Resolver,
                   shots: list[Shot], steps: list[dict[str, Any]]) -> AttemptResult:
        res = await page.goto(self.base_url + form.url_path + modes.query(), wait_until="domcontentloaded")
        if res is None or res.status >= 500:
            status = res.status if res else "nothing"
            raise SubmitError(UNAVAILABLE, f"the form page answered {status}", retryable=True)
        if res.status >= 400:
            raise SubmitError(NOT_FOUND, f"the form page answered {res.status}", retryable=False)
        await self._settle(page)
        specs = {s.name: s for s in form.fields}
        todo = [n for n in form.names if n in payload and payload[n] is not None]
        prefix = form.fields[0].test_id.split("-")[0] if form.fields and form.fields[0].test_id else ""

        for page_no in range(1, MAX_PAGES + 1):
            filled = await self._fill_page(page, form, payload, todo, resolver)
            todo = [n for n in todo if n not in filled]
            heading = await self._heading(page)
            shots.append(Shot(f"page {page_no} filled", await _shot(page)))
            nxt = await resolver.button(page, "next", [f"{prefix}-next"] if prefix else [])
            button = nxt
            if nxt is None:
                missing = [n for n in todo if not (specs[n].type == "checkbox" and payload[n] is False)]
                if missing:
                    raise SubmitError(NOT_FOUND, "could not find on the form: " + ", ".join(missing), retryable=False)
                button = await resolver.button(page, "submit", [f"{prefix}-submit"] if prefix else [])
                if button is None:
                    raise SubmitError(NOT_FOUND, "could not find the submit button", retryable=False)
            await self._check_halt(page)
            # Every filled field was read back from the page and matched before this point (see _fill).
            steps.append({"page": page_no, "heading": heading, "filled": filled, "verified": len(filled),
                          "locators": {n: resolver.used.get(n, "") for n in filled},
                          "button": resolver.used.get("button:next" if nxt else "button:submit", "")})
            assert button is not None
            await button.locator.click()
            after = await self._after_click(page, form, heading)
            steps[-1]["result"] = after.kind
            if after.kind == "moved":
                await self._settle(page)
                continue
            if after.kind == "confirmation":
                shots.append(Shot("confirmation", await _shot(page)))
                received = await self._read_confirmation(page, form)
                return AttemptResult(confirmation_ref=after.ref, portal_record=received)
            if after.kind == "duplicate":
                shots.append(Shot("already received", await _shot(page)))
                return AttemptResult(confirmation_ref=after.ref, adopted=True,
                                     notes=["The portal already had this application; its reference was kept."])
            if after.kind == "errors":
                raise SubmitError(REJECTED, f"the portal refused {len(after.errors)} field(s)", retryable=False,
                                  field_errors=after.errors)
            if after.kind == "banner":
                raise SubmitError(UNAVAILABLE, "the portal said it could not take the submission now", retryable=True)
            raise SubmitError(NO_CONFIRMATION if nxt is None else UNAVAILABLE,
                              "nothing happened after pressing the button", retryable=True)
        raise SubmitError(NOT_FOUND, "the form had more pages than expected", retryable=False)

    async def _settle(self, page: Page) -> None:
        """Let the page finish loading and its scripts take over the form (typing earlier would be lost)."""
        try:
            await page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
        except PlaywrightTimeout:
            pass

    async def _heading(self, page: Page) -> str:
        h1 = page.locator("h1")
        return (await h1.first.inner_text()).strip()[:80] if await h1.count() else ""

    async def _check_halt(self, page: Page) -> None:
        markers = [page.get_by_test_id("captcha"),
                   page.locator("iframe[src*='captcha'], iframe[title*='challenge' i], .g-recaptcha, .h-captcha, "
                                ".cf-turnstile"),
                   page.get_by_text(CAPTCHA_TEXT)]
        for m in markers:
            if await _visible(m):
                raise SubmitError(HUMAN_CHECK, "the portal is asking for a security check that a person must do",
                                  retryable=False)

    # ------------------------------------------------------------------ filling

    async def _fill_page(self, page: Page, form: FormSpec, payload: dict[str, Any], todo: list[str],
                         resolver: Resolver) -> list[str]:
        """Fill what this page shows. Several passes: setting one field can reveal another."""
        done: list[str] = []
        for _ in range(3):
            progress = False
            for name in [n for n in todo if n not in done]:
                spec = form.field(name)
                if await self._fill(page, spec, payload[name], resolver, form.fields):
                    done.append(name)
                    progress = True
            if not progress:
                break
            await page.wait_for_timeout(150)
        return done

    async def _fill(self, page: Page, spec: FieldSpec, value: Any, resolver: Resolver,
                    others: list[FieldSpec]) -> bool:
        if spec.type in ("radio", "multiselect"):
            values = value if isinstance(value, list) else [value]
            role = "radio" if spec.type == "radio" else "checkbox"
            for i, v in enumerate(values):
                found = await resolver.option(page, spec, _option(spec, v), role)
                if found is None:
                    if i == 0:
                        return False
                    raise SubmitError(NOT_FOUND, f"could not find the option for {spec.name}", retryable=False)
                await found.locator.check()
                if not await found.locator.is_checked():
                    raise SubmitError(NOT_SET, f"{spec.name} did not stay selected", retryable=True)
            return True

        found = await resolver.field(page, spec, others)
        if found is None:
            return False
        el = found.locator
        for attempt in range(2):
            expected = await self._set(page, el, spec, value)
            actual: Any = await el.is_checked() if spec.type == "checkbox" else await el.input_value()
            ok = actual == expected if isinstance(expected, bool) else _same_text(str(actual), str(expected))
            if ok:
                return True
            if attempt == 0:
                await page.wait_for_timeout(300)
        raise SubmitError(NOT_SET, f"{spec.name} read back differently after it was filled", retryable=True)

    async def _set(self, page: Page, el: Any, spec: FieldSpec, value: Any) -> Any:
        """Put the value in and return what the element should then read back as."""
        if spec.type == "checkbox":
            await el.set_checked(bool(value))
            return bool(value)
        tag = (await el.evaluate("e => e.tagName")).lower()
        if tag == "select":
            await el.select_option(value=str(value))
            return str(value)
        if spec.type == "combobox":
            label = _option(spec, value).label
            await el.fill(label)
            option = page.get_by_role("option", name=label, exact=True)
            if await _visible(option):
                await option.first.click()
            else:
                await el.press("Enter")
            return label
        if spec.type == "date":
            text = _date_text(str(value), await el.get_attribute("type"), await el.get_attribute("placeholder"))
            await el.fill(text)
            return text
        text = str(value)
        await el.fill(text)
        return text

    # ------------------------------------------------------------------ after pressing a button

    async def _after_click(self, page: Page, form: FormSpec, heading: str) -> _After:
        ref_re = re.compile(form.ref_pattern) if form.ref_pattern else None
        deadline = asyncio.get_running_loop().time() + AFTER_CLICK_S
        while asyncio.get_running_loop().time() < deadline:
            await page.wait_for_timeout(250)
            alerts = [t for t in await page.get_by_role("alert").all_inner_texts() if t.strip()]
            for text in alerts:
                m = ref_re.search(text) if ref_re else None
                if m and re.search(r"already", text, re.I):
                    return _After("duplicate", ref=m.group(0))
            errors = await self._field_errors(page, form)
            if errors:
                return _After("errors", errors=errors)
            if any(BUSY_TEXT.search(t) for t in alerts):
                return _After("banner")
            body = await page.inner_text("body")
            m = ref_re.search(body) if ref_re else None
            if m and not any(m.group(0) in t for t in alerts):
                return _After("confirmation", ref=m.group(0))
            if await self._heading(page) != heading:
                return _After("moved")
        return _After("stuck")

    async def _field_errors(self, page: Page, form: FormSpec) -> list[dict[str, str]]:
        names = set(form.names)
        out: list[dict[str, str]] = []
        invalid = page.locator('[aria-invalid="true"]')
        for i in range(await invalid.count()):
            el = invalid.nth(i)
            if not await el.is_visible():
                continue
            name = await el.get_attribute("name") or ""
            message = ""
            for ref in (await el.get_attribute("aria-describedby") or "").split():
                if ref.endswith("-error"):
                    message = (await page.locator(f"[id='{ref}']").inner_text()).replace("Error:", "").strip()
            out.append({"field": name if name in names else "unknown", "message": message[:200]})
        return out

    async def _read_confirmation(self, page: Page, form: FormSpec) -> dict[str, Any] | None:
        """What the confirmation page says was received, where the portal labels it (data-value)."""
        items = await page.eval_on_selector_all(
            "[data-testid*='-confirm-'][data-value]",
            "els => els.map(e => [e.getAttribute('data-testid'), e.getAttribute('data-value')])")
        if not items:
            return None
        types = {s.name: s.type for s in form.fields}
        out: dict[str, Any] = {}
        for testid, value in items:
            name = testid.split("-confirm-", 1)[1].replace("-", "_")
            kind = types.get(name)
            if kind == "multiselect":
                out[name] = [v for v in value.split(",") if v]
            elif kind == "checkbox":
                out[name] = value == "true"
            else:
                out[name] = value
        return out
