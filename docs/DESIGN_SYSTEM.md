# Design System — Audio Analysis Pipeline

Two themes, one token layer:

* **Light — Clean Analytical (Refined)** (primary; `:root` default) — neutral off-white base, refined indigo accent, near-black type. Crisp and instrument-like.
* **Dark — Studio Matte** — warm desaturated grays (never pure black), muted indigo accent. Built for long mastering sessions.

Restrained engineering console: flat surfaces, 1px borders instead of shadows, one primary accent, dense but legible data, no decorative gradients and **no glow shadows**. Both themes share every layout and component rule; **only colour tokens change**.

Source of truth: the token blocks at the top of `frontend/src/styles.css`, chart tokens in `frontend/src/lib/plotTheme.ts`, theme preference model in `frontend/src/lib/theme.ts`.

## 1. Theme preference model

| Preference | Behaviour |
|---|---|
| `light` / `dark` | Forces that theme. |
| `system` | Follows `prefers-color-scheme`, including live OS changes while the app is open. **Default when no choice is saved.** |

* With `system` and no dark OS preference the resolved theme is **Light** — the product's primary theme.
* The resolved theme is written to `<html data-theme="light|dark">` plus `color-scheme` and the `theme-color` meta tag.
* Persisted in `localStorage` under `aap_theme`; restored on reload/restart; kept in sync across tabs via the `storage` event.
* An **inline pre-paint script in `index.html`** resolves the theme before first paint, so there is no flash of the wrong theme (the app is client-rendered, so no hydration mismatch).
* Selectors: the top bar (`combobox` "Theme") and Settings → Appearance (`ToggleGroup` "Theme"). Both read and write the *same* preference — there is no second theme state.
* Switching is instant with no reload. Dialogs, dropdowns, menus, tooltips, toasts and chart overlays all inherit the active theme because they are styled from the same tokens.

## 2. Colour tokens

Colour definitions exist **only** in the two token blocks of `frontend/src/styles.css`. Components use semantic names (`--panel`, `--text-soft`, `--accent`), never raw hex.

### 2.1 Base palette

| Token | Light (Clean Analytical) | Dark (Studio Matte) |
|---|---|---|
| `--bg-0` app background | `#FAFAFA` warm off-white | `#121214` very dark gray |
| `--panel` card/table surface | `#FFFFFF` | `#1A1A1D` |
| `--panel-2` secondary surface | `#F4F4F5` | `#222226` |
| `--border` | `#E4E4E7` | `#2C2C30` |
| `--text` | `#18181B` almost black | `#E4E4E7` off-white |
| `--text-soft` | `#52525B` | `#A1A1AA` |
| `--muted` / `--faint` | `#65656D` | `#939399` |
| `--accent` (fill) | `#4F46E5` refined indigo | `#5B5FE8` muted indigo |
| `--accent-hover` | `#4338CA` | `#6265EF` |
| `--accent-text` (as text) | `#4338CA` | `#A5B4FC` |
| `--accent-graphic` (icons) | `#4F46E5` | `#6366F1` |
| `--selected-bg` | `#EEF2FF` pale indigo | `#2A2A42` indigo slate |
| `--focus` | `#4F46E5` | `#A5B4FC` |
| `--chart-bg` | `#FFFFFF` | `#1A1A1D` |

**Dark surfaces are never `#000000`**, which avoids halation (text blooming) on OLED and keeps panel separation visible. Light uses an off-white app background rather than `#FFFFFF` for the same reason.

### 2.2 Status pairs (per theme)

| Status | Light fg / bg | Dark fg / bg |
|---|---|---|
| Success | `#11813A` / `#F0FDF4` | `#51CF66` / `#0D2110` |
| Warning | `#A75C05` / `#FFFBEB` | `#FFD43B` / `#292209` |
| Critical | `#D82525` / `#FEF2F2` | `#FF6B6B` / `#291111` |
| Information | `#0275B1` / `#F0F9FF` | `#74C0FC` / `#131F28` |
| Pending | `#65656D` / `#F4F4F5` | `#A1A1AA` / `#222226` |
| Processing | `#4F46E5` / `#EEF2FF` | `#A5B4FC` / `#2A2A42` |

**Every pair measures ≥4.5:1** on the panel, the app background *and* its own soft tint. Status is **never colour-only** — every badge carries an icon and a word: Pass ✓, Info ⓘ, Warning ⚠, Critical ⊗. Backend severities map normal→Pass, information→Info, warning→Warning, error→Critical.

Badges use the soft pair plus a 22% outline of the same hue, so they read as printed labels rather than saturated pills.

### 2.3 Deviations from the off-the-shelf palette — and why

The proposed palettes were adopted, but five values had to be adjusted because they fail WCAG **on this app's actual surfaces**. Each keeps its intended hue; only lightness changed:

| Token | Proposed | Shipped | Reason |
|---|---|---|---|
| Light `--muted` | `#71717A` | `#65656D` | 4.40 on `--panel-2`, and **3.95** on the accent-tinted active nav — both below 4.5 |
| Light `--faint` | `#A1A1AA` | `#65656D` | 2.33:1 as text — unusable for the 35 places that render it |
| Light `--success` | `#16A34A` | `#11813A` | 3.30 on panel, 3.15 on its own soft tint |
| Light `--warning` | `#D97706` | `#A75C05` | 3.19 on panel, 3.07 on soft |
| Light `--error` | `#DC2626` | `#D82525` | 4.83 on panel but 4.41 on soft |
| Light `--info` | `#0284C7` | `#0275B1` | 4.10 on panel, 3.84 on soft |
| Dark `--accent-text` | `#6366F1` | `#A5B4FC` | indigo as *text* is 3.89 on the dark panel; the lighter tint is 8.71 |

Composited surfaces are the trap: an "active" chip or nav item is `accent` at 8–16% over a surface, which lands **darker than any flat token**. `--muted` is solved against those composites, not just the flat backgrounds.

### 2.4 Control boundaries

Decorative dividers use `--border`, but **interactive control edges need 3:1** (WCAG 1.4.11), which the divider colour does not reach:

| Token | Light | Dark |
|---|---|---|
| `--border-strong` / `--control-border` | `#71717A` (4.40:1 worst case) | `#6D6D70` (3.07:1) |

Inputs, selects, textareas and the segmented control use `--control-border`. Focus uses a ring built from `--focus` (`--focus-ring`).

### 2.5 Measured contrast (WCAG 2.2 AA)

Verified by `axe-core` in Chromium on all 15 sections × both themes at 1440 px and 390 px: **0 violations**. Also enforced by unit tests that parse the real token blocks (`src/lib/redesign.test.tsx`).

| Pair | Light (worst) | Dark (worst) |
|---|---|---|
| `--text` on any surface | 16.12 | 12.49 |
| `--text-soft` on any surface | 7.03 | 6.18 |
| `--muted` on any surface *and* tinted composites | 4.52 | 4.56 |
| `--accent-text` on its surfaces | 7.07 | 6.98 |
| Status pairs | 4.53 | 5.35 |
| `--control-border` on surfaces | 4.32 | 3.07 |

## 3. Chart tokens

* **Per-theme series palette, stable identity.** Sections build traces with Light identity colours; the `Plot` component runs each figure through `themeFigure()` on every render, which maps Light→Dark per series. Track *N* therefore keeps its identity (blue stays blue-family, etc.) across a theme switch, and no section re-computes on theme change.

| Series | Light | Dark |
|---|---|---|
| Track 1 / primary | `#4F46E5` indigo | `#665EE8` |
| Track 2 | `#0D9488` teal | `#0D9488` |
| Track 3 | `#7C3AED` violet | `#884CEF` |
| Track 4 | `#D97706` amber | `#D97706` |
| Track 5 | `#BE123C` crimson | `#C93A5D` |
| Reference | `#71717A` | `#71717A` |

  Tracks 6–8 extend the palette for multi-file overlays. Every entry is ≥3:1 against its own chart surface (measured: Light 3.19–6.29 on `#FFFFFF`, Dark 3.21–12.18 on `#1A1A1D`); `rgba()` tints are remapped too. A unit test also asserts no identity colour is mapped twice — a duplicate key would silently override an earlier pair.
* Overlaid series also differ by dash pattern (`DASHES`) or bar pattern, so they remain distinguishable without colour.
* Chart surface is `#FFFFFF` in Light and `#1A1A1D` in Dark. Axis, grid, tick and legend colours are read from `--chart-*` tokens at render time, so charts follow the theme; geometry, margins and axis ranges are identical in both themes.
* **Spectrograms use Magma**; the chromagram uses **Viridis** — perceptually uniform scientific maps, identical in both themes (the magnitude mapping never changes with the theme). No decorative rainbow scales.
* Level/loudness axes use `minSpanRange()` so a sub-LU wobble never fills the plot height.
* Toolbar: zoom, pan, reset, client-side PNG; **Plotly Cloud "Share chart" is removed** — measurement data never leaves the app.

## 4. Typography

System sans stack (`Inter`, Segoe UI, system-ui…) and mono stack for code. No web-font download (works offline, no third-party request).

| Token | Size | Use |
|---|---|---|
| `--text-xs` | 12 px | Labels, badges, hints (minimum size anywhere) |
| `--text-sm` | 13 px | Secondary text, controls |
| `--text-base` | 14 px | Body |
| `--text-md` | 16 px | Card titles, breadcrumb |
| `--text-lg` / `--text-xl` | 18 / 22 px | Mobile values / KPI and metric values |
| `--text-2xl` | 28 px | Page title (`h1`, one per page) |

**Measurements use a real monospace face.** `.num`, `.stat-value`, `.kpi-value`, `.metric-value`, `.qc-row-measure` and numeric table cells use `--font-mono` (JetBrains Mono → Geist Mono → IBM Plex Mono → Cascadia Code → Consolas) with `font-variant-numeric: tabular-nums` and `font-feature-settings: 'tnum' 1, 'zero' 1`. That makes columns of LUFS, dBTP, Hz and BPM align digit-for-digit and gives the slashed zero a measurement feel. Labels and prose stay in the sans stack; units are set smaller and muted beside the value. No web-font download — the stacks resolve to locally installed faces.

## 5. Spacing, shape, depth, layers

* Spacing: 4 px grid — `--space-1` 4 … `--space-8` 48.
* Radius: `--radius` 8 px (cards, tiles), `--radius-sm` 6 px (controls), `--radius-pill`.
* Depth: cards and tables use **borders**, not shadows (`--shadow-soft: none`); `--shadow` is reserved for popovers and toasts. No glows — the active navigation indicator is a solid accent bar, not a glow.
* Z-index: `--z-sticky` 20, `--z-sidebar` 40, `--z-overlay` 50, `--z-popover` 60, `--z-toast` 70.
* Breakpoints: 1380 / 1180 / 1040 / 900 / 720 / 520 px. ≤900: compact top bar; ≤720: 2-column KPIs and quick actions, stacked section headers, `.stack-mobile` tables become labelled cards, toasts move to the bottom; ≤520: metric grid 2 columns. Verified at 1440 / 834 / 390 px in both themes with **no horizontal overflow and no theme-related layout change**.

## 6. Components

| Component | File | Behaviour |
|---|---|---|
| Buttons `.btn`, `.btn-primary`, `.btn-danger`, `.btn-sm`, `.icon-button`, `.link-button` | styles.css | 36 / 32 px high (44 px on coarse pointers); primary is solid accent with `--on-accent` text; hover/active/focus/disabled all distinguishable; icon-only buttons always have `aria-label` |
| Inputs, selects, textareas, `.input-with-unit`, `.search-field` | styles.css | 36 px; `--control-border` edge, `--input-bg` fill; `aria-invalid` shows an error ring; errors are text next to the field; disabled state uses `--disabled-fg/bg` and stays distinguishable |
| `Card`, `SectionHeader` | components/UI.tsx | One `h1` per page (section header); card titles are `h3` |
| `Kpi` tiles | sections/DashboardSection.tsx | Real values only; crisp 1px `--border` outline, `box-shadow: none`, tone stripe on the left edge; value in `--font-mono` with tabular figures |
| `MetricCard` | components/UI.tsx | Name, value, unit, status (from the QC rule), Measured/Estimate + confidence, `InfoTip` explanation; missing value → "Not available", never a pass |
| `InfoTip` | components/UI.tsx | Button with `aria-describedby`; opens on hover, focus or tap; Escape closes; themed tooltip |
| `SeverityBadge`, `Badge` | components/UI.tsx | Icon + text; status soft pair plus a 22% same-hue outline (`color-mix`), so it reads as a printed label rather than a saturated pill |
| `TableWrap` + `.data-table` | components/UI.tsx | Labelled, keyboard-focusable scroll region; sticky header (`--table-header-bg`); `th[scope=row]`; sortable headers use `.th-sort` + `aria-sort`; row hover/selected use `--table-row-hover` / `--table-row-selected` |
| `ToggleGroup` | components/UI.tsx | Segmented control with `aria-pressed` (used for the Settings theme selector) |
| Theme select | App.tsx | `combobox` "Theme" in the top bar on every screen size; Light / Dark / System |
| `Plot` | components/Plot.tsx | Lazy-loads Plotly; loading / empty / error states; figure name + text summary; re-renders on theme change via `themeFigure()` |
| `ActiveFileBar` | components/ActiveFileBar.tsx | Sticky file context for analysis screens: selector, properties, QC status, previous/next |
| `ProgressBar` | components/UI.tsx | `role=progressbar` with `aria-valuenow`; only shows server-reported progress |
| Toasts | components/Toast.tsx | `aria-live=polite`, `--toast-bg` surface; bottom-right (bottom full-width on mobile) |
| Print | styles.css `@media print` | Forces white paper / near-black ink regardless of theme — the only literals outside the token blocks, intentional for printing |

Dialogs: the application uses the native `window.confirm` for the single destructive action (delete session), which is keyboard and screen-reader accessible; no custom modal component is needed.

## 7. Interaction rules

* Navigation is hash-based (`#/section?file=…&start=…&end=…`): deep links and Back/Forward work; a QC time position opens the waveform zoomed to that range. Active navigation uses `--selected-bg` + accent bar, hover a neutral surface, focus a visible ring.
* The active file is shared by every analysis section; overlays add extra files locally.
* Buttons that cannot act are disabled *and* explain why (hint text or `title`).
* Long operations show the backend's real stage text and progress; nothing is estimated client-side.
* Motion: 150–250 ms colour/border transitions only; `prefers-reduced-motion` and the in-app "Reduce animations" setting disable section/toast animation.
* Theme choice never resets on navigation, refresh, route change, upload, analysis, chart render or report generation.

## 8. Verification

| Check | Command | Result |
|---|---|---|
| Unit + token-contrast guards | `cd frontend && npx vitest run` | 34 passed |
| Typecheck / build | `cd frontend && npm run build` | clean |
| Browser suite (incl. theme, navigation, charts, exports) | `python -m pytest frontend/e2e/test_ui.py -q` | 26 passed |
| Axe, 15 sections × 2 themes × 2 widths | `python frontend/e2e/axe_detail.py --session …` | 0 violations |
| Visual regression, 4 pages × 2 themes | `AAP_UPDATE_BASELINE=1` then re-run | 8 baselines, stable |
| Responsive overflow, 5 sections × 2 themes × 3 widths | screenshot script | 30/30 no horizontal overflow |

Screenshots for both themes at desktop/tablet/mobile live in `frontend/e2e/screenshots/`.

## 9. Implementation record

Changes made in this pass, in the format *original → required → implemented → tested → result*.

| # | Original | Required change | Implemented | Test | Result |
|---|---|---|---|---|---|
| 1 | Single dark-leaning palette; token names `--bg-0`, `--panel`, `--accent`… | Two exact specified palettes, centrally defined | Rewrote both token blocks at the top of `styles.css` with the exact Light and Dark values; kept existing token names, added semantic ones (`--series-*`, `--chart-*`, `--control-border`, `--table-*`, `--status-soft`) | `vitest` token-contrast suite parses both blocks | pass |
| 2 | Two-state sun/moon button; default dark | Light / Dark / **System**, persisted, system-following, no flash | `lib/theme.ts` (pure model) + `Workspace.tsx` controller + pre-paint script in `index.html`; top-bar `combobox` and Settings `ToggleGroup` share one preference | `test_theme_toggle_persists_and_restyles_charts`, `test_system_theme_follows_os_and_updates_live`, `test_no_saved_preference_follows_os_and_defaults_to_light` | pass |
| 3 | Chart series had fixed colours; charts did not re-theme | Per-theme series colours that keep track identity | `themeFigure()` in `Plot.tsx` remaps identity→theme pair on every render, including `rgba()` tints; `PAIRS` defines the mapping | `test_dark_chart_series_keeps_track_identity`, unit test on `themeColor` | pass |
| 4 | Status/confidence chips used ad-hoc alpha tints of the foreground | Specified per-theme status pairs; WCAG AA | `.conf-*`, `.deviation`, `.status-*` now use `--*-soft` pairs; removed the duplicated `.status-pill.status-*` block | `axe_detail.py` (was 12 failing nodes incl. 4.29/4.48) | 0 violations |
| 5 | 21 hard-coded colour literals in 4 sections + unused legacy palette | No colours outside the token layer | Replaced literals with `COLORS`/tokens; deleted dead `BAND_COLORS` | grep for hex literals in `src/**/*.tsx` | none found |
| 6 | `--faint` used on tinted surfaces (4.27–4.37:1) | ≥4.5:1 on every surface it is used on | Stat labels, hints, file-chip meta and file-list meta use `--muted` | `axe_detail.py` Light, all sections | 0 violations |
| 7 | Active nav carried a glow shadow | No neon glows (spec) | Solid accent bar, no `box-shadow` glow | visual baseline review | pass |
| 8 | Visual baselines captured from the old palette, single theme | Baselines for both themes | Parametrised `test_visual_regression` over `light`/`dark`; regenerated 8 baselines | `pytest -k visual_regression` | 8 pass |
| 9 | Legacy browser test clicked the removed "Switch to light theme" button | Cover the new selector and persistence | Rewrote as three focused tests + theme-persistence and chart-identity tests | full `pytest frontend/e2e/test_ui.py` | 26 pass |
| 10 | Cool blue/white SaaS light theme; indigo unused | Refined "Clean Analytical": `#FAFAFA` base, `#18181B` type, `#4F46E5` indigo accent | Rewrote the light token block; accents, selected states, tooltips, table tokens and chart series all moved to the indigo system | `vitest` contrast suite + `axe_detail.py` | pass / 0 violations |
| 11 | `--faint` rendered at 2.33:1 with the proposed `#A1A1AA` | Muted text ≥4.5 on every surface | `--muted`/`--faint` = `#65656D`, solved against flat surfaces **and** the accent-tinted composites (active chip 4.93, active nav 4.52) | new unit test `muted text survives the accent-tinted composites`; verified it fails on `#71717A` | pass |
| 12 | Proposed status hues measured 2.6–3.3:1 | Status text ≥4.5 on panel, app bg and its own soft tint | Kept the hues, darkened to `#11813A` / `#A75C05` / `#D82525` / `#0275B1` | `axe_detail.py` all sections | 0 violations |
| 13 | KPI tiles used the panel background with a tone stripe | Crisp 1px border, no shadow, sharper numbers | `.kpi` keeps `border: 1px solid var(--border)` and forces `box-shadow: none`; values use the mono stack | screenshot review | pass |
| 14 | Table header used `--muted` at 700 weight / 0.08em | Distinct header so rows scan faster | Header uses `--table-header-bg` / `--table-header-text`, 600 weight, 0.05em | screenshot review | pass |
| 15 | Critical badge was a saturated pill | Printed-label feel | Badges keep the soft pair and gain a 22% same-hue outline via `color-mix` | `axe_detail.py` (contrast unchanged — outline only) | 0 violations |
| 16 | Active tab used `--accent` as text | Fill colours are not text-safe on dark | `.tabs button.active` uses `--accent-text` (dark: 8.71:1 instead of 3.2:1) | `axe_detail.py` dark/spectrogram | fixed |
| 17 | `PAIRS` listed `#4F46E5` and `#71717A` twice | A duplicate identity key silently overrides | De-duplicated; added a unit test asserting each identity maps once | `vitest` duplicate-key guard | pass |

## 10. Changing the theme

1. Edit a value in the relevant token block of `frontend/src/styles.css` — never a component.
2. If it is a chart series, update the matching pair in `PAIRS` (`src/lib/plotTheme.ts`).
3. Run `npx vitest run` (contrast guards) and `npm run build`.
4. Re-capture baselines with `AAP_UPDATE_BASELINE=1` only when the change is intended.
