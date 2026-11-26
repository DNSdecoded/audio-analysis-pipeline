"""End-to-end UI tests against the real backend with real audio (no mocks).

Requires a running server that serves the built frontend:

    cd backend && python -m uvicorn app.main:app --port 8765
    python -m pytest frontend/e2e/test_ui.py -q            # AAP_E2E_BASE overrides the URL

Each test verifies behaviour and displayed data, not only that a page renders.
"""

from __future__ import annotations

import csv
import io
import os
import re
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

BASE = os.environ.get("AAP_E2E_BASE", "http://127.0.0.1:8765")
ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "backend" / "data" / "test_audio"
SEED = ["c_major_120bpm.wav", "out_of_phase_stereo.wav", "clipped_220.wav", "mono_1k.wav"]
BASELINE = Path(__file__).parent / "visual-baseline"


def _seed(files: list[str], name: str) -> dict:
    client = httpx.Client(base_url=BASE, timeout=300)
    session = client.post("/api/sessions", json={"name": name}).json()
    payload = [("files", (f, (AUDIO / f).read_bytes(), "audio/wav")) for f in files]
    assert not client.post(f"/api/sessions/{session['id']}/files", files=payload).json()["errors"]
    client.post(f"/api/sessions/{session['id']}/analyze", json={})
    deadline = time.time() + 300
    while time.time() < deadline:
        state = client.get(f"/api/sessions/{session['id']}").json()
        if all(f["status"] in {"complete", "error"} for f in state["files"]):
            return state
        time.sleep(1)
    raise AssertionError("seeding timed out")


@pytest.fixture(scope="session")
def seeded() -> dict:
    try:
        httpx.get(f"{BASE}/api/health", timeout=5).raise_for_status()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"server not reachable at {BASE}: {exc}")
    return _seed(SEED, "E2E session")


def _page(
    browser,
    session_id: str,
    width=1440,
    height=900,
    theme: str | None = None,
    color_scheme: str = "light",
) -> Page:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        accept_downloads=True,
        color_scheme=color_scheme,
    )
    script = f"localStorage.setItem('aap_session_id', '{session_id}');"
    if theme:
        script += f"localStorage.setItem('aap_theme', '{theme}');"
    context.add_init_script(script)
    page = context.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    return page


def _go(page: Page, hash_: str):
    page.goto(f"{BASE}/{hash_}")
    page.wait_for_load_state("networkidle")


def _ids(seeded) -> dict[str, str]:
    return {f["original_name"]: f["id"] for f in seeded["files"]}


# ------------------------------------------------------------------ navigation
def test_every_sidebar_link_opens_its_section_and_back_works(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/dashboard")
    expected = {
        "Dashboard": "Project dashboard", "Upload": "Multi-file upload", "Files": "Files & validation",
        "File overview": "File overview", "Waveform": "Waveform analysis", "Spectrum": "Frequency spectrum",
        "Spectrogram": "Spectrogram analysis", "Musical": "Musical analysis", "Loudness & gain": "Loudness and gain",
        "Dynamics": "Dynamic range", "Stereo & phase": "Stereo and phase", "Comparison": "Multi-file comparison",
        "Quality control": "Quality control", "Reports": "Reports and exports", "Settings": "Settings",
    }
    nav = page.get_by_role("navigation", name="Sections")
    for link, heading in expected.items():
        item = nav.get_by_role("link", name=re.compile(rf"^{re.escape(link)}(\s*,|$)"))
        item.click()
        expect(page.get_by_role("heading", level=1)).to_have_text(heading)
        expect(item).to_have_attribute("aria-current", "page")
    page.go_back()
    expect(page.get_by_role("heading", level=1)).to_have_text("Reports and exports")
    assert page.errors == []
    # exactly one h1 per page (topbar title is no longer a heading)
    assert page.locator("h1").count() == 1


# ------------------------------------------------------------- active file
def test_open_from_dashboard_opens_that_file_and_selection_persists(browser, seeded):
    ids = _ids(seeded)
    page = _page(browser, seeded["id"])
    _go(page, "#/dashboard")
    page.get_by_role("button", name="Open analysis of clipped_220.wav").click()
    expect(page.get_by_role("heading", level=1)).to_have_text("File overview")
    select = page.get_by_label("Active file")
    expect(select).to_have_value(ids["clipped_220.wav"])
    # the overview shows clipped_220's real clipping (≈50 %), not the first file's 0 %
    clip_card = page.locator(".metric", has_text="Clipping").first
    expect(clip_card).to_contain_text("50.08")
    expect(clip_card).to_contain_text("Critical")
    # switching sections keeps the file
    page.get_by_role("navigation", name="Sections").get_by_role("link", name="Loudness & gain").click()
    expect(page.get_by_label("Active file")).to_have_value(ids["clipped_220.wav"])
    # switching with the bar changes every section
    page.get_by_label("Active file").select_option(ids["mono_1k.wav"])
    page.get_by_role("navigation", name="Sections").get_by_role("link", name="Stereo & phase").click()
    expect(page.get_by_text("Mono file", exact=False).first).to_be_visible()


def test_missing_measurements_are_not_shown_as_pass(browser, seeded):
    ids = _ids(seeded)
    page = _page(browser, seeded["id"])
    _go(page, f"#/overview?file={ids['c_major_120bpm.wav']}")
    snr = page.locator(".metric", has_text="Signal-to-noise ratio")
    expect(snr).to_contain_text("Not available")
    expect(snr).not_to_contain_text("Pass")
    expect(page.locator(".metric", has_text="Musical key")).to_contain_text("Estimate")
    expect(page.locator(".metric", has_text="True peak").first).to_contain_text("Measured")


# ---------------------------------------------------------------------- QC
def test_qc_lists_all_files_readably_and_jumps_to_waveform(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/qc")
    table = page.get_by_role("region", name="Quality-control findings")
    expect(table).to_be_visible()
    files_in_table = set(table.locator("td.qc-file").all_inner_texts())
    assert {"clipped_220.wav", "out_of_phase_stereo.wav"} <= files_in_table
    measured = " ".join(table.locator("td.num").all_inner_texts())
    assert "{" not in measured and '"' not in measured, "raw JSON in QC values"
    # critical clipping shows the error limit that caused it
    clip_row = table.locator("tr", has_text="Clipping").filter(has_text="clipped_220.wav").first
    expect(clip_row).to_contain_text("critical ≥ 0.05 %")
    # time position → waveform at that range
    clip_row.locator("button.time-chip").first.click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Waveform analysis")
    expect(page.get_by_text("Showing", exact=False).first).to_contain_text("Clipping")
    params = dict(item.split("=") for item in page.url.split("?", 1)[1].split("&"))
    start = float(page.get_by_label("Selection start").input_value())
    end = float(page.get_by_label("Selection end").input_value())
    assert abs(start - float(params["start"])) < 0.001 and abs(end - float(params["end"])) < 0.001
    assert params["file"] == _ids(seeded)["clipped_220.wav"]


def test_severity_tiles_filter_findings(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/qc")
    table = page.get_by_role("region", name="Quality-control findings")
    before = table.locator("tbody tr.qc-tr").count()
    page.get_by_role("button", name=re.compile("Info")).first.click()  # hide Info
    after = table.locator("tbody tr.qc-tr").count()
    assert 0 < after < before
    assert table.locator("tbody .badge-info").count() == 0


# --------------------------------------------------------------- comparison
def test_comparison_findings_sort_filter(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/comparison")
    summary = page.get_by_role("region", name="File summary")
    expect(summary).to_be_visible(timeout=60000)
    findings = page.locator(".finding-values")
    expect(findings.first).to_be_visible()
    assert "fil_" not in " ".join(findings.all_inner_texts()), "internal IDs shown to user"
    # sort summary by loudness
    header = summary.get_by_role("button", name="Loudness", exact=True)
    cell = summary.locator("th").filter(has=page.locator("button.th-sort", has_text=re.compile("^Loudness$")))
    header.click()
    expect(cell).to_have_attribute("aria-sort", "ascending")
    lufs = [float(v.split()[0]) for v in summary.locator("tbody tr td:nth-child(5)").all_inner_texts() if "LUFS" in v]
    assert lufs == sorted(lufs)
    header.click()
    expect(cell).to_have_attribute("aria-sort", "descending")
    # parameter filter + sort
    params = page.get_by_role("region", name="Parameter comparison")
    page.get_by_placeholder("Filter parameters").fill("peak")
    labels = params.locator("tbody th[scope='row'] strong").all_inner_texts()
    assert labels and all("peak" in label.lower() for label in labels)
    page.get_by_placeholder("Filter parameters").fill("")
    page.get_by_label("Sort").select_option("status")
    first_status = params.locator("tbody tr").first.locator(".status-pill").inner_text()
    assert first_status == "Large deviation"


# ------------------------------------------------------------------- charts
def test_plotly_cloud_share_is_removed_and_charts_use_real_data(browser, seeded):
    ids = _ids(seeded)
    page = _page(browser, seeded["id"])
    _go(page, f"#/spectrogram?file={ids['c_major_120bpm.wav']}")
    page.wait_for_selector(".js-plotly-plot .heatmaplayer", timeout=60000)
    assert page.locator('[data-title="Share chart..."]').count() == 0
    colorscale = page.evaluate("() => document.querySelector('.js-plotly-plot').data[0].colorscale")
    assert colorscale[0][1].lower() == "#000004" and colorscale[-1][1].lower() == "#fcfdbf", "magma map not applied"
    yaxis_type = page.evaluate("() => document.querySelector('.js-plotly-plot').layout.yaxis.type")
    assert yaxis_type == "log"
    _go(page, f"#/loudness?file={ids['c_major_120bpm.wav']}")
    page.wait_for_selector(".js-plotly-plot .scatterlayer", timeout=60000)
    lo, hi = page.evaluate("() => document.querySelector('.js-plotly-plot').layout.yaxis.range")
    assert hi - lo >= 12, "small loudness variation must not fill the axis"
    analysis = httpx.get(f"{BASE}/api/sessions/{seeded['id']}/files/{ids['c_major_120bpm.wav']}/analysis").json()
    plotted = page.evaluate("() => document.querySelector('.js-plotly-plot').data[0].y.slice(0, 5)")
    assert plotted == analysis["loudness"]["short_term"]["lufs"][:5]


# -------------------------------------------------------------------- theme
THEME = "document.documentElement.dataset.theme"

# Plotly echoes a colour as '#FFF', '#1A1A1D' or 'rgb(26, 26, 29)'; normalise
# every form to six-digit uppercase hex before comparing.
_PLOT_BG = """() => {
    const raw = (document.querySelector('.js-plotly-plot')?.layout.plot_bgcolor ?? '').trim();
    const m = /rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/.exec(raw);
    if (m) {
        return '#' + [m[1], m[2], m[3]]
            .map((v) => Number(v).toString(16).padStart(2, '0')).join('').toUpperCase();
    }
    const hex = raw.replace('#', '').toUpperCase();
    if (hex.length === 3) return '#' + hex.split('').map((c) => c + c).join('');
    return '#' + hex;
}"""


# The theme picker is a native <select> whose wrapping <label> also contains the
# option text, so it is targeted by role ("combobox", name "Theme").


def test_theme_toggle_persists_and_restyles_charts(browser, seeded):
    """Light/Dark/System selector switches live, restyles charts, and persists.

    No theme is injected into localStorage: the OS reports light, so the app
    starts in Light, and everything after that comes from the user's choice —
    which is what makes the reload assertion real.
    """
    page = _page(browser, seeded["id"])
    _go(page, "#/loudness")
    assert page.evaluate(THEME) == "light"
    assert page.evaluate("() => localStorage.getItem('aap_theme')") is None
    page.wait_for_selector(".js-plotly-plot .scatterlayer", timeout=60000)
    assert page.evaluate(_PLOT_BG) == "#FFFFFF"

    selector = page.get_by_role("combobox", name="Theme")
    # no saved preference yet → the preference is System, resolved to Light
    expect(selector).to_have_value("system")
    selector.select_option("dark")
    assert page.evaluate(THEME) == "dark"
    # the visible chart re-themes without a reload
    page.wait_for_function(
        "() => (document.querySelector('.js-plotly-plot')?.layout.plot_bgcolor ?? '')"
        ".toLowerCase() !== '#ffffff'",
        timeout=30000,
    )
    assert page.evaluate(_PLOT_BG) == "#1A1A1D"
    assert page.evaluate("() => document.documentElement.style.colorScheme") == "dark"
    assert page.evaluate("() => localStorage.getItem('aap_theme')") == "dark"

    # preference survives a full reload
    page.reload()
    page.wait_for_load_state("networkidle")
    assert page.evaluate(THEME) == "dark"
    expect(page.get_by_role("combobox", name="Theme")).to_have_value("dark")

    # an explicit choice wins over the OS preference
    page.get_by_role("combobox", name="Theme").select_option("light")
    assert page.evaluate(THEME) == "light"
    assert page.errors == []


def test_system_theme_follows_os_and_updates_live(browser, seeded):
    """With 'System' selected the theme tracks the OS, including live changes."""
    page = _page(browser, seeded["id"], theme="system", color_scheme="dark")
    _go(page, "#/dashboard")
    assert page.evaluate(THEME) == "dark"
    expect(page.get_by_role("combobox", name="Theme")).to_have_value("system")

    # OS switches to light while the app is open
    page.emulate_media(color_scheme="light")
    page.wait_for_function(f"() => {THEME} === 'light'", timeout=15000)
    page.emulate_media(color_scheme="dark")
    page.wait_for_function(f"() => {THEME} === 'dark'", timeout=15000)

    # an explicit choice stops following the OS
    page.get_by_role("combobox", name="Theme").select_option("light")
    page.emulate_media(color_scheme="light")
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(300)
    assert page.evaluate(THEME) == "light"
    assert page.errors == []


def test_no_saved_preference_follows_os_and_defaults_to_light(browser, seeded):
    """No saved choice: follow the OS, falling back to Light."""
    light = _page(browser, seeded["id"], color_scheme="light")
    _go(light, "#/dashboard")
    assert light.evaluate(THEME) == "light"
    assert light.evaluate("() => localStorage.getItem('aap_theme')") is None

    dark = _page(browser, seeded["id"], color_scheme="dark")
    _go(dark, "#/dashboard")
    assert dark.evaluate(THEME) == "dark"


def test_theme_persists_across_routes_tables_and_forms(browser, seeded):
    """Every surface keeps the chosen theme: tables, forms, status badges."""
    page = _page(browser, seeded["id"], theme="dark")
    _go(page, "#/qc")
    expect(page.get_by_role("region", name="Quality-control findings")).to_be_visible()
    assert page.evaluate(THEME) == "dark"
    # token-driven surfaces agree with the theme, not a stale hardcoded colour
    surfaces = page.evaluate(
        """() => {
            const css = getComputedStyle(document.documentElement);
            const body = getComputedStyle(document.body);
            const header = document.querySelector('.data-table thead th');
            // The visible control boundary sits on the .search-field wrapper;
            // the inner input is deliberately borderless.
            const field = document.querySelector('.search-field');
            return {
                bg: css.getPropertyValue('--bg-0').trim(),
                panel: css.getPropertyValue('--panel').trim(),
                border: css.getPropertyValue('--border').trim(),
                headerBg: header ? getComputedStyle(header).backgroundColor : null,
                fieldBorder: field ? getComputedStyle(field).borderTopColor : null,
                bodyColor: body.color,
                bodyBg: body.backgroundColor,
            };
        }"""
    )
    assert surfaces["bg"].lower() == "#121214"
    assert surfaces["panel"].lower() == "#1a1a1d"
    assert surfaces["border"].lower() == "#2c2c30"
    assert surfaces["bodyColor"] == "rgb(228, 228, 231)"
    assert surfaces["bodyBg"] == "rgb(18, 18, 20)"
    assert surfaces["headerBg"] == "rgb(34, 34, 38)"
    # control boundary uses --control-border (3:1 on the dark surfaces), not --border
    assert surfaces["fieldBorder"] == "rgb(109, 109, 112)"
    page.get_by_role("navigation", name="Sections").get_by_role("link", name="Settings").click()
    expect(page.get_by_label("Target loudness")).to_be_visible()
    assert page.evaluate(THEME) == "dark"
    # Settings offers the same selector and both stay in sync
    group = page.get_by_role("group", name="Theme")
    expect(group.get_by_role("button", name=re.compile("^Dark"))).to_have_attribute("aria-pressed", "true")
    group.get_by_role("button", name=re.compile("^Light")).click()
    assert page.evaluate(THEME) == "light"
    expect(page.get_by_role("combobox", name="Theme")).to_have_value("light")
    assert page.errors == []


def test_dark_chart_series_keeps_track_identity(browser, seeded):
    """Track 1 stays indigo across themes; only the shade shifts for the surface."""
    page = _page(browser, seeded["id"], theme="dark")
    _go(page, "#/loudness")
    page.wait_for_selector(".js-plotly-plot .scatterlayer", timeout=60000)
    dark_line = page.evaluate("() => document.querySelector('.js-plotly-plot').data[0].line.color")
    assert dark_line == "#665EE8", f"dark track 1 should be lightened indigo, got {dark_line}"

    page.get_by_role("combobox", name="Theme").select_option("light")
    page.wait_for_function(
        "() => document.querySelector('.js-plotly-plot').data[0].line.color === '#4F46E5'",
        timeout=30000,
    )
    # same trace/series order in both themes (identity preserved, not reordered)
    names = page.evaluate("() => document.querySelector('.js-plotly-plot').data.map(t => t.name)")
    assert names[0].endswith("short-term")


# ----------------------------------------------------------------- settings
def test_settings_validation_and_cancel(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/settings")
    save = page.get_by_role("button", name="Save settings")
    expect(save).to_be_disabled()  # nothing changed
    page.get_by_label("Target loudness").fill("-80")
    expect(page.get_by_text("Target loudness must be between")).to_be_visible()
    expect(save).to_be_disabled()
    page.get_by_role("button", name="Cancel changes").click()
    expect(page.get_by_label("Target loudness")).to_have_value("-14")
    # hop larger than FFT is not selectable
    page.get_by_label("FFT size").select_option("512")
    disabled = page.locator("select[aria-describedby='err-hop'] option[disabled]").all_inner_texts()
    assert any(text.startswith("1024") for text in disabled)
    page.get_by_role("button", name="Cancel changes").click()


# ----------------------------------------------------------------- keyboard
def test_keyboard_skip_link_and_navigation(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/dashboard")
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "main-content"
    link = page.get_by_role("navigation", name="Sections").get_by_role("link", name=re.compile("^Reports"))
    link.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", level=1)).to_have_text("Reports and exports")
    # table regions are reachable by keyboard
    _go(page, "#/qc")
    region = page.get_by_role("region", name="Quality-control findings")
    assert region.get_attribute("tabindex") == "0"


# ------------------------------------------------------------------- mobile
def test_mobile_drawer_and_no_overflow(browser, seeded):
    page = _page(browser, seeded["id"], width=390, height=844)
    _go(page, "#/dashboard")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("button", name="Open navigation").click()
    expect(page.locator(".app-shell.mobile-nav-open")).to_have_count(1)
    page.keyboard.press("Escape")
    expect(page.locator(".app-shell.mobile-nav-open")).to_have_count(0)
    # file table stacks into cards: the Open action is visible without scrolling
    open_button = page.get_by_role("button", name=re.compile("^Open analysis of")).first
    box = open_button.bounding_box()
    assert box and box["x"] + box["width"] <= 390
    _go(page, "#/waveform")
    player = page.locator("audio.audio-player").first.bounding_box()
    assert player and player["height"] >= 30


# ------------------------------------------------------------------ exports
def test_csv_export_matches_analysis(browser, seeded):
    ids = _ids(seeded)
    page = _page(browser, seeded["id"])
    _go(page, "#/reports")
    with page.expect_download() as info:
        page.get_by_role("button", name="Download Measurements CSV").click()
    path = info.value.path()
    rows = list(csv.DictReader(io.StringIO(Path(path).read_text(encoding="utf-8-sig"))))
    by_name = {row["file_name"]: row for row in rows}
    assert set(by_name) == set(ids)
    analysis = httpx.get(f"{BASE}/api/sessions/{seeded['id']}/files/{ids['clipped_220.wav']}/analysis").json()
    assert float(by_name["clipped_220.wav"]["integrated_lufs"]) == pytest.approx(analysis["loudness"]["integrated_lufs"])


# ----------------------------------------------------------------- sessions
def test_new_analysis_keeps_previous_session_reopenable(browser, seeded):
    page = _page(browser, seeded["id"])
    _go(page, "#/dashboard")
    page.get_by_role("button", name="New analysis").first.click()
    expect(page.locator(".kpi", has_text="Uploaded files").locator(".kpi-value")).to_have_text("0")
    recent = page.get_by_role("region", name="Recent analysis sessions")
    open_old = recent.get_by_role("button", name="Open session E2E session").first
    expect(open_old).to_be_visible()
    open_old.click()
    expect(page.locator(".kpi", has_text="Uploaded files").locator(".kpi-value")).to_have_text(str(len(SEED)))


# ------------------------------------------------------------------- upload
def test_upload_through_ui_validates_and_rejects(browser, tmp_path):
    session = httpx.post(f"{BASE}/api/sessions", json={"name": "Upload E2E"}).json()
    bad = tmp_path / "broken.wav"
    bad.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40)
    page = _page(browser, session["id"])
    _go(page, "#/upload")
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name=re.compile("Drop audio files here")).click()
    chooser.value.set_files([str(AUDIO / "mono_1k.wav"), str(AUDIO / "stereo_tones.wav"), str(bad)])
    expect(page.get_by_text("Rejected files")).to_be_visible(timeout=60000)
    expect(page.get_by_text("broken.wav").first).to_be_visible()
    state = httpx.get(f"{BASE}/api/sessions/{session['id']}").json()
    assert sorted(f["original_name"] for f in state["files"]) == ["mono_1k.wav", "stereo_tones.wav"]
    assert all(f["status"] == "validated" for f in state["files"])
    httpx.delete(f"{BASE}/api/sessions/{session['id']}")


# ----------------------------------------------------------- visual regression
VISUAL_PAGES = ["dashboard", "overview", "qc", "settings"]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("section", VISUAL_PAGES)
def test_visual_regression(browser, seeded, section, theme):
    """Pixel diff against a stored per-theme baseline (created on first run).

    Both themes are covered, so a palette edit that only regresses Light (or
    only Dark) is caught. Charts are excluded (masked) because Plotly
    anti-aliasing differs slightly between runs; the layout, typography and
    colours around them are compared.
    """
    from PIL import Image, ImageChops

    if os.environ.get("AAP_SKIP_VISUAL"):
        pytest.skip("visual baselines are platform-specific (fonts); set by CI on Linux")

    page = _page(browser, seeded["id"], theme=theme)
    _go(page, f"#/{section}?file={_ids(seeded)['clipped_220.wav']}")
    assert page.evaluate(THEME) == theme
    page.wait_for_timeout(1500)
    shot = page.screenshot(
        full_page=False,
        mask=[page.locator(".js-plotly-plot"), page.locator(".toast-stack"), page.locator(".app-footer")],
        animations="disabled",
    )
    BASELINE.mkdir(exist_ok=True)
    baseline = BASELINE / f"{section}-{theme}.png"
    if not baseline.exists() or os.environ.get("AAP_UPDATE_BASELINE"):
        baseline.write_bytes(shot)
        pytest.skip(f"baseline written: {baseline.name}")
    current = Image.open(io.BytesIO(shot)).convert("RGB")
    reference = Image.open(baseline).convert("RGB")
    assert current.size == reference.size
    diff = ImageChops.difference(current, reference).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = diff.histogram()[255] / (current.size[0] * current.size[1])
    assert changed < 0.01, f"{section} ({theme}): {changed:.2%} of pixels changed"
