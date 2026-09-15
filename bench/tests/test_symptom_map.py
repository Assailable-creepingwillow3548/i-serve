"""The symptom map and its JSON skeleton: one home, one checked derivative.

`docs/symptom-map.md` is the operator's decision tree, prose. `docs/symptom-map.json`
is the subset of it the advisor on the site evaluates as rules -- the decision
edges, with each node's text copied out of the markdown. That copy is the same
exemption the front-page chart lives under (bench/tests/test_plot_predicted_vs_measured.py):
a restated fact is allowed only because a test holds it equal to its source.
So this file asserts, for every JSON node, that the id exists in the markdown
and the text is that line, and for every link in either file that the target
heading exists -- computed the way GitHub computes an anchor, not guessed.

No dependency on pytest, which is not installed here -- plain functions, plain
asserts, and a runner at the bottom:

    python3 bench/tests/test_symptom_map.py
"""

# Two ways in, and both have to work. `pytest bench/` gets bench/ on the import
# path from tests/conftest.py; `python3 bench/tests/test_roofline.py` on a rented
# pod, where pytest is not installed, gets only this directory. The three lines
# below are what make the second one work, and they are here rather than in
# conftest.py for exactly that reason.
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))


import json
import re

ROOT = _pathlib.Path(__file__).resolve().parent.parent.parent
DOCS = ROOT / "docs"
MD = DOCS / "symptom-map.md"
JSON = DOCS / "symptom-map.json"

ID_RE = re.compile(r"<!-- ([a-z][a-z0-9-]*(?:\.[a-z0-9-]+){1,2}) -->\s*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MARKS = ("measured", "seen", "watched", "watched firing", "checked", "run once")
KINDS = ("probe", "branch", "trap", "continuation")
OPS = ("gt", "gte", "lt", "lte", "eq", "ne", "is_null", "not_null")


def github_slug(heading: str) -> str:
    """What GitHub makes of a heading: lowercase, drop punctuation, spaces to
    hyphens. Underscores survive, em dashes and section signs do not.
    """
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors_of(path: _pathlib.Path) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            s = github_slug(line.lstrip("#"))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
    return out


def markdown_nodes() -> dict[str, dict]:
    nodes = {}
    for line in MD.read_text(encoding="utf-8").splitlines():
        m = ID_RE.search(line)
        if not m:
            continue
        body = re.sub(r"^\s*-\s+", "", line[:m.start()]).strip()
        text = re.sub(r"\s+", " ", LINK_RE.sub(r"\1", body)).strip()
        nodes[m.group(1)] = {"line": line, "text": text, "body": body}
    return nodes


def normalised_text(line: str) -> str:
    """The rule the JSON's `text` field is held to: the markdown line without
    its leading bullet, its trailing id comment, and with every [x](y) read as x.
    """
    body = ID_RE.sub("", line)
    body = re.sub(r"^\s*-\s+", "", body).strip()
    return re.sub(r"\s+", " ", LINK_RE.sub(r"\1", body)).strip()


def links_in(path: _pathlib.Path) -> list[str]:
    return [target for _, target in LINK_RE.findall(path.read_text(encoding="utf-8"))]


def resolve(target: str, base: _pathlib.Path) -> tuple[_pathlib.Path, str]:
    path, _, anchor = target.partition("#")
    return (base / path if path else MD), anchor


def test_every_node_has_a_unique_well_formed_id():
    lines = [l for l in MD.read_text(encoding="utf-8").splitlines() if l.lstrip().startswith("- ")]
    ids = [ID_RE.search(l).group(1) for l in lines if ID_RE.search(l)]
    assert len(ids) == len(lines), "a bullet without a trailing <!-- id -->"
    assert len(set(ids)) == len(ids), "duplicate id"
    assert len(ids) >= 60, len(ids)


def test_every_link_in_the_map_resolves_to_a_heading():
    bad = []
    for target in links_in(MD):
        path, anchor = resolve(target, DOCS)
        if not path.exists():
            bad.append(("missing file", target))
        elif anchor and path.suffix == ".md" and anchor not in anchors_of(path):
            bad.append(("missing anchor", target))
    assert not bad, bad


def test_every_json_node_is_a_line_of_the_markdown():
    data = json.loads(JSON.read_text(encoding="utf-8"))
    nodes = markdown_nodes()
    problems = []
    for node in data["nodes"]:
        src = nodes.get(node["id"])
        if src is None:
            problems.append(f"{node['id']}: not in the markdown")
            continue
        if node["text"] != normalised_text(src["line"]):
            problems.append(f"{node['id']}: text differs\n  json: {node['text']}\n  md:   "
                            f"{normalised_text(src['line'])}")
        if node["evidence"] is not None and f"**{node['evidence']}**" not in src["body"]:
            problems.append(f"{node['id']}: evidence {node['evidence']!r} is not bold on the line")
        if node["evidence"] is None and any(f"**{m}**" in src["body"] for m in MARKS):
            problems.append(f"{node['id']}: the line carries a mark the JSON drops")
    assert not problems, "\n".join(problems)


def test_json_shape_and_vocabulary():
    data = json.loads(JSON.read_text(encoding="utf-8"))
    inputs = set(data["inputs"]) | set(data["derived"])
    symptoms = {s["id"] for s in data["symptoms"]}
    ids = {n["id"] for n in data["nodes"]}
    assert len(ids) == len(data["nodes"]), "duplicate node id in the JSON"

    def check_pred(pred, where):
        clauses = pred.get("all", []) + pred.get("any", [])
        assert set(pred) <= {"all", "any"}, where
        for c in clauses:
            assert c["field"] in inputs, f"{where}: unknown field {c['field']}"
            assert c["op"] in OPS, f"{where}: unknown op {c['op']}"
            if isinstance(c.get("value"), dict):
                assert c["value"]["field"] in inputs, f"{where}: unknown field ref"

    for s in data["symptoms"]:
        check_pred(s["active_when"], s["id"])
        assert set(s["requires"]) <= inputs, s["id"]
    for n in data["nodes"]:
        assert n["kind"] in KINDS, n["id"]
        assert n["symptom"] in symptoms, n["id"]
        assert n["evidence"] in MARKS + (None,), n["id"]
        assert set(n["requires"]) <= inputs, n["id"]
        if "when" in n:
            check_pred(n["when"], n["id"])
        if n["kind"] == "branch":
            assert "when" in n and "knobs" in n and "next_number" in n, n["id"]
        if n["kind"] == "continuation":
            assert n["parent"] in ids, f"{n['id']}: parent {n.get('parent')} missing"
    # Every input a rule reads is either a dashboard reading or derived from one.
    for name, spec in data["inputs"].items():
        assert spec["type"] in ("number", "enum", "bool") and spec["panel"], name


def test_every_source_in_the_json_resolves():
    data = json.loads(JSON.read_text(encoding="utf-8"))
    targets = [n["source"] for n in data["nodes"] if n["source"]]
    targets += [k["source"] for n in data["nodes"] for k in n.get("knobs", [])]
    bad = []
    for target in targets:
        path, anchor = resolve(target, DOCS)
        if not path.exists():
            bad.append(("missing file", target))
        elif anchor and path.suffix == ".md" and anchor not in anchors_of(path):
            bad.append(("missing anchor", target))
    assert not bad, bad


def test_the_runbook_no_longer_promises_a_map_it_does_not_have():
    """Two sentences used to say "the symptom map in the benchmark reports";
    no such file existed. They point here now.
    """
    runbook = (DOCS / "runbook.md").read_text(encoding="utf-8")
    assert "symptom map in the benchmark reports" not in runbook
    assert "symptom-map.md" in runbook


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
