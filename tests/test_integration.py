"""
Integration tests for RSTS.

Requires Docker and a pre-built image tagged 'rsts:test'.
Build with:  docker build -t rsts:test .
Run with:    pytest tests/ -v
"""

import os
import shutil
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

    def __init__(self, *, data_dir: str, env: dict[str, str] | None = None):
        port = _Container._next_port
        _Container._next_port += 1
        self.port = port
        self.url = f"http://localhost:{port}"
        self.name = f"rsts-test-{port}"

        cmd = [
            "docker", "run", "-d",
            "--name", self.name,
            "-p", f"{port}:80",
            "-v", f"{data_dir}:/data",
        ]
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
            "instance_id", "started_at", "write_count",
            "rsts_stands_for",
        }
        assert required <= set(body.keys())

    def test_initial_data_is_initialized(self, container):
        r = requests.get(f"{container.url}/")
        assert r.json()["data"] == "initialized"

    def test_rsts_stands_for_is_nonempty(self, container):
        r = requests.get(f"{container.url}/")
        val = r.json()["rsts_stands_for"]
        assert isinstance(val, str) and len(val) > 0


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
