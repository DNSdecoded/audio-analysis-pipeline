"""Real-browser UI audit: screenshots, console errors, overflow, touch targets, axe-core.

Runs against a live backend that serves the built frontend.  A session is
seeded with real reference audio through the public API, so every screen is
rendered with actual measurement data (no fixtures, no mocks).

    python frontend/e2e/audit.py --base http://127.0.0.1:8765 --out <dir> --label before
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "backend" / "data" / "test_audio"
AXE = ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
SEED_FILES = ["c_major_120bpm.wav", "out_of_phase_stereo.wav", "clipped_220.wav", "mono_1k.wav"]
SECTIONS = [
    "dashboard", "upload", "files", "overview", "waveform", "spectrum", "spectrogram", "musical",
    "loudness", "dynamics", "stereo", "comparison", "qc", "reports", "settings",
]
VIEWPORTS = {"desktop": (1440, 900), "tablet": (768, 1024), "mobile": (390, 844)}


def seed(base: str) -> str:
    client = httpx.Client(base_url=base, timeout=300)
    session = client.post("/api/sessions", json={"name": "UI audit session"}).json()
    files = [("files", (name, (AUDIO / name).read_bytes(), "audio/wav")) for name in SEED_FILES]
    upload = client.post(f"/api/sessions/{session['id']}/files", files=files).json()
    assert not upload["errors"], upload["errors"]
    client.post(f"/api/sessions/{session['id']}/analyze", json={})
    deadline = time.time() + 300
    while time.time() < deadline:
        state = client.get(f"/api/sessions/{session['id']}").json()
        if all(f["status"] in {"complete", "error"} for f in state["files"]):
            break
        time.sleep(1)
    return session["id"]


PAGE_CHECKS = """
() => {
  const vw = window.innerWidth;
  const doc = document.documentElement;
  const overflowX = doc.scrollWidth - vw;
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > vw + 2 && getComputedStyle(el).position !== 'fixed') {
      // ignore children of intentional horizontal scrollers
      let p = el.parentElement, scrolled = false;
      while (p) { const s = getComputedStyle(p); if (/(auto|scroll)/.test(s.overflowX) && p.scrollWidth > p.clientWidth) { scrolled = true; break; } p = p.parentElement; }
      if (!scrolled) offenders.push((el.className && el.className.baseVal === undefined ? el.className : el.tagName).toString().slice(0, 60));
    }
  }
  const small = [];
  for (const el of document.querySelectorAll('button, a[href], input, select, [role="button"], [tabindex="0"]')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (el.type === 'hidden') continue;
    if (r.width < 24 || r.height < 24) small.push(((el.getAttribute('aria-label') || el.textContent || el.className || el.tagName) + '').trim().slice(0, 40));
  }
  const unnamed = [];
  for (const el of document.querySelectorAll('button, a[href], [role="button"]')) {
    const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim();
    if (!name) unnamed.push(el.outerHTML.slice(0, 80));
  }
  const headings = [...document.querySelectorAll('h1,h2,h3,h4')].map(h => h.tagName + ':' + h.textContent.trim().slice(0, 40));
  const plots = document.querySelectorAll('.js-plotly-plot').length;
  const emptyPlots = [...document.querySelectorAll('.js-plotly-plot')].filter(p => !p.querySelector('.scatterlayer .trace, .heatmaplayer image, .barlayer .trace, .scattergl, canvas')).length;
  return { overflowX, overflowOffenders: [...new Set(offenders)].slice(0, 12), smallTargets: [...new Set(small)].slice(0, 15),
           smallTargetCount: small.length, unnamedButtons: unnamed.slice(0, 10), headings, plots, emptyPlots,
           title: document.title };
}
"""


def run(base: str, out: Path, label: str, session_id: str | None, sections: list[str], viewports: list[str], theme: str = "light") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    session_id = session_id or seed(base)
    axe_source = AXE.read_text(encoding="utf-8")
    report: dict = {"label": label, "session_id": session_id, "theme": theme, "pages": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp_name in viewports:
            width, height = VIEWPORTS[vp_name]
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            context.add_init_script(f"localStorage.setItem('aap_session_id', '{session_id}'); localStorage.setItem('aap_theme', '{theme}');")
            page = context.new_page()
            console: list[str] = []
            failed: list[str] = []
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}"[:300]) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: console.append(f"pageerror: {e}"[:300]))
            page.on("requestfailed", lambda r: failed.append(f"{r.method} {r.url} {r.failure}"[:200]))
            page.on("response", lambda r: failed.append(f"{r.status} {r.url}"[:200]) if r.status >= 400 else None)
            for section in sections:
                console.clear(); failed.clear()
                page.goto(f"{base}/#/{section}")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1800)  # Plotly draws asynchronously
                shot = out / f"{label}-{vp_name}-{section}.png"
                page.screenshot(path=str(shot), full_page=True)
                checks = page.evaluate(PAGE_CHECKS)
                page.add_script_tag(content=axe_source)
                axe = page.evaluate("""async () => {
                    const r = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'] } });
                    return r.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help,
                                                    sample: v.nodes.slice(0, 3).map(n => n.target.join(' ')) }));
                }""")
                report["pages"].append({
                    "viewport": vp_name, "section": section, "screenshot": shot.name,
                    "console": list(console), "failed_requests": list(failed), "axe": axe, **checks,
                })
                print(f"{vp_name:8s} {section:12s} console={len(console)} failed={len(failed)} "
                      f"overflowX={checks['overflowX']} small={checks['smallTargetCount']} axe={sum(v['nodes'] for v in axe)} "
                      f"plots={checks['plots']} empty={checks['emptyPlots']}")
            context.close()
        browser.close()
    (out / f"{label}-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="audit")
    parser.add_argument("--session", default=None)
    parser.add_argument("--sections", default=",".join(SECTIONS))
    parser.add_argument("--viewports", default=",".join(VIEWPORTS))
    parser.add_argument("--theme", default="light", choices=["light", "dark"])
    args = parser.parse_args()
    run(args.base, Path(args.out), args.label, args.session, args.sections.split(","), args.viewports.split(","), args.theme)
