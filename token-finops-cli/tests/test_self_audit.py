"""`token-finops self-audit` against a synthetic CLAUDE_CONFIG_DIR: dedup,
sub-agent attribution, activity buckets, 5h blocks and the JSON shape."""
from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from conftest import NOW, build_claude_tree, transcript_line, write_transcript

from token_finops_cli.cli import BUCKETS, _bucket


@pytest.fixture
def tree(home):
    cfg = home / ".claude"
    expected = build_claude_tree(cfg, NOW)
    expected["cfg"] = cfg
    return expected


def _row(lines, prefix):
    return next(ln for ln in lines if ln.strip().startswith(prefix))


# --------------------------------------------------------------------------- #
# bucketing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool, bucket", [
    ("Bash", "File & shell ops"), ("Read", "File & shell ops"), ("Edit", "File & shell ops"),
    ("NotebookEdit", "File & shell ops"), ("WebSearch", "Web research"), ("WebFetch", "Web research"),
    ("mcp__github__list_issues", "Connectors (MCP)"), ("mcp__claude-in-chrome__navigate", "Claude in Chrome"),
    ("Agent", "Sub-agent launches"), ("TodoWrite", "Other tools"), ("", "Text / reasoning"),
])
def test_bucket(tool, bucket):
    assert _bucket(tool) == bucket


def test_buckets_are_exhaustive_and_ordered():
    names = [n for n, _ in BUCKETS]
    assert names.index("Claude in Chrome") < names.index("Connectors (MCP)")   # specific before generic
    assert names[-1] == "Text / reasoning"


# --------------------------------------------------------------------------- #
# text report
# --------------------------------------------------------------------------- #
def test_self_audit_latest_session_text(tree, run_cli):
    out = run_cli("self-audit", "--config-dir", str(tree["cfg"]))
    lines = out.splitlines()
    assert lines[0] == "Self-audit: Claude Code session sess-1"
    assert lines[1] == "  span: 2026-09-15 12:00 UTC -> 2026-09-15 19:00 UTC"
    assert lines[2] == "  API calls (deduplicated): 11  = main loop 8 + sub-agents 3"

    # by-model table: sonnet (main + 1 sub) and haiku (2 sub calls)
    header_idx = lines.index("By model (the thing that actually decides the bill):")
    table = lines[header_idx + 1:header_idx + 4]
    assert table[0].split()[:2] == ["model", "calls"]
    models = {ln.split()[0]: int(ln.split()[1]) for ln in table[1:]}
    assert models == {"claude-sonnet-5": 9, "claude-haiku-4-5": 2}
    assert table[1].startswith("  claude-sonnet-5")             # sorted by USD, biggest first

    # sub-agent section
    assert "Sub-agents:" in lines
    sonnet_row = _row(lines, "sonnet1")
    haiku_row = _row(lines, "haiku1")
    assert sonnet_row.split()[1:3] == ["claude-sonnet-5", "1"]
    assert haiku_row.split()[1:3] == ["claude-haiku-4-5", "2"]
    assert lines.index(sonnet_row) < lines.index(haiku_row)      # by USD desc
    share = _row(lines, "sub-agents = ")
    pct = int(re.search(r"= (\d+)% of", share).group(1))
    assert 0 < pct < 100

    # activity buckets over the main loop only
    act_idx = lines.index("By activity (main loop, bucketed by the first tool called in each turn):")
    rows = {}
    for ln in lines[act_idx + 2:]:
        if not ln.startswith("  ") or ln.startswith("  activity"):
            break
        name = ln[:24].strip()
        rows[name] = int(ln[24:].split()[0])
    assert rows == tree["buckets"]
    shares = [int(m.group(1)) for m in re.finditer(r"(\d+)%$", "\n".join(lines[act_idx + 2:act_idx + 10]), re.M)]
    assert 98 <= sum(shares) <= 102

    # 5h blocks: 12:00 and 19:00 fall into two blocks
    assert "5-hour billing blocks touched: 2" in lines
    blocks = [ln for ln in lines if re.match(r"  2026-09-15 \d\d:00 -> \d\d:00 UTC", ln)]
    assert blocks[0].startswith("  2026-09-15 12:00 -> 17:00 UTC  calls   10")
    assert blocks[1].startswith("  2026-09-15 19:00 -> 00:00 UTC  calls    1")
    assert "reviewed 20" in lines[-1] and lines[-1].startswith("Note: 'API-equivalent'")


def test_self_audit_bucket_percentages_use_usd(tree, run_cli):
    out = run_cli("self-audit", "--config-dir", str(tree["cfg"]))
    lines = out.splitlines()
    start = lines.index("By activity (main loop, bucketed by the first tool called in each turn):") + 2
    shares = {}
    for ln in lines[start:]:
        if not ln.startswith("  "):
            break
        shares[ln[:24].strip()] = int(ln.rstrip("%").split()[-1])
    # the text turn had 10x the output tokens of any other single turn, so among the
    # one-turn buckets it carries the largest share; rows are sorted by USD desc
    one_turn = {k: v for k, v in shares.items() if k != "File & shell ops"}
    assert one_turn["Text / reasoning"] == max(one_turn.values())
    assert list(shares.values()) == sorted(shares.values(), reverse=True)


def test_self_audit_session_prefix_and_unknown(tree, run_cli, home):
    # add a second, older session so "latest" and the prefix matter
    cfg = tree["cfg"]
    write_transcript(cfg / "projects" / "-home-x" / "older.jsonl", [
        transcript_line(NOW - timedelta(days=2), "o1", "or1", session="older", tool="Bash"),
    ])
    out = run_cli("self-audit", "--config-dir", str(cfg), "--session", "old")
    assert out.startswith("Self-audit: Claude Code session older")
    assert "API calls (deduplicated): 1  = main loop 1 + sub-agents 0" in out
    assert "Sub-agents:" not in out
    assert "5-hour billing blocks touched: 1" in out

    out = run_cli("self-audit", "--config-dir", str(cfg), "--session", "latest")
    assert out.startswith("Self-audit: Claude Code session sess-1")
    out = run_cli("self-audit", "--config-dir", str(cfg))
    assert out.startswith("Self-audit: Claude Code session sess-1")

    out = run_cli("self-audit", "--config-dir", str(cfg), "--session", "nope")
    assert out.startswith("No session starting with 'nope'. Known: older, sess-1")


def test_self_audit_json(tree, run_cli):
    out = run_cli("self-audit", "--config-dir", str(tree["cfg"]), "--json")
    data = json.loads(out)
    assert set(data) == {"session", "calls", "main", "subagents", "by_model"}
    assert (data["session"], data["calls"], data["main"], data["subagents"]) == ("sess-1", 11, 8, 3)
    assert set(data["by_model"]) == {"claude-sonnet-5", "claude-haiku-4-5"}
    sonnet = data["by_model"]["claude-sonnet-5"]
    assert set(sonnet) == {"calls", "input", "output", "cache_read", "cache_write", "reasoning", "usd", "usd_known"}
    assert sonnet["calls"] == 9 and sonnet["usd_known"] == 9 and sonnet["usd"] > data["by_model"]["claude-haiku-4-5"]["usd"]


def test_self_audit_uses_config_dir_env(tree, run_cli, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tree["cfg"]))
    out = run_cli("self-audit")
    assert out.startswith("Self-audit: Claude Code session sess-1")


def test_self_audit_missing_and_empty_trees(home, run_cli):
    out = run_cli("self-audit", "--config-dir", str(home / "nothing"))
    assert out.startswith("No Claude Code transcripts under ")
    assert out.rstrip().endswith("nothing/projects")
    empty = home / "empty" / "projects" / "p"
    empty.mkdir(parents=True)
    (empty / "s.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    assert run_cli("self-audit", "--config-dir", str(home / "empty")) == "No usage events found.\n"


def test_self_audit_without_usd_still_renders(home, run_cli):
    cfg = home / ".claude"
    write_transcript(cfg / "projects" / "p" / "s.jsonl", [
        transcript_line(NOW, "m1", "r1", model="ollama/qwen3:latest", tool="Bash", session="s"),
    ])
    out = run_cli("self-audit", "--config-dir", str(cfg))
    assert "  ollama/qwen3:latest" in out
    assert "File & shell ops" in out and "0%" in out
