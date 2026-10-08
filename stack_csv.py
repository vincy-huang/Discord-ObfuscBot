"""Stack session JSONL files into an analysis CSV. Does not call Discord or the model.

The live stacked rows are written by the relay into Mongo. Use
`python relay/manage.py export` for the OSF copy. This script remains the
local fallback when a session was logged only to transcripts/.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRANSCRIPTS = ROOT / "transcripts"
MESSAGES = TRANSCRIPTS / "messages.csv"
SESSIONS = TRANSCRIPTS / "sessions.csv"

MESSAGE_FIELDS = [
    "session_id",
    "condition_stamped",
    "condition_final",
    "n_present",
    "participant_discord_id",
    "author_role",
    "ts_utc",
    "text",
    "discord_message_id",
]
SESSION_FIELDS = [
    "session_id",
    "condition_stamped",
    "condition_inferred",
    "condition_final",
    "n_present",
    "n_present_final",
    "participant_discord_id",
    "receiver_discord_id",
    "receiver_role",
    "style",
    "minutes",
    "ts_utc",
    "corrected",
    "correction_reason",
]


def main() -> None:
    messages = []
    sessions = []
    corrections: dict[str, dict] = {}
    for path in sorted(TRANSCRIPTS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "message":
                messages.append(row)
            elif row.get("event") == "session_open":
                sessions.append(row)
            elif row.get("event") == "condition_correction":
                corrections[row["session_id"]] = row
    for row in messages:
        fix = corrections.get(row["session_id"])
        row["condition_stamped"] = row["condition"]
        row["condition_final"] = fix["condition"] if fix else row["condition"]
    messages.sort(key=lambda row: (row["session_id"], row.get("ts_utc", "")))
    for row in sessions:
        fix = corrections.get(row["session_id"])
        sid = row["session_id"]
        turns = [m for m in messages if m["session_id"] == sid]
        bot_turns = [m for m in turns if m.get("author_role") == "bot"]
        human_receivers = [m for m in turns if m.get("author_role") == "receiver"]
        if bot_turns:
            row["condition_inferred"] = "ai"
            row["receiver_discord_id"] = bot_turns[0].get("participant_discord_id")
            row["receiver_role"] = "bot"
        elif human_receivers:
            row["condition_inferred"] = "human"
            row["receiver_discord_id"] = human_receivers[0].get("participant_discord_id")
            row["receiver_role"] = "receiver"
        else:
            row["condition_inferred"] = "unknown"
            row["receiver_role"] = ""
        row["condition_stamped"] = row.get("condition")
        row["condition_final"] = fix["condition"] if fix else row["condition_inferred"]
        row["n_present_final"] = fix["n_present"] if fix else row.get("n_present")
        row["corrected"] = bool(fix)
        row["correction_reason"] = fix["text"] if fix else ""
    with MESSAGES.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MESSAGE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(messages)
    with SESSIONS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SESSION_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sessions)
    print(f"Wrote {len(messages)} messages and {len(sessions)} sessions")


if __name__ == "__main__":
    main()
