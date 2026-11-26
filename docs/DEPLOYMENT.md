# Deployment

## 1. Deployment model

```
            ┌───────────────────────────────┐
 Browser ──▶│ Reverse proxy (nginx/Caddy)    │
            │  • TLS termination             │
            │  • client_max_body_size        │
            └───────────────┬───────────────┘
                            │ http://127.0.0.1:8000
            ┌───────────────▼───────────────┐
            │ uvicorn + FastAPI             │
            │  • sessions, jobs, artifacts  │
            │  • serves frontend/dist        │
            └───────────────┬───────────────┘
                            │
                 ┌──────────▼──────────┐
                 │ AAP_DATA_DIR        │
                 │  sessions/<id>/...  │
                 └─────────────────────┘
```

The application is a single stateful service. Session state (uploads, analyses, job progress) is
stored on the local filesystem, so **all requests for a session must reach the same process**.

## 2. Minimal production setup

```bash
cd /opt/audio-analysis-pipeline/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cd ../frontend && npm ci && npm run build && cd ../backend

export AAP_DATA_DIR=/var/lib/audio-analysis
export AAP_MAX_FILE_MB=300
export AAP_MAX_DURATION_SECONDS=1200
export AAP_MAX_CONCURRENT_JOBS=2
export AAP_SESSION_TTL_HOURS=12

.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

> **Single worker is required** unless the storage layer is replaced. `app/storage.py` and
> `app/jobs.py` keep session state in the process. With multiple workers, a follow-up request can
> land on a worker that has never seen the session. If you need horizontal scaling, put a sticky
> cookie/IP hash in front of the workers or replace the storage module with a shared database.

## 3. systemd unit

```ini
# /etc/systemd/system/audio-analysis.service
[Unit]
Description=Audio Analysis Pipeline
After=network.target

[Service]
Type=simple
User=aap
Group=aap
WorkingDirectory=/opt/audio-analysis-pipeline/backend
Environment="AAP_DATA_DIR=/var/lib/audio-analysis"
Environment="AAP_FRONTEND_DIST=/opt/audio-analysis-pipeline/frontend/dist"
Environment="AAP_MAX_FILE_MB=300"
Environment="AAP_MAX_CONCURRENT_JOBS=2"
Environment="AAP_API_KEY=replace-with-a-long-random-value"
ExecStart=/opt/audio-analysis-pipeline/backend/.venv/bin/python -m uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/audio-analysis

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/lib/audio-analysis && sudo chown aap:aap /var/lib/audio-analysis
sudo systemctl daemon-reload
sudo systemctl enable --now audio-analysis
sudo systemctl status audio-analysis
```

## 4. nginx reverse proxy

```nginx
server {
    listen 443 ssl http2;
    server_name audio.example.com;

    ssl_certificate     /etc/letsencrypt/live/audio.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/audio.example.com/privkey.pem;

    # Match AAP_MAX_FILE_MB with a small margin for multipart overhead.
    client_max_body_size 320m;
    client_body_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }
}
```

Analysis jobs are asynchronous, so the proxy read timeout only has to cover report generation
(typically a few seconds for two files).

## 5. Windows service (NSSM)

```powershell
nssm install AudioAnalysis "C:\srv\aap\backend\.venv\Scripts\python.exe" `
    "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1"
nssm set AudioAnalysis AppDirectory "C:\srv\aap\backend"
nssm set AudioAnalysis AppEnvironmentExtra "AAP_DATA_DIR=D:\aap-data AAP_MAX_FILE_MB=300"
nssm start AudioAnalysis
```

## 6. Container

```dockerfile
FROM python:3.12-slim AS backend
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
ENV AAP_DATA_DIR=/data AAP_FRONTEND_DIST=/app/frontend/dist
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM backend AS final
COPY --from=frontend /app/dist /app/frontend/dist
```

```bash
docker build -t audio-analysis:1.0.0 .
docker run -d --name aap -p 8000:8000 -v aap-data:/data -e AAP_API_KEY=change-me audio-analysis:1.0.0
```

## 7. Security

* **API key** — set `AAP_API_KEY`; every `/api` route except `/api/health` then requires the
  `X-API-Key` header. The dashboard reads the key at build time from `VITE_API_KEY`.
* **Security headers** — `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy` and `Cross-Origin-Resource-Policy` are set by the application middleware.
* **CORS** — only the local Vite origins are allowed by default. Extend `settings.cors_origins` in
  `backend/app/config.py` if the dashboard is hosted on a different origin.
* **TLS** — terminate TLS at the reverse proxy; the application speaks plain HTTP on localhost.
* **Least privilege** — run the service as an unprivileged user with write access only to
  `AAP_DATA_DIR`.
* **File uploads** — the container is sniffed before decoding, damaged files are rejected, and the
  extension must match the detected container.

## 8. Storage, retention and cleanup

| Path | Content | Lifetime |
| --- | --- | --- |
| `AAP_DATA_DIR/sessions/<session_id>/files/<file_id>/original.<ext>` | Untouched upload | Until session deletion or TTL expiry |
| `AAP_DATA_DIR/sessions/<session_id>/files/<file_id>/analysis.json` | Analysis artifact | Same as the session |
| `AAP_DATA_DIR/sessions/<session_id>/session.json` | Session metadata and settings | Same as the session |
| `AAP_DATA_DIR/tmp/` | Temporary decode buffers | Removed after use |

A background thread (`_cleanup_loop`) removes expired sessions every
`AAP_CLEANUP_INTERVAL_SECONDS` (default 600 s). Sessions also expire after
`AAP_SESSION_TTL_HOURS` (default 12 h). Deleted sessions remove the original uploads as well.

For stricter data-retention policies, reduce `AAP_SESSION_TTL_HOURS` or schedule an external job:

```bash
0 3 * * * find /var/lib/audio-analysis/sessions -maxdepth 1 -type d -mtime +1 -exec rm -rf {} +
```

## 9. Health checks and monitoring

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Liveness, version, supported formats and effective limits (no API key required) |
| `GET /api/settings` | Defaults, threshold schema, methods and limits |

Example probe:

```bash
curl -fsS http://127.0.0.1:8000/api/health | jq .status
```

Monitor: process RSS, job queue depth (`session.jobs` in the session payload), analysis duration
(`analysis.analysis_duration_seconds`), request latency for `/reports` and disk usage of
`AAP_DATA_DIR`.

## 10. Upgrades

1. Build the frontend into a versioned directory.
2. Install the new backend requirements into the virtual environment.
3. Restart the service (systemd `systemctl restart audio-analysis`).
4. Sessions from the previous version remain readable — the analysis payload carries a
   `schema_version` field; invalidate old sessions with `DELETE /api/sessions/{id}` if the schema
   changes in an incompatible way.

## 11. Capacity notes

* Analysis is CPU-bound; a 10-minute stereo file typically needs 20–60 s of CPU time.
* `AAP_MAX_CONCURRENT_JOBS=2` keeps memory at roughly 1–1.5 GB for 20-minute files.
* Memory is bounded by the artifact caps in `backend/app/config.py`
  (`max_spectrogram_frames=320`, `max_feature_points=1200`, `max_waveform_buckets=4000`,
  `pitch_analysis_seconds=30`, `hpss_analysis_seconds=120`).
* JSON reports are large for long files (≈ 3–7 MB for two files) because they embed the complete
  analysis payload. Use the CSV or PDF exports for archiving.
