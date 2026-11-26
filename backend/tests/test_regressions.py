"""Regression tests for the defects recorded in docs/audits/BUG_AUDIT.md (local audit notes).

Every test uses a reference signal with a documented expected value and
tolerance, and asserts the *value*, not merely that a value exists.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from conftest import click_track, major_chord, sine, stereo_pair

SR = 48000


def _wav_bytes(data: np.ndarray, sr: int = SR, subtype: str = "PCM_16") -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, data, sr, subtype=subtype, format="WAV")
    return buffer.getvalue()


def _session_with(client, files: list[tuple[str, bytes]], name: str = "regression") -> tuple[str, list[str]]:
    session_id = client.post("/api/sessions", json={"name": name}).json()["id"]
    payload = [("files", (fname, data, "audio/wav")) for fname, data in files]
    upload = client.post(f"/api/sessions/{session_id}/files", files=payload).json()
    assert upload["errors"] == [], upload["errors"]
    return session_id, [f["id"] for f in upload["files"]]


def _analyse(client, session_id: str, timeout: float = 240.0) -> dict:
    assert client.post(f"/api/sessions/{session_id}/analyze", json={}).status_code == 200
    deadline = time.time() + timeout
    while time.time() < deadline:
        session = client.get(f"/api/sessions/{session_id}").json()
        if all(f["has_analysis"] or f["status"] == "error" for f in session["files"]):
            assert all(f["status"] == "complete" for f in session["files"]), session["files"]
            return session
        time.sleep(0.4)
    raise AssertionError("analysis timed out")


# ------------------------------------------------------------------ BUG-01/38
def _write_av(path: Path, codec: str, fmt: str, data: np.ndarray, sr: int = 44100) -> Path:
    av = pytest.importorskip("av")
    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=sr, layout="stereo")
        stream.format = fmt
        planar = np.stack([data, data])
        ints = (planar * 32767).astype(np.int16) if fmt.startswith("s16") else (planar * (2 ** 31 - 1)).astype(np.int32)
        if not fmt.endswith("p"):
            ints = ints.T.reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(ints, format=fmt, layout="stereo")
        frame.sample_rate = sr
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


@pytest.mark.parametrize("codec,fmt,ext", [("alac", "s16p", ".m4a"), ("pcm_s16le", "s16", ".mov"), ("pcm_s24le", "s32", ".mov")])
def test_integer_pcm_from_ffmpeg_is_scaled(tmp_path, codec, fmt, ext):
    from app.audio_io import decode_audio

    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(44100 * 2) / 44100)
    path = _write_av(tmp_path / f"t{ext}", codec, fmt, tone)
    data, sr, warnings = decode_audio(path)
    assert sr == 44100
    assert abs(float(np.max(np.abs(data))) - 0.5) < 0.002  # expected peak 0.5 (−6.02 dBFS)
    assert warnings == []


def test_alac_bit_depth_detected(tmp_path):
    from app.audio_io import probe_audio

    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(44100) / 44100)
    meta = probe_audio(_write_av(tmp_path / "t.m4a", "alac", "s16p", tone), ".m4a")
    assert meta["bit_depth"] == 16 and meta["is_lossy"] is False


# ---------------------------------------------------------------------- BUG-02
def test_qc_true_peak_of_exactly_zero_is_not_discarded():
    from app.analysis.qc import analyze_qc

    qc = analyze_qc({"loudness": {"true_peak_dbtp": 0.0}, "time_domain": {}, "stereo": {"supported": False}, "metadata": {}})
    check = next(c for c in qc["checks"] if c["id"] == "true_peak")
    assert check["measured_value"] == 0.0
    assert check["severity"] == "warning"  # > −1 dBTP warning, not > 0 dBTP error


def test_qc_missing_true_peak_is_information_not_normal():
    from app.analysis.qc import analyze_qc

    qc = analyze_qc({"loudness": {}, "time_domain": {}, "stereo": {"supported": False}, "metadata": {}})
    check = next(c for c in qc["checks"] if c["id"] == "true_peak")
    assert check["measured_value"] is None and check["severity"] == "information"


# ---------------------------------------------------------------------- BUG-03
def test_out_of_phase_stereo_is_not_silence():
    from app.analysis.time_domain import analyze_time_domain

    tone = sine(440, 0.5, 6.0)
    td = analyze_time_domain(stereo_pair(tone, -tone), SR)
    assert td["silence"]["percent"] == 0.0
    assert td["silence"]["digital_silence_duration_seconds"] == 0.0
    assert abs(td["rms"]["dbfs"] - (20 * np.log10(0.5 / np.sqrt(2)))) < 0.05  # −9.03 dBFS


def test_real_silence_is_still_detected():
    from app.analysis.time_domain import analyze_time_domain

    data = np.concatenate([np.zeros(SR * 3, dtype=np.float32), sine(440, 0.5, 3.0)])
    td = analyze_time_domain(stereo_pair(data, data), SR)
    assert 48.0 <= td["silence"]["percent"] <= 51.0  # 3 s of 6 s


# ---------------------------------------------------------------------- BUG-04
def test_spectral_feature_time_axis_covers_whole_file():
    from app.analysis.spectral import analyze_spectral

    spectral = analyze_spectral(sine(440, 0.4, 12.0), SR, 12.0)
    times = spectral["spectral_features"]["centroid_hz"]["series"]["times"]
    assert all(t is not None for t in times)
    assert times[0] == 0.0 and abs(max(times) - 12.0) < 0.1
    assert times == sorted(times)
    onset = spectral["onset_envelope"]
    assert len(onset["times"]) == len(onset["values"])
    centroid = spectral["spectral_features"]["centroid_hz"]["mean"]
    assert abs(centroid - 440.0) < 20.0  # pure tone centroid ≈ its frequency


# ---------------------------------------------------------------------- BUG-05
def test_five_one_channel_weighting_excludes_lfe_and_weights_surrounds():
    from app.analysis.loudness import measure_loudness

    n = SR * 6
    tone = 10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)
    lfe_only = np.zeros((n, 6), dtype=np.float32)
    lfe_only[:, 3] = tone
    assert measure_loudness(lfe_only, SR)["integrated_lufs"] is None
    front = np.zeros((n, 6), dtype=np.float32)
    front[:, 0] = tone
    surround = np.zeros((n, 6), dtype=np.float32)
    surround[:, 5] = tone  # BR
    lf = measure_loudness(front, SR)["integrated_lufs"]
    ls = measure_loudness(surround, SR)["integrated_lufs"]
    assert abs((ls - lf) - 10 * np.log10(1.41)) < 0.05  # +1.49 dB surround weight


# ------------------------------------------------------------------- BUG-06/17
def _music_like(seconds: float, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    levels = np.repeat(rng.uniform(0.05, 0.6, int(seconds * 4)), SR // 4)[: int(seconds * SR)]
    return (rng.standard_normal(levels.size) * levels).astype(np.float32)


def test_alignment_finds_known_offset_and_overlap(tmp_path):
    from app.analysis.alignment import align_files

    a = _music_like(12.0)
    sf.write(tmp_path / "a.wav", a, SR)
    sf.write(tmp_path / "b.wav", a[int(1.5 * SR):], SR)  # B starts 1.5 s into A
    result = align_files(tmp_path / "a.wav", tmp_path / "b.wav")
    assert abs(result["offset_seconds"] + 1.5) < 0.01
    assert abs(result["overlap_seconds"] - 10.5) < 0.02
    assert result["offset_samples_approx"] == -72000
    assert result["confidence_label"] in {"high", "medium"}


def test_alignment_of_unrelated_material_is_low_confidence(tmp_path):
    from app.analysis.alignment import align_files

    sf.write(tmp_path / "a.wav", _music_like(10.0, 1), SR)
    sf.write(tmp_path / "b.wav", sine(300, 0.3, 10.0), SR)
    for method in ("envelope", "auto"):
        result = align_files(tmp_path / "a.wav", tmp_path / "b.wav", method=method)
        assert result["confidence_label"] == "low", (method, result["confidence"])
        assert result["reliable"] is False


# ---------------------------------------------------------------------- BUG-10
def test_clipping_percent_uses_consistent_units():
    from app.analysis.time_domain import analyze_time_domain

    clipped = np.clip(sine(440, 1.5, 4.0), -1, 1)
    mono = analyze_time_domain(clipped[:, None], SR)["clipping"]
    stereo = analyze_time_domain(stereo_pair(clipped, clipped), SR)["clipping"]
    assert mono["clipped_percent"] == pytest.approx(stereo["clipped_percent"], abs=1e-6)
    assert stereo["clipped_samples"] == 2 * mono["clipped_samples"]
    assert stereo["clipped_frames"] == mono["clipped_samples"]
    one_side = analyze_time_domain(stereo_pair(clipped, sine(440, 0.2, 4.0)), SR)["clipping"]
    assert one_side["clipped_percent"] == pytest.approx(mono["clipped_percent"] / 2, abs=1e-4)


# ------------------------------------------------------------------ BUG-12/13
def test_silence_reports_unmeasurable_loudness_and_no_key():
    from app.analysis.loudness import gain_preview, measure_loudness
    from app.analysis.musical import detect_key
    from app.analysis.spectral import analyze_spectral

    loud = measure_loudness(np.zeros((SR * 4, 2), dtype=np.float32), SR)
    assert loud["integrated_lufs"] is None and loud["loudness_range_lu"] is None
    assert loud["peak_to_loudness_ratio_db"] is None and loud["crest_factor_db"] is None
    assert all(v is None for v in loud["momentary"]["lufs"])
    assert gain_preview(None, None, None, -14.0, -1.0)["supported"] is False
    spectral = analyze_spectral(np.zeros(SR * 3, dtype=np.float32), SR, 3.0)
    key = detect_key(np.asarray(spectral["chroma"]["mean_energy"]))
    assert key["supported"] is False and key["key"] is None


def test_partial_silence_minimum_loudness_is_not_a_floor_value():
    from app.analysis.loudness import measure_loudness

    data = np.concatenate([np.zeros(SR * 3, dtype=np.float32), sine(1000, 10 ** (-23 / 20), 10.0)])
    loud = measure_loudness(stereo_pair(data, data), SR)
    assert loud["momentary_min_lufs"] > -100.0  # was −200.69 (1e-20 floor)
    # Blocks straddling the silence→tone edge pass the relative gate and pull
    # the result slightly below −23 (−23.1 LUFS); ±0.2 LU covers that.
    assert abs(loud["integrated_lufs"] - (-23.0)) < 0.2


# ------------------------------------------------------------ EBU reference
def test_ebu_tech_3341_stereo_sine_minus_23():
    from app.analysis.loudness import measure_loudness

    tone = sine(1000, 10 ** (-23 / 20), 20.0)
    assert abs(measure_loudness(stereo_pair(tone, tone), SR)["integrated_lufs"] + 23.0) < 0.1


@pytest.mark.parametrize("levels,expected", [((-20, -30), 10.0), ((-20, -15), 5.0), ((-40, -20), 20.0), ((-50, -35, -20, -35, -50), 15.0)])
def test_ebu_tech_3342_loudness_range(levels, expected):
    from app.analysis.loudness import measure_loudness

    parts = [sine(1000, 10 ** (level / 20), 20.0) for level in levels]
    data = np.concatenate(parts)
    lra = measure_loudness(stereo_pair(data, data), SR)["loudness_range_lu"]
    assert abs(lra - expected) <= 1.0, lra  # Tech 3342 tolerance ±1 LU


# ---------------------------------------------------------------------- BUG-14
def test_tempo_accuracy_and_half_time_correction():
    from app.analysis.musical import analyze_musical

    for bpm in (90.0, 120.0, 175.0):
        tempo = analyze_musical(click_track(bpm, 20.0), SR, 20.0)["tempo"]
        assert abs(tempo["bpm"] - bpm) / bpm < 0.01, (bpm, tempo["bpm"])  # ±1 %
        assert tempo["confidence_label"] == "high"


def test_tempo_of_noise_is_low_confidence():
    from app.analysis.musical import analyze_musical

    noise = (0.2 * np.random.default_rng(3).standard_normal(SR * 12)).astype(np.float32)
    tempo = analyze_musical(noise, SR, 12.0)["tempo"]
    assert tempo["confidence_label"] == "low"
    assert tempo["periodicity"] < 0.3


# ---------------------------------------------------------------------- BUG-15
def test_polyphonic_input_is_not_reported_as_reliable_pitch():
    from app.analysis.musical import analyze_musical

    pitch = analyze_musical(major_chord(seconds=6.0), SR, 6.0)["pitch"]
    if pitch.get("supported"):
        assert pitch["reliable_single_pitch"] is False
        assert pitch["confidence_label"] == "low"


def test_monophonic_pitch_is_accurate_and_reliable():
    from app.analysis.musical import analyze_musical

    t = np.arange(SR * 4) / SR
    tone = sum(0.3 / h * np.sin(2 * np.pi * 220 * h * t) for h in (1, 2, 3, 4)).astype(np.float32)
    pitch = analyze_musical(tone, SR, 4.0)["pitch"]
    assert abs(pitch["f0_median_hz"] - 220.0) < 1.0  # no octave error
    assert pitch["reliable_single_pitch"] is True


# ---------------------------------------------------------------------- BUG-16
def test_sample_clipping_is_not_reported_as_intersample_over():
    from app.analysis.time_domain import analyze_time_domain

    clipped = np.clip(sine(997, 1.5, 4.0), -1, 1)
    clip = analyze_time_domain(clipped[:, None], SR)["clipping"]
    assert clip["clipped_samples"] > 0 and clip["intersample_overs"] is False
    # Pure ISP: fs/4 sine with 45° phase peaks between samples at +3 dB.
    isp = sine(SR / 4, 0.99, 4.0, phase=np.pi / 4)
    result = analyze_time_domain(isp[:, None], SR)["clipping"]
    assert result["clipped_samples"] == 0 and result["intersample_overs"] is True


# ---------------------------------------------------------------------- BUG-22
def test_gain_preview_respects_true_peak_limit():
    from app.analysis.loudness import gain_preview

    g = gain_preview(-20.0, -2.0, -1.5, -14.0, -1.0)
    assert g["gain_db"] == 6.0  # target − measured
    assert g["true_peak_status"] == "true_peak_limit_exceeded"
    assert g["target_reachable_with_gain_only"] is False
    assert g["max_gain_within_true_peak_limit_db"] == 0.5
    assert g["recommended_gain_db"] == 0.5
    assert g["peak_control_required_db"] == 5.5
    ok = gain_preview(-20.0, -12.0, -11.5, -14.0, -1.0)
    assert ok["target_reachable_with_gain_only"] is True and ok["recommended_gain_db"] == 6.0


# ---------------------------------------------------------------------- BUG-23
def test_silent_stereo_correlation_is_undefined():
    from app.analysis.stereo import analyze_stereo

    s = analyze_stereo(np.zeros((SR * 2, 2), dtype=np.float32), SR)
    assert s["correlation"]["value"] is None
    tone = sine(440, 0.5, 3.0)
    assert analyze_stereo(stereo_pair(tone, -tone), SR)["correlation"]["value"] == pytest.approx(-1.0, abs=1e-3)
    assert analyze_stereo(stereo_pair(tone, tone), SR)["correlation"]["value"] == pytest.approx(1.0, abs=1e-3)


# ------------------------------------------------------------------ BUG-28/34
def test_decode_errors_do_not_expose_server_paths(tmp_path):
    from app.audio_io import DecodeError, decode_audio

    path = tmp_path / "private_storage_dir" / "original.wav"
    path.parent.mkdir()
    path.write_bytes(b"RIFF....WAVEjunk" * 20)
    with pytest.raises(DecodeError) as excinfo:
        decode_audio(path)
    assert "private_storage_dir" not in str(excinfo.value)


def test_threshold_merge_ignores_invalid_sample_rates():
    from app.analysis.qc import merge_thresholds

    merged = merge_thresholds({"common_sample_rates": ["abc", None, 48000, "44100"]})
    assert merged["common_sample_rates"] == [44100, 48000]


# --------------------------------------------------- API-level regressions
@pytest.fixture(scope="module")
def tricky_session(request):
    client = request.getfixturevalue("client")
    tone = sine(440, 0.4, 6.0)
    files = [
        ("Café & <b Tom.wav", _wav_bytes(tone)),
        ("mix.wav", _wav_bytes(tone * 0.5)),
        ("mix.wav", _wav_bytes(tone * 0.25)),
        ("=HYPERLINK(1).wav", _wav_bytes(tone * 0.3)),
    ]
    session_id, ids = _session_with(client, files, name="R&B <mix>")
    _analyse(client, session_id)
    return client, session_id, ids


def test_waveform_and_spectrogram_ranges_use_absolute_times(tricky_session):
    client, session_id, ids = tricky_session
    w = client.get(f"/api/sessions/{session_id}/files/{ids[1]}/waveform", params={"start": 3.0, "end": 4.0, "buckets": 200}).json()
    assert 3.0 <= w["times"][0] < 3.01 and 3.99 < w["times"][-1] <= 4.0
    s = client.get(f"/api/sessions/{session_id}/files/{ids[1]}/spectrogram", params={"start": 2.0, "end": 4.0, "n_fft": 2048}).json()
    assert 2.0 <= s["times"][0] and s["times"][-1] <= 4.05


def test_plot_png_for_non_ascii_file_name(tricky_session):
    client, session_id, ids = tricky_session
    response = client.get(f"/api/sessions/{session_id}/files/{ids[0]}/plots/waveform.png")
    assert response.status_code == 200 and response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "filename*=UTF-8''Caf%C3%A9" in response.headers["content-disposition"]


def test_pdf_handles_markup_characters_in_names(tricky_session):
    client, session_id, _ids = tricky_session
    response = client.post(f"/api/sessions/{session_id}/reports", json={"format": "pdf"})
    assert response.status_code == 200 and response.content[:4] == b"%PDF"


def test_comparison_csv_keeps_duplicate_named_files_separate(tricky_session):
    client, session_id, ids = tricky_session
    response = client.post(f"/api/sessions/{session_id}/reports", json={"format": "comparison-csv"})
    import csv

    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    header = rows[0]
    mix_columns = [i for i, name in enumerate(header) if name.startswith("mix.wav [")]
    assert len(mix_columns) == 2
    rms = next(row for row in rows if row[0] == "RMS level")
    a, b = (float(rms[i]) for i in mix_columns)
    assert abs(abs(a - b) - 6.02) < 0.05  # 0.5 vs 0.25 amplitude


def test_csv_exports_neutralise_formulas(tricky_session):
    client, session_id, _ids = tricky_session
    for fmt in ("csv", "qc-csv", "comparison-csv"):
        body = client.post(f"/api/sessions/{session_id}/reports", json={"format": fmt}).content.decode("utf-8-sig")
        for line in body.splitlines():
            for cell in line.split(","):
                assert not cell.startswith("=HYPERLINK"), (fmt, line[:80])
    measurements = client.post(f"/api/sessions/{session_id}/reports", json={"format": "csv"}).content.decode("utf-8-sig")
    assert "-" in measurements  # negative numbers are still plain numbers


def test_exported_json_matches_stored_analysis(tricky_session):
    client, session_id, ids = tricky_session
    report = json.loads(client.post(f"/api/sessions/{session_id}/reports", json={"format": "json", "file_ids": [ids[1]]}).content)
    stored = client.get(f"/api/sessions/{session_id}/files/{ids[1]}/analysis").json()
    assert report["files"][0]["loudness"]["integrated_lufs"] == stored["loudness"]["integrated_lufs"]
    assert report["files"][0]["file_id"] == ids[1]


def test_comparison_gain_preview_for_silent_file(client):
    session_id, ids = _session_with(client, [("sil.wav", _wav_bytes(np.zeros(SR * 4, dtype=np.float32))), ("t.wav", _wav_bytes(sine(440, 0.4, 4.0)))])
    _analyse(client, session_id)
    comparison = client.post(f"/api/sessions/{session_id}/compare", json={"file_ids": ids}).json()
    silent = next(row for row in comparison["gain_preview"] if row["file_id"] == ids[0])
    assert silent["supported"] is False and silent["gain_db"] is None and silent["status"] == "unsupported"
    tone = next(row for row in comparison["gain_preview"] if row["file_id"] == ids[1])
    assert tone["supported"] is True and tone["gain_db"] is not None


def test_interrupted_analysis_can_be_resubmitted_and_recovered(client):
    from app.jobs import jobs
    from app.storage import store

    session_id, ids = _session_with(client, [("t.wav", _wav_bytes(sine(440, 0.4, 3.0)))])
    store.update_file(session_id, ids[0], status="analyzing", stage="Measuring", progress=40)
    assert jobs.recover_interrupted() >= 1
    record = store.get_file(session_id, ids[0])
    assert record["status"] == "error" and "interrupted" in record["error"].lower()
    store.update_file(session_id, ids[0], status="queued")
    response = client.post(f"/api/sessions/{session_id}/analyze", json={"file_ids": ids}).json()
    assert len(response["jobs"]) == 1


def test_analyze_unvalidated_file_is_a_client_error(client):
    from app.storage import store

    session_id = client.post("/api/sessions", json={}).json()["id"]
    record = store.add_file(session_id, "a.wav", ".wav", io.BytesIO(b"abc"), 1000)
    response = client.post(f"/api/sessions/{session_id}/files/{record['id']}/analyze")
    assert response.status_code == 409


def test_oversized_upload_request_is_rejected_early(client):
    session_id = client.post("/api/sessions", json={}).json()["id"]
    response = client.post(
        f"/api/sessions/{session_id}/files",
        content=b"x",
        headers={"content-length": str(10 ** 12), "content-type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 413


def test_original_upload_is_byte_identical_after_analysis(tricky_session):
    client, session_id, ids = tricky_session
    audio = client.get(f"/api/sessions/{session_id}/files/{ids[1]}/audio").content
    assert audio == _wav_bytes(sine(440, 0.4, 6.0) * 0.5)
