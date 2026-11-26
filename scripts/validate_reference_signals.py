"""Measure the generated reference signals and print a validation table.

Run after ``scripts/generate_test_audio.py``::

    python scripts/validate_reference_signals.py --audio backend/data/test_audio

The script measures each reference file with the real analysis pipeline and
prints the values that the documentation quotes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analysis.pipeline import run_full_analysis  # noqa: E402
from app.validation import validate_upload  # noqa: E402


def analyse(path: Path) -> dict:
    validation = validate_upload(path, path.name, path.suffix, path.stat().st_size)
    if not validation.get("ok"):
        raise SystemExit(f"{path.name} failed validation: {validation.get('errors')}")
    return run_full_analysis(
        path=path,
        ext=path.suffix,
        metadata=validation["metadata"],
        validation=validation,
        file_id="fil_" + "0" * 32,
        original_name=path.name,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", default="backend/data/test_audio")
    parser.add_argument("--json-out", default="docs/validation_results.json")
    args = parser.parse_args()

    audio_dir = Path(args.audio)
    files = sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in {".wav", ".flac", ".ogg", ".mp3"})
    results = {}

    header = f"{'file':34} {'LUFS':>8} {'dBTP':>8} {'peak':>8} {'RMS':>8} {'corr':>7} {'BPM':>7} {'key':>10} {'QC':>10}"
    print(header)
    print("-" * len(header))

    for path in files:
        analysis = analyse(path)
        loud = analysis["loudness"]
        td = analysis["time_domain"]
        musical = analysis["musical"]
        stereo = analysis["stereo"]
        correlation = stereo.get("correlation", {}).get("value")
        results[path.name] = {
            "integrated_lufs": loud.get("integrated_lufs"),
            "true_peak_dbtp": loud.get("true_peak_dbtp"),
            "sample_peak_dbfs": td["sample_peak"]["dbfs"],
            "rms_dbfs": td["rms"]["dbfs"],
            "dc_offset": td["dc_offset"]["max_abs"],
            "clipped_percent": td["clipping"]["clipped_percent"],
            "silence_percent": td["silence"]["percent"],
            "noise_floor_dbfs": td["noise"]["noise_floor_dbfs"],
            "snr_db": td["noise"]["snr_db"],
            "correlation": correlation,
            "tempo_bpm": musical.get("tempo", {}).get("bpm"),
            "key": musical.get("key", {}).get("key"),
            "key_confidence": musical.get("key", {}).get("confidence_label"),
            "qc_overall": analysis["qc"]["overall"],
            "qc_errors": analysis["qc"]["error_count"],
            "qc_warnings": analysis["qc"]["warning_count"],
            "bit_depth": analysis["metadata"].get("bit_depth"),
            "bit_depth_source": analysis["metadata"].get("bit_depth_source"),
            "bitrate_kbps": analysis["metadata"].get("bitrate_kbps"),
            "is_lossy": analysis["metadata"].get("is_lossy"),
        }
        row = results[path.name]
        print(
            f"{path.name:34} "
            f"{_fmt(row['integrated_lufs']):>8} {_fmt(row['true_peak_dbtp']):>8} {_fmt(row['sample_peak_dbfs']):>8} "
            f"{_fmt(row['rms_dbfs']):>8} {_fmt(correlation):>7} {_fmt(row['tempo_bpm']):>7} "
            f"{str(row['key']):>10} {row['qc_overall']:>10}"
        )

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    main()
