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
  "uptime_seconds": 42.7,
  "write_count": 0,
  "rsts_stands_for": "Runs Somewhere, Then Somewhere-else",
  "meta": {},
  "request": {
    "peer_ip": "10.0.0.1",
    "x_forwarded_for": null,
    "x_real_ip": null,
    "x_forwarded_proto": null,
    "host": "localhost:8080"
  }
}
```

`request` reports what RSTS observes about the incoming connection — useful for verifying that a reverse proxy in front of RSTS is forwarding `X-Forwarded-*` headers correctly.

`meta` echoes any `RSTS_META_*` environment variable (lowercased, prefix-stripped) so operators can tag instances with arbitrary metadata (`RSTS_META_SCHEMA_VERSION`, `RSTS_META_BACKUP_ID`, etc.) without code changes.

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

### `GET /checksum`

Returns sha256 over every file under `RSTS_DATA_DIR` (path + content). Lets backup/restore tests assert byte-perfect round-trip.

```json
{
  "sha256": "9a775ced6b0036b5f13fcc1b0d0d943f722639621db3f2eb922e4ddfc8aa2f51"
}
```

### `POST /seed/<bytes>`

Writes `<bytes>` of deterministic pseudorandom data to `seed.bin` in the data dir. Useful for exercising backup throughput at realistic sizes. Bounded by `RSTS_SEED_MAX_BYTES` (default 1 GB); requests above the cap return 413.

```json
{ "seeded_bytes": 1048576 }
```

### `POST /fail/<seconds>`

Drives `/health` to `500 unhealthy` for the next `<seconds>` seconds, then recovers. Lets smoke-test/rollback paths be exercised deterministically.

### `POST /exit/<code>`

Terminates the process with the given exit code (after a short delay so the response can be sent). Useful for validating container restart policies.

### `POST /slow/<ms>`

Adds `<ms>` milliseconds of latency to every `/health` response until cleared. `POST /slow/0` clears it. Useful for tuning compose healthcheck `timeout` / `interval` / `start_period` against realistic slowness.

```json
{ "slow_ms": 600 }
```

### TCP echo (optional)

When `RSTS_TCP_PORT` is set, RSTS opens a raw-TCP listener on that port that replies with `RSTS-ECHO\n<server-name>\n` and closes. Probes non-HTTP forwarding paths through a reverse proxy (Mailpit SMTP, Clickhouse, etc.):

```bash
docker run -d -p 8080:80 -p 9000:9000 -e RSTS_TCP_PORT=9000 ghcr.io/fdcastel/rsts
echo | nc localhost 9000   # -> RSTS-ECHO\n<server-name>\n
```

### `GET /health`

```json
{ "status": "ok" }
```

Returns `500 unhealthy` while a `/fail` window is active. Adds whatever delay was set via `/slow/<ms>` before responding.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RSTS_DATA_DIR` | `/data` | Directory for persistent state |
| `RSTS_SERVER_NAME` | `<hostname>` | Override reported server name |
| `RSTS_PORT` | `80` | Port to listen on |
| `RSTS_LOG_FORMAT` | _(off)_ | Set to `jsonl` to emit one JSON event per line to stdout (`startup`, `write`) |
| `RSTS_SEED_MAX_BYTES` | `1073741824` | Maximum size accepted by `POST /seed/<bytes>` (1 GB) |
| `RSTS_META_*` | _(none)_ | Any var matching this prefix is echoed under `meta` in `GET /` (lowercased, prefix-stripped) |
| `RSTS_TCP_PORT` | _(off)_ | If set, opens a raw-TCP listener that replies `RSTS-ECHO\n<server>\n` and closes — for probing non-HTTP forwarding paths |

## How It Works

RSTS is a "truth probe" for your platform. Deploy it, move it, and verify:

- **`server` + `hostname`** — where is the workload running?
- **`data`** — did state survive the move?
- **`instance_id`** — was this a restart or a relocation?
- **`started_at` / `uptime_seconds`** — when did this instance start, and how long has it been up? Same `instance_id` plus climbing `uptime_seconds` proves no restart happened (e.g. a no-op `compose up -d`).
- **`write_count`** — resets on restart; proves continuity vs. fresh start
- **`/checksum`** — sha256 over every file in the data dir; assert byte-perfect backup/restore.
- **`request`** — peer IP and `X-Forwarded-*` headers as observed by RSTS; verify your reverse proxy is forwarding correctly.
- **`POST /fail/<sec>` and `POST /exit/<code>`** — fault injection so smoke-test/rollback and restart-policy paths can be exercised deterministically.
- **`POST /slow/<ms>`** — latency injection on `/health`; tune compose healthcheck timeouts against realistic slowness.
- **`RSTS_TCP_PORT`** — optional raw-TCP echo listener; probes non-HTTP forwarding through a reverse proxy.

## License

MIT
