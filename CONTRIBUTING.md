# Contributing

Thank you for helping improve the Audio Analysis Pipeline. Contributions are accepted under the
[Apache License 2.0](LICENSE); by submitting a pull request you agree that your contribution is licensed
under the same terms (Apache-2.0, section 5).

## Development setup

See [docs/INSTALLATION.md](docs/INSTALLATION.md). In short (Python 3.11/3.12, Node 22.12+):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements-dev.txt -r frontend/e2e/requirements.txt
python -m playwright install chromium
cd frontend && npm ci && npm run build
```

## Before opening a pull request

```bash
cd backend && python -m pytest                       # backend
cd ../frontend && npx tsc -b && npm test && npm run build
# browser tests: start the server on port 8765 first
cd ../backend && python -m uvicorn app.main:app --port 8765
python -m pytest frontend/e2e -q                     # from the repository root
```

## Ground rules

- **No simulated data.** Every value shown in the UI or a report must come from the uploaded audio. Estimates
  (key, tempo, pitch) must be labelled with their confidence.
- **Originals are never modified.** Gain, alignment and QC are analysis/preview operations only.
- Add a test for every bug fix and every new measurement (analytic reference signals live in
  `scripts/generate_test_audio.py`).
- UI changes use the design tokens in `frontend/src/styles.css` (see [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md)),
  work in both themes, keep WCAG 2.2 AA (run `python frontend/e2e/audit.py --out <dir>`), and validate
  inputs with `frontend/src/lib/inputValidation.ts`.
- Keep pull requests focused; describe what changed and how it was verified.
- Do not commit uploaded audio, session data (`/data/`), `.env` files or local AI-assistant configuration
  (all are git-ignored).
