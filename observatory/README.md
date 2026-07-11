# Observatory

Phase 3 of tilt-spiral: a Go service that crawls players on demand and serves
their behavioral profile — the metrics the study validated (requeue delta,
quit asymmetry, the myth-check winrate), percentile-ranked against the study
population. Performance-tilt stats are deliberately absent: the study found
them null.

Job management is [gotaskqueue](https://github.com/VinKurup/gotaskqueue)
(retries, backoff, dead-letter queue, status). Interactive lookups and the
panel sweep run on separate queues, so a sweep (one task per study player)
can't starve a user's crawl. Rate limiting is not the queue's job: a dual
sliding window in the Riot client enforces the dev-key limits (20 req/s and
100 req/2min) across all workers on both queues, with 429 Retry-After as the
backstop. The crawl handler is idempotent, so a retried or redelivered task
skips what's already stored.

It reads and writes the **same SQLite schema** as the Python pipeline, so
`analyze.py` / `traits.py` / `figures.py` keep working against data this
service crawls. Looked-up players are marked `status='lookup'`, never
`'done'`, so self-selected lookups can't leak into the study population.

## Run

```sh
RIOT_API_KEY=... go run .          # serves :8080 against ../tilt.db
go test ./...                      # metric port is cross-checked vs Python
```

Open http://localhost:8080 — a single embedded page (go:embed, one static
binary) takes a Riot ID, shows live crawl progress, and renders the profile.

For the production shape (Redis-backed queue, data on a volume):

```sh
RIOT_API_KEY=... docker compose up --build
```

Config (env): `RIOT_REGION` (americas), `RIOT_PLATFORM` (na1), `TILT_DB`
(../tilt.db), `ADDR` (:8080), `WORKERS` (2 per queue), `QUEUE` (memory | redis),
`REDIS_ADDR`, `PANEL_INTERVAL_H` (0 = off; 168 sweeps the longitudinal
panel weekly — rank snapshot + match top-up for every done player).
`QUEUE=memory` is single-process and ephemeral; `QUEUE=redis` gives
at-least-once delivery and crash recovery via gotaskqueue's Redis backend.

The compose file also carries the Phase 1 expansion crawler
(`Dockerfile.crawler` at the repo root) behind a profile, sharing the same
`./data` volume, so the deploy box can grow the dataset itself:

```sh
docker compose --profile crawl up -d --build crawler
docker compose logs -f crawler
```

It exits 0 at `CRAWL_TARGET_MATCHES` and crashes on a dev-key expiry (403);
put the fresh key in `.env` and re-run the `up` to recreate it. Run the
crawler and the panel at different times — they share the key's rate budget.

## API

| | |
|---|---|
| `POST /api/lookup` `{"riotId":"Name#TAG"}` | enqueue a crawl of the player's last 100 ranked games → `{taskId}` |
| `GET /api/tasks/{id}` | queue status + crawl progress |
| `GET /api/profile?riotId=Name%23TAG` | behavioral profile + chase percentile vs the study's 345 players |
| `GET /api/stats` | queue stats + db counts |
| `GET /healthz` | liveness |

## Verification

`session_test.go` covers the session/metric logic (gap edge cases, quit-rate
censoring, streak tagging). The port is additionally cross-checked against
the Python implementation: both produce identical values (to 6 decimals) for
the same player on the real database.
