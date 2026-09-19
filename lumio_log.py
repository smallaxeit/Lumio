"""lumio_log.py — Event logging (local JSONL) and optional Supabase sync."""

import json
import os
import threading
import time
import uuid
from datetime import datetime

try:
    from supabase import create_client as _sb_create
    _SUPABASE_LIB = True
except ImportError:
    _SUPABASE_LIB = False

from theme import LOG_FILE

# ── Module-level state ────────────────────────────────────────────────────────

_log_lock           = threading.Lock()
_logging_enabled    = True
_huecontrol_recent  = {}   # gid → time.time() of last HueControl command
_sse_log_recent     = {}   # gid → time.time() of last external SSE log

_supabase_client = None
_outbox_wake     = threading.Event()
_outbox_started  = False
_on_sync_error   = None   # callable(msg) — registered by RoomGrid at startup

_log_max_mb  = 5.0
_write_count = 0
_TRIM_EVERY  = 200   # re-check the log size every N entries, not just at startup


# ── Hue-control recency tracking ─────────────────────────────────────────────

def _mark_huecontrol(gid: str) -> None:
    _huecontrol_recent[gid] = time.time()


def _is_huecontrol_recent(gid: str, window: float = 10.0) -> bool:
    return (time.time() - _huecontrol_recent.get(gid, 0)) < window


def _should_log_sse(gid: str, window: float = 5.0) -> bool:
    """True if enough time has passed since we last logged an external SSE event."""
    now = time.time()
    if now - _sse_log_recent.get(gid, 0) < window:
        return False
    _sse_log_recent[gid] = now
    return True


# ── Initialisation ────────────────────────────────────────────────────────────

def init_logging(settings: dict) -> None:
    """Initialise logging subsystem from settings. Call once at startup.

    The Supabase client and outbox worker are set up even when logging starts
    disabled: the settings popup can switch logging back on at runtime, and
    returning early here used to leave that session with no client and no
    worker, so entries piled up locally and silently never synced. Both the
    worker and the write path gate on _logging_enabled instead.
    """
    global _logging_enabled, _supabase_client, _outbox_started, _log_max_mb
    _logging_enabled = settings.get("logging_enabled", True)
    _log_max_mb      = float(settings.get("log_max_mb", 5))
    _trim_log_file(_log_max_mb)
    url = settings.get("supabase_url", "")
    key = settings.get("supabase_key", "")
    if url and key and _SUPABASE_LIB:
        try:
            _supabase_client = _sb_create(url, key)
            print("[logging] Supabase client initialised")
        except Exception as exc:
            print(f"[logging] Supabase init failed: {exc}")
            _supabase_client = None
    if _supabase_client and not _outbox_started:
        _outbox_started = True
        threading.Thread(target=_outbox_worker, daemon=True).start()


def _trim_log_file(max_mb: float = 5.0) -> None:
    """Trim oldest JSONL entries if the log file exceeds max_mb."""
    max_bytes = int(max_mb * 1024 * 1024)
    with _log_lock:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) <= max_bytes:
            return
        try:
            with open(LOG_FILE) as f:
                lines = [l for l in f if l.strip()]
            while lines and sum(len(l.encode()) for l in lines) > max_bytes:
                lines.pop(0)
            with open(LOG_FILE, "w") as f:
                f.writelines(lines)
            print(f"[logging] log trimmed to {len(lines)} entries")
        except Exception as exc:
            print(f"[logging] trim failed: {exc}")


# ── Supabase outbox ───────────────────────────────────────────────────────────

def _outbox_worker() -> None:
    """Background thread: drain JSONL outbox into Supabase every 60s or on wake."""
    while True:
        _outbox_wake.wait(timeout=60)
        _outbox_wake.clear()
        if _supabase_client and _logging_enabled:
            _flush_to_supabase()


def _flush_to_supabase() -> None:
    """Read JSONL entries, batch-insert into Supabase, remove sent entries on success."""
    with _log_lock:
        if not os.path.exists(LOG_FILE):
            return
        try:
            with open(LOG_FILE) as f:
                raw_lines = [l.strip() for l in f if l.strip()]
        except Exception:
            return

    if not raw_lines:
        return

    entries, lids = [], []
    for line in raw_lines:
        try:
            e = json.loads(line)
            lids.append(e.get("_lid"))
            entries.append({k: v for k, v in e.items() if k != "_lid"})
        except Exception:
            pass

    if not entries:
        return

    try:
        _supabase_client.table("hue_log").insert(entries).execute()
    except Exception as exc:
        print(f"[logging] Supabase flush failed: {exc}")
        if _on_sync_error:
            _on_sync_error(str(exc))
        return

    sent = set(lids)
    with _log_lock:
        try:
            with open(LOG_FILE) as f:
                current = [l.strip() for l in f if l.strip()]
            remaining = []
            for line in current:
                try:
                    if json.loads(line).get("_lid") not in sent:
                        remaining.append(line)
                except Exception:
                    remaining.append(line)
            with open(LOG_FILE, "w") as f:
                for line in remaining:
                    f.write(line + "\n")
        except Exception as exc:
            print(f"[logging] JSONL cleanup failed: {exc}")


# ── Public logging API ────────────────────────────────────────────────────────

def _write(entry: dict) -> None:
    """Append one JSONL line and periodically re-check the file size."""
    global _write_count
    with _log_lock:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        _write_count += 1
        due_for_trim = _write_count % _TRIM_EVERY == 0
    if due_for_trim:
        # Startup was the only trim point before, so a kiosk that runs for
        # months without a restart grew hue_log.jsonl without bound.
        _trim_log_file(_log_max_mb)
    if _supabase_client:
        _outbox_wake.set()


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log_event(room: str, room_id: str, event: str, bri_pct: int,
              source: str, owner_type: str = None, ts: str = None, **extra) -> None:
    """Append one JSONL line to hue_log.jsonl (thread-safe)."""
    if not _logging_enabled:
        return
    entry = {
        "_lid":    str(uuid.uuid4()),
        "ts":      ts or _now_iso(),
        "room":    room,
        "room_id": room_id,
        "event":   event,
        "bri_pct": bri_pct,
        "source":  source,
    }
    if owner_type:
        entry["owner_type"] = owner_type
    entry.update(extra)
    _write(entry)


def log_system(event: str, detail: str = None) -> None:
    """Append a system-level event (connect, disconnect, error, start, stop)."""
    if not _logging_enabled:
        return
    entry = {
        "_lid":   str(uuid.uuid4()),
        "ts":     _now_iso(),
        "event":  event,
        "source": "system",
    }
    if detail:
        entry["detail"] = detail
    _write(entry)
