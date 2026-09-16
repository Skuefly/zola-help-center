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

BASE = os.environ["BASE_SHA"]
HEAD = os.environ["HEAD_SHA"]
BODY = os.environ.get("PR_BODY") or ""

# An override must name a reason. "Gate-approved:" with nothing after it does not count.
override = re.search(r"^Gate-approved:[ \t]*(\S.*)$", BODY, re.M)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


status = [ln.split("\t") for ln in git("diff", "--name-status", f"{BASE}...{HEAD}").splitlines() if ln]
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
if any(p.startswith(".github/workflows/") for p in paths):
    holds.append("Changes an automation workflow (what runs by itself, with the deploy keys).")

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

with open("gate-report.md", "w") as fh:
    fh.write(
        "**Review gate: held for Josh.**\n\n"
        f"{reasons}\n\n"
        "Nothing is wrong yet — this only means the change touches something that "
        "needs a human look. To let it through, add a line to this pull request's "
        "description:\n\n```\nGate-approved: <why this is fine>\n```\n"
    )
print(f"Gate: HELD.\n{reasons}")
sys.exit(1)
