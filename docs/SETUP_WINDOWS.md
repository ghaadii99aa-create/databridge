# Windows setup guide

Everything runs from one folder named `databridge`. You need no GitHub account, cloud service, password or
API key.

## 1. Prerequisites (one time)

| Tool | Version | Get it |
|---|---|---|
| Python | 3.11, 3.12 or 3.13 | https://www.python.org/downloads/ (tick **Add python.exe to PATH**) |
| Node.js | 20 or 22 LTS | https://nodejs.org/ |
| Docker Desktop | optional, for the PostgreSQL stack | https://www.docker.com/products/docker-desktop/ |

Check in a new PowerShell window:

```powershell
python --version
node --version
```

## 2. Unzip and set up

Unzip `databridge.zip`, for example to `C:\Users\<you>\Projects\databridge`, then:

```powershell
cd C:\Users\<you>\Projects\databridge
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

The script creates a Python virtual environment in `backend\.venv`, installs pinned dependencies, creates
`backend\.env` from the example (SQLite by default), applies the database migrations and installs the frontend
packages. It stops with a clear message if any step fails. It takes a few minutes the first time.

`-ExecutionPolicy Bypass` applies to that one command only; it does not change your system policy.

## 3. Run it

**Development mode** (two windows, hot reload):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

* App: http://localhost:5173
* API documentation: http://127.0.0.1:8000/api/docs

**Production-like mode** (one process, built frontend, no dev servers):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-production.ps1
```

* App and API: http://127.0.0.1:8000

**Public demo mode** (what a visitor to a published demo sees; separate data folder):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

The sample is ready on the first page, read-only, and labelled as demonstration data. Open a second browser
to check that one visitor cannot see another's uploads. See `docs/DEMO_MODE.md`.

## 4. Try the demonstration

On the Overview page choose **Load sample dataset**, then follow `README.md → Demonstration walkthrough`.

## 5. Run the tests

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

This runs the backend tests (pytest), the frontend type check and the frontend tests (Vitest). To also run the
backend suite on PostgreSQL, pass a URL to an **empty test database**; the tests drop and recreate its tables:

```powershell
scripts\test.ps1 -Postgres "postgresql+psycopg://databridge:YOUR_PASSWORD@localhost:5432/databridge_test"
```

## 6. Full stack with PostgreSQL (Docker)

```powershell
Copy-Item .env.example .env
notepad .env          # set POSTGRES_PASSWORD to a long random value
docker compose up --build
```

Open http://localhost:8080. Compose refuses to start without `POSTGRES_PASSWORD`. Stop it with `Ctrl+C`, or
run `docker compose down` (add `-v` to delete the database volume).

To point the non-Docker backend at PostgreSQL instead of SQLite, set `DATABASE_URL` in `backend\.env`:

```
DATABASE_URL=postgresql+psycopg://databridge:YOUR_PASSWORD@localhost:5432/databridge
```

then run `backend\.venv\Scripts\python -m alembic upgrade head` from the `backend` folder.

## 7. Optional: AI analyst

Add to `backend\.env` (or the root `.env` for Docker). Keys stay on your machine and are never sent to the
browser:

```
AI_PROVIDER=anthropic        # or openai
AI_API_KEY=...               # your key
AI_MODEL=...                 # a model name your account can use
```

Restart the backend. The AI analyst page shows whether a provider is configured. Without one, it still answers
with statistical analysis.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` opens the Microsoft Store | Install Python from python.org and turn off the "App execution aliases" for python in Windows settings |
| Port 8000 or 5173 already in use | Close the other program, or change the port in `scripts\dev.ps1` / `frontend\vite.config.ts` |
| "API unreachable" in the sidebar | The backend window shows the error; check that `scripts\setup.ps1` finished |
| Start over with an empty database | `powershell -ExecutionPolicy Bypass -File scripts\reset-local-data.ps1` |
| Antivirus slows `npm ci` | Exclude the `frontend\node_modules` folder or retry |

## Folder layout

```
databridge/
├── backend/            FastAPI app, services, Alembic migrations, tests
├── frontend/           React + TypeScript + Vite app, nginx config
├── sample_data/        SAMPLE retail dataset (synthetic) + generator output
├── scripts/            PowerShell scripts, sample generator, benchmark
├── docs/               architecture, data quality, database, API, design, deployment, testing, portfolio
├── Dockerfile          single-service image (API + UI)
└── docker-compose.yml  PostgreSQL + backend + nginx frontend
```
