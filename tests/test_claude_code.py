import json
from datetime import datetime, timedelta, timezone

from token_finops.adapters.claude_code import ClaudeCodeAdapter, five_hour_blocks, parse_transcript


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
    from token_finops.core.pricing import estimate_usd
    five_min = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000)
    one_hour = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000)
    assert abs(five_min - 2.5) < 1e-9 and abs(one_hour - 4.0) < 1e-9
