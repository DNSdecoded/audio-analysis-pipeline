"""End-to-end API tests using the FastAPI test client."""

from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import click_track, sine


def _wav_bytes(data: np.ndarray, sr: int = 48000) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, data, sr, subtype="PCM_16", format="WAV")
    return buffer.getvalue()


def _create_session(client) -> str:
    response = client.post("/api/sessions", json={"name": "pytest"})
    assert response.status_code == 200
    return response.json()["id"]


def _upload(client, session_id: str, files: list[tuple[str, bytes]]) -> dict:
    payload = [("files", (name, data, "audio/wav")) for name, data in files]
    response = client.post(f"/api/sessions/{session_id}/files", files=payload)
    assert response.status_code == 200
    return response.json()


def _wait_for_analysis(client, session_id: str, expected: int, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    session = {}
    while time.time() < deadline:
        session = client.get(f"/api/sessions/{session_id}").json()
        done = sum(1 for file in session["files"] if file["has_analysis"] or file["status"] == "error")
        if done >= expected:
            return session
        time.sleep(0.5)
    raise AssertionError(f"analysis did not finish within {timeout}s: {session}")


@pytest.fixture(scope="module")
def analysed_session(request):
    """Create a session with two analysed files and share it across tests."""
    client = request.getfixturevalue("client")
    session_id = _create_session(client)
    tone = _wav_bytes(sine(frequency=440.0, amplitude=0.4, seconds=4.0))
    clicks = _wav_bytes(click_track(bpm=120.0, seconds=8.0))
    upload = _upload(client, session_id, [("tone.wav", tone), ("clicks.wav", clicks)])
    assert len(upload["files"]) == 2
    assert upload["errors"] == []

    response = client.post(f"/api/sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 2

    session = _wait_for_analysis(client, session_id, 2)
    assert all(file["has_analysis"] for file in session["files"])
    return session_id, session


def test_health_and_settings_endpoints(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["original_files_preserved"] is True
    assert "WAV" in health["supported_formats"]

    settings = client.get("/api/settings").json()
    assert settings["qc_thresholds"]
    assert settings["qc_threshold_schema"]
    assert settings["limits"]["max_file_size_mb"] > 0


def test_upload_validates_and_rejects_bad_files(client):
    session_id = _create_session(client)
    good = _wav_bytes(sine(frequency=220.0, amplitude=0.4, seconds=2.0))
    corrupt = b"RIFF\x00\x00\x00\x00WAVEjunkjunkjunk"

    result = _upload(client, session_id, [("good.wav", good), ("broken.wav", corrupt)])

    assert len(result["files"]) == 1
    assert result["files"][0]["original_name"] == "good.wav"
    assert result["files"][0]["metadata"]["sample_rate"] == 48000
    assert result["files"][0]["metadata"]["bit_depth"] == 16
    assert result["errors"][0]["file_name"] == "broken.wav"
    assert result["errors"][0]["errors"]


def test_unsupported_extension_is_rejected(client):
    session_id = _create_session(client)
    response = client.post(
        f"/api/sessions/{session_id}/files",
        files=[("files", ("notes.txt", b"not audio", "text/plain"))],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["files"] == []
    assert payload["errors"][0]["errors"]


def test_analysis_artifacts_and_overview(client, analysed_session):
    session_id, session = analysed_session
    file_id = session["files"][0]["id"]

    analysis = client.get(f"/api/sessions/{session_id}/files/{file_id}/analysis").json()
    assert analysis["file_id"] == file_id
    assert analysis["sha256"]
    assert analysis["loudness"]["integrated_lufs"] is not None
    assert analysis["qc"]["overall"] in {"normal", "information", "warning", "error"}
    assert analysis["methods"]["loudness"]

    overview = client.get(f"/api/sessions/{session_id}/overview").json()
    assert overview["totals"]["files"] == 2
    assert overview["totals"]["analysed"] == 2
    assert len(overview["files"]) == 2


def test_waveform_spectrum_and_spectrogram_endpoints(client, analysed_session):
    session_id, session = analysed_session
    file_id = session["files"][0]["id"]

    waveform = client.get(f"/api/sessions/{session_id}/files/{file_id}/waveform").json()
    assert waveform["bucket_count"] > 0
    assert len(waveform["times"]) == waveform["bucket_count"]

    spectrum = client.get(f"/api/sessions/{session_id}/files/{file_id}/spectrum").json()
    assert len(spectrum["frequencies_hz"]) == len(spectrum["average_dbfs"])

    spectrogram = client.get(f"/api/sessions/{session_id}/files/{file_id}/spectrogram").json()
    assert len(spectrogram["magnitude_db"]) == len(spectrogram["frequencies_hz"])


def test_compare_and_align_endpoints(client, analysed_session):
    session_id, session = analysed_session
    ids = [file["id"] for file in session["files"]]

    comparison = client.post(
        f"/api/sessions/{session_id}/compare",
        json={"file_ids": ids, "target_lufs": -14.0, "true_peak_limit": -1.0},
    )
    assert comparison.status_code == 200
    payload = comparison.json()
    assert payload["rows"]
    assert len(payload["files"]) == 2
    assert payload["gain_preview"]

    alignment = client.post(
        f"/api/sessions/{session_id}/align",
        json={"file_a": ids[0], "file_b": ids[1], "method": "auto"},
    )
    assert alignment.status_code == 200
    assert "offset_seconds" in alignment.json()


def test_qc_recompute_updates_classification(client, analysed_session):
    session_id, session = analysed_session
    file_id = session["files"][0]["id"]

    response = client.post(
        f"/api/sessions/{session_id}/qc/recompute",
        json={"thresholds": {"true_peak_warning_dbtp": -40.0, "true_peak_error_dbtp": -39.0}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"]
    assert payload["thresholds"]["true_peak_warning_dbtp"] == -40.0

    analysis = client.get(f"/api/sessions/{session_id}/files/{file_id}/analysis").json()
    true_peak = next(check for check in analysis["qc"]["checks"] if check["id"] == "true_peak")
    assert true_peak["severity"] == "error"

    # Restore the defaults for the remaining tests.
    client.post(f"/api/sessions/{session_id}/qc/recompute", json={"thresholds": None})


def test_report_exports_in_every_format(client, analysed_session):
    session_id, session = analysed_session
    ids = [file["id"] for file in session["files"]]

    expectations = {
        "pdf": b"%PDF",
        "json": b"{",
        "csv": b"file_name",
        "qc-csv": b"severity",
        "comparison-csv": b"parameter",
    }
    for fmt, marker in expectations.items():
        response = client.post(
            f"/api/sessions/{session_id}/reports",
            json={"format": fmt, "file_ids": ids, "include_comparison": True},
        )
        assert response.status_code == 200, response.text
        body = response.content
        assert len(body) > 100
        assert marker.lower() in body[:4000].lower()
        assert "attachment" in response.headers["content-disposition"]


def test_plot_endpoints_render_png(client, analysed_session):
    session_id, session = analysed_session
    file_id = session["files"][0]["id"]

    for kind in ("waveform", "spectrum", "spectrogram", "loudness", "stereo"):
        response = client.get(f"/api/sessions/{session_id}/files/{file_id}/plots/{kind}.png")
        assert response.status_code == 200, kind
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_segment_analysis_endpoint(client, analysed_session):
    session_id, session = analysed_session
    file_id = session["files"][0]["id"]

    response = client.post(
        f"/api/sessions/{session_id}/files/{file_id}/segment-analysis",
        json={"start": 0.5, "end": 2.5},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["segment"]["start"] == pytest.approx(0.5)
    assert payload["segment"]["end"] == pytest.approx(2.5)
    assert payload["loudness"]["integrated_lufs"] is not None


def test_session_settings_patch_and_file_removal(client, analysed_session):
    session_id, session = analysed_session
    file_id = session["files"][0]["id"]

    patched = client.patch(
        f"/api/sessions/{session_id}",
        json={"name": "renamed", "target_lufs": -16.0, "true_peak_limit": -1.5},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "renamed"
    assert patched.json()["settings"]["target_lufs"] == -16.0

    removed = client.delete(f"/api/sessions/{session_id}/files/{file_id}")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert len(removed.json()["session"]["files"]) == 1


def test_invalid_requests_return_client_errors(client):
    session_id = _create_session(client)
    assert client.post(f"/api/sessions/{session_id}/compare", json={"file_ids": []}).status_code == 400
    # A well-formed but unknown session id is a 404; a malformed id is rejected as a bad request.
    assert client.get(f"/api/sessions/ses_{'0' * 32}").status_code == 404
    assert client.get("/api/sessions/ses_does_not_exist").status_code == 400
