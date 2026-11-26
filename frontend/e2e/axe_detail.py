"""Print full axe-core details (with contrast data) for selected screens and themes.

    python frontend/e2e/axe_detail.py --session ses_... --sections dashboard,qc --themes dark,light
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

AXE = Path(__file__).resolve().parents[1] / "node_modules" / "axe-core" / "axe.min.js"

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8765")
parser.add_argument("--session", required=True)
parser.add_argument("--sections", default="dashboard,overview,waveform,qc,comparison,settings")
parser.add_argument("--themes", default="dark,light")
parser.add_argument("--width", type=int, default=1440)
args = parser.parse_args()

total = 0
with sync_playwright() as p:
    browser = p.chromium.launch()
    for theme in args.themes.split(","):
        context = browser.new_context(viewport={"width": args.width, "height": 900})
        context.add_init_script(
            f"localStorage.setItem('aap_session_id', '{args.session}'); localStorage.setItem('aap_theme', '{theme}');"
        )
        page = context.new_page()
        for section in args.sections.split(","):
            page.goto(f"{args.base}/#/{section}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
            page.add_script_tag(content=AXE.read_text(encoding="utf-8"))
            violations = page.evaluate("""async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'] } }))
                .violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 4).map(n => ({ target: n.target.join(' '), summary: n.failureSummary.replace(/\\s+/g, ' ').slice(0, 220) })) }))""")
            total += sum(len(v["nodes"]) for v in violations)
            print(f"[{theme}] {section}: {len(violations)} rule(s)")
            for v in violations:
                for node in v["nodes"]:
                    print(f"    {v['id']} ({v['impact']}) {node['target']} :: {node['summary']}")
        context.close()
    browser.close()
print("TOTAL violating nodes:", total)
