# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
streamlit run app/app.py
```

The app runs on `http://localhost:8501`. The `PROJECTS_ROOT` environment variable overrides the default projects directory (`projects/` at the repo root).

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
- `core/geometry.py` — shape volume formulas (`vol_cuboid`, `vol_cylinder`, `vol_truncated_cone`, `vol_truncated_rect_pyramid`) plus enclosure-geometry aggregation (`segment_volume`, `enclosure_volume_and_length`) and §6.4.3 hydraulic diameter orchestration (`enclosure_hydraulic_diameter`, `largest_cross_section`) that picks the circular/square/rectangular formula in `nfpa_68_ch6_equations.py` matching the shape of the enclosure's largest cross section.
- `core/enclosure_catalog.py` — named enclosure geometry templates: `circular_enclosure_default()`, `rectangular_enclosure_default()`, and a Donaldson dust-collector family/model catalog (`list_families()`, `list_models()`, `get_model()`).

The Chapter 7 gas-vent equivalents (`nfpa_68_ch7_*.py`) exist but are not yet wired into the UI.

### 2. Streamlit UI (`app/`)

- `app.py` — home page; handles project selection/creation and shows a run list
- `pages/1_Dust_Vent_NFPA68.py` — the main calculation page. Its top section, "Enclosure Geometry", lets the user establish V and L/D via a method dropdown (Circular Enclosure / Rectangular Enclosure / Donaldson / Custom / Manual Input) — the first four seed a segment-stack builder (add/edit/delete shape segments, unit toggle m/ft/in, 3D Plotly preview) from a preset or the Donaldson catalog, all fully editable afterward; Manual Input takes V and L/D directly. For the segment-stack modes, the hydraulic diameter and L/D come from `core.geometry.enclosure_hydraulic_diameter()` and `explosion_protection.nfpa_68_ch6_equations.ld_ratio()` (§6.4.3), with a manual override. **Vent location is intentionally not modeled**: per §6.4.3.2/.3, V and L are taken as Veff and H exactly as built — the engineer is responsible for modeling the segment stack to already end at the vent (e.g. excluding roof headspace above a side-mounted vent), or per §6.4.3.4 conservatively using the whole enclosure; either way no vent-position input is needed. Multiple vents at different elevations along the same axis (§6.4.3.2.2, which calls for a per-section L/D) is a known, unsupported edge case. Below that, the rest of the page builds the remaining input widgets (Dust, Vent, Duct, Turbulence, Partial Volume), calls the engine, renders the step-by-step result table, and drives save/PDF. The page performs no engineering calculations itself — only widget wiring, session-state bookkeeping for the geometry builder, and the Plotly 3D mesh construction (`_mesh_frustum`/`_mesh_box`/`_build_3d_figure`), which is UI rendering, not physics.
- `utils/project_store.py` — filesystem CRUD for projects and runs
- `utils/serializer.py` — converts engine dataclasses ↔ JSON-safe dicts for persistence and form pre-fill
- `components/report.py` — generates a PDF report from a saved run dict using WeasyPrint (renders HTML → PDF)

### 3. Project data (`projects/`)

```
projects/
└── {project_name}/
    ├── project.yaml          # name, client, description, created
    └── runs/
        ├── {run_id}.json     # inputs + outputs serialized by serializer.py
        └── {run_id}.pdf      # generated report (optional)
```

Run IDs are 8-character UUID hex strings. Runs are loaded back into the UI via `load_run()`, which pre-fills the form through the `_pre()` helper in the page module. Only the resolved `V`/`LD`/`Vsolid` are persisted — the Enclosure Geometry method and segment breakdown used to derive them are not saved, so reloading a run always lands on "Manual Input" with the saved numbers.

## Key conventions

- All physical quantities use SI units (m, m³, bar-g, kg/m², m/s) throughout the engine and storage layers.
- The calculation chain always proceeds Av0 → Av1 → Av2 → Av3 → Av4 → Avf; each step is a separate `_step_*` function in the orchestrator, making it straightforward to add new correction steps.
- All calculation logic (equations, geometry, catalogs) belongs in the `flowguard` package, not in `app/`. The webapp only calls into it and renders results; new physics or geometry math should be added there, not inlined in a Streamlit page.
- New calculation pages go in `app/pages/` and must manually add the `_workspace` path insertion (see the existing pattern in `1_Dust_Vent_NFPA68.py`) to import from the engine.
- `sys.path.insert(0, str(_workspace))` at the top of each page handles the package resolution for both the Streamlit multi-page layout and flat dev/test runs.
