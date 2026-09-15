"""The site's hover explanations stay inside the glossary's vocabulary.

`site/terms.js` explains the page's words in plain language. It is a second
text about the same terms, and the rule that keeps it honest is the glossary's
own: a term is registered in docs/GLOSSARY.md or it is not used. This file
holds every entry of terms.js to a glossary entry, and keeps the explanations
short and English.

No dependency on pytest -- plain functions, plain asserts, a runner at the bottom:

    python3 bench/tests/test_site_terms.py
"""

import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))


import json
import re

ROOT = _pathlib.Path(__file__).resolve().parent.parent.parent
TERMS = ROOT / "site" / "terms.js"
GLOSSARY = ROOT / "docs" / "GLOSSARY.md"


def terms() -> list[dict]:
    """The array literal behind `window.TERMS = `, read as JSON after the
    small JavaScript-only liberties (trailing commas, comments) are removed."""
    text = TERMS.read_text(encoding="utf-8")
    body = text[text.index("window.TERMS = ") + len("window.TERMS = "):]
    body = body[:body.rindex("];") + 1]
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    body = re.sub(r",(\s*[}\]])", r"\1", body)
    body = re.sub(r"(\{|,)\s*(\w+):", r'\1 "\2":', body)
    return json.loads(body)


def glossary_entries() -> set[str]:
    """Bold entry heads, backticks stripped, plus the notation tables' symbols."""
    out = set()
    for line in GLOSSARY.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\*\*(.+?)\*\*", line)
        if m:
            out.add(m.group(1).replace("`", "").strip().lower())
        m = re.match(r"\| `([^`]+)` \|", line)
        if m:
            out.add(m.group(1).strip().lower())
    return out


def test_every_term_is_registered_in_the_glossary():
    entries = glossary_entries()
    missing = [t["glossary"] for t in terms()
               if t["glossary"].replace("`", "").strip().lower() not in entries]
    assert not missing, f"not in docs/GLOSSARY.md: {missing}"


def test_explanations_are_short_plain_and_english():
    for t in terms():
        assert 40 <= len(t["plain"]) <= 260, (t["glossary"], len(t["plain"]))
        assert not re.search(r"[\u0400-\u04ff]", t["plain"]), t["glossary"]
        assert t["match"], t["glossary"]


def test_no_spelling_is_claimed_twice():
    seen = {}
    for t in terms():
        for m in t["match"]:
            assert m.lower() not in seen, f"{m!r} in both {seen.get(m.lower())} and {t['glossary']}"
            seen[m.lower()] = t["glossary"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}\n      {exc or test.__doc__}")
        else:
            print(f"ok    {test.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
