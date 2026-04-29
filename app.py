# /// script
# dependencies = ["flask"]
# ///

import hashlib
import json
import os
import random
import signal
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify
from flask import request as flask_request

# Python running as PID 1 (e.g. in Docker) ignores SIGTERM by default because
# the kernel suppresses default signal actions for init processes. Explicitly
# install a handler so 'docker stop' causes a clean, immediate shutdown.
signal.signal(signal.SIGTERM, lambda _sig, _frame: sys.exit(0))

app = Flask(__name__)

# --- Startup state (reset on each container start) ---
INSTANCE_ID = str(uuid.uuid4())
_STARTED_DT = datetime.now(timezone.utc)
STARTED_AT = _STARTED_DT.strftime("%Y-%m-%dT%H:%M:%SZ")
write_count = 0
_unhealthy_until = 0.0  # monotonic deadline; assumes single-threaded Flask dev server

# --- Configuration ---
DATA_DIR = os.environ.get("RSTS_DATA_DIR", "/data")
_SERVER_NAME = os.environ.get("RSTS_SERVER_NAME") or os.environ.get("SERVER_NAME") or socket.gethostname()
HOSTNAME = socket.gethostname()
PORT = int(os.environ.get("RSTS_PORT", "80"))
LOG_FORMAT = os.environ.get("RSTS_LOG_FORMAT", "").lower()
SEED_MAX_BYTES = int(os.environ.get("RSTS_SEED_MAX_BYTES", str(1024 * 1024 * 1024)))  # 1 GB default cap

# --- RSTS acronym expansions (the important stuff) ---
ACRONYMS = [
    "Runtime State Transfer Simulator",
    "Remote State Switching Tool",
    "Reschedulable Stateful Test Service",
    "Runtime State Tracking Service",
    "Replicated State Transition Stub",
    "Resilient State Transfer Sandbox",
    "Rolling State Transition Service",
    "Runtime Scheduling Test Service",
    "Relocation & State Sync Tester",
    "Reassignment State Test System",
    "Really Simple Test Service",
    "Runs Somewhere, Then Somewhere-else",
    "Randomly Switching Test Service",
    "Restart, Shift, Test, Smile",
    "Roaming Stateful Thingy Service",
]


def _state_file() -> Path:
    return Path(DATA_DIR) / "state.txt"


def _log_event(event: str, **kwargs) -> None:
    if LOG_FORMAT == "jsonl":
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "server": _SERVER_NAME,
            "instance_id": INSTANCE_ID,
            **kwargs,
        }
        print(json.dumps(record), flush=True)


def _ensure_state():
    """Create DATA_DIR and state.txt if they don't exist."""
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("initialized")


# Initialize on import
_ensure_state()
_log_event("startup", port=PORT, data_dir=DATA_DIR)


@app.route("/")
def index():
    data = _state_file().read_text()
    uptime_seconds = (datetime.now(timezone.utc) - _STARTED_DT).total_seconds()
    meta = {
        k[len("RSTS_META_"):].lower(): v
        for k, v in os.environ.items()
        if k.startswith("RSTS_META_")
    }
    return jsonify(
        server=_SERVER_NAME,
        hostname=HOSTNAME,
        data_dir=DATA_DIR,
        data=data,
        instance_id=INSTANCE_ID,
        started_at=STARTED_AT,
        uptime_seconds=uptime_seconds,
        write_count=write_count,
        rsts_stands_for=random.choice(ACRONYMS),
        meta=meta,
        request=dict(
            peer_ip=flask_request.remote_addr,
            x_forwarded_for=flask_request.headers.get("X-Forwarded-For"),
            x_real_ip=flask_request.headers.get("X-Real-IP"),
            x_forwarded_proto=flask_request.headers.get("X-Forwarded-Proto"),
            host=flask_request.headers.get("Host"),
        ),
    )


@app.route("/state/<value>", methods=["GET", "POST"])
def write(value: str):
    global write_count
    _state_file().write_text(value)
    write_count += 1
    _log_event("write", value=value, count=write_count)
    return jsonify(status="ok", written=value)


@app.route("/seed/<int:size_bytes>", methods=["POST"])
def seed(size_bytes: int):
    if size_bytes < 0:
        return jsonify(error="size must be non-negative"), 400
    if size_bytes > SEED_MAX_BYTES:
        return jsonify(error="size exceeds RSTS_SEED_MAX_BYTES", max=SEED_MAX_BYTES), 413
    rng = random.Random(f"{_SERVER_NAME}:{size_bytes}")
    Path(DATA_DIR, "seed.bin").write_bytes(rng.randbytes(size_bytes))
    return jsonify(seeded_bytes=size_bytes)


@app.route("/checksum")
def checksum():
    h = hashlib.sha256()
    for p in sorted(Path(DATA_DIR).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA_DIR).as_posix().encode())
            h.update(p.read_bytes())
    return jsonify(sha256=h.hexdigest())


@app.route("/fail/<int:seconds>", methods=["POST"])
def fail(seconds: int):
    global _unhealthy_until
    _unhealthy_until = time.monotonic() + seconds
    return jsonify(unhealthy_for=seconds)


@app.route("/exit/<int:code>", methods=["POST"])
def exit_(code: int):
    threading.Timer(0.1, lambda: os._exit(code)).start()
    return jsonify(exiting_with=code)


@app.route("/health")
def health():
    if time.monotonic() < _unhealthy_until:
        return jsonify(status="unhealthy"), 500
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
