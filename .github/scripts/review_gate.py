#!/usr/bin/env python3
"""The review gate's rules. Run by .github/workflows/review-gate.yml on every PR.

Each rule below is something Josh has already written down as needing his eyes.
The gate does not invent policy — it enforces what the workspace rules say.

Exit 0 = clear. Exit 1 = held, with the reasons written to gate-report.md.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_rules import workflow_change_is_routine  # noqa: E402

EVENT_BASE = os.environ["BASE_SHA"]
HEAD = os.environ["HEAD_SHA"]
BODY = os.environ.get("PR_BODY") or ""
# The base branch's name as GitHub reports it NOW (the workflow asks the API just
# before running this), not the one frozen into the event. Empty if that ask failed.
BASE_REF = (os.environ.get("BASE_REF") or "").strip()

# An override must name a reason. "Gate-approved:" with nothing after it does not count.
override = re.search(r"^Gate-approved:[ \t]*(\S.*)$", BODY, re.M)


# UNREADABLE BYTES ARE REPLACED, NEVER FATAL (2026-09-23, tripletail-legal #28). A diff
# carrying a byte that is not UTF-8 (a PDF drawing set, a Windows-1252 quote mark)
# crashed this script, and a crash counts as held — so Josh's approval line was read
# and still could not release the change. Replacing the byte cannot hide a rule
# match: the rules look at file paths and ASCII keywords, never at those bytes.
def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


# WHAT "THIS PULL REQUEST'S CHANGES" ARE MEASURED AGAINST (2026-09-19, PR #910).
#
# Every diff below is `BASE...HEAD`: what HEAD adds since it split from BASE. BASE
# used to be the event's base.sha, a snapshot taken when the event fired. #910 was
# stacked on #908's branch; after #908 merged, #910 was rebased onto main and
# force-pushed, then retargeted two seconds later. The push's run still carried
# the old branch's tip, whose split point with the rebased HEAD was an older
# main, so every PR merged since (#907's proxy write among them) read as #910's
# own lines. Rule 4 held it for code it did not contain, and that run finished
# last, so its hold overwrote three correct clears.
#
# So BASE is now the CURRENT tip of the branch the PR merges into right now,
# fetched fresh. Fetching the event's base.ref would not have been enough: the old
# stacked branch still exists, untouched, so a fresh fetch of it reproduces the
# same stale split point. Only the PR's live base names the right branch.
#
# If that cannot be read, the event's snapshot is the fallback. It can only
# over-hold (an older split point sweeps in MORE lines, never fewer), so a
# failure here costs Josh a false hold, never a missed one.
def current_base():
    if BASE_REF:
        try:
            git("fetch", "--quiet", "--no-tags", "origin",
                f"+refs/heads/{BASE_REF}:refs/remotes/origin/{BASE_REF}")
            tip = git("rev-parse", "--verify", f"refs/remotes/origin/{BASE_REF}^{{commit}}").strip()
            print(f"Gate: comparing against {BASE_REF} as it is now ({tip[:8]}).")
            return tip
        except subprocess.CalledProcessError as err:
            print(f"Gate: could not fetch {BASE_REF} ({(err.stderr or '').strip()}); "
                  "falling back to the event's base.")
    print(f"Gate: comparing against the event's base snapshot ({EVENT_BASE[:8]}).")
    return EVENT_BASE


BASE = current_base()

status = [ln.split("\t") for ln in git("diff", "--name-status", f"{BASE}...{HEAD}").splitlines() if ln]
status_rows = [(row[0], row[-1]) for row in status]
added_lines = [
    ln[1:] for ln in git("diff", "--unified=0", f"{BASE}...{HEAD}").splitlines()
    if ln.startswith("+") and not ln.startswith("+++")
]
paths = [row[-1] for row in status]
deleted = [row[-1] for row in status if row[0].startswith("D")]

holds = []
never_override = False  # a pasted credential is never fine, whatever reason is given

# 1. Secrets. Real credentials, not the placeholder shapes the repos use in examples.
SECRETS = [
    (r"shpat_[A-Za-z0-9]{20,}", "a Shopify admin token"),
    (r"shpss_[A-Za-z0-9]{20,}", "a Shopify secret"),
    (r"\bFlyV1 [A-Za-z0-9_\-]{20,}", "a Fly deploy token"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "a GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "an AWS key"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "a private key"),
    (r"postgres(?:ql)?://[^\s:@/]+:[^\s:@/]+@(?!host|localhost)", "a live database password"),
]
PLACEHOLDER = re.compile(r"x{6,}|\.\.\.|xxx|PASSWORD|YOUR_|EXAMPLE|<[a-z]+>", re.I)
for line in added_lines:
    if PLACEHOLDER.search(line):
        continue
    for pattern, what in SECRETS:
        if re.search(pattern, line):
            holds.append(f"Looks like {what} was pasted into the code.")
            never_override = True
            break

# 2. Anything that changes how the robots run. Workflow edits change what can
#    deploy, unattended, with the deploy keys attached.
#
#    ONE SHAPE IS NOW EXEMPT (Josh, 2026-09-16, by chips): a step that only runs
#    an existing test. He kept the gate but asked that the routine ones stop
#    costing him a hand-edit — "anything touching deploys, secrets, or keys
#    still stops for me". `workflow_change_is_routine` is where that line is
#    drawn, and it is deliberately narrow; see gate_rules.py.
if any(p.startswith(".github/workflows/") for p in paths):
    workflow_diff = git("diff", "--unified=0", f"{BASE}...{HEAD}", "--", ".github/workflows/").splitlines()
    if not workflow_change_is_routine(status_rows, workflow_diff):
        holds.append("Changes an automation workflow (what runs by itself, with the deploy keys).")

# 2b. THE GATE'S OWN RULES ALWAYS STOP. Rule 2 lets Claude approve a narrow
#     class of workflow change on its own; that is only safe while Claude
#     cannot also widen what "narrow" means. A gate whose keeper can edit the
#     lock is not a gate, so every edit to these files waits for Josh —
#     including the one that introduced this rule.
#
#     block-gate-approval.sh joined them on 2026-09-18 (Josh, by chips). It is the
#     hook that stops a session writing Josh's approval line at all, so it enforces
#     the gate exactly as much as the two rule files do — and until that day a
#     session could weaken it without anyone approving, which this pull request
#     itself demonstrated by sailing through untouched.
#
#     NOT held, and deliberately: .claude/settings.json, which WIRES that hook to the
#     tools. Removing the matcher there disables the lock without touching the script,
#     so this is a real remaining gap — it is left open because that file also carries
#     every permission rule, and holding it would put an approval in front of routine
#     tooling changes. Josh's call if the trade ever looks wrong.
if any(p in (".github/scripts/review_gate.py",
             ".github/scripts/gate_rules.py",
             ".github/scripts/block-gate-approval.sh") for p in paths):
    holds.append("Changes the review gate's own rules (what Claude may approve without you).")

# 3. Mass deletion. Big removals are the one mistake that is expensive to undo.
if len(deleted) > 25:
    holds.append(f"Deletes {len(deleted)} files.")

# 4. Store writes. The standing rule is no write without a read first, and the
#    proxy is meant to be closed unless a named job needs it.
STORE_WRITE = re.compile(
    r"ALLOW_MUTATIONS\s*[=:]\s*[\"']?1|"
    r"\bmutation\s+\w*(?:product|variant|order|draftOrder|inventory|price|customer)",
    re.I,
)
if any(STORE_WRITE.search(line) for line in added_lines):
    holds.append("Adds code that can write to a live Shopify store.")

# 5. Rulebook drift. The synced block has one master; editing a copy gets silently
#    overwritten by the next sync, so the change would look applied and not be.
#    Compare only the block itself — ordinary edits elsewhere in a CLAUDE.md are fine.
#    Compared against the MERGE BASE, not the event's base.sha: GitHub hands the
#    gate a snapshot of the base branch that can be many commits stale, and a
#    style sync that arrived through main then reads as an edit made in the PR.
#    That exact false hold happened on PR #90.
MERGE_BASE = git("merge-base", BASE, HEAD).strip()
BLOCK = re.compile(
    r"<!-- BEGIN workspace-response-style.*?<!-- END workspace-response-style -->",
    re.S,
)


def block_of(ref, path):
    try:
        found = BLOCK.search(git("show", f"{ref}:{path}"))
    except subprocess.CalledProcessError:
        return None                       # file did not exist at that ref
    return found.group(0) if found else None


# A real sync run edits the master too; that is the sanctioned way to change it.
syncing_master = "response-style.md" in paths
for path in [p for p in paths if p.endswith("CLAUDE.md")] if not syncing_master else []:
    if block_of(MERGE_BASE, path) != block_of(HEAD, path):
        holds.append(
            f"Edits the shared house-style block inside {path}. That block has one "
            "master (skuefly-shared/response-style.md) and the next sync overwrites "
            "anything changed here, so the edit would look applied and not be."
        )
        break

# 6. Theme changes on a stale mirror. This is the one that has actually cost Josh hours,
#    more than once: the team edits the theme live, a session edits the repo copy and
#    pushes, and the deploy silently overwrites their work. Shopify keeps no history of
#    what was overwritten. The rule is reconcile-before-change; this is what enforces it.
#    Match Shopify theme layout, not app folders that happen to share a name. A Remix app's
#    app/templates/ or config/ must never trip this — a gate that cries wolf gets switched off.
THEME_DIRS = ("templates/", "sections/", "snippets/", "layout/", "assets/", "config/", "locales/")
theme_files = [
    p for p in paths
    if p.endswith(".liquid")                       # only themes use .liquid
    or (p.startswith(THEME_DIRS) and p.endswith((".json", ".css", ".js")))
]
if theme_files:
    # The PR must show, in its own words, that live was pulled and diffed THIS change —
    # not last week, not "it looked fine". Git cannot see edits made in Shopify's editor.
    reconciled = re.search(r"^Reconciled-with-live:[ \t]*(\S.*)$", BODY, re.M)
    if not reconciled:
        holds.append(
            f"Changes {len(theme_files)} theme file(s) without showing that the live theme "
            "was pulled and compared first. The saved copy drifts the moment anyone edits "
            "in Shopify's Theme Editor, and deploying over the team's live work cannot be "
            "undone. Pull live, diff it, then add a line to this description:\n"
            "  `Reconciled-with-live: <what you pulled and what differed>`"
        )

if not holds:
    print("Gate: clear.")
    sys.exit(0)

reasons = "\n".join(f"- {h}" for h in dict.fromkeys(holds))

if override and not never_override:
    with open("gate-report.md", "w") as fh:
        fh.write(f"**Review gate: let through on a named reason.**\n\n{reasons}\n\n"
                 f"Reason given: {override.group(1).strip()}\n")
    print(f"Gate: held then released.\n{reasons}\nReason: {override.group(1).strip()}")
    sys.exit(0)

# WHAT THIS COMMENT MAY SAY (Josh, 2026-09-18). It used to tell him to edit this pull
# request's description, and sessions read that and sent him to GitHub to do it — twice in
# two days, months after the Approve button in Hub World made that unnecessary. His words:
# "I will never open a GitHub repo like that 830, hit edit, and make changes there... Never
# ask me to do that again in any session ever." So the hold names his own button and nothing
# else. The raw line stays documented for the machine that writes it (approveGate() in
# hub-world/tools/serve.mjs) and for a human reading the history — never as an instruction.
with open("gate-report.md", "w") as fh:
    fh.write(
        "**Review gate: held for Josh.**\n\n"
        f"{reasons}\n\n"
        "Nothing is wrong yet — this only means the change touches something that "
        "needs a human look.\n\n"
        "**To let it through: open Hub World, then Josh ▾ → Approve a held change.** "
        "One press, on your own Mac. Nothing to edit here.\n"
    )
print(f"Gate: HELD.\n{reasons}")
sys.exit(1)
