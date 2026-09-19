#!/usr/bin/env python3
"""The one gate rule that has a judgement in it, kept pure so it can be tested.

Josh, 2026-09-16, by chips, after the gate made him hand-edit a pull request
description for the first time ever: keep the gate, but let Claude approve the
routine ones — "anything touching deploys, secrets, or keys still stops for me."

WHAT "ROUTINE" HAS TO MEAN, or the gate is worth nothing. The workflow files are
what runs by itself with the deploy keys attached, so the only change that may
pass unwatched is one that cannot reach any of that. This says yes to exactly
one shape: adding a step that runs an existing test. Every other edit to a
workflow — one removed line, one changed line, one `uses:`, one `${{ … }}`, a
schedule, a permission, anything naming a secret or a deploy — still stops for
Josh.

WIDENED 2026-09-18, on Josh's word: "widen the exemption so node test steps
pass." The first version only knew `npm run test`, and nothing in this repo is
run that way — every hub-world and hub-app check is `node <file>` or `bash
<file>`. So the exemption he ratified on 2026-09-16 could never once fire, and
the very first step added under it was held. `node <path>.test.mjs` now counts
as the same shape, on the same terms.

That is parity, not a loosening: `npm run test` already runs whatever
package.json says it does, which is arbitrary code under another name. What is
still refused is anything that could be something else wearing a test's clothes
— an argument after the path, a `..` climbing out of the repo, a shell
metacharacter, a file not named as a test.

Held on purpose, and one word from Josh widens either: `bash <file>` steps (he
said node), and node steps running a file not named `*.test.*` or `*.spec.*`
(a render check, a syntax check).

It is deliberately easier to widen later than to discover it was too loose. A
gate that lets through more than it should is worse than no gate, because it
reads as a safety net while not being one.
"""
import re

# A step that runs one of the repo's own checks. Anything else in an added line
# — a `uses:`, an expression, an env var, a shell block — is not this shape.
ALLOWED = [
    re.compile(r"^-?\s*name:\s*\S.*$"),
    re.compile(r"^working-directory:\s*[\w./-]+$"),
    re.compile(r"^run:\s*npm run (?:test|verify)[\w:-]*$"),
    # `node hub-world/tools/systems.test.mjs` — the shape every check in this repo
    # actually uses. A repo-relative path and NOTHING after it: no arguments, no
    # `..`, no shell metacharacter (none of them are in the character class), and
    # the file has to be named as a test. `node -e '…'`, `node x.test.mjs && curl`
    # and `node build.mjs` all fail this, which is the point.
    re.compile(r"^run:\s*node\s+(?!.*\.\.)[\w.-]+(?:/[\w.-]+)*\.(?:test|spec)\.[cm]?js$"),
]

# Words that mean the change can reach what Josh said still needs his eyes.
# Matched on the raw added line, before any shape check, so a name: that merely
# MENTIONS deploying is held too — the cost of that false hold is one line in a
# description; the cost of the opposite is a deploy nobody watched.
NEAR_THE_KEYS = re.compile(
    r"secrets\.|\$\{\{|token|password|deploy|flyctl|permissions|"
    r"\benv\b|\buses\b|\bif\b|\bon\b|schedule|cron|environment",
    re.I,
)


def workflow_change_is_routine(status_rows, diff_lines):
    """True when the workflow edits only ADD steps that run existing checks.

    `status_rows` is (status, path) for every file in the diff; `diff_lines` is
    the unified diff of the workflow files ONLY. Both come from git in
    review_gate.py, which keeps this function free of subprocess calls.
    """
    workflow_rows = [(s, p) for s, p in status_rows if p.startswith(".github/workflows/")]
    if not workflow_rows:
        return False                       # nothing to be routine about
    # A new, deleted or renamed workflow file is a new robot, not a new step.
    if any(not s.startswith("M") for s, _ in workflow_rows):
        return False

    added = []
    for line in diff_lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("-"):
            return False                   # nothing may be removed or rewritten
        if line.startswith("+"):
            added.append(line[1:])
    if not added:
        return False                       # a whitespace-only edit is not a test step

    saw_a_step = False
    for raw in added:
        text = raw.strip()
        if not text or text.startswith("#"):
            continue                       # blank lines and comments ride along
        if NEAR_THE_KEYS.search(raw):
            return False
        if not any(p.match(text) for p in ALLOWED):
            return False
        saw_a_step = True
    # Caught by its own test on the first run: an edit of nothing but comments
    # satisfied every rule above and came back routine. Harmless in itself, but
    # the exemption is meant to name ONE shape, and "no shape at all" is not it.
    # Whatever this change is, it is not a test step, so it waits.
    return saw_a_step
