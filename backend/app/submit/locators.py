"""Finding elements on a page that may have changed since the form was described.

Each element is tried with a chain of strategies, most specific first:
  1. what worked last time (the learned cache)
  2. data-testid from the form definition
  3. the exact label
  4. the input's name attribute
  5. a label that is one of the field's aliases ("Given name" for first name)
  6. the closest label on the page, by text similarity (only if it is clearly the best one)
When the first strategy that works is not the cached or test-id one, the page has drifted: that is a "heal". It is
recorded (field, from, to) and the new locator is remembered, so the next run goes straight to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

from app.forms.base import FieldSpec, Option
from app.mapping.values import norm

FUZZY_MIN = 0.72     # a label this close counts as the field...
FUZZY_GAP = 0.08     # ...if no other label is nearly as close
NEXT_WORDS = ("continue", "next", "save and continue", "next step", "proceed")
SUBMIT_WORDS = ("submit", "send", "join", "become", "apply", "register", "sign up", "confirm", "finish")


@dataclass
class Found:
    locator: Locator
    strategy: str
    arg: str


@dataclass
class Learned:
    strategy: str
    arg: str


@dataclass
class Heal:
    target: str
    old: str
    new: str


@dataclass
class Resolver:
    """Locates elements for one form, using and updating what it has learned."""
    form_id: str
    cache: dict[str, Learned] = field(default_factory=dict)
    heals: list[Heal] = field(default_factory=list)
    learned: dict[str, Learned] = field(default_factory=dict)   # new or changed entries to save after the run
    used: dict[str, str] = field(default_factory=dict)          # target -> "strategy:arg", for the run's steps log

    # ---------------------------------------------------------------- the chain

    async def _first(self, page: Page, target: str, chain: list[tuple[str, str, Locator]],
                     primary: str | None) -> Found | None:
        cached = self.cache.get(target)
        if cached:
            chain = [c for c in chain if (c[0], c[1]) == (cached.strategy, cached.arg)] + \
                    [c for c in chain if (c[0], c[1]) != (cached.strategy, cached.arg)]
            if not any((c[0], c[1]) == (cached.strategy, cached.arg) for c in chain):
                rebuilt = _rebuild(page, cached)
                if rebuilt is not None:
                    chain = [(cached.strategy, cached.arg, rebuilt), *chain]
        for strategy, arg, loc in chain:
            try:
                if await loc.count() == 1 and await loc.first.is_visible():
                    found = Found(loc.first, strategy, arg)
                    break
            except Exception:  # noqa: S112 - a selector that errors is just a strategy that did not work
                continue
        else:
            return None
        expected = f"{cached.strategy}:{cached.arg}" if cached else primary
        now = f"{found.strategy}:{found.arg}"
        if expected and now != expected:
            self.heals.append(Heal(target, expected, now))
        if not cached or (cached.strategy, cached.arg) != (found.strategy, found.arg):
            self.learned[target] = Learned(found.strategy, found.arg)
            self.cache[target] = self.learned[target]   # later pages of this run start from what just worked
        self.used[target] = now
        return found

    async def field(self, page: Page, spec: FieldSpec, others: list[FieldSpec] | None = None) -> Found | None:
        """The input, select or combobox for a single-element field."""
        chain: list[tuple[str, str, Locator]] = []
        if spec.test_id:
            chain.append(("testid", spec.test_id, page.get_by_test_id(spec.test_id)))
        chain.append(("label", spec.label, page.get_by_label(spec.label, exact=True)))
        chain.append(("name", spec.name, page.locator(f'[name="{spec.name}"]:not([type="hidden"])')))
        for alias in _alias_texts(spec):
            chain.append(("alias", alias, page.get_by_label(re.compile(rf"^\s*{re.escape(alias)}\s*$", re.I))))
        fuzzy = await _closest_label(page, spec, others or [])
        if fuzzy:
            chain.append(("fuzzy", fuzzy, page.get_by_label(fuzzy, exact=True)))
        primary = f"testid:{spec.test_id}" if spec.test_id else f"label:{spec.label}"
        return await self._first(page, spec.name, chain, primary)

    async def option(self, page: Page, spec: FieldSpec, opt: Option, role: str) -> Found | None:
        """One radio button or one tick box of a group."""
        target = f"{spec.name}={opt.value}"
        chain: list[tuple[str, str, Locator]] = []
        if spec.test_id:
            tid = f"{spec.test_id}-{opt.value}"
            chain.append(("testid", tid, page.get_by_test_id(tid)))
        chain.append(("value", opt.value, page.locator(f'input[name="{spec.name}"][value="{opt.value}"]')))
        chain.append(("role", opt.label, page.get_by_role(role, name=opt.label, exact=True)))  # type: ignore[arg-type]
        for alt in opt.also[:3]:
            chain.append(("role-alias", alt, page.get_by_role(role, name=re.compile(rf"^{re.escape(alt)}$", re.I))))  # type: ignore[arg-type]
        primary = f"testid:{spec.test_id}-{opt.value}" if spec.test_id else f"value:{opt.value}"
        return await self._first(page, target, chain, primary)

    async def button(self, page: Page, kind: str, test_ids: list[str]) -> Found | None:
        """The page's next or submit button."""
        words = NEXT_WORDS if kind == "next" else SUBMIT_WORDS
        chain: list[tuple[str, str, Locator]] = [("testid", t, page.get_by_test_id(t)) for t in test_ids]
        names = await _button_names(page)
        for name in names:
            if any(re.search(rf"\b{re.escape(w)}\b", name.lower()) for w in words):
                chain.append(("button", name, page.get_by_role("button", name=name, exact=True)))
        if kind == "submit":   # last resort: the form's own submit button
            chain.append(("submit", "form submit", page.locator('form button[type="submit"]')))
        primary = f"testid:{test_ids[0]}" if test_ids else None
        return await self._first(page, f"button:{kind}", chain, primary)


def _rebuild(page: Page, learned: Learned) -> Locator | None:
    s, a = learned.strategy, learned.arg
    if s in ("testid",):
        return page.get_by_test_id(a)
    if s in ("label", "fuzzy"):
        return page.get_by_label(a, exact=True)
    if s == "button":
        return page.get_by_role("button", name=a, exact=True)
    return None


def _alias_texts(spec: FieldSpec) -> list[str]:
    seen: list[str] = []
    for a in [spec.name, *spec.aliases]:
        text = a.replace("_", " ").strip()
        if text and text.lower() not in (s.lower() for s in seen):
            seen.append(text)
    return seen


async def _labels(page: Page) -> list[str]:
    texts: list[str] = await page.eval_on_selector_all(
        "label, legend", "els => els.filter(e => e.offsetParent !== null).map(e => e.innerText.trim())")
    return [t for t in texts if t and len(t) <= 120]


def _score(label: str, spec: FieldSpec) -> float:
    wanted = [norm(spec.label), *(norm(a) for a in _alias_texts(spec))]
    return max(SequenceMatcher(None, norm(label), w).ratio() for w in wanted)


async def _closest_label(page: Page, spec: FieldSpec, others: list[FieldSpec]) -> str | None:
    """The page label most like this field's, if it is clearly the closest and no other field claims it more."""
    labels = await _labels(page)
    if not labels:
        return None
    scored = sorted(((_score(lbl, spec), lbl) for lbl in labels), reverse=True)
    best, label = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best < FUZZY_MIN or best - runner_up < FUZZY_GAP:
        return None
    if any(_score(label, o) > best for o in others if o.name != spec.name):
        return None   # that label belongs to another field
    return label


async def _button_names(page: Page) -> list[str]:
    names: list[str] = await page.eval_on_selector_all(
        "button", "els => els.filter(e => e.offsetParent !== null && !e.disabled).map(e => e.innerText.trim())")
    return [n for n in names if n]


def describe(found: Found | None) -> dict[str, Any]:
    return {"strategy": found.strategy, "arg": found.arg} if found else {}
