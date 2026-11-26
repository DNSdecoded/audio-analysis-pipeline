# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's
**Security → Report a vulnerability** (private advisory) on this repository. Do not open a public
issue for security problems.

Include the affected version, a description of the impact and the steps to reproduce. You should receive
an acknowledgement within 7 days. Fixes are released as patch versions and credited in the changelog
unless you ask otherwise.

## Deployment guidance

The server is designed for local or trusted-network use:

- It binds to `127.0.0.1` by default. Before exposing it, set `AAP_API_KEY`, put it behind a TLS reverse
  proxy and restrict `AAP_CORS_ORIGINS` (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).
- Uploaded files are validated by content, stored unmodified and deleted when the session expires
  (`AAP_SESSION_TTL_HOURS`).
- CSV exports neutralise spreadsheet formulas; error messages do not expose server file paths.
- Keep dependencies current (`pip install -U -r backend/requirements.txt`, `npm audit`), in particular PyAV
  and soundfile, which ship native decoders.
