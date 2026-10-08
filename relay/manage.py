"""Edit assignments and export stacked rows. Uses relay/.env, not the RA .env.

Examples:
  python manage.py add s014 ai ac_high
  python manage.py list
  python manage.py export
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from stack_logic import MESSAGE_FIELDS, SESSION_FIELDS  # noqa: E402


def database():
    uri = os.environ.get("MONGO_URI", "")
    if not uri:
        raise SystemExit("Set MONGO_URI in discord_bot/relay/.env")
    return MongoClient(uri)[os.environ.get("MONGO_DB", "capitalization")]


def add(session_id: str, condition: str, style: str) -> None:
    condition = condition.lower().strip()
    style = style.lower().strip() or "ac_high"
    if condition not in ("ai", "human"):
        raise SystemExit("condition must be ai or human")
    database().assignments.update_one(
        {"session_id": session_id},
        {"$set": {"session_id": session_id, "condition": condition, "style": style}},
        upsert=True,
    )
    print(f"{session_id} {condition} {style}")


def list_rows() -> None:
    rows = list(database().assignments.find({}, {"_id": 0}).sort("session_id", 1))
    if not rows:
        print("No assignments.")
        return
    for row in rows:
        print(f"{row['session_id']},{row.get('condition','')},{row.get('style','ac_high')}")


def export_csv() -> None:
    base = database()
    out = ROOT.parent / "transcripts"
    out.mkdir(exist_ok=True)
    messages = list(base.messages.find({}, {"_id": 0}).sort([("session_id", 1), ("ts_utc", 1)]))
    sessions = list(base.sessions.find({}, {"_id": 0}).sort("session_id", 1))
    messages_path = out / "messages.csv"
    sessions_path = out / "sessions.csv"
    with messages_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MESSAGE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(messages)
    with sessions_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SESSION_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sessions)
    print(f"Wrote {len(messages)} messages and {len(sessions)} sessions to {out}")
    print("Copy those CSVs to the private OSF component. Do not commit them.")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_cmd = sub.add_parser("add")
    add_cmd.add_argument("session_id")
    add_cmd.add_argument("condition")
    add_cmd.add_argument("style", nargs="?", default="ac_high")
    sub.add_parser("list")
    sub.add_parser("export")
    args = parser.parse_args()
    if args.cmd == "add":
        add(args.session_id, args.condition, args.style)
    elif args.cmd == "list":
        list_rows()
    else:
        export_csv()


if __name__ == "__main__":
    main()
