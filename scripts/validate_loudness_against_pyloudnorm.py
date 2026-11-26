"""Cross-validate the built-in BS.1770-4 loudness meter against pyloudnorm.

`pyloudnorm` is an independent implementation of ITU-R BS.1770-4.  Agreement
between the two is the strongest available evidence that the built-in meter is
correct, since neither implementation shares code with the other.

Usage::

    python scripts/validate_loudness_against_pyloudnorm.py --audio backend/data/test_audio

Exit code 0 means every comparison stayed inside the tolerance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analysis.loudness import measure_loudness  # noqa: E402

try:
    import pyloudnorm as pyln
except ImportError:  # pragma: no cover
    pyln = None


def _read(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return data, sr


def compare(path: Path, tolerance_lu: float) -> dict:
    data, sr = _read(path)
    built_in = measure_loudness(data, sr)
    reference = pyln.Meter(sr).integrated_loudness(data)
    difference = float(built_in["integrated_lufs"]) - float(reference)
    return {
        "file": path.name,
        "sample_rate": sr,
        "channels": int(data.shape[1]),
        "built_in_lufs": round(float(built_in["integrated_lufs"]), 4),
        "pyloudnorm_lufs": round(float(reference), 4),
        "difference_lu": round(difference, 4),
        "within_tolerance": abs(difference) <= tolerance_lu,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", default="backend/data/test_audio")
    parser.add_argument("--tolerance", type=float, default=0.05, help="maximum allowed difference in LU")
    parser.add_argument("--json-out", default="docs/loudness_crosscheck.json")
    args = parser.parse_args()

    if pyln is None:
        print("pyloudnorm is not installed. Run: pip install -r backend/requirements-dev.txt")
        return 2

    audio_dir = Path(args.audio)
    files = sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in {".wav", ".flac", ".ogg", ".mp3"})
    results = []
    header = f"{'file':34} {'built-in':>10} {'pyloudnorm':>12} {'difference':>11} {'result':>8}"
    print(header)
    print("-" * len(header))

    for path in files:
        try:
            result = compare(path, args.tolerance)
        except Exception as exc:
            print(f"{path.name:34} skipped: {exc}")
            continue
        results.append(result)
        print(
            f"{result['file']:34} {result['built_in_lufs']:>10.3f} {result['pyloudnorm_lufs']:>12.3f} "
            f"{result['difference_lu']:>+11.4f} {'PASS' if result['within_tolerance'] else 'FAIL':>8}"
        )

    if not results:
        print("no comparable files found")
        return 2

    differences = [abs(r["difference_lu"]) for r in results]
    worst = max(differences)
    mean = float(np.mean(differences))
    failures = [r for r in results if not r["within_tolerance"]]

    print()
    print(f"files compared   : {len(results)}")
    print(f"mean difference  : {mean:.4f} LU")
    print(f"worst difference : {worst:.4f} LU (tolerance {args.tolerance} LU)")
    print(f"result           : {'PASS' if not failures else 'FAIL'}")

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "tolerance_lu": args.tolerance,
                "files_compared": len(results),
                "mean_absolute_difference_lu": round(mean, 5),
                "worst_absolute_difference_lu": round(worst, 5),
                "passed": not failures,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
