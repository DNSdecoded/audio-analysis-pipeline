"""Report builder tests: CSV, JSON and PDF output."""

from __future__ import annotations

import csv
import io
import json

import pytest

from app.reporting import build_comparison_csv, build_csv, build_json_report, build_pdf, build_qc_csv
from conftest import sine


@pytest.fixture(scope="module")
def analysis(request):
    tmp_path_factory = request.getfixturevalue("tmp_path_factory")
    from app.analysis.pipeline import run_full_analysis
    from conftest import write_wav

    path = write_wav(
        tmp_path_factory.mktemp("reports") / "report.wav",
        sine(frequency=440.0, amplitude=0.4, seconds=4.0),
        48000,
    )
    return run_full_analysis(
        path=path,
        ext=".wav",
        metadata={"sample_rate": 48000, "channels": 1, "duration": 4.0},
        validation={"ok": True, "errors": [], "warnings": []},
        file_id="fil_report00000000000000000000000000",
        original_name="report.wav",
    )


def test_measurement_csv_has_a_row_per_file(analysis):
    content = build_csv([analysis])
    rows = list(csv.reader(io.StringIO(content)))

    assert rows[0][0] == "file_id"
    assert "file_name" in rows[0]
    assert len(rows) == 2
    assert "report.wav" in rows[1]
    assert "integrated_lufs" in rows[0]


def test_qc_csv_lists_every_check(analysis):
    content = build_qc_csv([analysis])
    rows = list(csv.reader(io.StringIO(content)))

    assert rows[0][0] == "file_id"
    assert any("severity" in cell.lower() for cell in rows[0])
    assert len(rows) >= 2


def test_json_report_is_serialisable_and_complete(analysis):
    payload = json.loads(build_json_report({"id": "ses_test", "name": "pytest", "settings": {}}, [analysis], None, None))

    assert payload["session"]
    assert payload["files"]
    assert payload["files"][0]["original_name"] == "report.wav"
    assert payload["files"][0]["loudness"]["integrated_lufs"] is not None
    assert payload["files"][0]["methods"]
    assert payload["disclaimer"]


def test_pdf_report_starts_with_the_pdf_signature(analysis):
    content = build_pdf({"id": "ses_test", "name": "pytest", "settings": {}}, [analysis], None, None)

    assert isinstance(content, (bytes, bytearray))
    assert bytes(content[:4]) == b"%PDF"
    assert len(content) > 5000


def test_comparison_csv_requires_a_comparison(analysis):
    from app.analysis.comparison import compare_analyses

    other = dict(analysis)
    comparison = compare_analyses(
        {"fil_a": analysis, "fil_b": other},
        ["fil_a", "fil_b"],
        {"fil_a": "a.wav", "fil_b": "b.wav"},
    )
    content = build_comparison_csv(comparison)
    rows = list(csv.reader(io.StringIO(content)))

    assert rows
    assert len(rows[0]) >= 2


# ----------------------------------------------------- report/export audit (RPT-xx)
def test_rpt01_measurements_csv_handles_files_with_different_columns(analysis):
    import copy

    no_bands = copy.deepcopy(analysis)
    no_bands["spectral"]["bands"]["bands"] = []
    rows = list(csv.DictReader(io.StringIO(build_csv([no_bands, analysis]))))
    assert len(rows) == 2
    assert rows[0]["band_bass_percent"] == ""
    assert rows[1]["band_bass_percent"] != ""


def test_rpt02_qc_csv_contains_passed_checks_too(analysis):
    rows = list(csv.DictReader(io.StringIO(build_qc_csv([analysis]))))
    assert len(rows) == len(analysis["qc"]["checks"])
    assert "normal" in {row["severity"] for row in rows}
    assert {"limit", "rule_id", "error_threshold_value"} <= set(rows[0])


def test_rpt03_structured_measurements_are_json_not_python_repr(analysis):
    import copy

    a = copy.deepcopy(analysis)
    a["qc"]["checks"][0]["measured_value"] = {"correlation": -1, "mono_loss_db": -85.4}
    rows = list(csv.DictReader(io.StringIO(build_qc_csv([a]))))
    value = next(r["measured_value"] for r in rows if r["rule_id"] == a["qc"]["checks"][0]["id"])
    assert json.loads(value) == {"correlation": -1, "mono_loss_db": -85.4}


def test_rpt04_critical_findings_name_the_error_limit():
    from app.analysis.qc import DEFAULT_THRESHOLDS, describe_limit

    check = {"id": "true_peak", "severity": "error", "threshold_value": -1.0, "threshold_unit": "dBTP warning"}
    assert describe_limit(check, DEFAULT_THRESHOLDS) == "critical >= 0 dBTP (warning >= -1 dBTP)"
    check["severity"] = "warning"
    assert describe_limit(check, DEFAULT_THRESHOLDS) == "-1 dBTP warning"
    corr = {"id": "correlation", "severity": "error", "threshold_value": -0.1, "threshold_unit": "r"}
    assert describe_limit(corr, DEFAULT_THRESHOLDS).startswith("critical <= -0.5 r")
