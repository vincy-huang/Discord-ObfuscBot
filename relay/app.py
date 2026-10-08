"""Assignment and transcript relay. The RA bot never gets the Mongo login.

RA token can read one assignment row and append events.
Admin token can edit the assignment list and export the stacked rows.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from stack_logic import stack_events

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

MONGO_URI = os.environ.get("MONGO_URI", "")
DB_NAME = os.environ.get("MONGO_DB", "capitalization")
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

app = FastAPI(title="Stage-1 assignment relay")
_client: MongoClient | None = None


def db():
    global _client
    if not MONGO_URI:
        raise HTTPException(status_code=503, detail="MONGO_URI is not set on the relay")
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    base = _client[DB_NAME]
    base.assignments.create_index("session_id", unique=True)
    base.events.create_index([("session_id", 1), ("ts_utc", 1)])
    base.events.create_index("discord_message_id", unique=True, sparse=True)
    return base


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def require_ra(authorization: str | None = Header(default=None)) -> None:
    if not RELAY_TOKEN or bearer(authorization) != RELAY_TOKEN:
        raise HTTPException(status_code=401, detail="RA token rejected")


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not ADMIN_TOKEN or bearer(authorization) != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Admin token rejected")


class AssignmentIn(BaseModel):
    condition: str = Field(pattern="^(ai|human)$")
    style: str = "ac_high"


class EventIn(BaseModel):
    event: str
    session_id: str
    condition: str | None = None
    condition_source: str | None = None
    n_present: int | None = None
    participant_discord_id: str | None = None
    author_role: str | None = None
    receiver_discord_id: str | None = None
    ts_utc: str | None = None
    text: str | None = None
    style: str | None = None
    minutes: int | None = None
    discord_message_id: str | None = None

    model_config = {"extra": "allow"}


def public_assignment(row: dict) -> dict:
    return {
        "session_id": row["session_id"],
        "condition": row.get("condition", ""),
        "style": row.get("style") or "ac_high",
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": DB_NAME}


@app.get("/assignments/{session_id}")
def get_assignment(session_id: str, _: None = Depends(require_ra)) -> dict:
    row = db().assignments.find_one({"session_id": session_id}, {"_id": 0})
    if row is None:
        raise HTTPException(status_code=404, detail=f"No assignment for {session_id}")
    return public_assignment(row)


@app.post("/events")
def post_event(event: EventIn, _: None = Depends(require_ra)) -> dict:
    base = db()
    row = event.model_dump()
    if row.get("discord_message_id") in ("", None):
        row.pop("discord_message_id", None)
    try:
        base.events.insert_one(row)
    except DuplicateKeyError:
        return {"stored": False, "duplicate": True, "session_id": event.session_id}
    events = list(base.events.find({"session_id": event.session_id}, {"_id": 0}).sort("ts_utc", 1))
    messages, session = stack_events(events)
    if session is not None:
        base.sessions.replace_one({"session_id": event.session_id}, session, upsert=True)
    if messages:
        base.messages.delete_many({"session_id": event.session_id})
        base.messages.insert_many(messages)
    return {"stored": True, "session_id": event.session_id, "messages": len(messages)}


@app.get("/admin/assignments")
def list_assignments(_: None = Depends(require_admin)) -> list[dict]:
    rows = base_rows()
    return rows


def base_rows() -> list[dict]:
    return [
        public_assignment(row)
        for row in db().assignments.find({}, {"_id": 0}).sort("session_id", 1)
    ]


@app.put("/admin/assignments/{session_id}")
def put_assignment(session_id: str, body: AssignmentIn, _: None = Depends(require_admin)) -> dict:
    row = {
        "session_id": session_id,
        "condition": body.condition,
        "style": body.style,
    }
    saved = db().assignments.find_one_and_update(
        {"session_id": session_id},
        {"$set": row},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    return public_assignment(saved)


@app.delete("/admin/assignments/{session_id}")
def delete_assignment(session_id: str, _: None = Depends(require_admin)) -> dict:
    result = db().assignments.delete_one({"session_id": session_id})
    return {"deleted": result.deleted_count, "session_id": session_id}
