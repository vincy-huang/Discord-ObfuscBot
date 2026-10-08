"""Turn raw session events into the same rows stack_csv.py writes."""

from __future__ import annotations

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


def stack_events(events: list[dict]) -> tuple[list[dict], dict | None]:
    """Rebuild one session. events must already be for a single session_id."""
    messages: list[dict] = []
    session: dict | None = None
    correction: dict | None = None
    for row in events:
        kind = row.get("event")
        if kind == "message":
            messages.append(dict(row))
        elif kind == "session_open":
            session = dict(row)
        elif kind == "condition_correction":
            correction = row
        elif kind == "session_close" and session is not None:
            session["closed_utc"] = row.get("ts_utc", "")
            session["stop_reason"] = row.get("text", "")
    if session is None and not messages:
        return [], None
    fix = correction
    for row in messages:
        row["condition_stamped"] = row.get("condition")
        row["condition_final"] = fix["condition"] if fix else row.get("condition")
    messages.sort(key=lambda row: row.get("ts_utc", ""))
    if session is None:
        session = {"session_id": messages[0]["session_id"]}
    bot_turns = [m for m in messages if m.get("author_role") == "bot"]
    human_receivers = [m for m in messages if m.get("author_role") == "receiver"]
    if bot_turns:
        session["condition_inferred"] = "ai"
        session["receiver_discord_id"] = bot_turns[0].get("participant_discord_id")
        session["receiver_role"] = "bot"
    elif human_receivers:
        session["condition_inferred"] = "human"
        session["receiver_discord_id"] = human_receivers[0].get("participant_discord_id")
        session["receiver_role"] = "receiver"
    else:
        session["condition_inferred"] = "unknown"
        session["receiver_role"] = ""
        session.setdefault("receiver_discord_id", None)
    session["condition_stamped"] = session.get("condition")
    session["condition_final"] = fix["condition"] if fix else session["condition_inferred"]
    session["n_present_final"] = fix["n_present"] if fix else session.get("n_present")
    session["corrected"] = bool(fix)
    session["correction_reason"] = fix.get("text", "") if fix else ""
    return messages, session
