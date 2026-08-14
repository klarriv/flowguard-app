# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
streamlit run app/app.py
```

The app runs on `http://localhost:8501`.

PDF report generation requires WeasyPrint:

```bash
pip install weasyprint
```

## Architecture

FlowGuard is a Streamlit engineering-calculation app focused on explosion protection per NFPA 68 (2023). This repo (`flowguard-app`) contains the Streamlit UI only — no calculation logic. All engineering calculations live in the separate `flowguard` package (sibling repo, installed via `requirements.txt`'s `git+https://github.com/klarriv/flowguard.git`), which provides two top-level packages importable from the UI: `explosion_protection` and `core`.

### 1. Calculation engine (external `flowguard` package)

Pure-Python library with no Streamlit dependency, versioned in its own repo. Not editable from within `flowguard-app` — changes require editing the `flowguard` repo and reinstalling.

- `explosion_protection/nfpa_68_ch6_equations.py` — general venting fundamentals shared across Chapters 7/8 (§6.1–§6.8): deflagration index, enclosure design pressure/reaction forces, and the §6.4.3 hydraulic diameter/L-D equations (`hydraulic_diameter_circular/square/rectangular`, `effective_area`, `ld_ratio`).
- `explosion_protection/nfpa_68_ch8_equations.py` — raw equation implementations (§8.2–§8.5 formulas, each function maps directly to one NFPA equation)
- `explosion_protection/nfpa_68_ch8_dust_vent.py` — orchestrator that sequences the equations into the full calculation chain (Av0 → Av1 → Av2 → Av3 → Av4 → Avf). This file owns the input dataclasses (`Enclosure`, `Dust`, `Vent`, `Duct`, `TurbulenceInputs`, `PartialVolumeInputs`), enums (`TurbulenceMode`, `SubatmosphericMethod`), result dataclass (`DustVentResult`), and the two public entry points: `vent_area_dust()` and `dust_collector_vent_area()`.
- `core/geometry.py` — shape volume formulas (`vol_cuboid`, `vol_cylinder`, `vol_truncated_cone`, `vol_truncated_rect_pyramid`) plus enclosure-geometry aggregation (`segment_volume`, `enclosure_volume_and_length`) and §6.4.3 hydraulic diameter orchestration (`enclosure_hydraulic_diameter`, `largest_cross_section`) that picks the circular/square/rectangular formula in `nfpa_68_ch6_equations.py` matching the shape of the enclosure's largest cross section. A segment may set `cols`/`rows` (default 1×1) to represent identical side-by-side copies (e.g. multiple hoppers under one shared body) — `segment_count()` scales volume and combined cross-section area by `cols*rows`, but never height, since parallel copies share the same vertical span.
- `core/enclosure_catalog.py` — named enclosure geometry templates: `circular_enclosure_default()`, `rectangular_enclosure_default()`, and a Donaldson dust-collector family/model catalog (`list_families()`, `list_models()`, `get_model()`).
- `core/vent_panel_catalog.py` — manufacturer vent panel catalog (`VENT_PANEL_CATALOG`, keyed by manufacturer then panel type, currently just `Vigilex` × `Standard`/`Vacuum`/`High Vacuum`). Each `VentPanel` stores raw `w_mm`/`h_mm` and derives `nominal_metric`/`nominal_imperial` display strings from them (imperial rounds to the nearest whole inch, half-up); `model` is the manufacturer's product-line code from the source datasheet (`"VL"`/`"VD"`/`"VD-HV"` for Vigilex — one per `panel_type`), not a manufacturer SKU. `STOCKED_SIZES_MM` is a fixed set of 14 nominal (w, h) sizes normally kept in stock, applied uniformly across manufacturers/types (`VentPanel.is_stocked` checks membership — not every stocked size exists in every panel type, e.g. High Vacuum only carries 10 of the 14). `list_manufacturers()`, `list_panel_types(manufacturer)`, `list_panels()`, and `compute_panel_selection(avf_m2, manufacturers, panel_types, efficiency, stocked_only=False)` (both filter args are lists — the panel-count/effective-area math backing the page's Selection section, merging results across every requested manufacturer × panel type, optionally restricted to stocked sizes, and sorting ascending by panels required) round out the module.

The Chapter 7 gas-vent equivalents (`nfpa_68_ch7_*.py`) exist but are not yet wired into the UI.

### 2. Streamlit UI (`app/`)

- `app.py` — home page; a static stub (logo, sidebar nav links to the calculation pages). No project selection/creation and no run list — see "Project data" below.
- `pages/1_Dust_Vent_NFPA68.py` — the main calculation page. Its top section, "Enclosure Geometry", lets the user establish V and L/D via a method dropdown (Circular Enclosure / Rectangular Enclosure / Donaldson / Manual Input) — the first three seed a segment-stack builder (add/edit/delete shape segments, unit toggle m/ft/in, 3D Plotly preview) from a preset or the Donaldson catalog, all fully editable afterward; Manual Input takes V and L/D directly. A "Reset All" button clears all geometry-section session state back to defaults. Any segment can be set to 1/2/4 side-by-side copies (with an along-X/along-Y arrangement choice for 2) to model parallel discharge paths — setting the same copies/arrangement on consecutive segments (e.g. a hopper and the barrel below it) groups them into one repeated, aligned sub-stack in the 3D view; this is a manual convention, not automatic grouping. For the segment-stack modes, the hydraulic diameter and L/D come directly from `core.geometry.enclosure_hydraulic_diameter()` and `explosion_protection.nfpa_68_ch6_equations.ld_ratio()` (§6.4.3) — no manual override. **Vent location is intentionally not modeled**: per §6.4.3.2/.3, V and L are taken as Veff and H exactly as built — the engineer is responsible for modeling the segment stack to already end at the vent (e.g. excluding roof headspace above a side-mounted vent), or per §6.4.3.4 conservatively using the whole enclosure; either way no vent-position input is needed. Multiple vents at different elevations along the same axis (§6.4.3.2.2, which calls for a per-section L/D) is a known, unsupported edge case. Below that, the rest of the page builds the remaining input widgets (Dust, Vent, Duct, Turbulence, Partial Volume), calls the engine, and renders the step-by-step result table. Between Results and Report/Export sits "Selection": Manufacturer and Panel Type are multiselect *filters* (default to everything in `core.vent_panel_catalog`, not a single-value picker) narrowing which catalog panels are considered; Efficiency [%] is a single numeric input; a "Stocked sizes only" toggle (default **on**) restricts to `STOCKED_SIZES_MM`, switchable off to see the full manufacturer range. Together they drive `compute_panel_selection(Avf, manufacturers, panel_types, efficiency, stocked_only)`, tabulating every matching catalog panel (Manufacturer, Model, Nominal metric/imperial, Vent Area, Panel Density, Panels Required, Total Effective Area — sorted ascending by panels required) so the engineer can compare options; a "Final Selection" dropdown below the table then picks exactly one row. Only that final pick (not the filtered table) is persisted to the run JSON and shown in the PDF report — the table is an on-page comparison aid. The Report/Export section also has a free-text "Comments" field (persisted to `meta.comments`, shown as its own section in the PDF, HTML-escaped). The page performs no engineering calculations itself — only widget wiring, session-state bookkeeping for the geometry builder, and the Plotly 3D mesh construction (`_mesh_frustum`/`_mesh_box`/`_build_3d_figure`), which is UI rendering, not physics.
- `utils/serializer.py` — converts engine dataclasses ↔ JSON-safe dicts for persistence and form pre-fill
- `components/report.py` — generates a PDF report from a saved run dict using WeasyPrint (renders HTML → PDF). Includes an "Enclosure Geometry" section (method, V/L/Dhe/L/D, per-segment breakdown) whenever the run's `inputs.geometry` is present — i.e. whenever the run wasn't built with Manual Input. No 3D image is embedded — the segment-stack view is interactive-only, in the app's Plotly preview. Section numbers are computed, not hardcoded, so the optional sections (Geometry, Vent Panel Selection, Comments) don't leave gaps when omitted.

### 3. Project data

There is no filesystem persistence — runs are not saved to disk anywhere by the app.
A completed calculation is exported via "Download JSON" (the full inputs+outputs
payload built by `build_run_payload()`) and/or "Download PDF". "Load Previous Run"
in the sidebar re-uploads a previously-downloaded JSON file into
`st.session_state["loaded_run"]`, which pre-fills the form through the `_pre()`
helper in the page module. The Enclosure Geometry method, unit, and full segment
breakdown are persisted in that JSON alongside the resolved `V`/`LD`/`Vsolid`
(needed for the PDF's Enclosure Geometry section), and reload re-seeds the segment
builder from them via `_seed_segments()` — landing back on the original method
(Circular/Rectangular/Donaldson) with the same segments, not Manual Input. Segments
are always re-seeded in metres (`_seed_segments` stores values as-is with no unit
conversion) regardless of the unit the run was originally built in; the user can
switch display units afterward as normal. Runs saved before this geometry-persistence
existed (or that used Manual Input) have no `inputs.geometry` key and still land on
Manual Input with the saved `V`/`LD` numbers.

## Key conventions

- All physical quantities use SI units (m, m³, bar-g, kg/m², m/s) throughout the engine and storage layers.
- The calculation chain always proceeds Av0 → Av1 → Av2 → Av3 → Av4 → Avf; each step is a separate `_step_*` function in the orchestrator, making it straightforward to add new correction steps.
- All calculation logic (equations, geometry, catalogs) belongs in the `flowguard` package, not in `app/`. The webapp only calls into it and renders results; new physics or geometry math should be added there, not inlined in a Streamlit page.
- New calculation pages go in `app/pages/` and must manually add the `_workspace` path insertion (see the existing pattern in `1_Dust_Vent_NFPA68.py`) to import from the engine.
- `sys.path.insert(0, str(_workspace))` at the top of each page handles the package resolution for both the Streamlit multi-page layout and flat dev/test runs.
