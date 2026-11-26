"""End-to-end smoke test against a running server.

Usage::

    python scripts/smoke_test.py --base http://127.0.0.1:8000

Exercises the complete documented workflow over HTTP: health, session creation,
multi-file upload, background analysis, artifact retrieval, plot rendering,
comparison, alignment, QC re-classification and all five report formats.

Exit code 0 means every step succeeded.
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

import numpy as np

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx is required: pip install httpx")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "backend" / "data" / "test_audio"


def _wav_bytes(data: np.ndarray, sr: int = 48000) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, data, sr, subtype="PCM_16", format="WAV")
    return buffer.getvalue()


def _sine(frequency: float, amplitude: float, seconds: float, sr: int = 48000) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def _click(bpm: float = 120.0, seconds: float = 8.0, sr: int = 48000) -> np.ndarray:
    signal = np.zeros(int(sr * seconds), dtype=np.float32)
    click = np.arange(int(sr * 0.02)) / sr
    burst = 0.9 * np.sin(2 * np.pi * 1800.0 * click) * np.exp(-click * 120.0)
    step = int(sr * 60.0 / bpm)
    for position in range(0, signal.size, step):
        end = min(signal.size, position + burst.size)
        signal[position:end] += burst[: end - position]
    return signal


class Smoke:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.client = httpx.Client(base_url=self.base, timeout=180.0)
        self.failures: list[str] = []
        self.checks = 0

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        self.checks += 1
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            self.failures.append(label)
        return condition

    # ------------------------------------------------------------------ helpers
    def _sample_files(self) -> list[tuple[str, bytes]]:
        files: list[tuple[str, bytes]] = []
        if REFERENCE.exists():
            for name in ("sine_1khz_mono_48k.wav", "c_major_120bpm.wav"):
                path = REFERENCE / name
                if path.exists():
                    files.append((name, path.read_bytes()))
        if len(files) < 2:
            files = [
                ("tone.wav", _wav_bytes(_sine(440.0, 0.4, 4.0))),
                ("clicks.wav", _wav_bytes(_click())),
            ]
        return files

    def _wait_for_analysis(self, session_id: str, expected: int, timeout: float = 240.0) -> dict:
        deadline = time.time() + timeout
        session: dict = {}
        while time.time() < deadline:
            response = self.client.get(f"/api/sessions/{session_id}")
            if response.status_code == 200:
                session = response.json()
                done = sum(
                    1 for f in session.get("files", [])
                    if f.get("has_analysis") or f.get("status") == "error"
                )
                if done >= expected:
                    return session
            time.sleep(0.5)
        print(f"       timed out after {timeout}s waiting for {expected} analyses")
        return session

    # -------------------------------------------------------------------- main
    def run(self) -> int:
        print(f"Smoke test against {self.base}\n")

        print("Health and settings")
        health = self.client.get("/api/health")
        self.check("GET /api/health", health.status_code == 200, f"HTTP {health.status_code}")
        if health.status_code == 200:
            body = health.json()
            self.check("health reports status ok", body.get("status") == "ok")
            self.check("health confirms originals preserved", body.get("original_files_preserved") is True)
            self.check("health lists WAV", "WAV" in body.get("supported_formats", []))
        settings = self.client.get("/api/settings")
        self.check("GET /api/settings", settings.status_code == 200, f"HTTP {settings.status_code}")
        if settings.status_code == 200:
            payload = settings.json()
            self.check("settings expose QC thresholds", bool(payload.get("qc_thresholds")))
            self.check("settings expose the threshold schema", bool(payload.get("qc_threshold_schema")))
            self.check("settings expose the limits", (payload.get("limits") or {}).get("max_file_size_mb", 0) > 0)
        root = self.client.get("/")
        self.check(
            "GET / serves the built dashboard",
            root.status_code == 200 and "<html" in root.text.lower(),
            f"HTTP {root.status_code}",
        )

        print("\nSession and upload")
        created = self.client.post("/api/sessions", json={"name": "smoke"})
        self.check("POST /api/sessions", created.status_code == 200, f"HTTP {created.status_code}")
        if created.status_code != 200:
            return self.finish()
        session_id = created.json()["id"]
        print(f"       session {session_id}")

        samples = self._sample_files()
        payload = [("files", (name, data, "audio/wav")) for name, data in samples]
        uploaded = self.client.post(f"/api/sessions/{session_id}/files", files=payload)
        self.check("POST files (multi-upload)", uploaded.status_code == 200, f"HTTP {uploaded.status_code}")
        if uploaded.status_code != 200:
            return self.finish()
        body = uploaded.json()
        accepted = body.get("files", [])
        self.check("all files accepted", len(accepted) == len(samples), f"{len(accepted)}/{len(samples)}")
        self.check("no upload errors", body.get("errors") == [], str(body.get("errors")))
        if accepted:
            metadata = accepted[0].get("metadata", {})
            self.check("metadata reports the native sample rate", metadata.get("sample_rate") == 48000)
            self.check("metadata reports the PCM bit depth", metadata.get("bit_depth") == 16)
            self.check("original file name preserved", accepted[0].get("original_name") == samples[0][0])

        corrupt = self.client.post(
            f"/api/sessions/{session_id}/files",
            files=[("files", ("broken.wav", b"RIFF\x00\x00\x00\x00WAVEjunkjunkjunk", "audio/wav"))],
        )
        corrupt_body = corrupt.json() if corrupt.status_code == 200 else {}
        self.check(
            "corrupt file is rejected",
            corrupt.status_code == 200 and bool(corrupt_body.get("errors")),
            str(corrupt_body.get("errors")),
        )

        unsupported = self.client.post(
            f"/api/sessions/{session_id}/files",
            files=[("files", ("notes.txt", b"not audio", "text/plain"))],
        )
        unsupported_body = unsupported.json() if unsupported.status_code == 200 else {}
        self.check(
            "unsupported extension is rejected",
            unsupported.status_code == 200 and bool(unsupported_body.get("errors")),
        )

        print("\nAnalysis")
        started = self.client.post(f"/api/sessions/{session_id}/analyze", json={})
        self.check("POST analyze", started.status_code == 200, f"HTTP {started.status_code}")
        if started.status_code == 200:
            self.check("one job per file", len(started.json().get("jobs", [])) == len(samples))
        expected = len(accepted)
        session = self._wait_for_analysis(session_id, expected)
        analysed = [f for f in session.get("files", []) if f.get("has_analysis")]
        self.check("all files analysed", len(analysed) == expected, f"{len(analysed)}/{expected}")
        if not analysed:
            return self.finish()

        file_id = analysed[0]["id"]
        artifact_response = self.client.get(f"/api/sessions/{session_id}/files/{file_id}/analysis")
        self.check("GET analysis artifact", artifact_response.status_code == 200, f"HTTP {artifact_response.status_code}")
        if artifact_response.status_code == 200:
            artifact = artifact_response.json()
            self.check("artifact has a sha256", bool(artifact.get("sha256")))
            self.check(
                "artifact has integrated loudness",
                artifact.get("loudness", {}).get("integrated_lufs") is not None,
            )
            self.check(
                "artifact has a true peak",
                artifact.get("loudness", {}).get("true_peak_dbtp") is not None,
            )
            self.check(
                "artifact has a QC verdict",
                artifact.get("qc", {}).get("overall") in {"normal", "information", "warning", "error"},
            )
            self.check("artifact documents its methods", bool(artifact.get("methods")))
            self.check(
                "every QC check has an explanation and a recommendation",
                all(c.get("explanation") and c.get("recommendation") for c in artifact.get("qc", {}).get("checks", [])),
            )
            self.check(
                "artifact has waveform buckets",
                artifact.get("time_domain", {}).get("waveform", {}).get("bucket_count", 0) > 0,
            )
            self.check(
                "artifact has all seven frequency bands",
                len(artifact.get("spectral", {}).get("bands", {}).get("bands", [])) == 7,
            )
            stereo = artifact.get("stereo", {})
            if stereo.get("mono"):
                self.check(
                    "mono file reports no stereo values",
                    "correlation" not in stereo and "mid_side" not in stereo,
                )

        overview = self.client.get(f"/api/sessions/{session_id}/overview")
        self.check("GET overview", overview.status_code == 200, f"HTTP {overview.status_code}")
        if overview.status_code == 200:
            totals = overview.json().get("totals", {})
            self.check("overview counts the files", totals.get("files") == expected)
            self.check("overview counts the analysed files", totals.get("analysed") == expected)

        print("\nData and plots")
        for kind in ("waveform", "spectrum", "spectrogram"):
            response = self.client.get(f"/api/sessions/{session_id}/files/{file_id}/{kind}")
            self.check(f"GET {kind}", response.status_code == 200, f"HTTP {response.status_code}")

        for kind in ("waveform", "spectrum", "spectrogram", "loudness", "stereo"):
            response = self.client.get(f"/api/sessions/{session_id}/files/{file_id}/plots/{kind}.png")
            self.check(
                f"PNG plot {kind}",
                response.status_code == 200 and response.content[:8] == b"\x89PNG\r\n\x1a\n",
                f"HTTP {response.status_code}",
            )

        print("\nComparison, alignment and QC")
        ids = [f["id"] for f in session.get("files", [])]
        comparison = self.client.post(
            f"/api/sessions/{session_id}/compare",
            json={"file_ids": ids, "target_lufs": -14.0, "true_peak_limit": -1.0},
        )
        self.check("POST compare", comparison.status_code == 200, f"HTTP {comparison.status_code}")
        if comparison.status_code == 200:
            payload = comparison.json()
            self.check("comparison has rows", bool(payload.get("rows")))
            self.check("comparison has a gain preview", bool(payload.get("gain_preview")))

        if len(ids) >= 2:
            alignment = self.client.post(
                f"/api/sessions/{session_id}/align",
                json={"file_a": ids[0], "file_b": ids[1], "method": "auto"},
            )
            self.check("POST align", alignment.status_code == 200, f"HTTP {alignment.status_code}")
            if alignment.status_code == 200:
                payload = alignment.json()
                self.check("alignment reports an offset field", "offset_seconds" in payload)
                self.check("alignment declares that the audio is untouched", payload.get("does_not_modify_audio") is True)

        recomputed = self.client.post(
            f"/api/sessions/{session_id}/qc/recompute",
            json={"thresholds": {"true_peak_warning_dbtp": -40.0, "true_peak_error_dbtp": -39.0}},
        )
        self.check("POST qc/recompute", recomputed.status_code == 200, f"HTTP {recomputed.status_code}")
        if recomputed.status_code == 200:
            payload = recomputed.json()
            self.check("qc recompute updated every analysed file", len(payload.get("updated", [])) == expected)
            self.check(
                "qc recompute echoes the new thresholds",
                payload.get("thresholds", {}).get("true_peak_warning_dbtp") == -40.0,
            )
            artifact = self.client.get(f"/api/sessions/{session_id}/files/{file_id}/analysis").json()
            true_peak = next(
                (c for c in artifact.get("qc", {}).get("checks", []) if c.get("id") == "true_peak"),
                {},
            )
            self.check("the tightened threshold reclassifies the true peak", true_peak.get("severity") == "error")
            # Restore the defaults for anything that runs after this script.
            self.client.post(f"/api/sessions/{session_id}/qc/recompute", json={"thresholds": None})

        print("\nReports")
        expectations = {
            "pdf": b"%PDF",
            "json": b"{",
            "csv": b"file_id",
            "qc-csv": b"severity",
            "comparison-csv": b"parameter",
        }
        for fmt, marker in expectations.items():
            response = self.client.post(
                f"/api/sessions/{session_id}/reports",
                json={"format": fmt, "file_ids": ids, "include_comparison": True},
            )
            ok = response.status_code == 200 and marker.lower() in response.content[:4000].lower()
            self.check(f"report {fmt}", ok, f"HTTP {response.status_code}, {len(response.content)} bytes")

        print("\nSession cleanup")
        deleted = self.client.delete(f"/api/sessions/{session_id}")
        self.check("DELETE session", deleted.status_code == 200, f"HTTP {deleted.status_code}")
        gone = self.client.get(f"/api/sessions/{session_id}")
        self.check("the deleted session now returns 404", gone.status_code == 404, f"HTTP {gone.status_code}")

        return self.finish()

    def finish(self) -> int:
        print(f"\n{'=' * 64}")
        if self.failures:
            print(f"RESULT: FAIL - {len(self.failures)} of {self.checks} checks failed")
            for failure in self.failures:
                print(f"  - {failure}")
            return 1
        print(f"RESULT: PASS - all {self.checks} checks succeeded")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        smoke = Smoke(args.base)
    except Exception as exc:
        print(f"could not connect to {args.base}: {exc}")
        return 2
    try:
        return smoke.run()
    finally:
        smoke.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
