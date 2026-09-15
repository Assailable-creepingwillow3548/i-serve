# The site

The calculator and the advisor, as one static page for GitHub Pages. No
framework, no build step, no `npm`: a reader needs a browser, and a
contributor needs Python and, for the one check that must run JavaScript, the
`node` that GitHub's runners already carry.

| Path | Written by | What it is |
|---|---|---|
| `index.html`, `style.css` | hand | the page: one sentence for the situation, three steps under it, light theme only |
| `fonts/` | Google Fonts, latin subsets | Newsreader, IBM Plex Sans and IBM Plex Mono as woff2 with their OFL licences, so the page looks the same from `file://` with no network |
| `terms.js` | hand | the plain-language explanations shown on hover; every term is registered in `docs/GLOSSARY.md` (a test holds that) |
| `calc.js` | hand | `bench/roofline.py` and `predictions.what_if_point()`, ported in the same order of operations |
| `selftest.js` | hand | runs every row of `data/golden.json` through `calc.js` and compares — the page's badge and CI's step |
| `draw.js` | hand | the two SVG pictures |
| `advisor.js` | hand | evaluates `docs/symptom-map.json` as rules over the readings |
| `ui.js` | hand | the sentence's popovers and the sliders ↔ state ↔ URL hash ↔ render; the answers written in plain words, the glossary term small beside them |
| `data/model.{json,js}` | `python3 bench/export_site_data.py` | every constant: cards with provenance, the models and which one a run measured, fits, rates, presets, measured points |
| `data/golden.{json,js}` | the same | the parity grid |
| `data/symptom-map.js` | the same | a `window.SYMPTOM_MAP = …` twin of `docs/symptom-map.json` |

The `.js` twins exist because `fetch()` fails on a `file://` URL: a reader who
double-clicks `index.html` gets the same page as one on Pages.

## Run it

    python3 bench/export_site_data.py        # after any change under bench/
    node site/selftest.js                    # "211/211 rows agree", exit 0
    python3 -m http.server -d site 8000      # then open http://localhost:8000/

`open site/index.html` works too. The parity badge in the footer is the same
check the second command runs.

## What holds it together

Three guards, the same three the front-page chart has: `bench/tests/test_export_site_data.py`
asserts the committed `data/` is what the export produces; `.github/workflows/bench.yml`
regenerates it on a clean checkout, diffs, and runs `selftest.js`; and
`.github/workflows/pages.yml` refuses to deploy a page whose JavaScript
disagrees with Python. `<repo-url>` in `index.html` is filled on the day the
public repository gets a name.
