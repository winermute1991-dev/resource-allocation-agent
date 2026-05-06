"""Main entry point. Run daily (cron / APScheduler / Airflow).

Usage:
    python run.py                    # print report to stdout
    DISCORD_WEBHOOK_URL=... python run.py    # also POST to Discord
    ANTHROPIC_API_KEY=... python run.py      # use LLM-driven path

Or put ANTHROPIC_API_KEY=... and DISCORD_WEBHOOK_URL=... into a .env file
in the same folder — it will be loaded automatically.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request

# Load .env if present (so users don't have to export env vars manually).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.data import generate_world
from src.agent import run_agent


def post_to_discord(text: str, webhook_url: str) -> None:
    """Discord limits messages to ~2000 chars; split on line boundaries."""
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.split("\n"):
        if cur_len + len(line) + 1 > 1900 and cur:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))

    for ch in chunks:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"content": ch}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Discord rejects requests without a User-Agent (returns 403).
                "User-Agent": "ResourceAllocationAgent/1.0 (+https://github.com/anthropics)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            resp.read()


def main() -> int:
    state = generate_world()
    report = run_agent(state, verbose="-v" in sys.argv)
    print(report)

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook:
        post_to_discord(report, webhook)
        print("\n[posted to Discord]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
