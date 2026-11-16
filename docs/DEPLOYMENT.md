# Always-on deployment strategy

**Status: not deployed.** The application is built and tested locally only. This document compares hosting
options for when deployment happens. Prices were checked on 15 November 2026 from provider pages and recent
pricing write-ups. **Confirm them on each provider's pricing page before you buy**, because they change.

## What DataBridge needs from a host

| Requirement | Why |
|---|---|
| No sleep / scale-to-zero | Recruiters open the link at random times; a cold start would be the first impression |
| ~1 GB RAM for comfortable use | Measured on this build: about 150 MB idle per worker, 261 MB peak for a 50,000-row file and 556 MB peak for a 200,000-row (17 MB) file |
| Managed PostgreSQL with backups | Processed tables and history must survive redeploys |
| A persistent disk, or acceptance of losing uploads | Original files and generated reports are stored on disk (see "Storage" below) |
| Docker deploys | The repo ships a single-service `Dockerfile` (API + UI in one container) and a compose stack |

## Options compared

| Option | Always-on? | Cold start | Approx. monthly cost (app + Postgres) | Database | Deployment simplicity |
|---|---|---|---|---|---|
| **Render**: Starter web service + Basic Postgres | Yes; paid instances do not spin down | None on paid instances | about $13 (Starter $7 with 512 MB + Basic-256mb Postgres about $6); **Standard (2 GB) is $25** | Managed | High: Docker deploy from Git, health checks, TLS |
| Render free tier | **No.** Spins down after 15 min idle; about 1 minute to wake | ~1 min | $0 | Free Postgres expires after 30 days | High, but unsuitable |
| **Fly.io**: 1 GB machine, `min_machines_running = 1` | Yes, when auto-stop is disabled or a minimum is kept running | None if a machine stays running (defaults stop idle machines) | about $7 machine + Managed Postgres from about $38, or self-run Postgres on a machine | Managed (paid) or self-managed | Medium: `fly.toml`, more knobs |
| **Railway** Hobby | Yes by default; "Serverless" sleeping is opt-in | None unless Serverless is enabled | Usage-based on a $5 minimum; app + Postgres commonly a few dollars to $12+ | Railway Postgres (container) | High |
| **DigitalOcean** App Platform + Managed Postgres | Yes | None | about $20+ (container from $5 + managed Postgres from $15) | Managed, daily backups | High |
| **VPS** (e.g. a 1–2 GB droplet) + `docker compose` | Yes (you run it) | None | about $6–12 | Self-managed in the compose stack | Low: you own OS updates, TLS, backups, monitoring |

### Sources
- [Render: hosting costs for small businesses](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses): free web services spin down after 15 minutes idle; paid instances run continuously; Starter + Basic-256mb Postgres was about $13/month in July 2026.
- [Render: platforms with a free tier](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026): spin-up takes about one minute; paid tiers remove spin-down.
- [Fly.io pricing](https://fly.io/pricing) and [Fly.io PaaS pricing comparison](https://fly.io/learn/paas-pricing-compared.md): per-second machine billing; shared-cpu-1x 1 GB about $6.70; Managed Postgres Basic $38.
- [Railway docs: understanding your bill](https://docs.railway.com/pricing/understanding-your-bill): Serverless automatically stops inactive services (opt-in).
- [DigitalOcean App Platform pricing](https://digitalocean.com/pricing/app-platform) and [managed PostgreSQL pricing](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/): databases from $15/month.

## Recommendation

**Render, one web service (Docker, root `Dockerfile`) plus a managed Postgres.**

* **Portfolio demo budget (~$13/month):** Starter instance (512 MB) with `WEB_CONCURRENCY=1` and
  `DEMO_MODE=true` (which applies the 10 MB and 50,000-row limits; see [DEMO_MODE.md](DEMO_MODE.md)). The measured 50,000-row peak of 261 MB leaves headroom; the sample
  dataset uses ~160 MB.
* **Comfortable (~$31/month):** Standard instance (2 GB) with 2 workers and the default limits, which handles
  the 200,000-row case measured at 556 MB per worker.

Why Render: fixed, predictable prices; paid instances never sleep; managed Postgres with backups; deploys
straight from the Dockerfile with a health check path. Railway is a close alternative but usage-based. Fly.io
is cheapest for compute but needs explicit always-on settings and either an expensive managed database or
self-run Postgres. A VPS is cheapest overall but makes you the operations team, which is a poor trade for a
portfolio.

Pick the region nearest your expected visitors from the provider's region list. For visitors in Saudi Arabia
and Europe, an EU region keeps latency lower than a US one.

## Deployment checklist (when ready)

1. Push the repository to GitHub.
2. Create the Postgres instance; copy its internal connection URL.
3. Create a Web Service from the repo using the root `Dockerfile`, with health check path `/api/health`.
4. Set environment variables (never in code):
   `DATABASE_URL=postgresql+psycopg://…` (note the `+psycopg` driver), `ENVIRONMENT=production`,
   `DEMO_MODE=true` for a public demo, `WEB_CONCURRENCY`, `CORS_ORIGINS=https://<your-domain>`, and optionally
   `AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`.
5. The container runs `alembic upgrade head` on start, so the first deploy creates the schema.
6. Add a persistent disk mounted at `/app/data` if originals and reports must survive redeploys.
7. Configure an external uptime monitor (for example UptimeRobot or Better Stack) on
   `https://<domain>/api/health` every 5 minutes, with alerts. It is a monitor, not a keep-alive: the
   instance is always-on regardless.
8. With `DEMO_MODE=true` the shared sample, a pipeline run and a report are created automatically on the first
   start, and visitor uploads are cleaned up after 24 hours. `ENVIRONMENT=production` makes the visitor cookie
   HTTPS-only. Keep `WEB_CONCURRENCY=1` on a small instance (rate-limit counters are per worker).

## Storage

Uploaded originals and generated reports are files under `DATA_DIR`. On platforms with ephemeral disks,
attach a persistent disk or accept that these files are lost on redeploy; database rows are unaffected.
Moving them to object storage (S3-compatible) is on the roadmap.

## Already in the codebase for fast, reliable access

* Production builds only: Vite build with code splitting per page; charts load only on pages that need them.
* Hashed assets cached for a year (`immutable`); `index.html` never cached so deploys apply immediately.
* gzip (nginx, or FastAPI `GZipMiddleware` in single-service mode).
* Self-hosted fonts (no third-party CDN on the critical path).
* `pool_pre_ping` and `pool_recycle` on the database pool; startup migration; startup recovery of runs left
  `running` by a crash.
* `/api/health` (liveness, no database call) and `/api/health/ready` (runs `SELECT 1`, returns 503 if the
  database is down).
* Column statistics cached per immutable row table.
* Measured locally: first contentful paint about 244 ms (median of 5 cold loads on localhost, so it excludes
  network latency).
