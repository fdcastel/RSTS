"""
Integration tests for RSTS.

Requires Docker and a pre-built image tagged 'rsts:test'.
Build with:  docker build -t rsts:test .
Run with:    pytest tests/ -v
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time

import requests

IMAGE = os.environ.get("RSTS_TEST_IMAGE", "rsts:test")
BASE_PORT = 18080


def _wait_for_healthy(url: str, timeout: float = 15.0):
    """Poll /health until it responds 200 or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{url}/health", timeout=2)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Container not healthy after {timeout}s at {url}")


class _Container:
    """Thin wrapper to start/stop a Docker container for testing."""

    _next_port = BASE_PORT

    def __init__(
        self,
        *,
        data_dir: str,
        env: dict[str, str] | None = None,
        tcp_port: int | None = None,
    ):
        port = _Container._next_port
        _Container._next_port += 1
        self.port = port
        self.url = f"http://localhost:{port}"
        self.name = f"rsts-test-{port}"
        self.tcp_host_port: int | None = None

        cmd = [
            "docker", "run", "-d",
            "--name", self.name,
            "-p", f"{port}:80",
            "-v", f"{data_dir}:/data",
        ]
        if tcp_port is not None:
            self.tcp_host_port = _Container._next_port
            _Container._next_port += 1
            cmd += ["-p", f"{self.tcp_host_port}:{tcp_port}"]
        for k, v in (env or {}).items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(IMAGE)

        subprocess.run(cmd, check=True, capture_output=True)
        _wait_for_healthy(self.url)

    def stop(self):
        subprocess.run(
            ["docker", "rm", "-f", self.name],
            capture_output=True,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealth:
    """T1: /health endpoint."""

    def test_health_returns_ok(self, container):
        r = requests.get(f"{container.url}/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestIndex:
    """T2, T3, T9: GET / response shape and defaults."""

    def test_has_all_required_fields(self, container):
        r = requests.get(f"{container.url}/")
        body = r.json()
        required = {
            "server", "hostname", "data_dir", "data",
            "instance_id", "started_at", "uptime_seconds", "write_count",
            "rsts_stands_for", "request", "meta",
        }
        assert required <= set(body.keys())

    def test_initial_data_is_initialized(self, container):
        r = requests.get(f"{container.url}/")
        assert r.json()["data"] == "initialized"

    def test_rsts_stands_for_is_nonempty(self, container):
        r = requests.get(f"{container.url}/")
        val = r.json()["rsts_stands_for"]
        assert isinstance(val, str) and len(val) > 0

    def test_uptime_seconds_is_nonnegative_and_increases(self, container):
        t1 = requests.get(f"{container.url}/").json()["uptime_seconds"]
        assert isinstance(t1, (int, float)) and t1 >= 0
        time.sleep(1.1)
        t2 = requests.get(f"{container.url}/").json()["uptime_seconds"]
        assert t2 > t1

    def test_request_subobject_reports_forwarded_headers(self, container):
        r = requests.get(
            f"{container.url}/",
            headers={
                "X-Forwarded-For": "203.0.113.7",
                "X-Real-IP": "203.0.113.7",
                "X-Forwarded-Proto": "https",
            },
        )
        req = r.json()["request"]
        assert req["x_forwarded_for"] == "203.0.113.7"
        assert req["x_real_ip"] == "203.0.113.7"
        assert req["x_forwarded_proto"] == "https"
        assert req["peer_ip"]  # docker bridge IP, just non-empty
        assert req["host"]


class TestWrite:
    """T4-T8: write endpoint."""

    def test_post_write(self, container):
        r = requests.post(f"{container.url}/state/hello")
        assert r.status_code == 200
        body = r.json()
        assert body == {"status": "ok", "written": "hello"}

    def test_data_persists_after_write(self, container):
        requests.post(f"{container.url}/state/hello")
        r = requests.get(f"{container.url}/")
        assert r.json()["data"] == "hello"

    def test_write_count_increments(self, container):
        requests.post(f"{container.url}/state/a")
        r = requests.get(f"{container.url}/")
        assert r.json()["write_count"] == 1

    def test_get_write_also_works(self, container):
        requests.get(f"{container.url}/state/world")
        r = requests.get(f"{container.url}/")
        assert r.json()["data"] == "world"

    def test_write_count_accumulates(self, container):
        requests.post(f"{container.url}/state/a")
        requests.post(f"{container.url}/state/b")
        r = requests.get(f"{container.url}/")
        assert r.json()["write_count"] == 2


class TestChecksum:
    """C.1: /checksum endpoint."""

    def test_checksum_is_sha256_hex(self, container):
        r = requests.get(f"{container.url}/checksum")
        assert r.status_code == 200
        sha = r.json()["sha256"]
        assert isinstance(sha, str) and len(sha) == 64
        int(sha, 16)  # raises if not valid hex

    def test_checksum_changes_after_write(self, container):
        before = requests.get(f"{container.url}/checksum").json()["sha256"]
        requests.post(f"{container.url}/state/something-new")
        after = requests.get(f"{container.url}/checksum").json()["sha256"]
        assert before != after

    def test_checksum_is_deterministic_across_processes(self):
        """Same data dir -> same checksum even after a fresh container."""
        data_dir = tempfile.mkdtemp(prefix="rsts-checksum-")
        try:
            c1 = _Container(data_dir=data_dir)
            requests.post(f"{c1.url}/state/round-trip-me")
            sha1 = requests.get(f"{c1.url}/checksum").json()["sha256"]
            c1.stop()

            c2 = _Container(data_dir=data_dir)
            sha2 = requests.get(f"{c2.url}/checksum").json()["sha256"]
            c2.stop()

            assert sha1 == sha2
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


class TestTcpEcho:
    """A.2: optional raw-TCP echo listener gated on RSTS_TCP_PORT."""

    def test_tcp_echo_responds_with_server_name(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-tcp-")
        try:
            c = _Container(
                data_dir=data_dir,
                env={"RSTS_TCP_PORT": "9000", "RSTS_SERVER_NAME": "tcp-probe"},
                tcp_port=9000,
            )

            # The TCP listener may take a moment to bind after startup.
            deadline = time.monotonic() + 5
            last_err: Exception | None = None
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("localhost", c.tcp_host_port), timeout=2) as s:
                        s.settimeout(2)
                        chunks = []
                        while True:
                            data = s.recv(1024)
                            if not data:
                                break
                            chunks.append(data)
                        payload = b"".join(chunks)
                    break
                except (ConnectionRefusedError, socket.timeout) as e:  # noqa: PERF203
                    last_err = e
                    time.sleep(0.3)
            else:
                raise AssertionError(f"TCP echo never accepted: {last_err}")

            assert payload == b"RSTS-ECHO\ntcp-probe\n", f"got {payload!r}"
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

class TestSeed:
    """C.2: POST /seed/<bytes> writes pseudorandom bytes to seed.bin."""

    def test_seed_writes_requested_size_and_changes_checksum(self, container):
        before = requests.get(f"{container.url}/checksum").json()["sha256"]
        r = requests.post(f"{container.url}/seed/1024")
        assert r.status_code == 200
        assert r.json() == {"seeded_bytes": 1024}
        after = requests.get(f"{container.url}/checksum").json()["sha256"]
        assert before != after

    def test_seed_is_deterministic_for_same_server_and_size(self, container):
        sha_a = requests.post(f"{container.url}/seed/4096") and requests.get(f"{container.url}/checksum").json()["sha256"]
        sha_b = requests.post(f"{container.url}/seed/4096") and requests.get(f"{container.url}/checksum").json()["sha256"]
        assert sha_a == sha_b

    def test_seed_rejects_oversize(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-seed-cap-")
        try:
            c = _Container(data_dir=data_dir, env={"RSTS_SEED_MAX_BYTES": "1024"})
            r = requests.post(f"{c.url}/seed/2048")
            assert r.status_code == 413
            body = r.json()
            assert body["max"] == 1024
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


class TestFail:
    """D.1: POST /fail/<seconds> makes /health return 500 for the window."""

    def test_health_unhealthy_during_window_then_recovers(self, container):
        assert requests.get(f"{container.url}/health").status_code == 200
        r = requests.post(f"{container.url}/fail/2")
        assert r.status_code == 200
        assert r.json() == {"unhealthy_for": 2}

        r = requests.get(f"{container.url}/health")
        assert r.status_code == 500
        assert r.json()["status"] == "unhealthy"

        # After the window, /health recovers.
        time.sleep(2.5)
        assert requests.get(f"{container.url}/health").status_code == 200


class TestExit:
    """D.2: POST /exit/<code> exits the process with status."""

    def test_exit_terminates_container(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-exit-")
        try:
            c = _Container(data_dir=data_dir)
            r = requests.post(f"{c.url}/exit/0")
            assert r.status_code == 200
            assert r.json() == {"exiting_with": 0}

            # Process should be gone within a couple of seconds.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    requests.get(f"{c.url}/health", timeout=0.5)
                except requests.RequestException:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("Container still responding after /exit")
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


class TestRestart:
    """T10: volume persistence across restart."""

    def test_data_survives_restart_and_instance_id_changes(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-restart-")
        try:
            # First container
            c1 = _Container(data_dir=data_dir)
            requests.post(f"{c1.url}/state/persisted")
            r1 = requests.get(f"{c1.url}/")
            id1 = r1.json()["instance_id"]
            c1.stop()

            # Second container reusing same volume
            c2 = _Container(data_dir=data_dir)
            r2 = requests.get(f"{c2.url}/")
            body = r2.json()

            assert body["data"] == "persisted"
            assert body["write_count"] == 0
            assert body["instance_id"] != id1
            c2.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


class TestJsonlLogs:
    """E.1: RSTS_LOG_FORMAT=jsonl emits one JSON event per line to stdout."""

    def test_startup_and_write_events_emitted(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-jsonl-")
        try:
            c = _Container(data_dir=data_dir, env={"RSTS_LOG_FORMAT": "jsonl"})
            requests.post(f"{c.url}/state/jsonl-probe")

            # Pull container logs and find well-formed JSON lines.
            logs = subprocess.run(
                ["docker", "logs", c.name],
                check=True, capture_output=True, text=True,
            ).stdout

            events = []
            for line in logs.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass

            event_names = [e.get("event") for e in events]
            assert "startup" in event_names
            assert "write" in event_names

            write_event = next(e for e in events if e["event"] == "write")
            assert write_event["value"] == "jsonl-probe"
            assert write_event["count"] == 1
            assert "ts" in write_event and "instance_id" in write_event
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_default_format_emits_no_jsonl(self):
        """Without RSTS_LOG_FORMAT, write events are not emitted."""
        data_dir = tempfile.mkdtemp(prefix="rsts-jsonl-off-")
        try:
            c = _Container(data_dir=data_dir)
            requests.post(f"{c.url}/state/quiet")
            logs = subprocess.run(
                ["docker", "logs", c.name],
                check=True, capture_output=True, text=True,
            ).stdout
            for line in logs.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    parsed = json.loads(line)
                    assert parsed.get("event") not in {"startup", "write"}
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


class TestMeta:
    """C.3: any RSTS_META_* env var auto-publishes under top-level meta."""

    def test_meta_contains_operator_supplied_keys(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-meta-")
        try:
            c = _Container(
                data_dir=data_dir,
                env={
                    "RSTS_META_SCHEMA_VERSION": "v3",
                    "RSTS_META_BACKUP_ID": "bak-2026-04-29",
                },
            )
            meta = requests.get(f"{c.url}/").json()["meta"]
            assert meta == {
                "schema_version": "v3",
                "backup_id": "bak-2026-04-29",
            }
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_meta_is_empty_when_no_env_vars(self, container):
        meta = requests.get(f"{container.url}/").json()["meta"]
        assert meta == {}


class TestServerNameOverride:
    """T11: SERVER_NAME env var."""

    def test_server_name_override(self):
        data_dir = tempfile.mkdtemp(prefix="rsts-sname-")
        try:
            c = _Container(data_dir=data_dir, env={"SERVER_NAME": "custom-42"})
            r = requests.get(f"{c.url}/")
            assert r.json()["server"] == "custom-42"
            c.stop()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# pytest fixture: one container per test class that needs it
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture()
def container(tmp_path):
    """Start a fresh container for each test, stop on teardown."""
    c = _Container(data_dir=str(tmp_path))
    yield c
    c.stop()
