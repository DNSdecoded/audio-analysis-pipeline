"""Regression tests for the second UI/UX audit (docs/audits/UI_UX_FIX_LOG.md, FE-xx IDs).

Real backend, real reference audio, Chromium.  Start the server first:

    cd backend && python -m uvicorn app.main:app --port 8765
    python -m pytest frontend/e2e/test_audit_fixes.py -q
"""

from __future__ import annotations

import re
import time

import httpx
import pytest
from playwright.sync_api import expect

from test_ui import AUDIO, BASE, _go, _ids, _page, _seed  # noqa: F401  (shared helpers)

SEED = ["c_major_120bpm.wav", "out_of_phase_stereo.wav", "clipped_220.wav", "mono_1k.wav"]


@pytest.fixture(scope="module")
def session():
    try:
        httpx.get(f"{BASE}/api/health", timeout=5).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"server not reachable at {BASE}: {exc}")
    state = _seed(SEED, "Audit fixes session")
    yield state
    httpx.delete(f"{BASE}/api/sessions/{state['id']}")


def _fresh(files: list[str], name: str) -> dict:
    return _seed(files, name)


def _file_names(session_id: str) -> list[str]:
    return sorted(f["original_name"] for f in httpx.get(f"{BASE}/api/sessions/{session_id}").json()["files"])


# --------------------------------------------------------------- FE-01
def test_fe01_files_section_links_open_the_selected_file(browser, session):
    ids = _ids(session)
    page = _page(browser, session["id"])
    _go(page, "#/files")
    page.locator(".file-list-item", has_text="clipped_220.wav").click()
    page.locator(".quick-nav").get_by_role("button", name="Waveform").click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Waveform analysis")
    expect(page.get_by_label("Active file")).to_have_value(ids["clipped_220.wav"])
    assert f"file={ids['clipped_220.wav']}" in page.url
    # and the selection made on Files is the shared active file
    page.get_by_role("navigation", name="Sections").get_by_role("link", name="Stereo & phase").click()
    expect(page.get_by_label("Active file")).to_have_value(ids["clipped_220.wav"])
    assert page.errors == []


# --------------------------------------------------------------- FE-02
def test_fe02_remove_requires_confirmation_and_only_removes_that_file(browser):
    state = _fresh(["mono_1k.wav", "stereo_tones.wav", "clipped_220.wav"], "Remove E2E")
    page = _page(browser, state["id"])
    _go(page, "#/upload")
    page.get_by_role("button", name="Remove stereo_tones.wav").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Remove stereo_tones.wav?")
    # destructive dialogs focus Cancel; Escape cancels
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert _file_names(state["id"]) == ["clipped_220.wav", "mono_1k.wav", "stereo_tones.wav"]
    # focus returns to the control that opened the dialog
    expect(page.get_by_role("button", name="Remove stereo_tones.wav")).to_be_focused()
    # confirm → only that file is removed, the others keep their analyses
    page.get_by_role("button", name="Remove stereo_tones.wav").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Remove file").click()
    expect(page.get_by_role("button", name="Remove stereo_tones.wav")).to_have_count(0)
    assert _file_names(state["id"]) == ["clipped_220.wav", "mono_1k.wav"]
    remaining = httpx.get(f"{BASE}/api/sessions/{state['id']}").json()["files"]
    assert all(f["has_analysis"] for f in remaining)
    httpx.delete(f"{BASE}/api/sessions/{state['id']}")


# --------------------------------------------------------------- FE-03
def test_fe03_upload_can_be_cancelled(browser):
    created = httpx.post(f"{BASE}/api/sessions", json={"name": "Cancel E2E"}).json()
    page = _page(browser, created["id"])
    _go(page, "#/upload")
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False, "latency": 50, "downloadThroughput": 5_000_000, "uploadThroughput": 40_000,
    })
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name=re.compile("Drop audio files here")).click()
    chooser.value.set_files([str(AUDIO / "out_of_phase_stereo.wav")])
    cancel = page.get_by_role("button", name="Cancel upload")
    expect(cancel).to_be_visible(timeout=10000)
    cancel.click()
    expect(page.locator(".toast", has_text="Upload cancelled")).to_be_visible()
    expect(cancel).to_have_count(0)
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    time.sleep(1.5)
    assert _file_names(created["id"]) == []
    httpx.delete(f"{BASE}/api/sessions/{created['id']}")


# --------------------------------------------------------------- FE-28
def test_fe28_duplicates_and_unsupported_files_are_caught_before_upload(browser, tmp_path):
    state = _fresh(["mono_1k.wav"], "Duplicate E2E")
    text = tmp_path / "notes.txt"
    text.write_text("not audio")
    page = _page(browser, state["id"])
    _go(page, "#/upload")
    posts: list[str] = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/files") and posts.append(r.url))
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name=re.compile("Drop audio files here")).click()
    chooser.value.set_files([str(AUDIO / "mono_1k.wav"), str(text)])
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("already in this session")
    dialog.get_by_role("button", name="Skip duplicates").click()
    expect(page.get_by_role("heading", name="Rejected files")).to_be_visible()
    expect(page.locator(".finding-error", has_text="notes.txt")).to_contain_text("Unsupported file type")
    page.wait_for_timeout(500)
    assert posts == [], "nothing should be uploaded"
    assert _file_names(state["id"]) == ["mono_1k.wav"]
    httpx.delete(f"{BASE}/api/sessions/{state['id']}")


# --------------------------------------------------------------- FE-04/05
def test_fe04_fe05_stereo_and_dynamics_are_readable_and_width_chart_uses_two_axes(browser, session):
    ids = _ids(session)
    page = _page(browser, session["id"])
    _go(page, f"#/stereo?file={ids['out_of_phase_stereo.wav']}")
    expect(page.locator(".finding-measure").first).to_be_visible()
    assert page.locator("pre.inline-json").count() == 0
    text = " ".join(page.locator(".finding-measure").all_inner_texts())
    assert "{" not in text and '"' not in text
    assert "Correlation: -1" in text
    width = page.locator("figure[aria-label^='Stereo width and mid/side levels'] .js-plotly-plot")
    expect(width).to_be_visible()
    page.wait_for_function("() => [...document.querySelectorAll('.js-plotly-plot')].some(g => g.layout && g.layout.yaxis2)")
    axes = page.evaluate("""() => {
        const g = [...document.querySelectorAll('.js-plotly-plot')].find(x => x.layout && x.layout.yaxis2);
        return { y: g.layout.yaxis.title.text, y2: g.layout.yaxis2.title.text, traces: g.data.map(t => t.yaxis || 'y') };
    }""")
    assert axes == {"y": "Side/mid ratio", "y2": "Level (dBFS)", "traces": ["y", "y2", "y2"]}
    _go(page, f"#/dynamics?file={ids['clipped_220.wav']}")
    expect(page.locator(".finding-measure").first).to_be_visible()
    assert page.locator("pre.inline-json").count() == 0
    assert page.errors == []


# --------------------------------------------------------------- FE-06
def test_fe06_waveform_selection_is_validated_and_zoom_buttons_work(browser, session):
    ids = _ids(session)
    page = _page(browser, session["id"])
    _go(page, f"#/waveform?file={ids['c_major_120bpm.wav']}")
    expect(page.locator(".js-plotly-plot").first).to_be_visible()
    start = page.get_by_label("Selection start")
    start.fill("999")
    expect(start).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#sel-start-err")).to_contain_text("before the end of the file")
    expect(page.get_by_role("button", name="Analyze selection")).to_be_disabled()
    start.fill("1")
    page.get_by_label("Selection end").fill("2")
    expect(page.get_by_role("button", name="Analyze selection")).to_be_enabled()
    # zoom in halves the visible range, zoom out restores it
    page.get_by_role("button", name="Zoom in on time axis").click()
    expect(page.locator(".waveform-toolbar")).to_contain_text("Visible range: 2.00–6.00 s")
    page.get_by_role("button", name="Zoom out on time axis").click()
    expect(page.locator(".waveform-toolbar")).to_contain_text("Visible range: full file")
    assert page.errors == []


# --------------------------------------------------------------- FE-07
def test_fe07_spectrum_and_spectrogram_parameters_are_validated(browser, session):
    page = _page(browser, session["id"])
    _go(page, "#/spectrum")
    fft = page.get_by_label("FFT size", exact=False).first
    options = [int(v) for v in fft.locator("option").evaluate_all("o => o.map(x => x.value)")]
    assert all(v & (v - 1) == 0 for v in options), "FFT sizes must be powers of two"
    fft.select_option("512")
    expect(page.locator("select[aria-describedby='spec-hop-err'] option[value='1024']")).to_have_attribute("disabled", "")
    page.get_by_label("End (s)").fill("999")
    expect(page.get_by_role("button", name="Compute")).to_be_disabled()
    expect(page.locator("#spec-end-err")).to_contain_text("cannot exceed the file duration")
    _go(page, "#/spectrogram")
    expect(page.get_by_role("button", name="STFT spectrogram", exact=True)).to_have_attribute("aria-pressed", "true")
    page.get_by_label("Floor (dB)").fill("-10")
    page.get_by_label("Ceiling (dB)").fill("-20")
    expect(page.locator("#sg-ceiling-err")).to_contain_text("higher than the floor")
    page.get_by_role("button", name="Mel spectrogram", exact=True).click()
    expect(page.get_by_role("button", name="Mel spectrogram", exact=True)).to_have_attribute("aria-pressed", "true")
    assert page.errors == []


# --------------------------------------------------------------- FE-08/26
def test_fe08_qc_empty_threshold_is_invalid_and_file_link_scopes_qc(browser, session):
    ids = _ids(session)
    page = _page(browser, session["id"])
    _go(page, f"#/qc?file={ids['clipped_220.wav']}")
    expect(page.get_by_role("button", name=re.compile("^Active file: clipped_220.wav"))).to_have_attribute("aria-pressed", "true")
    files = set(page.locator("td.qc-file").all_inner_texts())
    assert files == {"clipped_220.wav"}
    page.get_by_role("button", name="Thresholds").click()
    first = page.locator(".threshold-field input").first
    first.fill("")
    expect(first).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_role("button", name="Save and recompute")).to_be_disabled()


# --------------------------------------------------------------- FE-10/19
def test_fe10_failed_analysis_load_shows_error_and_retry(browser, session):
    ids = _ids(session)
    page = _page(browser, session["id"])
    failing = {"on": True}

    def handler(route):
        if failing["on"]:
            route.fulfill(status=500, content_type="application/json", body='{"detail":"Simulated storage failure"}')
        else:
            route.continue_()

    page.route(re.compile(r".*/files/fil_[0-9a-f]+/analysis$"), handler)
    _go(page, f"#/overview?file={ids['mono_1k.wav']}")
    note = page.locator(".info-note-error", has_text="Could not load the measurements")
    expect(note).to_contain_text("Simulated storage failure")
    # the error toast is an alert and is not auto-dismissed
    expect(page.locator(".toast-error[role='alert']").first).to_be_visible()
    failing["on"] = False
    note.get_by_role("button", name="Retry").click()
    expect(page.locator(".metric").first).to_be_visible()
    expect(note).to_have_count(0)


# --------------------------------------------------------------- FE-11/15
def test_fe11_fe15_reports_validate_targets_and_downloads_keep_file_names(browser, session):
    ids = _ids(session)
    page = _page(browser, session["id"])
    _go(page, "#/reports")
    target = page.get_by_label("Comparison gain target (LUFS)")
    target.fill("")
    expect(target).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_role("button", name="Download PDF report")).to_be_disabled()
    target.fill("-16")
    expect(page.get_by_role("button", name="Download PDF report")).to_be_enabled()
    _go(page, f"#/loudness?file={ids['clipped_220.wav']}")
    with page.expect_download() as info:
        page.get_by_role("button", name="Download loudness plot PNG for clipped_220.wav").click()
    assert info.value.suggested_filename == "clipped_220.wav-loudness.png"
    expect(page.locator(".toast", has_text="clipped_220.wav-loudness.png")).to_be_visible()


# --------------------------------------------------------------- FE-14
def test_fe14_manual_offset_runs_only_on_request(browser, session):
    page = _page(browser, session["id"])
    _go(page, "#/comparison")
    expect(page.get_by_text("File summary")).to_be_visible(timeout=60000)
    calls: list[str] = []
    page.on("request", lambda r: "/align" in r.url and calls.append(r.url))
    field = page.get_by_label("Manual offset B (s)")
    field.focus()
    field.blur()
    page.wait_for_timeout(800)
    assert calls == []
    field.fill("0.25")
    page.get_by_role("button", name="Check offset").click()
    expect(page.locator(".alignment-result")).to_be_visible()
    assert len(calls) == 1


# --------------------------------------------------------------- FE-18
def test_fe18_settings_threshold_label_and_delete_confirmation(browser):
    state = _fresh(["mono_1k.wav"], "Settings E2E")
    page = _page(browser, state["id"])
    _go(page, "#/settings")
    expect(page.get_by_text("Default QC thresholds")).to_be_visible()
    page.get_by_role("button", name="Delete this session and start a new one").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Delete this session permanently?")
    dialog.get_by_role("button", name="Cancel").click()
    assert httpx.get(f"{BASE}/api/sessions/{state['id']}").status_code == 200
    expect(page.get_by_role("button", name="Comfortable")).to_have_attribute("aria-pressed", "true")
    httpx.delete(f"{BASE}/api/sessions/{state['id']}")


# --------------------------------------------------------------- FE-17
def test_fe17_navigation_icons_match_their_sections(browser, session):
    page = _page(browser, session["id"])
    _go(page, "#/dashboard")
    nav = page.get_by_role("navigation", name="Sections")
    expected = {
        "Waveform": "lucide-audio-waveform",
        "Spectrogram": "lucide-grid-3x3",
        "Dynamics": "lucide-chart-column-big",
        "Comparison": "lucide-git-compare-arrows",
        "Quality control": "lucide-shield-check",
        "Reports": "lucide-file-text",
        "Settings": "lucide-settings",
    }
    for label, icon_class in expected.items():
        link = nav.get_by_role("link", name=re.compile(rf"^{re.escape(label)}(\s*,|$)"))
        cls = link.locator("svg").first.get_attribute("class") or ""
        assert icon_class in cls, f"{label}: {cls}"


# --------------------------------------------------------------- FE-31
def test_fe31_qc_all_files_never_drops_a_file_silently(browser, session):
    """User report: QC 'All files (2)' showed one file.  A file whose analysis
    could not be loaded must be named, with Retry, not omitted."""
    ids = _ids(session)
    page = _page(browser, session["id"])
    failing = {"on": True}
    broken = ids["clipped_220.wav"]

    def handler(route):
        if failing["on"] and broken in route.request.url:
            route.fulfill(status=500, content_type="application/json", body='{"detail":"Simulated failure"}')
        else:
            route.continue_()

    page.route(re.compile(r".*/files/fil_[0-9a-f]+/analysis$"), handler)
    _go(page, "#/qc")
    expect(page.get_by_role("button", name="All files (4)")).to_have_attribute("aria-pressed", "true")
    note = page.locator(".info-note", has_text="Findings from 3 of 4 file(s)")
    expect(note).to_contain_text("clipped_220.wav")
    failing["on"] = False
    note.get_by_role("button", name="Retry").click()
    expect(note).to_have_count(0)
    expect(page.locator("td.qc-file", has_text="clipped_220.wav").first).to_be_visible()
    assert {"clipped_220.wav", "out_of_phase_stereo.wav"} <= set(page.locator("td.qc-file").all_inner_texts())
