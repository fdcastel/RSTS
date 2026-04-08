# RSTS — Relocatable Stateful Test Service

[![CI](https://github.com/fdcastel/RSTS/actions/workflows/ci.yml/badge.svg)](https://github.com/fdcastel/RSTS/actions/workflows/ci.yml)

A minimal Dockerized HTTP service that proves your infrastructure can move stateful workloads correctly.

Single state file. Zero external dependencies. Fully observable via JSON.

## Quick Start

```bash
docker run -d \
  -p 8080:80 \
  -v /opt/app1/data:/data \
  -e SERVER_NAME=server-1 \
  ghcr.io/fdcastel/rsts
```

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
| `DATA_DIR` | `/data` | Directory for persistent state |
| `SERVER_NAME` | `<hostname>` | Override reported server name |

## How It Works

RSTS is a "truth probe" for your platform. Deploy it, move it, and verify:

- **`server` + `hostname`** — where is the workload running?
- **`data`** — did state survive the move?
- **`instance_id`** — was this a restart or a relocation?
- **`started_at`** — when did this instance start?
- **`write_count`** — resets on restart; proves continuity vs. fresh start

## License

MIT
