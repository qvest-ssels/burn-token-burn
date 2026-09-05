"""Build a synthetic Copilot session-store.db, for demos and tests.

Creates a throwaway SQLite database with only the columns the CLI's
queries actually reference (see cli.py's SQL) - it doesn't need to match
GitHub's real internal schema exactly, just provide those columns with
plausible fake data so the tool can be demonstrated/tested without ever
touching a real ~/.copilot/session-store.db.
"""
import random
import sqlite3
from datetime import datetime, timedelta, timezone


def build_synthetic_db(path, days=14, events_per_day=8, seed=42):
    rng = random.Random(seed)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE assistant_usage_events (
            session_id TEXT,
            created_at TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            reasoning_tokens INTEGER,
            duration_ms REAL,
            total_nano_aiu INTEGER
        )
        """
    )

    now = datetime.now(timezone.utc)
    rows = []
    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        session_id = f"demo-session-{day_offset // 3}"
        for _ in range(events_per_day):
            ts = day - timedelta(minutes=rng.randint(0, 1439))
            input_tokens = rng.randint(200, 4000)
            output_tokens = rng.randint(100, 2500)
            reasoning_tokens = rng.randint(0, 800)
            duration_ms = rng.uniform(800, 15000)
            # Roughly proportional to tokens, in "nano AI units".
            total_nano_aiu = int(
                (input_tokens + output_tokens) * rng.uniform(150_000_000, 400_000_000)
            )
            rows.append((
                session_id, ts.isoformat(), input_tokens, output_tokens,
                reasoning_tokens, duration_ms, total_nano_aiu,
            ))

    cur.executemany(
        """
        INSERT INTO assistant_usage_events
        (session_id, created_at, input_tokens, output_tokens,
         reasoning_tokens, duration_ms, total_nano_aiu)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    con.close()
    return len(rows)
