"""`.githooks/no-secrets.sh` fires on a credential and stays quiet on the rest.

The gate's own header records what this file exists to prevent: eight patterns
written with `\\b` were inert from the day they were written, because git's ERE
engine does not implement it and a pattern it cannot parse matches nothing and
exits 0. They were found by remembering a line, not by the check failing. A
pattern list with no fixture is a rule with no instrument.

So this test never re-implements a pattern. Python's `re` is not PCRE, and a
verification done with a kinder engine is the exact mistake above. It builds a
scratch repository, stages planted text, runs the script itself, and reads its
exit code and its output -- the engine that will run in the hook is the engine
under test.

Two halves, and the second is the one that matters in practice: a check that
refuses a legitimate line is removed by the first person it blocks. The
negatives are real lines from the runsheets and the captured logs.

No dependency on pytest -- plain functions, plain asserts, and a runner at the
bottom:

    python3 bench/tests/test_no_secrets.py
"""

import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))


import subprocess
import tempfile


SCRIPT = _pathlib.Path(__file__).resolve().parents[2] / ".githooks" / "no-secrets.sh"


# Each of these must be refused. The shapes are the ones that reach a captured
# terminal: an environment assignment, a header a benchmark client echoes back
# in its argument dump, a key block pasted whole.
#
# **Every one is split.** This file is inside the tree the script searches --
# no exclusion, because an exclusion is a hole -- so a fixture that spelled a
# credential out would be a credential in the repository, and the hook would
# refuse the commit that added its own test. The seam always falls inside the
# prefix the pattern matches on, which is why `"...=hf" + "_Ab..."` is inert and
# `"...=hf_Ab..."` would not be. Joining these back up is not a tidy-up;
# `test_the_fixture_is_not_itself_a_credential` is what says so out loud.
POSITIVES = [
    "VLLM_API_KEY=sk-" + "0123456789abcdef0123456789abcdef",
    "export HF_TOKEN=hf" + "_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    'curl -H "Authorization: Bearer sk-' + "abcdef0123456789abcdef\" 127.0.0.1:8000",
    "GH=ghp" + "_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "github_pat" + "_11ABCDEFG0abcdefghijkl_ABCDEFGHIJKLMNOP",
    "aws_access_key_id = AKIA" + "IOSFODNN7EXAMPLE",
    "-----BEGIN OPENSSH PRIVATE" + " KEY-----",
    "vllm bench serve --api-key sk-" + "deadbeefdeadbeefdead",
    # Synthetic, and deliberately not the one this rule was written for: the
    # point of the pattern is that no fingerprint is worth writing down.
    "SHA256:" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfG",
    "SLACK=xox" + "b-1234567890-abcdefghij",
    "MY_SERVICE_PASSWORD=" + "hunter2hunter2hunter2",
]

# Each of these must pass. Every one is a line this repository actually
# contains, or the shape of one: the variable named without its value, the key
# generated rather than quoted, the header carrying `$VAR`, and the flag whose
# name ends in `_TOKENS` rather than `_TOKEN`.
NEGATIVES = [
    "VLLM_API_KEY is an environment variable at deploy time, not something typed",
    "`VLLM_API_KEY` -- from the password manager, generated with",
    'echo "sk-$(openssl rand -hex 32)"',
    "The default key is `sk-<pod-id>`, and the pod id is in the public proxy URL",
    'curl -s 127.0.0.1:8000/v1/models -H "Authorization: Bearer $VLLM_API_KEY"',
    "export $(tr '\\0' '\\n' < /proc/1/environ | grep '^VLLM_API_KEY=')",
    '[ -n "$VLLM_API_KEY" ] && echo present || echo MISSING',
    "vllm serve --max-num-batched-tokens 8192 --kv-cache-dtype fp8",
    "MAX_NUM_BATCHED_TOKENS=8192",
    "HF_TOKEN=",
    "docker pull vllm/vllm-openai@sha256:" + "0123456789abcdef" * 4,
    'Set VLLM_API_KEY="<paste from the password manager>"',
]


def _run_over(lines):
    """Stage `lines` in a scratch repository and return the script's output.

    One line per file, so a pattern that matches the wrong line cannot hide
    behind a neighbour that matched correctly: the file name in the output says
    which input fired.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = _pathlib.Path(tmp)
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": tmp,
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
        for i, line in enumerate(lines):
            (root / f"f{i:02d}.txt").write_text(line + "\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
        done = subprocess.run(
            ["sh", str(SCRIPT), "--cached"],
            cwd=root, env=env, capture_output=True, text=True,
        )
        return done.returncode, done.stderr


def test_every_planted_credential_is_refused():
    """One at a time: a list that fires on ten of eleven still exits 1."""
    for line in POSITIVES:
        code, err = _run_over([line])
        assert code == 1, f"not refused: {line!r}"
        assert "no-secrets" in err


def test_no_legitimate_line_is_refused():
    """All at once, because the failure names the file that fired."""
    code, err = _run_over(NEGATIVES)
    assert code == 0, f"false positive:\n{err}"


def test_the_message_says_rotate_before_unstage():
    """Removing the line is not the fix if the object ever reached a remote."""
    _, err = _run_over([POSITIVES[0]])
    assert "rotate" in err


def test_the_fixture_is_not_itself_a_credential():
    """This file is searched like any other, so the planted text must stay split.

    The check that would otherwise catch this catches it too late: the hook
    refuses the commit, and the person reading the error sees a credential
    reported in a test file and has to work out that it is a fixture.
    """
    code, err = _run_over([_pathlib.Path(__file__).read_text()])
    assert code == 0, f"the fixture spells a credential out:\n{err}"


def test_the_pattern_list_does_not_match_itself():
    """The script is inside the tree it searches -- no exclusion, so no hole.

    That holds only while every pattern's literal prefix is followed by a
    character class, which is what makes `sk-[A-Za-z0-9_-]{16,}` fail to match
    the text `sk-[A-Za-z0-9_-]{16,}`. A pattern added without one would make
    the hook refuse the commit that added it, and the error would name this
    file rather than the mistake.
    """
    code, err = _run_over([SCRIPT.read_text()])
    assert code == 0, f"the pattern list matches itself:\n{err}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all good")
