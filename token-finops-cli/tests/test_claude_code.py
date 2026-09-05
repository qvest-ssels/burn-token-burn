import json
from datetime import datetime, timedelta, timezone

from token_finops_cli.adapters.claude_code import ClaudeCodeAdapter, five_hour_blocks, parse_transcript


def _line(ts, msg_id, req_id, model="claude-sonnet-5", block="text", tool=None, agent=None,
          usage=None):
    content = [{"type": "text", "text": "hi"}] if block == "text" else \
        [{"type": "tool_use", "id": "toolu_1", "name": tool, "input": {}}]
    e = {
        "type": "assistant", "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "sessionId": "sess-1", "requestId": req_id, "uuid": f"u-{msg_id}-{block}",
        "isSidechain": bool(agent), "cwd": "/w",
        "message": {"id": msg_id, "model": model, "role": "assistant", "content": content,
                    "usage": usage or {"input_tokens": 5, "output_tokens": 50,
                                       "cache_read_input_tokens": 20_000,
                                       "cache_creation_input_tokens": 1_000,
                                       "cache_creation": {"ephemeral_1h_input_tokens": 1_000,
                                                          "ephemeral_5m_input_tokens": 0}}},
    }
    if agent:
        e["agentId"] = agent
    return json.dumps(e)


def _write(root, now):
    proj = root / "-home-x"
    (proj / "sess-1" / "subagents").mkdir(parents=True)
    main = proj / "sess-1.jsonl"
    lines = [
        _line(now, "m1", "r1", block="text"),
        _line(now, "m1", "r1", block="tool", tool="Bash"),        # duplicate of m1 (2nd content block)
        _line(now + timedelta(minutes=1), "m2", "r2", block="tool", tool="WebSearch"),
        '{"type":"user","message":{"role":"user","content":"x"}}',
        "not json",
    ]
    main.write_text("\n".join(lines) + "\n")
    sub = proj / "sess-1" / "subagents" / "agent-abc.jsonl"
    sub.write_text(_line(now + timedelta(minutes=2), "m3", "r3", model="claude-haiku-4-5",
                         block="text", agent="abc") + "\n")
    return main, sub


def test_dedup_and_tool_merge(tmp_path):
    now = datetime(2026, 9, 15, 10, 30, tzinfo=timezone.utc)
    main, _ = _write(tmp_path, now)
    events = list(parse_transcript(str(main)))
    assert len(events) == 2                      # m1 (2 lines) + m2
    m1 = next(e for e in events if e.event_id.startswith("m1"))
    assert m1.tags["first_tool"] == "Bash"       # picked up from the second line
    assert m1.cache_read_tokens == 20_000 and m1.cache_write_tokens == 1_000
    assert m1.usd_estimate is not None and m1.usd_estimate > 0


def test_subagents_and_models(tmp_path):
    now = datetime(2026, 9, 15, 10, 30, tzinfo=timezone.utc)
    _write(tmp_path, now)
    ad = ClaudeCodeAdapter(str(tmp_path))
    events = ad.events()
    assert len(events) == 3
    sub = [e for e in events if e.agent_id]
    assert len(sub) == 1 and sub[0].model_norm == "claude-haiku-4-5" and sub[0].initiator == "agent"
    assert sub[0].session_id == "sess-1"


def test_five_hour_blocks(tmp_path):
    now = datetime(2026, 9, 15, 10, 30, tzinfo=timezone.utc)
    _write(tmp_path, now)
    events = ClaudeCodeAdapter(str(tmp_path)).events()
    late = events[0].__class__(**{**events[0].__dict__, "ts_utc": now + timedelta(hours=7)})
    blocks = five_hour_blocks(events + [late])
    assert len(blocks) == 2
    assert blocks[0]["start"] == now.replace(minute=0)


def test_one_hour_cache_write_priced_at_2x(tmp_path):
    from token_finops_cli.core.pricing import estimate_usd
    five_min = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000)
    one_hour = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000)
    assert abs(five_min - 2.5) < 1e-9 and abs(one_hour - 4.0) < 1e-9


def test_parse_transcript_skips_bad_json_and_bad_timestamps(tmp_path):
    from conftest import NOW, transcript_line

    p = tmp_path / "s.jsonl"
    good = transcript_line(NOW, "m1", "r1")
    bad_ts = json.loads(transcript_line(NOW, "m2", "r2"))
    bad_ts["timestamp"] = "yesterday-ish"
    no_id = json.loads(transcript_line(NOW, "m3", "r3"))
    del no_id["message"]["id"]
    no_id["uuid"] = "uuid-3"
    p.write_text("\n".join([good, '{"broken json', json.dumps(bad_ts), json.dumps(no_id), json.dumps(no_id)]) + "\n")
    events = list(parse_transcript(str(p)))
    assert [e.event_id for e in events] == ["m1:r1", "uuid-3:None"]     # uuid fallback key, deduped


def test_parse_transcript_since_and_agent_file_outside_subagents(tmp_path):
    from conftest import NOW, transcript_line

    sess = tmp_path / "sess-9"
    sess.mkdir()
    p = sess / "agent-zed.jsonl"
    line = json.loads(transcript_line(NOW, "m1", "r1"))
    del line["sessionId"]
    p.write_text(json.dumps(line) + "\n" + transcript_line(NOW - timedelta(days=3), "m0", "r0") + "\n")
    events = list(parse_transcript(str(p), since=NOW - timedelta(days=1)))
    assert len(events) == 1
    assert events[0].agent_id == "zed" and events[0].session_id == "sess-9" and events[0].initiator == "agent"


def test_default_policy_and_root(monkeypatch, tmp_path):
    from token_finops_cli.core.model import CycleKind, Unit

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    ad = ClaudeCodeAdapter()
    assert ad.root == str(tmp_path / "cfg" / "projects") and not ad.available()
    p = ad.default_policy()
    assert (p.unit, p.cycle, p.window_length, p.allowance, p.source_of_truth, p.window_id) == \
        (Unit.PERCENT, CycleKind.ROLLING, timedelta(hours=5), 1.0, "provider_pct", "5h")
    assert ad.default_policy(0.5).allowance == 0.5
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ClaudeCodeAdapter().root == str(tmp_path / ".claude" / "projects")


def test_five_hour_blocks_gap_rule_and_totals(tmp_path):
    from conftest import NOW, make_event

    # 10:30 starts block A [10:00, 15:00). 14:59 is inside; 16:00 is past the end -> block B.
    # 20:30 is within B's [16:00, 21:00) but 4.5h after the last event -> stays; 21:30 opens C.
    t0 = NOW.replace(hour=10, minute=30)
    evs = [make_event(0, now=t0, model="claude-sonnet-5", usd=1.0, inp=10, out=0),
           make_event(0, now=t0.replace(hour=14, minute=59), model="claude-haiku-4-5", usd=0.5, inp=5, out=0),
           make_event(0, now=t0.replace(hour=16, minute=0), usd=None, inp=1, out=0),
           make_event(0, now=t0.replace(hour=20, minute=30), usd=2.0, inp=1, out=0),
           make_event(0, now=t0.replace(hour=21, minute=30), usd=2.0, inp=1, out=0)]
    blocks = five_hour_blocks(evs)
    assert [(b["start"].hour, b["end"].hour) for b in blocks] == [(10, 15), (16, 21), (21, 2)]
    a = blocks[0]
    assert a["usd"] == 1.5 and a["tokens"] == 15 and a["models"] == {"claude-sonnet-5": 1, "claude-haiku-4-5": 1}
    assert blocks[1]["usd"] == 2.0 and len(blocks[1]["events"]) == 2
    assert five_hour_blocks([]) == []
    # a gap >= 5h inside a block boundary still splits: 10:30 then 15:00 sharp
    split = five_hour_blocks([evs[0], make_event(0, now=t0.replace(hour=15, minute=0), inp=1, out=0)])
    assert len(split) == 2
