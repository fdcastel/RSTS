# /// script
# dependencies = ["flask"]
# ///

import os
import random
import signal
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify

# Python running as PID 1 (e.g. in Docker) ignores SIGTERM by default because
# the kernel suppresses default signal actions for init processes. Explicitly
# install a handler so 'docker stop' causes a clean, immediate shutdown.
signal.signal(signal.SIGTERM, lambda _sig, _frame: sys.exit(0))

app = Flask(__name__)

# --- Startup state (reset on each container start) ---
INSTANCE_ID = str(uuid.uuid4())
STARTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
write_count = 0

# --- Configuration ---
DATA_DIR = os.environ.get("RSTS_DATA_DIR", "/data")
_SERVER_NAME = os.environ.get("RSTS_SERVER_NAME") or os.environ.get("SERVER_NAME") or socket.gethostname()
HOSTNAME = socket.gethostname()
PORT = int(os.environ.get("RSTS_PORT", "80"))

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


def _ensure_state():
    """Create DATA_DIR and state.txt if they don't exist."""
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("initialized")


# Initialize on import
_ensure_state()


@app.route("/")
def index():
    data = _state_file().read_text()
    return jsonify(
        server=_SERVER_NAME,
        hostname=HOSTNAME,
        data_dir=DATA_DIR,
        data=data,
        instance_id=INSTANCE_ID,
        started_at=STARTED_AT,
        write_count=write_count,
        rsts_stands_for=random.choice(ACRONYMS),
    )


@app.route("/state/<value>", methods=["GET", "POST"])
def write(value: str):
    global write_count
    _state_file().write_text(value)
    write_count += 1
    return jsonify(status="ok", written=value)


@app.route("/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
