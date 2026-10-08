"""RA-side calls. The Mongo login is not in this file.

Render's free service sleeps after 15 minutes. The first call waits for it to wake.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


class RelayError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.environ.get("RELAY_URL"))


def _base() -> str:
    return os.environ.get("RELAY_URL", "").rstrip("/")


def request(method: str, path: str, payload: dict | None = None, timeout: int = 25) -> dict:
    base = _base()
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
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            return {}
        raise RelayError(f"Relay {method} {path} failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RelayError(f"Relay unreachable at {base}: {exc.reason}") from exc


def wake(wait_seconds: int = 75) -> None:
    """Hit /health until Render is up. No token. No study data."""
    base = _base()
    if not base:
        return
    deadline = time.monotonic() + wait_seconds
    last = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=20) as response:
                if response.status == 200:
                    return
                last = f"status {response.status}"
        except Exception as exc:
            last = str(exc)
        time.sleep(5)
    raise RelayError(f"Relay did not wake at {base}: {last}")


def assignment(session_id: str) -> dict | None:
    wake()
    row = request("GET", f"/assignments/{session_id}")
    if not row:
        return None
    return {
        "condition": str(row.get("condition", "")).lower().strip(),
        "style": str(row.get("style") or "ac_high").lower().strip() or "ac_high",
    }


def post_event(row: dict) -> None:
    last: Exception | None = None
    for _ in range(3):
        try:
            wake(wait_seconds=70)
            request("POST", "/events", row)
            return
        except RelayError as exc:
            last = exc
            time.sleep(3)
    raise RelayError(str(last) if last else "Relay did not store the turn")
