# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-26

First public release under the Apache License 2.0.

### Added
- FastAPI backend with a custom ITU-R BS.1770-4 / EBU R128 loudness meter (cross-checked against
  pyloudnorm: worst difference 0.0061 LU), time-domain, spectral, musical, stereo and dynamics analysis,
  deterministic quality control with configurable thresholds, multi-file comparison and alignment.
- Reports: PDF, JSON, measurements CSV, QC CSV, comparison CSV and 14 server-rendered plot types.
- React dashboard with 15 screens, Light ("Executive Slate & Cobalt") and Dark ("Obsidian & Electric Indigo")
  themes plus System mode, responsive from 390 px.
- Confirmation dialog for every destructive action; upload cancellation; client-side upload pre-checks
  (type, size, empty files, duplicates).
- Validated inputs for every analysis parameter (time ranges, FFT/hop, loudness targets, colour ranges,
  QC thresholds) with messages beside the field.
- Per-file loading and error states with Retry on all analysis screens.
- QC exports list every check (passed checks included) and name the limit that was crossed.
- Test suites: 106 backend tests, 46 frontend unit tests, 40 browser end-to-end tests; CI on Linux,
  Windows and macOS.

### Fixed (since the internal pre-release)
- Measurements CSV no longer fails (HTTP 500) when files differ in optional columns.
- Critical QC findings in the PDF and QC CSV now show the error limit, not the warning limit.
- Structured QC values in CSV are JSON instead of Python syntax.
- Opening a section from the Files page opens the selected file.
- Stereo and dynamics observations no longer show raw JSON; the stereo-width chart uses separate axes for
  ratio and dBFS.
- Exported plot files keep the server's file name (`<audio file>-<plot>.png`).
- Full list: 38 corrections across the frontend, the report/export logic and the repository configuration
  (internal audit notes, not published).

### Known limitations
- Browser verification covers Chromium; Firefox and Safari are not yet tested automatically.
- The comparison CSV always compares full files (segment mode is shown in the UI only).
- Audio playback does not work when `AAP_API_KEY` is set (the `<audio>` element cannot send the header).
- Analysis jobs cannot be cancelled once started.
