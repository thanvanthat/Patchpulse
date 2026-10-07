# PatchPulse

Turns player feedback (Steam, Discord, CSV) into ranked themes and, in later phases, traces
complaint spikes to the release and commit that likely caused them.

> Work in progress — Phase 1 (foundation). Full README lands in Step 10.

## Quick start

```bash
cp .env.example .env
make up        # db (Postgres 16 + pgvector), redis, api, worker
make migrate   # create schema
make test
curl localhost:8000/health
```
