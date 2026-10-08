"""RA-side calls. The Mongo login is not in this file."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class RelayError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.environ.get("RELAY_URL"))


def request(method: str, path: str, payload: dict | None = None) -> dict:
    base = os.environ.get("RELAY_URL", "").rstrip("/")
    token = os.environ.get("RELAY_TOKEN", "")
    if not base or not token:
        raise RelayError("RELAY_URL and RELAY_TOKEN are required")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            return {}
        raise RelayError(f"Relay {method} {path} failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RelayError(f"Relay unreachable at {base}: {exc.reason}") from exc


def assignment(session_id: str) -> dict | None:
    row = request("GET", f"/assignments/{session_id}")
    if not row:
        return None
    return {
        "condition": str(row.get("condition", "")).lower().strip(),
        "style": str(row.get("style") or "ac_high").lower().strip() or "ac_high",
    }


def post_event(row: dict) -> None:
    request("POST", "/events", row)
