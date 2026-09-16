#!/bin/sh
# What a commit may not carry, third rule: a credential.
#
# The other two rules in `.githooks/pre-commit` guard prose a human wrote. This
# one guards prose nobody wrote. `docs/benchmarks/raw/` is captured terminal --
# `tee` output, a console log, a `--save-result` JSON -- and a captured terminal
# is the one place in this repository where a secret can arrive without anyone
# typing it. Two live paths, both one keystroke from the procedure as written:
#
#   * `vllm bench serve --header "Authorization: Bearer ..."` lands in the
#     `Namespace(...)` dump the client prints, which `tee` writes into the file
#     the run commits. Every captured file today reads `header=None`; the first
#     run that needs auth writes the key there instead.
#   * `runsheets/l40s-first-run.md` reads `/proc/1/environ` through a `grep` for
#     one variable. Drop the `grep` -- the obvious next move when it matched
#     nothing -- and the whole pod environment is in the transcript the report
#     is built from.
#
# Neither is hypothetical and neither is careless; both are what the procedure
# looks like one step off its rails. Until this file existed the logs were clean
# by procedure and not by check, which is the same state the map's inert `\b`
# patterns were in.
#
# Called with a tree-ish to judge: `--cached` for a commit, a SHA for a push,
# `HEAD` in CI. Same shape as the hook beside it, so all three can share it.
#
# `-P` and never `-E`: git's ERE engine does not implement the constructs below,
# and a pattern it cannot parse matches nothing and exits 0 -- a clean search and
# a broken one then look identical. `bench/tests/test_no_secrets.py` runs this
# script over planted text for exactly that reason: the patterns are verified by
# the engine that will run them, never by a second tool that is kinder.
set -e

tree=${1:---cached}

# Vendor-shaped tokens. Each is a fixed prefix and a length no placeholder
# reaches, so `sk-<pod-id>` and `sk-$(openssl rand -hex 32)` -- both of which
# appear in the runsheets as instructions -- do not match: the character after
# the prefix is `<` or `$`, and neither is in the class.
PATTERN='sk-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{30,}|gh[pousr]_[A-Za-z0-9]{30,}'
PATTERN="$PATTERN|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}"
PATTERN="$PATTERN|xox[baprs]-[A-Za-z0-9-]{10,}"
# A private key block, whatever the header says between BEGIN and PRIVATE KEY.
PATTERN="$PATTERN|-----BEGIN [A-Z ]*PRIVATE KEY-----"
# An authorization header carrying a value rather than a variable. The runsheet
# form `Bearer $VLLM_API_KEY` is the one that must pass, and it does: `$` is not
# in the class, so the match needs a literal token.
PATTERN="$PATTERN|Bearer [A-Za-z0-9._~+/=-]{16,}"
# A named variable or flag assigned something that looks like a value. The name
# must end at the `=`, which is why `MAX_NUM_BATCHED_TOKENS=8192` is not a hit --
# `_TOKENS=` is not `_TOKEN=`. Twelve characters is the floor: below it the
# false positives outnumber the credentials.
PATTERN="$PATTERN|[A-Z][A-Z0-9_]*_(KEY|TOKEN|SECRET|PASSWORD)=[\"']?[A-Za-z0-9+/_.-]{12,}"
PATTERN="$PATTERN|--api[-_]?key[= ]+[\"']?[A-Za-z0-9+/_.-]{12,}"
# An SSH public-key fingerprint. Not a secret and not reversible -- it is here
# because it is a permanent identifier of a key that exists, published for no
# reader's benefit: `runsheets/l40s-first-run.md` carried one until 2026-09-16,
# in a step whose point ("check it against the console") survives as
# `<fingerprint>`. Upper-case only, so a `sha256:` image digest is not a hit.
PATTERN="$PATTERN|SHA256:[A-Za-z0-9+/]{43}"

# Nothing is excluded, this file included: an exclusion is a hole, and a pattern
# list is a safe thing to publish -- unlike the gate that cannot be. The list
# does not match itself because every pattern's literal prefix is followed by a
# character class, and `[` is in none of them. A pattern added without one would
# make this script refuse itself, which the test catches on the first run.
#
# `-I` skips binary files. A match inside compressed bytes is noise a reader
# cannot act on, and the file this rule exists for -- a captured terminal -- is
# text by definition.
if [ "$tree" = "--cached" ]; then
    found=$(git grep --cached -nIP "$PATTERN" || true)
else
    found=$(git grep -nIP "$PATTERN" "$tree" || true)
fi

if [ -n "$found" ]; then
    printf 'no-secrets: what looks like a credential:\n%s\n\n' "$found" >&2
    printf 'Removing the line is the second step, not the first. If this ever\n' >&2
    printf 'reached a remote, the object stays addressable by its SHA whether or\n' >&2
    printf 'not a branch points at it -- so rotate the credential, then unstage.\n' >&2
    exit 1
fi
