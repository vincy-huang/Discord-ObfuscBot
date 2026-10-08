"""Stage-1 Discord bot. The session RA does not enter or see the condition.

assignments.csv is sealed. /start looks up the row from the relay and never repeats it.
/start does not take a user option: Discord's member picker lists the channel
and would show one person versus two. After /start the bot posts an
"I'm sharing" button. The first human click claims the sharer. Staff and RA
cannot claim. The username is written to the staff log only. The next other
human message is the receiver.
The live Staff channel shows a timer and a turn count, not message text.
Condition is recovered after the slot from who spoke: a bot turn means the
receiver was the bot; another human turn means that account was the receiver.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv
from openai import OpenAI

import relay_client

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
TRANSCRIPTS = ROOT / "transcripts"
SESSIONS_PATH = ROOT / "sessions.json"
ASSIGNMENTS_PATH = ROOT / "assignments.csv"

load_dotenv(ROOT / ".env")

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
STAFF_ROLE_NAME = os.environ.get("STAFF_ROLE_NAME", "Staff")
COMMAND_ROLE_NAMES = {
    part.strip()
    for part in os.environ.get("COMMAND_ROLE_NAMES", "Staff,RA").split(",")
    if part.strip()
} or {STAFF_ROLE_NAME}
SESSIONS_CATEGORY = os.environ.get("SESSIONS_CATEGORY", "Sessions")
STAFF_CATEGORY = os.environ.get("STAFF_CATEGORY", "Staff")

ISOLATION = (
    "This is a new conversation with one student. You have no memory of any "
    "other student, any earlier session, or any conversation between two "
    "people. Do not refer to one. Do not claim you watched or heard another room."
)

openai_client = OpenAI()
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
TIMERS: dict[str, asyncio.Task] = {}
CLAIM_LOCKS: dict[int, asyncio.Lock] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_sessions() -> dict:
    if not SESSIONS_PATH.exists():
        return {}
    return json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))


def save_sessions(data: dict) -> None:
    SESSIONS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def append_jsonl(session_id: str, row: dict) -> None:
    TRANSCRIPTS.mkdir(exist_ok=True)
    path = TRANSCRIPTS / f"{session_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if relay_client.enabled():
        relay_client.post_event(row)


def style_path(style: str) -> Path:
    path = PROMPTS / f"{style}.txt"
    if not path.exists():
        raise FileNotFoundError(f"No prompt file prompts/{style}.txt")
    return path


def load_assignment(session_id: str) -> dict | None:
    """Condition comes from Mongo through the relay, not from who joined."""
    if relay_client.enabled():
        return relay_client.assignment(session_id)
    if not ASSIGNMENTS_PATH.exists():
        return None
    with ASSIGNMENTS_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("session_id", "").strip() == session_id:
                return {
                    "condition": row.get("condition", "").lower().strip(),
                    "style": row.get("style", "ac_high").lower().strip() or "ac_high",
                }
    return None


def attendance_matches(condition: str, n_present: int) -> str | None:
    if condition == "ai" and n_present != 1:
        return "Assignment is ai, but n_present is not 1. Do not flip the arm. Record a no-show."
    if condition == "human" and n_present != 2:
        return "Assignment is human, but n_present is not 2. Do not flip the arm. Record a no-show."
    return None


def find_session(session_id: str) -> dict | None:
    return next(
        (row for row in load_sessions().values() if row["session_id"] == session_id),
        None,
    )


def is_staff(interaction: discord.Interaction) -> bool:
    """Command gate. Staff or RA. The mirror overwrite still uses Staff only."""
    roles = getattr(interaction.user, "roles", [])
    return any(getattr(role, "name", None) in COMMAND_ROLE_NAMES for role in roles)


def find_category(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    return discord.utils.get(guild.categories, name=name)


def staff_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=STAFF_ROLE_NAME)


def message_row(session: dict, author_id: int, role: str, text: str, when: str, message_id: int | None) -> dict:
    return {
        "event": "message",
        "session_id": session["session_id"],
        "condition": session["condition"],
        "n_present": session["n_present"],
        "participant_discord_id": str(author_id),
        "author_role": role,
        "ts_utc": when,
        "text": text,
        "discord_message_id": None if message_id is None else str(message_id),
    }


def seen_message_ids(session_id: str) -> set[str]:
    path = TRANSCRIPTS / f"{session_id}.jsonl"
    if not path.exists():
        return set()
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("discord_message_id"):
            seen.add(row["discord_message_id"])
    return seen


def record_turn(session: dict, author_id: int, role: str, text: str, when: str, message_id: int | None) -> bool:
    if message_id is not None and str(message_id) in seen_message_ids(session["session_id"]):
        return False
    append_jsonl(session["session_id"], message_row(session, author_id, role, text, when, message_id))
    return True



def author_role(session: dict, author_id: int) -> str:
    if author_id == client.user.id:
        return "bot"
    if author_id == session.get("sharer_id"):
        return "sharer"
    if author_id == session.get("receiver_id"):
        return "receiver"
    return "other"


def is_command_member(member) -> bool:
    """Staff and RA must not become the sharer by typing in the room."""
    roles = getattr(member, "roles", [])
    return any(getattr(role, "name", None) in COMMAND_ROLE_NAMES for role in roles)


def claim_receiver(session: dict, author_id: int) -> str:
    """Sharer comes from the button. A later other human is the receiver."""
    if session.get("sharer_id") is None:
        return "other"
    if author_id == session.get("receiver_id") or session.get("receiver_id") is None:
        session["receiver_id"] = author_id
        return "receiver"
    return "other"


def clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def timer_text(minutes_total: int, left: int) -> str:
    return (
        f"Time left: {clock(left)} of {minutes_total}:00. "
        "The conversation ends when this reaches 0:00."
    )


ENDED_TEXT = (
    "Time is up. This conversation has ended. "
    "Please stop typing and wait for the researcher."
)


CLAIM_TEXT = "If you were asked to share good news, click I'm sharing. Only the first click counts."
CLAIMED_TEXT = "Sharing started. Send your news when you are ready."
CLAIM_NUDGE = "Click I'm sharing before you send your news."


def is_system_notice(text: str) -> bool:
    return (
        text.startswith("Time left:")
        or text.startswith("Time is up")
        or text == "One minute left."
        or text == CLAIM_TEXT
        or text == CLAIMED_TEXT
        or text == CLAIM_NUDGE
    )


async def backfill(session: dict) -> int:
    channel = client.get_channel(session["channel_id"])
    if channel is None:
        channel = await client.fetch_channel(session["channel_id"])
    started = parse_utc(session["started_utc"])
    added = 0
    async for msg in channel.history(limit=500, oldest_first=True):
        if msg.created_at < started or not msg.content:
            continue
        role = author_role(session, msg.author.id)
        if role == "other" or is_system_notice(msg.content):
            continue
        when = msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        if record_turn(session, msg.author.id, role, msg.content, when, msg.id):
            added += 1
    return added


async def slot_status(session: dict, line: str) -> None:
    channel = client.get_channel(session["staff_log_id"])
    if channel is None:
        return
    await channel.send(line[:1900])


async def participant_channel(channel_id: int):
    channel = client.get_channel(channel_id)
    if channel is None:
        channel = await client.fetch_channel(channel_id)
    return channel


async def announce_ended(session: dict) -> None:
    """Same stop line in the AI arm and the human arm. Not a transcript turn."""
    room = await participant_channel(session["channel_id"])
    notice_id = session.get("timer_message_id")
    if notice_id:
        try:
            notice = await room.fetch_message(int(notice_id))
            await notice.edit(content=ENDED_TEXT)
        except (discord.HTTPException, discord.NotFound):
            pass
    await room.send(ENDED_TEXT)


async def lock_bot_out(channel_id: int) -> None:
    channel = client.get_channel(channel_id)
    if channel is None:
        channel = await client.fetch_channel(channel_id)
    await channel.set_permissions(
        channel.guild.me,
        view_channel=False,
        read_message_history=False,
        send_messages=False,
    )


async def ai_reply(session: dict, channel: discord.TextChannel, latest: discord.Message) -> None:
    if session["condition"] != "ai" or not latest.content:
        return
    started = parse_utc(session["started_utc"])
    history = []
    async for msg in channel.history(limit=200, oldest_first=True):
        if msg.created_at < started or not msg.content:
            continue
        if msg.author.id not in (session["sharer_id"], client.user.id):
            continue
        if is_system_notice(msg.content):
            continue
        role = "assistant" if msg.author.id == client.user.id else "user"
        history.append({"role": role, "content": msg.content})
    if not history or history[-1]["content"] != latest.content:
        history.append({"role": "user", "content": latest.content})
    system = ISOLATION + "\n\n" + Path(session["prompt_file"]).read_text(encoding="utf-8")
    temperature = 0.7 if session["style"] == "ac_high" else 0.4
    completion = openai_client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        max_tokens=80,
        messages=[{"role": "system", "content": system}, *history],
    )
    text = completion.choices[0].message.content.strip()
    sent = await channel.send(text)
    record_turn(session, client.user.id, "bot", text, utc_now(), sent.id)


async def close_session(session_id: str, why: str) -> str:
    sessions = load_sessions()
    key = next((k for k, row in sessions.items() if row["session_id"] == session_id and row.get("open")), None)
    if key is None:
        return "already closed"
    match = sessions[key]
    when = utc_now()
    match["open"] = False
    match["stopped_utc"] = when
    match["stop_reason"] = why
    save_sessions(sessions)
    task = TIMERS.pop(session_id, None)
    if task is not None and task is not asyncio.current_task():
        task.cancel()
    try:
        await announce_ended(match)
    except discord.HTTPException:
        pass
    added = await backfill(match)
    append_jsonl(
        session_id,
        {
            "event": "session_close",
            "session_id": session_id,
            "condition": match["condition"],
            "n_present": match.get("n_present"),
            "participant_discord_id": "" if match.get("sharer_id") is None else str(match["sharer_id"]),
            "author_role": "sharer",
            "receiver_discord_id": None if match.get("receiver_id") is None else str(match["receiver_id"]),
            "ts_utc": when,
            "text": why,
            "minutes": match.get("minutes"),
        },
    )
    await slot_status(match, f"{session_id} closed. Participants were told to stop. Do not open the transcript until Stage 2 is done.")
    await lock_bot_out(match["channel_id"])
    await lock_bot_out(match["staff_log_id"])
    return f"Closed {session_id}. Backfilled {added} turn(s)."


async def run_timer(session_id: str) -> None:
    session = find_session(session_id)
    if session is None:
        return
    end = parse_utc(session["started_utc"]).timestamp() + session["minutes"] * 60
    warned = False
    channel = client.get_channel(session["channel_id"])
    if channel is None:
        channel = await client.fetch_channel(session["channel_id"])
    notice = await channel.send(timer_text(session["minutes"], session["minutes"] * 60))
    try:
        await notice.pin()
    except discord.HTTPException:
        pass
    sessions = load_sessions()
    for row in sessions.values():
        if row.get("session_id") == session_id and row.get("open"):
            row["timer_message_id"] = notice.id
            save_sessions(sessions)
            break
    while True:
        left = int(end - datetime.now(timezone.utc).timestamp())
        if left > 0:
            try:
                await notice.edit(content=timer_text(session["minutes"], left))
            except discord.HTTPException:
                pass
        await slot_status(session, f"{session_id} running. Time left {clock(left)}.")
        if left <= 60 and not warned:
            warned = True
            if channel is not None:
                await channel.send("One minute left.")
        if left <= 0:
            await close_session(session_id, "timer")
            return
        await asyncio.sleep(30)


@tree.command(name="start", description="Start the slot. Does not ask for or show the condition.")
@app_commands.describe(
    session_id="Study id only, e.g. s014",
    minutes="Visible time limit. Default 8.",
)
async def start(
    interaction: discord.Interaction,
    session_id: str,
    minutes: app_commands.Range[int, 1, 15] = 8,
):
    if not is_staff(interaction):
        await interaction.response.send_message("Staff or RA only.", ephemeral=True)
        return
    room = interaction.channel
    if not isinstance(room, discord.TextChannel):
        await interaction.response.send_message("Run this in the session channel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        assignment = load_assignment(session_id)
    except relay_client.RelayError as exc:
        await interaction.followup.send(f"Relay did not answer. {exc}", ephemeral=True)
        return
    if assignment is None:
        await interaction.followup.send(
            f"No sealed row for {session_id}. Do not guess the arm.",
            ephemeral=True,
        )
        return
    if assignment["condition"] not in ("ai", "human"):
        await interaction.followup.send("Sealed row is unusable. Ask the supervisor.", ephemeral=True)
        return
    try:
        prompt = style_path(assignment["style"])
    except FileNotFoundError:
        await interaction.followup.send("Prompt file missing. Ask the supervisor.", ephemeral=True)
        return
    guild = interaction.guild
    role = staff_role(guild)
    staff_cat = find_category(guild, STAFF_CATEGORY)
    if role is None or staff_cat is None:
        await interaction.followup.send("Missing Staff role or Staff category.", ephemeral=True)
        return
    everyone = guild.default_role
    slot = await guild.create_text_channel(
        f"staff-log-{session_id}",
        category=staff_cat,
        topic="Timer and turn count only. No message text.",
        overwrites={
            everyone: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        },
    )
    started = utc_now()
    record = {
        "session_id": session_id,
        "condition": assignment["condition"],
        "condition_stamped": assignment["condition"],
        "condition_source": "mongo" if relay_client.enabled() else "assignments.csv",
        "n_present": None,
        "style": assignment["style"],
        "prompt_file": str(prompt),
        "channel_id": room.id,
        "staff_log_id": slot.id,
        "sharer_id": None,
        "receiver_id": None,
        "started_utc": started,
        "open": True,
        "minutes": minutes,
        "turns": 0,
    }
    sessions = load_sessions()
    sessions[str(room.id)] = record
    save_sessions(sessions)
    append_jsonl(
        session_id,
        {
            "event": "session_open",
            "session_id": session_id,
            "condition": assignment["condition"],
            "condition_source": "mongo" if relay_client.enabled() else "assignments.csv",
            "n_present": None,
            "participant_discord_id": "",
            "author_role": "sharer",
            "receiver_discord_id": None,
            "ts_utc": started,
            "text": "",
            "style": assignment["style"],
            "minutes": minutes,
        },
    )
    await slot.send(f"{session_id} started. Time limit {minutes}:00. No message text in this channel.")
    claim_msg = await room.send(CLAIM_TEXT, view=ClaimView())
    sessions = load_sessions()
    sessions[str(room.id)]["claim_message_id"] = claim_msg.id
    save_sessions(sessions)
    TIMERS[session_id] = asyncio.create_task(run_timer(session_id))
    await interaction.followup.send(
        f"Started {session_id}. Participants can see a {minutes}:00 timer and an I'm sharing button. "
        "The staff channel shows time left and turn count only. "
        "Do not type in this channel, and do not click the button.",
        ephemeral=True,
    )


@tree.command(name="stop", description="End the slot without showing the condition")
@app_commands.describe(session_id="Study id, e.g. s014")
async def stop(interaction: discord.Interaction, session_id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("Staff or RA only.", ephemeral=True)
        return
    note = await close_session(session_id, "staff")
    await interaction.response.send_message(note, ephemeral=True)


@tree.command(name="status", description="Timer and turn count. Does not show the condition.")
@app_commands.describe(session_id="Study id, e.g. s014")
async def status(interaction: discord.Interaction, session_id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("Staff or RA only.", ephemeral=True)
        return
    match = find_session(session_id)
    if match is None:
        await interaction.response.send_message("No session with that id.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"{session_id}: open={match.get('open')}, minutes={match.get('minutes')}, turns={match.get('turns', 0)}.",
        ephemeral=True,
    )


async def announce_relay() -> None:
    """Print only after /health answers. The wake sleeps, so it stays off the Discord loop."""
    url = os.environ.get("RELAY_URL", "")
    print(f"Waking relay at {url}")
    try:
        await asyncio.to_thread(relay_client.wake)
    except relay_client.RelayError as exc:
        print(f"Relay did not wake: {exc}")
        return
    print("Relay awakened. You may run /start in Discord.")


class ClaimView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="I'm sharing",
        style=discord.ButtonStyle.primary,
        custom_id="claim_sharer",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await claim_sharer(interaction, button)


async def claim_sharer(interaction: discord.Interaction, button: discord.ui.Button) -> None:
    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message("Run this in the session channel.", ephemeral=True)
        return
    if is_command_member(interaction.user):
        await interaction.response.send_message("Staff cannot claim the sharer.", ephemeral=True)
        return
    lock = CLAIM_LOCKS.setdefault(channel.id, asyncio.Lock())
    async with lock:
        sessions = load_sessions()
        session = sessions.get(str(channel.id))
        if session is None or not session.get("open"):
            await interaction.response.send_message("This slot is not open.", ephemeral=True)
            return
        if session.get("sharer_id") is not None:
            await interaction.response.send_message("Someone already clicked I'm sharing.", ephemeral=True)
            return
        session["sharer_id"] = interaction.user.id
        sessions[str(channel.id)] = session
        save_sessions(sessions)
        append_jsonl(
            session["session_id"],
            {
                "event": "sharer_claim",
                "session_id": session["session_id"],
                "condition": session["condition"],
                "n_present": session.get("n_present"),
                "participant_discord_id": str(interaction.user.id),
                "author_role": "sharer",
                "ts_utc": utc_now(),
                "text": str(interaction.user),
            },
        )
    button.disabled = True
    view = ClaimView()
    view.children[0].disabled = True
    await interaction.response.edit_message(content=CLAIMED_TEXT, view=view)
    await slot_status(
        session,
        f"{session['session_id']} sharer claimed: {interaction.user} ({interaction.user.id}).",
    )


@client.event
async def on_ready():
    client.add_view(ClaimView())
    tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {client.user}")
    if relay_client.enabled():
        asyncio.create_task(announce_relay())


@client.event
async def on_message(message: discord.Message):
    if message.guild is None or not message.content:
        return
    sessions = load_sessions()
    session = sessions.get(str(message.channel.id))
    if session is None or not session.get("open"):
        return
    if message.author.bot and message.author.id != client.user.id:
        return
    if message.author.id != client.user.id and is_command_member(message.author):
        return
    role = author_role(session, message.author.id)
    if role == "other" and session.get("sharer_id") is None:
        if not session.get("claim_nudged"):
            session["claim_nudged"] = True
            sessions[str(message.channel.id)] = session
            save_sessions(sessions)
            await message.channel.send(CLAIM_NUDGE)
        return
    if role == "other":
        role = claim_receiver(session, message.author.id)
        sessions[str(message.channel.id)] = session
        save_sessions(sessions)
    if role == "other":
        return
    wrote = record_turn(session, message.author.id, role, message.content, utc_now(), message.id)
    if not wrote:
        return
    session["turns"] = session.get("turns", 0) + 1
    sessions[str(message.channel.id)] = session
    save_sessions(sessions)
    await slot_status(session, f"{session['session_id']} turn {session['turns']}. Time limit {session.get('minutes')}:00.")
    if session["condition"] == "ai" and role == "sharer":
        await ai_reply(session, message.channel, message)


if __name__ == "__main__":
    TRANSCRIPTS.mkdir(exist_ok=True)
    client.run(TOKEN)
