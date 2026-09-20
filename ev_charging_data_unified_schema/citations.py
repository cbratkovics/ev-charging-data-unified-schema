"""Artifact citations in documents and the number checker's rules (ADR-0013 items 2 to 4).

A citation is an HTML comment placed after the sentence it covers:

    <!-- cite: artifacts/silver/latest.json#by_source.boulder.accepted; artifacts/x/latest.json#k -->

``latest.json`` resolves to the current file of that kind; a run-id path is point in time.
Keys are dotted paths into the JSON, with ``[i]`` for list indexes and ``name["0.999"]`` for a
dictionary key that itself contains a dot. ``<!-- scratch -->`` (ADRs
only) marks a sentence whose numbers came from an exploratory query, not a committed artifact;
``<!-- param -->`` marks a sentence whose numbers are design parameters or arithmetic constants
(a threshold, a tolerance, a minutes-in-a-day figure), not measurements.
Generated blocks (``<!-- generated:<name> start -->`` ... ``end``) are skipped: their renderer's
``--check`` validates them.

A ratio stated in words ("about four times", "more than a quarter of") is a measured claim
too: it needs a citation and the cited value must satisfy the qualifier (``word_ratio_bounds``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CITE_RE = re.compile(r"<!--\s*cite:\s*(.*?)\s*-->", re.S)
SCRATCH_RE = re.compile(r"<!--\s*scratch\s*-->")
PARAM_RE = re.compile(r"<!--\s*param\s*-->")
GENERATED_RE = re.compile(
    r"<!--\s*generated:[\w-]+ start\s*-->.*?<!--\s*generated:[\w-]+ end\s*-->", re.S
)
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
NUMBER_RE = re.compile(
    r"(?<![\w.\-/])([+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+\.\d+|[+-]?\d+)(\s*%)?(?![\w/])"
)
MEASURE_WORDS = (
    "rows",
    "row",
    "sessions",
    "session",
    "stations",
    "station",
    "files",
    "file",
    "kwh",
    "minutes",
    "minute",
    "hours",
    "hour",
    "days",
    "day",
    "keys",
    "key",
    "columns",
    "column",
    "ports",
    "port",
    "events",
    "event",
    "gaps",
    "ids",
)
ALLOW_RE = [
    re.compile(r"^(19|20)\d{2}$"),  # years
    re.compile(r"^\d{4}-\d{2}(-\d{2})?$"),  # ISO dates handled by NUMBER_RE exclusion of '-' anyway
]
LICENCE_VERSION_RE = re.compile(
    r"(CC0 |OGL |Licence v|License v|v|§ ?|rule |section |item |Phase |Brief |Python |DuckDB |dbt-core |dbt-duckdb |pandas |pyarrow )\d+(\.\d+)*$",
    re.I,
)
CONTEXT_ALLOW_RE = re.compile(
    r"(ADR-|Phase |phase |item |§ |v\d|version |dbt[- ]core|duckdb|python )", re.I
)
# ratios in words: "<number word> times" (a multiple) and "<fraction> of" (a share). "half hour",
# "a third source" and "counted twice" are not ratios and do not match.
MULTIPLE_WORDS = {
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
}
FRACTION_WORDS = {
    "half": 0.5,
    "a third": 1 / 3,
    "two thirds": 2 / 3,
    "a quarter": 0.25,
    "three quarters": 0.75,
    "a fifth": 0.2,
    "a tenth": 0.1,
}
UPPER_QUALIFIERS = ("up to", "at most", "no more than", "under", "less than", "below")
LOWER_QUALIFIERS = ("more than", "over", "at least", "above")
APPROX_QUALIFIERS = ("about", "roughly", "around", "some")
NEARLY_QUALIFIERS = ("nearly", "almost", "just under")
_QUALIFIER_RE = "|".join(
    re.escape(q)
    for q in UPPER_QUALIFIERS + LOWER_QUALIFIERS + APPROX_QUALIFIERS + NEARLY_QUALIFIERS
)
WORD_RATIO_RE = re.compile(
    rf"\b((?:(?:{_QUALIFIER_RE})\s+)*)"
    rf"(?:({'|'.join(MULTIPLE_WORDS)})\s+times\b|({'|'.join(FRACTION_WORDS)})\s+of\b)",
    re.I,
)


@dataclass
class Number:
    text: str
    value: float
    is_percent: bool
    measured: bool
    sentence: str
    file: str
    line: int


def resolve(path: str, key: str, repo_root: Path) -> Any:
    """Load the cited artifact (through latest.json when named) and walk the dotted key."""
    p = repo_root / path
    if not p.exists():
        raise FileNotFoundError(path)
    data = json.loads(p.read_text())
    if p.name == "latest.json":
        target = p.parent / data["path"]
        if not target.exists():
            raise FileNotFoundError(f"{path} -> {data['path']}")
        data = json.loads(target.read_text())
    cur: Any = data
    for kind, token in _key_tokens(key):
        if kind == "index":
            if not isinstance(cur, list) or int(token) >= len(cur):
                raise KeyError(f"{key} (index {token})")
            cur = cur[int(token)]
        else:
            if not isinstance(cur, dict) or token not in cur:
                raise KeyError(f"{key} (at {token!r})")
            cur = cur[token]
    return cur


def _key_tokens(key: str) -> list[tuple[str, str]]:
    """``a.b[2]["x.y"].c`` -> [(name a), (name b), (index 2), (name x.y), (name c)]."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(key)
    buf = ""
    while i < n:
        ch = key[i]
        if ch == ".":
            if buf:
                out.append(("name", buf))
                buf = ""
            i += 1
        elif ch == "[":
            if buf:
                out.append(("name", buf))
                buf = ""
            j = key.index("]", i)
            inner = key[i + 1 : j]
            if inner.startswith('"') and inner.endswith('"'):
                out.append(("name", inner[1:-1]))
            elif inner.isdigit():
                out.append(("index", inner))
            else:
                raise KeyError(f"{key} (bad bracket {inner!r})")
            i = j + 1
        else:
            buf += ch
            i += 1
    if buf:
        out.append(("name", buf))
    return out


def parse_number(text: str, percent: bool) -> float:
    return float(text.replace(",", ""))


def is_measured(num_text: str, percent: bool, following: str) -> bool:
    if percent or "," in num_text or "." in num_text:
        return True
    try:
        if abs(float(num_text)) >= 1000:
            return True
    except ValueError:
        return False
    nxt = following.strip().lower().split(" ")[0].strip(".,;:)") if following.strip() else ""
    return nxt in MEASURE_WORDS


def strip_skipped(text: str) -> str:
    """Blank out code fences and generated blocks, preserving line numbers."""

    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = GENERATED_RE.sub(blank, FENCE_RE.sub(blank, text))
    # inline code spans are names and examples, never claims
    return INLINE_CODE_RE.sub(blank, text)


def sentences_with_context(text: str) -> list[tuple[int, str, str]]:
    """(line, sentence, trailing comment) triples. A sentence ends at '.', '!' or '?' followed by
    whitespace, or at a blank line; a citation comment after it belongs to it."""
    out = []
    pos = 0
    line = 1
    for para in re.split(r"\n\s*\n", text):
        para_start = pos
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`*(\[0-9])|(?<=-->)\s+", para)
        offset = 0
        for part in parts:
            comment = " ".join(re.findall(r"<!--.*?-->", part, re.S))
            out.append((line + para[:offset].count("\n"), part, comment))
            offset += len(part) + 1
        pos = para_start + len(para) + 2
        line += para.count("\n") + 2
    return out


def values_match(printed: float, is_percent: bool, actual: Any, printed_text: str) -> bool:
    if isinstance(actual, bool) or actual is None:
        return False
    try:
        a = float(actual)
    except (TypeError, ValueError):
        return False
    if is_percent and abs(a) <= 1.0:
        a = a * 100
    decimals = len(printed_text.split(".")[1]) if "." in printed_text else 0
    return (
        round(a, decimals) == round(printed, decimals)
        or abs(a - printed) < 0.5 * 10 ** (-decimals) + 1e-9
    )


def word_ratio_bounds(qualifiers: str, value: float) -> tuple[float, float]:
    """The [low, high] interval a cited value must fall in for a ratio in words to hold. The
    tolerance is a quarter for a multiple ("about four times" covers 3.75 to 4.25) and a tenth of
    the fraction for a share ("about a quarter of" covers 22.5% to 27.5%). "up to" and "more
    than" are one-sided; "about" widens the open side of a one-sided phrase."""
    words = qualifiers.lower().split()
    text = " ".join(words)
    tol = 0.25 if value >= 1 else value / 10
    upper = any(q in text for q in UPPER_QUALIFIERS)
    lower = any(q in text for q in LOWER_QUALIFIERS)
    approx = any(q in text for q in APPROX_QUALIFIERS)
    nearly = any(q in text for q in NEARLY_QUALIFIERS)
    if upper:
        return (float("-inf"), value + (tol if approx else 0.0))
    if lower:
        return (value - (tol if approx else 0.0), float("inf"))
    if nearly:
        return (value - tol, value)
    return (value - tol, value + tol)


def word_ratios(core: str) -> list[tuple[str, float, float, float]]:
    """(phrase, ratio, low, high) for every ratio stated in words in the sentence."""
    out = []
    for m in WORD_RATIO_RE.finditer(core):
        qualifiers, multiple, fraction = m.group(1) or "", m.group(2), m.group(3)
        value = MULTIPLE_WORDS[multiple.lower()] if multiple else FRACTION_WORDS[fraction.lower()]
        lo, hi = word_ratio_bounds(qualifiers, value)
        out.append((m.group(0).strip(), value, lo, hi))
    return out


def ratio_matches(lo: float, hi: float, actual: Any) -> bool:
    if isinstance(actual, bool) or actual is None:
        return False
    try:
        a = float(actual)
    except (TypeError, ValueError):
        return False
    return lo - 1e-9 <= a <= hi + 1e-9


def check_document(
    path: Path, repo_root: Path, *, allow_scratch: bool
) -> tuple[list[str], int, int, int]:
    """Returns (problems, numbers checked, scratch sentences, param sentences)."""
    text = path.read_text(encoding="utf-8")
    body = strip_skipped(text)
    problems: list[str] = []
    checked = 0
    scratch = 0
    params = 0
    rel = path.relative_to(repo_root).as_posix()
    for line, sentence, comment in sentences_with_context(body):
        core = re.sub(r"<!--.*?-->", "", sentence, flags=re.S)
        cites = [c.strip() for c in CITE_RE.findall(comment) for c in c.split(";") if c.strip()]
        is_scratch = bool(SCRATCH_RE.search(comment))
        is_param = bool(PARAM_RE.search(comment))
        if is_param:
            params += 1
        if is_scratch:
            if not allow_scratch:
                problems.append(f"{rel}:{line}: scratch marker is only allowed in ADRs")
            scratch += 1
        cited_values: list[tuple[str, Any]] = []
        for c in cites:
            if "#" not in c:
                problems.append(f"{rel}:{line}: citation without a key: {c}")
                continue
            apath, key = c.split("#", 1)
            try:
                cited_values.append((c, resolve(apath, key, repo_root)))
            except (FileNotFoundError, KeyError, IndexError, TypeError) as e:
                problems.append(
                    f"{rel}:{line}: dangling citation {c} ({e.__class__.__name__}: {e})"
                )
        for m in NUMBER_RE.finditer(core):
            num_text, pct = m.group(1), bool(m.group(2))
            following = core[m.end() : m.end() + 24]
            before = core[max(0, m.start() - 12) : m.start()]
            if any(r.fullmatch(num_text) for r in ALLOW_RE) and not pct:
                continue
            if LICENCE_VERSION_RE.search(before + num_text):
                continue
            if (
                CONTEXT_ALLOW_RE.search(before)
                and not pct
                and "," not in num_text
                and "." not in num_text
            ):
                continue
            if not is_measured(num_text, pct, following):
                continue
            if is_scratch or is_param:
                continue
            checked += 1
            value = parse_number(num_text, pct)
            if not cites:
                problems.append(
                    f"{rel}:{line}: uncited number {num_text}{'%' if pct else ''} in: {core.strip()[:110]}"
                )
                continue
            if cited_values and not any(
                values_match(value, pct, v, num_text) for _, v in cited_values
            ):
                problems.append(
                    f"{rel}:{line}: number {num_text}{'%' if pct else ''} does not match any cited value {[(c, v) for c, v in cited_values][:4]}"
                )
        for phrase, _value, lo, hi in word_ratios(core):
            if is_scratch or is_param:
                continue
            checked += 1
            if not cites:
                problems.append(
                    f"{rel}:{line}: uncited ratio in words {phrase!r} in: {core.strip()[:110]}"
                )
                continue
            if cited_values and not any(ratio_matches(lo, hi, v) for _, v in cited_values):
                problems.append(
                    f"{rel}:{line}: ratio in words {phrase!r} (needs a cited value in [{lo:.3g}, {hi:.3g}]) does not match any cited value {[(c, v) for c, v in cited_values][:4]}"
                )
    return problems, checked, scratch, params
