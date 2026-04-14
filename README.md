# RSTS: Relocatable Stateful Test Service

A minimal Dockerized HTTP service that proves your infrastructure can move stateful workloads correctly.

Single state file. Zero external dependencies. Fully observable via JSON.

## Quick Start

### Docker
```bash
docker run -d \
  -p 8080:80 \
  -v /opt/app1/data:/data \
  -e RSTS_SERVER_NAME=server-1 \
  ghcr.io/fdcastel/rsts
```

### Bash
```bash
export RSTS_DATA_DIR="/tmp/rsts/data"
export RSTS_SERVER_NAME="server-1"
export RSTS_PORT="8080"
uv run https://raw.githubusercontent.com/fdcastel/RSTS/master/app.py
```

### Powershell
```powershell
$env:RSTS_DATA_DIR = "/tmp/rsts/data"
$env:RSTS_SERVER_NAME = "server-1"
$env:RSTS_PORT = "8080"
uv run https://raw.githubusercontent.com/fdcastel/RSTS/master/app.py
```

Demonstration scripts for migrating workloads:
- [`docker-example.sh`](docker-example.sh) — Docker-based demo (Linux/macOS)
- [`example.ps1`](example.ps1) — `uv`-based demo, no Docker required (PowerShell 7+, Windows and Linux)

## Endpoints

### `GET /`

Returns full status:

```json
{
  "server": "server-1",
  "hostname": "a1b2c3d4",
  "data_dir": "/data",
  "data": "initialized",
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_at": "2026-04-07T12:00:00Z",
  "write_count": 0,
  "rsts_stands_for": "Runs Somewhere, Then Somewhere-else"
}
```

### `GET /state/<value>`

Returns the current state value.

### `POST /state/<value>`

Overwrites `state.txt` with `<value>`:

```json
{
  "status": "ok",
  "written": "hello"
}
```

### `GET /health`

```json
{
  "status": "ok"
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RSTS_DATA_DIR` | `/data` | Directory for persistent state |
| `RSTS_SERVER_NAME` | `<hostname>` | Override reported server name |
| `RSTS_PORT` | `80` | Port to listen on |

## How It Works

RSTS is a "truth probe" for your platform. Deploy it, move it, and verify:

- **`server` + `hostname`** — where is the workload running?
- **`data`** — did state survive the move?
- **`instance_id`** — was this a restart or a relocation?
- **`started_at`** — when did this instance start?
- **`write_count`** — resets on restart; proves continuity vs. fresh start

## License

MIT
