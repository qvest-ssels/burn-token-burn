# 00 — Why This Guide Exists

A retail client's engineering team had a shared GitHub Copilot seat pool. One morning, requests started failing for everyone — not with an error that said "budget exhausted," but with a generic failure that took an hour of Slack messages to diagnose. Someone had run a long agentic loop overnight, burned through the team's monthly AI credits, and the reset was three weeks away. Nobody could prove who did it, because the only visibility anyone had was a single aggregate number on an admin dashboard, refreshed once a day, with no per-user breakdown. The team lost velocity for three weeks, and the retro produced exactly one actionable finding: nobody had been watching the meter, because nobody could.

That incident is the reason this repository exists. Not because token spend is inherently interesting, but because the tooling around it is bad enough that a team can lose three weeks of productivity to a problem that a $20 monitoring script would have caught on day one.

## Why individual visibility is hard, and why it matters anyway

Modern coding agents don't run as one clean conversation. They spawn sub-agents — for research, for parallel file edits, for review passes — and those sub-agents burn tokens against the same shared budget as the main session, often on a different, more expensive model. Attribution gets murky fast: was that spike "the developer" or "the three research sub-agents their agent launched without asking"? Most tools don't even record sub-agent transcripts in a place you can find, let alone attribute them to the human who kicked off the run.

That murkiness matters for a mundane reason: a $500/month Fable- or Opus-tier license used daily is worth defending, and a hard rate limit that hits at 2pm instead of running out gracefully at midnight is a lost afternoon, not an abstract inefficiency. If you can't see your own burn rate against your own reset clock, you find out you're over budget the same way the retail client did — from a failure message, not a dashboard. Runway — burn rate vs. time left in the cycle — is the single number that turns "something feels expensive" into "you have 1.9 hours left in this window, slow down or switch models."

## What this guide is

This is a practitioner's guide to where token spend actually goes when you use AI coding agents daily, written from the inside of a repository that measures itself. Every number attributed to "our own session" in the chapters that follow comes from `token-finops self-audit` run against the transcript of the session that built this tool — cache-read shares, model-cost splits, sub-agent overhead, the works. It is opinionated: we tell you what we'd do differently now, not just what happened.

## What this guide is not

It is not a catalogue of monitoring tools. Two good, actively maintained lists already do that job — [QuesmaOrg/awesome-ai-tokenomics](https://github.com/QuesmaOrg/awesome-ai-tokenomics) (190+ entries: dashboards, eBPF, OTEL, caching, context engineering) and [pleasedodisturb/awesome-llm-token-optimization](https://github.com/pleasedodisturb/awesome-llm-token-optimization) (cost-tracking tools, optimization papers). We send our own tool's PR to both rather than starting a third list. If you're looking for "which dashboard should I install," go there first; this guide covers `docs/landscape.md` only for the narrow niche this repo actually fills — local, per-agent quota/runway tracking — and points elsewhere for everything else.

What follows is six chapters: what a token costs and why the price is intentionally hard to compare (01), where the money actually goes inside a real session (02), how to route work to cheaper models without hurting output quality (03), when running a model on your own hardware beats the cloud — and, more often, when it doesn't (04), and how to govern a team's spend without either a blind pool or a productivity-killing hard stop (05).
