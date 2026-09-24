# `budget-check` — a CI guardrail for coding-agent spend

A reusable composite GitHub Action that turns `token-finops` from a personal dashboard into a
team guardrail: it comments on a pull request (and optionally fails the job) when a coding-agent
session's exported usage exceeds a configured USD budget.

## What this does — and does not — check

`token-finops` reads *local* telemetry (`~/.claude/projects/`, `~/.copilot/session-store.db`,
etc.) that only exists on the machine where an agentic coding session actually ran. It does not
exist on a GitHub Actions runner unless something put it there first. So this action **does not**
run `token-finops report` cold on the runner and hope for real data — that would silently report
"no usage" on every run and teach people to ignore it.

Instead, this action reads a **JSON file that was already produced by a real session**, one of:

- `token-finops self-audit --json` — the total API-equivalent cost of one Claude Code session
  (main loop + sub-agents), keyed by model. This is the natural fit for "did this PR's
  agent session blow the budget?" and is the primary supported shape.
- `token-finops report --json` — a list of per-tool runway objects. Only rows whose `unit` is
  `usd` contribute to the budget total; rows priced in `percent`/`aiu`/`requests` (e.g. Copilot)
  are listed in the comment for context but not summed into a dollar figure, because they aren't
  one.

The action's job is strictly: **read the exported number, compare it to a threshold, report the
result.** It does no telemetry discovery of its own.

## Getting the usage JSON onto the runner

Three realistic ways, roughly in order of how much process they assume a team already has:

1. **Committed alongside the PR.** If your workflow already asks contributors (human or agent)
   to run `self-audit` and paste the result — this repo's own
   [`.github/PULL_REQUEST_TEMPLATE.md`](../../../.github/PULL_REQUEST_TEMPLATE.md) has a
   collapsed `<details>` block for exactly this — have the agent also save
   `token-finops self-audit --json > self-audit.json` and commit it (or a CI step extracts the
   fenced block from the PR body into a file). This keeps the artifact human-reviewable in the
   diff.
2. **Uploaded as a build artifact by an earlier job.** A local pre-push hook, a scheduled job, or
   the agent's own tooling runs `token-finops self-audit --json > self-audit.json` and uploads it
   with `actions/upload-artifact`; this workflow downloads it with `actions/download-artifact`
   before calling this action. Best fit for teams that already run agent sessions inside CI-adjacent
   automation rather than purely on a laptop.
3. **A path already present in the checked-out branch.** Some teams keep a
   `.token-finops/last-session.json` file in the repo (gitignored except for this one export) that
   a local git hook refreshes. Simplest to wire, weakest guarantee that it's fresh.

Parsing the PR *description* for an embedded JSON block directly (rather than a separate file) was
considered and rejected for the default flow: it works, but couples this action's parser to GitHub's
comment-body quoting/escaping and to whichever heading a team happens to use, and makes the
"malformed input" failure mode (empty diff, four-space vs fence indentation) far more common than
just shipping a file. If your team wants that convention anyway, add one cheap step before this
action that extracts the fenced block from `${{ github.event.pull_request.body }}` into a file and
point `usage-json-path` at it — the action itself stays decoupled from that choice.

## Inputs

| Input | Required | Default | Meaning |
|---|---|---|---|
| `usage-json-path` | yes | — | Path to a `self-audit --json` or `report --json` file already in the workspace. |
| `budget-usd` | yes | — | Budget threshold in USD. |
| `fail-on-exceed` | no | `"false"` | Fail the job when over budget. Default is comment-only — see "Why comment-only by default" below. |
| `comment-on-pr` | no | `"true"` | Post/update a PR comment with the result (only on `pull_request` events). |
| `github-token` | no | `${{ github.token }}` | Token used to post the comment. |

## Outputs

| Output | Meaning |
|---|---|
| `over-budget` | `"true"` or `"false"` |
| `total-usd` | Computed usage total in USD |
| `budget-usd` | Echo of the configured budget |

## Why comment-only by default

This is an *API-equivalent estimate* derived from local telemetry, priced at pay-per-token list
rates even when the session ran on a flat-rate subscription (see the main README's "API-equivalent"
framing). Hard-blocking a merge on an estimate is a strong claim to make by default. Set
`fail-on-exceed: "true"` explicitly once your team has watched the comment-only signal for a while
and trusts it enough to gate on.

## Example: comment-only, using a committed self-audit export

```yaml
name: Agent budget check

on:
  pull_request:

jobs:
  budget-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check agent session budget
        uses: qvest-ssels/burn-token-burn/.github/actions/budget-check@main
        with:
          usage-json-path: self-audit.json
          budget-usd: "25"
```

This assumes the PR branch includes a `self-audit.json` produced by
`token-finops self-audit --json > self-audit.json` before the PR was opened.

## Example: artifact handoff + hard fail

```yaml
name: Agent budget check

on:
  pull_request:

jobs:
  budget-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download session usage artifact
        uses: actions/download-artifact@v4
        with:
          name: agent-usage
          path: .

      - name: Check agent session budget
        uses: qvest-ssels/burn-token-burn/.github/actions/budget-check@main
        with:
          usage-json-path: agent-usage.json
          budget-usd: "50"
          fail-on-exceed: "true"
```

Here `agent-usage.json` (either shape) was uploaded by whatever ran the agent session — a
scheduled job, a pre-push hook, or a self-hosted runner with real telemetry on disk — via
`actions/upload-artifact` earlier in the pipeline.

## Verification performed

There is no way to exercise a composite Action end-to-end without a real workflow run in a real
repository, so that was **not** done. What was verified locally:

- `action.yml` and the example workflow YAML above parse as valid YAML (`python3 -c
  "import yaml, sys; yaml.safe_load(open(sys.argv[1]))"`, and the same for a full example
  workflow file).
- `check_budget.py`'s logic was exercised directly (`python3 check_budget.py --usage-json ...
  --budget-usd ...`) against synthetic fixtures shaped like real `self-audit --json` and
  `report --json` output, covering both an under-budget and an over-budget case for each shape,
  plus a malformed-JSON case and an unrecognised-shape case (both exit 2 as designed).
- A real GitHub Actions run — including the `actions/github-script` comment step and the
  `fail-on-exceed` job-failure path — was **not** exercised.
