# Installation

## 1. Prerequisites

| Component | Version | Notes |
| --- | --- | --- |
| Python | 3.11 or 3.12 (tested on 3.12.10) | 64-bit; Windows, macOS (Intel / Apple silicon) or Linux (x86-64 / ARM64, glibc) |
| Node.js | 22.12+ (Vite 8 needs ≥ 20.19 to build; the Vitest test runner needs ≥ 22.12) | Only needed to build and test the dashboard |
| Disk | ≥ 2 GB free | Session uploads, analysis JSON and reports |
| RAM | ≥ 2 GB for 20-minute files | Analysis is in-memory; see *Resource behaviour* |

No system FFmpeg installation is required: MP3/AAC/MP4 decoding is provided by the bundled PyAV
wheels, and WAV/FLAC/AIFF/OGG are handled by libsndfile through `soundfile`.

## 2. Backend

```bash
cd backend
python -m venv .venv
```

Activate the environment:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# macOS / Linux
source .venv/bin/activate
```

Install the runtime dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Verify the installation:

```bash
python -c "import app.main; print('backend import ok')"
python -m compileall -q app
```

### Optional development extras

```bash
pip install -r requirements-dev.txt   # pytest, httpx, pyloudnorm
```

`pyloudnorm` is only used by the validation suite to cross-check the built-in BS.1770-4
implementation.

## 3. Frontend

```bash
cd frontend
npm install
npm run build        # emits frontend/dist
```

The build output is served by FastAPI in production, so `npm run build` must be executed before
starting the server in that mode.

For development with hot module reload:

```bash
npm run dev          # http://127.0.0.1:5173, proxies /api to 127.0.0.1:8000
```

The backend must be running separately on port 8000.

## 4. Configuration

All settings are environment variables; no configuration file is required.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AAP_DATA_DIR` | `<repo>/data` | Session storage, analysis artifacts and temporary files |
| `AAP_FRONTEND_DIST` | `<repo>/frontend/dist` | Directory served as the single-page application |
| `AAP_MAX_FILE_MB` | `300` | Maximum upload size per file |
| `AAP_MAX_DURATION_SECONDS` | `1200` | Maximum analysed duration (20 minutes) |
| `AAP_MAX_FILES_PER_SESSION` | `12` | Maximum number of files per session |
| `AAP_MAX_CONCURRENT_JOBS` | `2` | Parallel analysis jobs |
| `AAP_SESSION_TTL_HOURS` | `12` | Session expiry and cleanup interval |
| `AAP_CLEANUP_INTERVAL_SECONDS` | `600` | Cleanup thread interval |
| `AAP_API_KEY` | *(unset)* | When set, all `/api` routes require the `X-API-Key` header |
| `AAP_CORS_ORIGINS` | the four local dev origins | Comma-separated origins allowed to call the API, when the frontend is served from another host or port |
| `AAP_API_TARGET` | `http://127.0.0.1:8000` | Dev only: backend the Vite server proxies `/api` to |
| `VITE_PORT` | `5173` | Dev only: port the Vite dev server listens on |
| `VITE_API_BASE` | *(empty)* | Frontend build-time API base URL (leave empty when same-origin) |
| `VITE_API_KEY` | *(empty)* | Frontend build-time API key, if the server requires one |

Example (PowerShell):

```powershell
$env:AAP_DATA_DIR = "D:\aap-data"
$env:AAP_MAX_FILE_MB = "500"
$env:AAP_API_KEY = "change-me"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 5. Running the application

### Production (single process, built frontend)

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Production (multiple workers)

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

> **Note** — analysis jobs and session state live in the process that accepted the upload. With more
> than one worker, uploads and analysis requests must reach the same worker. Use a single worker with
> a reverse proxy, or a sticky-session load balancer, unless the storage layer is replaced with a
> shared one. See [DEPLOYMENT.md](DEPLOYMENT.md).

### Development

Terminal 1:

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

Terminal 2:

```bash
cd frontend && npm run dev
```

## 6. Reference signals and validation

```bash
python scripts/generate_test_audio.py --out backend/data/test_audio
python scripts/validate_reference_signals.py --audio backend/data/test_audio
python scripts/validate_loudness_against_pyloudnorm.py --audio backend/data/test_audio
```

The second command writes `docs/validation_results.json` with the measured values quoted in
[VALIDATION.md](VALIDATION.md). The third cross-checks the built-in ITU-R BS.1770-4 meter
against `pyloudnorm` and writes `docs/loudness_crosscheck.json`; it exits with a non-zero status
if any file differs by more than 0.05 LU.

An end-to-end HTTP smoke test is available for a running server:

```bash
python scripts/smoke_test.py --base http://127.0.0.1:8000
```

## 7. Running the tests

```bash
cd backend
python -m pytest
```

Expected: **62 passed** in roughly one minute on a modern laptop.
The suite creates its own temporary data directory (`AAP_DATA_DIR` is redirected inside
`backend/tests/conftest.py`), so it never touches real session data.

## 8. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `python: command not found` | Python is not on `PATH`. Use the full path to `python.exe`, e.g. `C:\Users\<user>\AppData\Local\Programs\Python\Python312\python.exe`. |
| `Access is denied` spawning `pwsh.exe` | Windows App Execution Alias interference. Re-run the command, or launch the terminal from the system PowerShell installation (`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`). |
| `ImportError: libsndfile` | Reinstall `soundfile`; on Windows use a Python build with the bundled libsndfile wheels. |
| AAC/MP4 upload rejected | The file must contain a real ADTS/MP4 audio stream; re-export with a standard AAC encoder. |
| `npm run build` fails with out-of-memory | Plotly is a large bundle; build on a machine with ≥ 2 GB free RAM or use `--max-old-space-size=4096`. |
| Frontend shows “Server connected” but no data | The browser is pointing at a different backend. Set `VITE_API_BASE` at build time or use the Vite proxy. |
| 404 on `/` | The frontend has not been built. Run `npm run build` in `frontend/`, or start the Vite dev server. |
| Analysis job fails with “Decoding failed” | The file is damaged or truncated. Validation should have rejected it earlier — check the upload response. |

## 9. Uninstall

```bash
# stop the server
# remove the virtual environment and data
rm -rf backend/.venv data frontend/node_modules frontend/dist
```

No system-wide components (FFmpeg, codecs, services) are installed by this project.
