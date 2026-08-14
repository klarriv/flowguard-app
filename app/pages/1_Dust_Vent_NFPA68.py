"""
pages/1_Dust_Vent_NFPA68.py
============================
NFPA 68 (2023) Chapter 8 — Deflagration Vent Sizing for Dusts.
"""

import base64
import json
import math
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from core.geometry import (
    segment_volume, enclosure_volume_and_length, enclosure_hydraulic_diameter,
    largest_cross_section,
)
from core.enclosure_catalog import (
    circular_enclosure_default, rectangular_enclosure_default,
    list_families, list_models, get_model,
)
from core.vent_panel_catalog import (
    list_manufacturers, list_panel_types as list_vent_panel_types,
    compute_panel_selection,
)
from explosion_protection.nfpa_68_ch6_equations import ld_ratio as ch6_ld_ratio
from explosion_protection.nfpa_68_ch8_dust_vent import (
    Enclosure, Dust, Vent, Duct, TurbulenceInputs, PartialVolumeInputs,
    TurbulenceMode, SubatmosphericMethod,
    vent_area_dust, dust_collector_vent_area,
    DustVentResult,
)

from utils.serializer import inputs_to_dict, result_to_dict, build_run_payload

# ── Enclosure Geometry — unit conversion (display-only; math lives in flowguard) ─
UNIT_TO_M     = {"m": 1.0,   "ft": 0.3048, "in": 0.0254}
UNIT_STEP     = {"m": 0.05,  "ft": 0.1,    "in": 0.5}
UNIT_MIN_POS  = {"m": 0.001, "ft": 0.003,  "in": 0.04}
_DIM_PREFIXES = ("eb_a_", "eb_b_", "eb_h_", "eb_r_", "eb_R_", "eb_A_", "eb_B_")

_SEG_COLORS = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756",
    "#72B7B2", "#FF9DA7", "#9D755D", "#BAB0AC",
]

SHAPES = {
    "cuboid":                 "Rectangular Box",
    "cylinder":               "Cylinder",
    "truncated_cone":         "Truncated Cone (Conical Hopper)",
    "truncated_rect_pyramid": "Truncated Rectangular Pyramid (Hopper)",
}
SHAPE_LABELS = {v: k for k, v in SHAPES.items()}

# Side-by-side segment copies: single source of truth for the
# (copies_label, arrangement) <-> (cols, rows) mapping, looked up in both
# directions (UI -> cols/rows in the editor loop, cols/rows -> UI in
# _seed_segments) so the two can't drift apart.
SEGMENT_COPY_LAYOUTS = [
    ("1", None,      1, 1),
    ("2", "Along X", 2, 1),
    ("2", "Along Y", 1, 2),
    ("4", None,      2, 2),
]


def _copy_layout_to_cols_rows(copies_label, arrangement):
    for lbl, arr, cols, rows in SEGMENT_COPY_LAYOUTS:
        if lbl == copies_label and (arr is None or arr == arrangement):
            return cols, rows
    return 1, 1


def _cols_rows_to_copy_layout(cols, rows):
    for lbl, arr, c, r in SEGMENT_COPY_LAYOUTS:
        if (c, r) == (cols, rows):
            return lbl, arr
    return "1", None


def _mesh_frustum(R: float, r: float, h: float, z0: float, N: int = 60):
    """
    Triangulated solid mesh for a circular frustum (truncated cone).
    R = bottom radius, r = top radius. All args in metres.
    Returns (x, y, z, i, j, k) for go.Mesh3d.
    """
    theta = np.linspace(0, 2 * math.pi, N, endpoint=False)
    ct, st_ = np.cos(theta), np.sin(theta)

    x = np.concatenate([R * ct, r * ct, [0.0, 0.0]])
    y = np.concatenate([R * st_, r * st_, [0.0, 0.0]])
    z = np.concatenate([np.full(N, z0), np.full(N, z0 + h), [z0, z0 + h]])

    ii, jj, kk = [], [], []
    for idx in range(N):
        nxt = (idx + 1) % N
        ii += [idx,     idx     ]; jj += [nxt,     N + nxt]; kk += [N + nxt, N + idx]
        ii += [2 * N  ]; jj += [nxt      ]; kk += [idx      ]
        ii += [2*N + 1]; jj += [N + idx  ]; kk += [N + nxt  ]

    return x.tolist(), y.tolist(), z.tolist(), ii, jj, kk


def _mesh_box(ax: float, bx: float, ax2: float, bx2: float, h: float, z0: float):
    """
    Triangulated solid mesh for a rectangular frustum. All args in metres.
    Bottom base ax × bx, top base ax2 × bx2, both centred at origin.
    Returns (x, y, z, i, j, k) for go.Mesh3d.
    """
    ha, hb   = ax  / 2, bx  / 2
    ha2, hb2 = ax2 / 2, bx2 / 2

    x = [-ha,  ha,  ha, -ha, -ha2,  ha2,  ha2, -ha2]
    y = [-hb, -hb,  hb,  hb, -hb2, -hb2,  hb2,  hb2]
    z = [z0]*4 + [z0 + h]*4

    ii = [0, 0,  4, 4,  0, 0,  2, 2,  0, 0,  1, 1]
    jj = [3, 2,  5, 6,  1, 5,  3, 7,  4, 7,  2, 6]
    kk = [2, 1,  6, 7,  5, 4,  7, 6,  7, 3,  6, 5]

    return x, y, z, ii, jj, kk


def _segment_footprint(seg: dict) -> tuple[float, float]:
    """Natural (width, depth) footprint of one copy of a segment — the top-facing
    size used to space tiled side-by-side copies without overlap."""
    stype = seg["type"]
    if stype in ("cylinder", "truncated_cone"):
        d = 2 * max(seg.get("r", 0.0), seg.get("R", 0.0))
        return d, d
    if stype == "cuboid":
        return seg["a"], seg["b"]
    if stype == "truncated_rect_pyramid":
        return seg["A"], seg["B"]
    return 0.0, 0.0


def _build_3d_figure(seg_params: list[dict]) -> go.Figure:
    """Build a Plotly 3D figure. seg_params dicts carry SI values."""
    traces = []
    z_base = sum(seg["h"] for seg in seg_params)   # top of the stack

    # Group consecutive segments sharing the same (cols, rows) into runs, so a
    # repeated sub-stack (e.g. a hopper and the barrel below it, both tiled
    # x4) uses one consistent spacing and stays aligned copy-for-copy.
    run_of: dict[int, int] = {}
    run_members: dict[int, list[int]] = {}
    cur_run_id, cur_key = None, None
    for idx, seg in enumerate(seg_params):
        key = (seg.get("cols", 1), seg.get("rows", 1))
        if key != cur_key:
            cur_run_id, cur_key = idx, key
            run_members[cur_run_id] = []
        run_of[idx] = cur_run_id
        run_members[cur_run_id].append(idx)

    run_spacing = {
        run_id: (
            max(_segment_footprint(seg_params[i])[0] for i in idxs),
            max(_segment_footprint(seg_params[i])[1] for i in idxs),
        )
        for run_id, idxs in run_members.items()
    }

    for idx, seg in enumerate(seg_params):
        z_base -= seg["h"]
        color = _SEG_COLORS[idx % len(_SEG_COLORS)]
        stype = seg["type"]
        h     = seg["h"]
        label = SHAPES.get(stype, stype)

        if stype == "cylinder":
            args = _mesh_frustum(seg["r"], seg["r"], h, z_base)
        elif stype == "truncated_cone":
            args = _mesh_frustum(seg["r"], seg["R"], h, z_base)
        elif stype == "cuboid":
            args = _mesh_box(seg["a"], seg["b"], seg["a"], seg["b"], h, z_base)
        elif stype == "truncated_rect_pyramid":
            args = _mesh_box(seg["a"], seg["b"], seg["A"], seg["B"], h, z_base)
        else:
            continue

        xv0, yv0, zv, iv, jv, kv = args
        cols, rows  = seg.get("cols", 1), seg.get("rows", 1)
        ref_w, ref_h = run_spacing[run_of[idx]]

        first_copy = True
        for j in range(cols):
            for k in range(rows):
                ox = (j - (cols - 1) / 2) * ref_w
                oy = (k - (rows - 1) / 2) * ref_h
                xv = [x + ox for x in xv0] if (ox or oy) else xv0
                yv = [y + oy for y in yv0] if (ox or oy) else yv0
                copy_note = f" — copy {j * rows + k + 1}/{cols * rows}" if cols * rows > 1 else ""
                traces.append(go.Mesh3d(
                    x=xv, y=yv, z=zv,
                    i=iv, j=jv, k=kv,
                    color=color,
                    opacity=0.88,
                    flatshading=True,
                    name=f"Seg {idx + 1} — {label}",
                    showlegend=first_copy,
                    hovertemplate=(
                        f"<b>Segment {idx + 1}</b>{copy_note}<br>{label}<br>"
                        f"V = {seg['vol_si']:.4f} m³<extra></extra>"
                    ),
                ))
                first_copy = False

    if not traces:
        return go.Figure()

    fig = go.Figure(data=traces)
    fig.update_layout(
        scene=dict(
            aspectmode="data",
            xaxis=dict(title="", showticklabels=False, showbackground=True,
                       backgroundcolor="rgba(240,240,240,0.5)"),
            yaxis=dict(title="", showticklabels=False, showbackground=True,
                       backgroundcolor="rgba(240,240,240,0.5)"),
            zaxis=dict(title="", showticklabels=False, showbackground=True,
                       backgroundcolor="rgba(230,230,230,0.5)"),
            camera=dict(up=dict(x=0, y=0, z=1), eye=dict(x=1.4, y=1.4, z=1.1)),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="top", y=-0.02,
                    xanchor="left", x=0, font=dict(size=11)),
        height=520,
    )
    return fig


def _seed_segments(segments: list[dict]) -> None:
    """Reset the Enclosure Geometry segment builder to a given list of segment dicts (SI)."""
    old_len = len(st.session_state.get("eb_seg_types", []))
    st.session_state.eb_seg_types = [s["type"] for s in segments]
    for i, seg in enumerate(segments):
        st.session_state[f"eb_type_sel_{i}"] = SHAPES[seg["type"]]
        cols, rows = seg.get("cols", 1), seg.get("rows", 1)
        copies_label, arrangement = _cols_rows_to_copy_layout(cols, rows)
        st.session_state[f"eb_copies_{i}"] = copies_label
        if arrangement is not None:
            st.session_state[f"eb_arrange_{i}"] = arrangement
        else:
            st.session_state.pop(f"eb_arrange_{i}", None)
        for k, v in seg.items():
            if k not in ("type", "cols", "rows"):
                st.session_state[f"eb_{k}_{i}"] = float(v)
    for i in range(len(segments), old_len):
        for suffix in ("a", "b", "h", "r", "R", "A", "B", "type_sel", "copies", "arrange"):
            st.session_state.pop(f"eb_{suffix}_{i}", None)


@st.cache_data(show_spinner=False)
def _make_pdf(payload_json: str, logo_path_str: str | None) -> bytes:
    from components.report import generate_pdf_bytes
    return generate_pdf_bytes(json.loads(payload_json), logo_path=logo_path_str)

LOGO_PATH = str(Path(__file__).parent.parent / "assets" / "logo_capt-air.jpg")

st.set_page_config(
    page_title="Dust Vent — NFPA 68 Ch.8",
    page_icon="💨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    logo_path = Path(__file__).parent.parent / "assets" / "logo_capt-air.jpg"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    st.markdown("---")
    st.markdown("### Calculations")
    st.page_link("app.py", label="Home")
    st.page_link("pages/1_Dust_Vent_NFPA68.py", label="💨 Dust Vent — NFPA 68 Ch.8")
    st.markdown("---")
    st.markdown("### Load Previous Run")
    uploaded = st.file_uploader("Upload a saved JSON file", type=["json"], label_visibility="collapsed")
    if uploaded is not None and uploaded.file_id != st.session_state.get("_loaded_run_file_id"):
        try:
            data = json.loads(uploaded.read())
            st.session_state["loaded_run"] = data
            st.session_state["_loaded_run_file_id"] = uploaded.file_id
            st.session_state["_show_loaded_banner"] = True
            # Seed the Enclosure Geometry segment builder here, once, at upload
            # time — not on every rerun (see the persistent `loaded` read below).
            _geo = (data.get("inputs") or {}).get("geometry")
            if _geo:
                st.session_state["eg_mode"] = _geo["mode"]
                st.session_state["eb_unit"] = "m"  # segments are persisted in SI
                if _geo["mode"] == "Donaldson" and _geo.get("donaldson_family") and _geo.get("donaldson_model"):
                    st.session_state["eg_family"] = _geo["donaldson_family"]
                    st.session_state["eg_model"]  = _geo["donaldson_model"]
                _seed_segments(_geo["segments"])
            st.rerun()
        except Exception:
            st.error("Could not parse JSON file.")
    st.markdown("---")
    st.page_link("app.py", label="← Home")

# ── Pre-fill from loaded run ───────────────────────────────────────────────────
# Read (not pop!) — every input widget's `value=_pre(...)` needs this to stay
# stable across every rerun for the rest of the session, not just the first one
# after upload. Popping it here made `_pre()` silently fall back to hardcoded
# defaults on the very next rerun (i.e. the moment the user edited any field),
# which — since none of these widgets have an explicit `key=` — made Streamlit
# treat the changed `value=` as a brand-new widget and discard the edit.
loaded = st.session_state.get("loaded_run", None)

def _pre(key: str, default):
    if loaded is None:
        return default
    inp   = loaded.get("inputs", {})
    parts = key.split(".")
    val   = inp
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p, default)
        else:
            return default
    return val if val is not None else default

def _pre_meta(key: str, default=""):
    return loaded.get("meta", {}).get(key, default) if loaded else default

def _b64_img(filename):
    p = Path(__file__).parent.parent / "assets" / filename
    if not p.exists():
        return None
    mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif"}.get(p.suffix.lstrip(".").lower(), "png")
    return f"data:image/{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"

def _label(container, text, tip=None, tip_img=None):
    if tip_img:
        src = _b64_img(tip_img)
        if src:
            container.markdown(
                f'<div class="tt-label">{text}'
                f' <span class="tt-icon">ⓘ</span>'
                f'<div class="tt-box tt-box-img">'
                f'<img src="{src}" style="max-width:300px;width:100%;border-radius:4px;display:block">'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            return
    elif tip:
        container.markdown(
            f'<div class="tt-label">{text}'
            f' <span class="tt-icon">ⓘ</span>'
            f'<div class="tt-box">{tip}</div></div>',
            unsafe_allow_html=True,
        )
        return
    container.write(text)


def _warn_ld(value):
    if value > 6.0:
        st.warning(f"L/D = {value:.2f} exceeds 6.0 — outside NFPA 68 §8.1.1 scope. "
                   "Verify applicability with your engineer of record.")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="column"] { overflow: visible !important; }
.tt-label {
    position: relative; cursor: default;
    padding-top: 8px; font-size: 0.9rem; line-height: 1.4;
}
.tt-icon { opacity: 0.45; font-size: 0.8em; margin-left: 3px; cursor: help; }
.tt-box {
    visibility: hidden;
    background: #1e1e1e; color: #f0f0f0;
    border-radius: 5px; padding: 6px 10px;
    position: absolute; left: 0; top: 110%;
    z-index: 9999; pointer-events: none;
    white-space: normal; max-width: 260px;
    font-size: 0.78rem; line-height: 1.45;
    box-shadow: 0 2px 8px rgba(0,0,0,0.35);
}
.tt-label:hover .tt-box { visibility: visible; }
.tt-box-img { max-width: 320px; width: max-content; white-space: normal; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
st.title("Dust Deflagration Vent Sizing")
st.caption("NFPA 68 (2023) · Chapter 8 · §8.2 – §8.5")

if st.session_state.pop("_show_loaded_banner", False):
    st.success(f"Loaded: **{loaded.get('meta', {}).get('label', '—')}** — form pre-filled.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ENCLOSURE GEOMETRY — defines V and L/D consumed by the Enclosure section below
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("Enclosure Geometry")
st.caption("Define the protected enclosure's volume and L/D ratio")

st.markdown("""
<style>
.st-key-reset_all_btn button {
    background-color: #C8392B;
    border-color: #C8392B;
    color: #fff;
}
.st-key-reset_all_btn button:hover {
    background-color: #a52d21;
    border-color: #a52d21;
    color: #fff;
}
</style>
""", unsafe_allow_html=True)
_, reset_col = st.columns([4, 1])
if reset_col.button("🔄 Reset All", key="reset_all_btn", use_container_width=True):
    for k in list(st.session_state.keys()):
        if k.startswith("eb_") or k.startswith("eg_"):
            del st.session_state[k]
    st.rerun()

GEOM_MODES = ["Circular Enclosure", "Rectangular Enclosure", "Donaldson", "Manual Input"]
_prev_geom_mode = st.session_state.get("eg_mode", "Manual Input")
geom_mode = st.selectbox(
    "Enclosure geometry method",
    GEOM_MODES,
    index=GEOM_MODES.index(_prev_geom_mode) if _prev_geom_mode in GEOM_MODES else len(GEOM_MODES) - 1,
)

_reseed = geom_mode != _prev_geom_mode

donaldson_family, donaldson_model = None, None

if geom_mode == "Donaldson":
    families = list_families()
    _prev_family = st.session_state.get("eg_family", families[0])
    donaldson_family = st.selectbox(
        "Family", families,
        index=families.index(_prev_family) if _prev_family in families else 0,
    )
    if donaldson_family != _prev_family:
        _reseed = True

    models = list_models(donaldson_family)
    _prev_model = st.session_state.get("eg_model", models[0])
    donaldson_model = st.selectbox(
        "Model", models,
        index=models.index(_prev_model) if _prev_model in models else 0,
    )
    if donaldson_model != _prev_model:
        _reseed = True

    st.session_state["eg_family"] = donaldson_family
    st.session_state["eg_model"]  = donaldson_model

    if _reseed:
        _seed_segments(get_model(donaldson_family, donaldson_model).segments)

elif geom_mode == "Circular Enclosure" and _reseed:
    _seed_segments(circular_enclosure_default())
elif geom_mode == "Rectangular Enclosure" and _reseed:
    _seed_segments(rectangular_enclosure_default())
st.session_state["eg_mode"] = geom_mode

if _reseed:
    st.rerun()

geometry_dict = None

if geom_mode == "Manual Input":
    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Volume V [m³]")
    V = ic.number_input("Volume V [m³]", label_visibility="collapsed",
                        value=float(_pre("enclosure.V", 25.0)),
                        min_value=0.01, step=0.5, format="%.2f")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "L/D ratio [—]")
    LD = ic.number_input("L/D ratio [—]", label_visibility="collapsed",
                         value=float(_pre("enclosure.LD", 1.0)),
                         min_value=1.0, step=0.1, format="%.2f")
    _warn_ld(LD)

else:
    if "eb_seg_types" not in st.session_state:
        st.session_state.eb_seg_types = []

    _prev_unit = st.session_state.get("eb_unit", "m")
    unit = st.radio("Input unit", ["m", "ft", "in"],
                     index=["m", "ft", "in"].index(_prev_unit), horizontal=True)

    if unit != _prev_unit:
        ratio = UNIT_TO_M[_prev_unit] / UNIT_TO_M[unit]
        for k, v in list(st.session_state.items()):
            if isinstance(v, float) and any(k.startswith(p) for p in _DIM_PREFIXES):
                st.session_state[k] = v * ratio
        st.session_state["eb_unit"] = unit
        st.rerun()

    st.session_state["eb_unit"] = unit
    factor = UNIT_TO_M[unit]
    u_lbl  = unit
    u3     = f"{unit}³" if unit != "in" else "in³"

    st.caption(
        "For parallel discharge paths (e.g. a hopper and the barrel below it, "
        "repeated side by side), set the same copies/arrangement on every "
        "segment you want grouped so the 3D view renders them aligned."
    )

    seg_params: list[dict] = []
    delete_idx = None
    step = UNIT_STEP[unit]
    mpos = UNIT_MIN_POS[unit]

    for i, stype in enumerate(st.session_state.eb_seg_types):
        shape_label = SHAPES.get(stype, stype)
        with st.expander(f"**Segment {i + 1}** — {shape_label}", expanded=True):
            top_left, top_right = st.columns([3, 1])

            with top_left:
                sel = st.selectbox(
                    "Shape",
                    options=list(SHAPES.values()),
                    index=list(SHAPES.keys()).index(stype),
                    key=f"eb_type_sel_{i}",
                    label_visibility="collapsed",
                )
                new_type = SHAPE_LABELS[sel]
                if new_type != st.session_state.eb_seg_types[i]:
                    st.session_state.eb_seg_types[i] = new_type
                    st.rerun()

            with top_right:
                if st.button("🗑 Delete", key=f"eb_del_{i}", use_container_width=True):
                    delete_idx = i

            params: dict = {"type": stype}

            if stype == "cuboid":
                c1, c2, c3 = st.columns(3)
                a = c1.number_input(f"Length a [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_a_{i}", 1.0), step=step, format="%.3f", key=f"eb_a_{i}")
                b = c2.number_input(f"Width b [{u_lbl}]",  min_value=mpos, value=st.session_state.get(f"eb_b_{i}", 1.0), step=step, format="%.3f", key=f"eb_b_{i}")
                h = c3.number_input(f"Height h [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
                params.update(a=a * factor, b=b * factor, h=h * factor)

            elif stype == "cylinder":
                c1, c2 = st.columns(2)
                r = c1.number_input(f"Radius r [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_r_{i}", 0.5), step=step, format="%.3f", key=f"eb_r_{i}")
                h = c2.number_input(f"Height h [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
                params.update(r=r * factor, h=h * factor)

            elif stype == "truncated_cone":
                c1, c2, c3 = st.columns(3)
                R = c1.number_input(f"Large radius R [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_R_{i}", 0.5), step=step, format="%.3f", key=f"eb_R_{i}")
                r = c2.number_input(f"Small radius r [{u_lbl}]", min_value=0.0,  value=st.session_state.get(f"eb_r_{i}", 0.1), step=step, format="%.3f", key=f"eb_r_{i}")
                h = c3.number_input(f"Height h [{u_lbl}]",        min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
                params.update(R=R * factor, r=r * factor, h=h * factor)

            elif stype == "truncated_rect_pyramid":
                c1, c2, c3, c4, c5 = st.columns(5)
                A = c1.number_input(f"Large A [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_A_{i}", 1.0), step=step, format="%.3f", key=f"eb_A_{i}")
                B = c2.number_input(f"Large B [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_B_{i}", 1.0), step=step, format="%.3f", key=f"eb_B_{i}")
                a = c3.number_input(f"Small a [{u_lbl}]", min_value=0.0,  value=st.session_state.get(f"eb_a_{i}", 0.2), step=step, format="%.3f", key=f"eb_a_{i}")
                b = c4.number_input(f"Small b [{u_lbl}]", min_value=0.0,  value=st.session_state.get(f"eb_b_{i}", 0.2), step=step, format="%.3f", key=f"eb_b_{i}")
                h = c5.number_input(f"Height h [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
                params.update(A=A * factor, B=B * factor, a=a * factor, b=b * factor, h=h * factor)

            cc1, cc2 = st.columns([1, 2])
            copy_opts = ["1", "2", "4"]
            copies_label = cc1.selectbox(
                "Side-by-side copies", copy_opts,
                index=copy_opts.index(st.session_state.get(f"eb_copies_{i}", "1")),
                key=f"eb_copies_{i}",
                help="Identical copies of this segment arranged side by side "
                     "(e.g. multiple hoppers under one shared body).",
            )
            arrangement = None
            if copies_label == "2":
                arrange_opts = ["Along X", "Along Y"]
                arrangement = cc2.radio(
                    "Arrangement", arrange_opts,
                    index=arrange_opts.index(st.session_state.get(f"eb_arrange_{i}", "Along X")),
                    key=f"eb_arrange_{i}", horizontal=True,
                )
            cols_n, rows_n = _copy_layout_to_cols_rows(copies_label, arrangement)
            params["cols"], params["rows"] = cols_n, rows_n

            vol_si = segment_volume(params)
            params["vol_si"] = vol_si
            vol_disp = vol_si / factor**3
            count = cols_n * rows_n
            if count > 1:
                st.caption(
                    f"Segment volume: **{vol_disp:.4f} {u3}** × {count} copies = "
                    f"**{vol_disp * count:.4f} {u3}** ({vol_si * count:.4f} m³ total)"
                )
            else:
                st.caption(f"Segment volume: **{vol_disp:.4f} {u3}** ({vol_si:.4f} m³)")

            seg_params.append(params)

    if delete_idx is not None:
        st.session_state.eb_seg_types.pop(delete_idx)
        for suffix in ("a", "b", "h", "r", "R", "A", "B", "type_sel", "copies", "arrange"):
            st.session_state.pop(f"eb_{suffix}_{delete_idx}", None)
        st.rerun()

    col_add, _ = st.columns([1, 4])
    if col_add.button("＋ Add segment", use_container_width=True):
        st.session_state.eb_seg_types.append("cuboid")
        st.rerun()

    if not seg_params:
        st.info("Add at least one segment above to compute volume and L/D.")
        V, LD = 0.01, 1.0
    else:
        V_si, L_si   = enclosure_volume_and_length(seg_params)
        Dhe_si       = enclosure_hydraulic_diameter(seg_params, V_si, L_si)
        family, R    = largest_cross_section(seg_params)
        V_disp, L_disp, Dhe_disp = V_si / factor**3, L_si / factor, Dhe_si / factor

        if family == "circular":
            shape_help = "Circular cross section (§6.4.3.6.1)."
        elif R < 1.2:
            shape_help = f"Square cross section, R={R:.2f} (§6.4.3.6.2)."
        else:
            shape_help = f"Rectangular cross section, R={R:.2f} (§6.4.3.6.3)."

        geom_left, geom_right = st.columns([1, 1], gap="large")

        with geom_left:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Volume V",         f"{V_disp:.2f} {u3}")
            m2.metric("Total Height L",         f"{L_disp:.2f} {u_lbl}")
            m3.metric("Hydraulic Diameter Dhe", f"{Dhe_disp:.2f} {u_lbl}",
                      help=f"NFPA 68 §6.4.3.6 — {shape_help}")
            if unit != "m":
                m1.caption(f"{V_si:.2f} m³")
                m2.caption(f"{L_si:.2f} m")
                m3.caption(f"{Dhe_si:.2f} m")
            st.caption(shape_help)

            st.caption(
                "V and L should already represent Veff and H (§6.4.3.2/.3) — build the "
                "segment stack to end at the vent, not necessarily the physical extent "
                "of the enclosure, or conservatively use the whole enclosure (§6.4.3.4). "
                "Multiple vents at different elevations along the same axis (§6.4.3.2.2) "
                "aren't supported — model each section separately if that applies."
            )
            ld_final = ch6_ld_ratio(L_si, Dhe_si)
            st.metric("L/D", f"{ld_final:.2f}")

            _warn_ld(ld_final)

        with geom_right:
            fig = _build_3d_figure(seg_params)
            st.plotly_chart(fig, use_container_width=True)

        V, LD = V_si, ld_final

        geometry_dict = {
            "mode": geom_mode, "unit": unit, "segments": seg_params,
            "V": V_si, "L": L_si, "Dhe": Dhe_si, "LD": ld_final,
            "cross_section_family": family,
            "donaldson_family": donaldson_family, "donaldson_model": donaldson_model,
        }

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 1 — Enclosure · Dust / Hybrid Mixture
# ══════════════════════════════════════════════════════════════════════════════

r1_left, r1_right = st.columns(2, gap="large")

with r1_left:
    st.subheader("Enclosure")
    st.caption("§8.1.1 — Scope: L/D ≤ 6")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Enclosure type")
    calc_variant = ic.selectbox(
        "Enclosure type",
        ["Standard enclosure", "Dust collector (§8.7)"],
        index=1 if "Dust collector" in _pre("calc_variant", "Standard enclosure") else 0,
        label_visibility="collapsed",
    )

    flex_filters = False
    if "Dust collector" in calc_variant:
        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Flexible filters above vent free end, no internal restraints?",
               "Applies 25% area increase per §8.7.2")
        flex_filters = ic.checkbox("Flexible filters above vent free end, no internal restraints?",
                                   value=bool(_pre("flexible_filters", False)),
                                   label_visibility="collapsed")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Volume V · L/D ratio", "Set above in Enclosure Geometry")
    ic.markdown(f"`{V:.4f} m³ · {LD:.2f}`")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Solid volume [m³]", "Volume of solid objects inside (§8.4.1)")
    Vsolid = ic.number_input("Solid volume [m³]", label_visibility="collapsed",
                             value=float(_pre("enclosure.Vsolid", 0.0)), min_value=0.0, step=0.1, format="%.2f")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Pred [bar-g]")
    Pred = ic.number_input("Pred [bar-g]", label_visibility="collapsed",
                           value=float(_pre("vent.Pred", 0.2)), min_value=0.05, max_value=2.0,
                           step=0.05, format="%.2f")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Pinitial [bar-g]", "0.0 = atmospheric")
    Pinitial = ic.number_input("Pinitial [bar-g]", label_visibility="collapsed",
                               value=float(_pre("dust.Pinitial", 0.0)), min_value=-1.0, max_value=4.0,
                               step=0.05, format="%.2f")

    if -0.2 <= Pinitial <= 0.2:
        st.caption("🟢 Near-atmospheric → Eq. 8.2.1.1")
        subatm_method = SubatmosphericMethod.GENERAL
    elif Pinitial < -0.2:
        st.caption("🟡 Subatmospheric → Eq. 8.2.1.2")
        choice = st.radio("Subatmospheric method",
                          ["General (Eq. 8.2.1.2)", "Simplified (Eq. 8.2.1.2.2)"],
                          horizontal=True)
        subatm_method = (SubatmosphericMethod.SIMPLIFIED
                         if "Simplified" in choice
                         else SubatmosphericMethod.GENERAL)
    else:
        st.caption("🔴 Elevated pressure → Eq. 8.2.1.2")
        subatm_method = SubatmosphericMethod.GENERAL

with r1_right:
    st.subheader("Dust / Hybrid Mixture")
    st.caption("§8.1.2 — Explosion characteristics")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "KSt [bar·m/s]")
    KSt = ic.number_input("KSt [bar·m/s]", label_visibility="collapsed",
                           value=float(_pre("dust.KSt", 200.0)), min_value=1.0, step=5.0, format="%.0f")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Pmax [bar-g]")
    Pmax = ic.number_input("Pmax [bar-g]", label_visibility="collapsed",
                           value=float(_pre("dust.Pmax", 8.0)), min_value=0.5, step=0.5, format="%.2f")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 2 — Vent Panel · Vent Duct
# ══════════════════════════════════════════════════════════════════════════════

r2_left, r2_right = st.columns(2, gap="large")

with r2_left:
    st.subheader("Vent Panel")
    st.caption("§8.3 panel inertia")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Pstat [bar-g]")
    Pstat = ic.number_input("Pstat [bar-g]", label_visibility="collapsed",
                            value=float(_pre("vent.Pstat", 0.1)), min_value=0.001, max_value=1.0,
                            step=0.01, format="%.2f")
    if Pstat >= Pred:
        st.error("⚠ Pstat must be less than Pred.")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Number of panels 'n'")
    n_panels = ic.number_input("Panels n", label_visibility="collapsed",
                               value=int(_pre("vent.n", 1)), min_value=1, max_value=20, step=1)

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Mass M [kg/m²]")
    M_panel = ic.number_input("Mass M [kg/m²]", label_visibility="collapsed",
                              value=float(_pre("vent.M", 0.0)), min_value=0.0, max_value=40.0,
                              step=0.5, format="%.2f")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Shape factor Fsh", "1.0 translating · 1.1 hinged (§8.3.4)")
    Fsh = ic.selectbox("Shape factor Fsh", [1.0, 1.1],
                       index=0 if _pre("vent.Fsh", 1.1) == 1.0 else 1,
                       label_visibility="collapsed")

with r2_right:
    st.subheader("Vent Duct")
    st.caption("§8.5 — Not permitted when Pinitial > 0.2 bar-g")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Duct attached to vent")
    use_duct = ic.toggle("Duct attached to vent?", label_visibility="collapsed",
                         value=(_pre("duct", None) is not None))
    duct_obj = None

    if use_duct:
        if Pinitial > 0.2:
            st.error("⚠ Duct correction not permitted when Pinitial > 0.2 bar-g (§8.5.5)")
        else:
            dct = _pre("duct", {}) or {}

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Duct length [m]")
            Lduct = ic.number_input("Duct length [m]", label_visibility="collapsed",
                                    value=float(dct.get("Lduct", 3.0)), min_value=0.1, step=0.5, format="%.2f")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Diameter Dh [m]")
            Dh = ic.number_input("Diameter Dh [m]", label_visibility="collapsed",
                                 value=float(dct.get("Dh", 0.6)), min_value=0.05, step=0.05, format="%.3f")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Kinlet [—]", tip_img="nfpa68_2023_figure_A85a.jpg")
            Kinlet = ic.number_input("Kinlet [—]", label_visibility="collapsed",
                                     value=float(dct.get("Kinlet", 1.5)), min_value=0.0, step=0.1, format="%.2f")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Kelbows [—]", tip_img="nfpa68_2023_figure_A85b_c.jpg")
            Kelbows = ic.number_input("Kelbows [—]", label_visibility="collapsed",
                                      value=float(dct.get("Kelbows", 0.0)), min_value=0.0, step=0.1, format="%.1f")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Koutlet [—]", tip_img="nfpa68_2023_figure_A85d.jpg")
            Koutlet = ic.number_input("Koutlet [—]", label_visibility="collapsed",
                                      value=float(dct.get("Koutlet", 0.0)), min_value=0.0, step=0.1, format="%.2f")

            duct_obj = Duct(Lduct=Lduct, Dh=Dh, Kinlet=Kinlet, Kelbows=Kelbows, Koutlet=Koutlet)
            st.caption(f"Computed: fD = {duct_obj.fD:.4f} · **K = {duct_obj.K:.3f}** (Eq. 8.5.1d)")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 3 — Turbulence · Partial Volume
# ══════════════════════════════════════════════════════════════════════════════

r3_left, r3_right = st.columns(2, gap="large")

with r3_left:
    st.subheader("Turbulence")
    st.caption("§8.2.4")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Turbulence mode")
    turb_label = ic.selectbox(
        "Turbulence mode",
        ["None (< 20 m/s)", "Process equipment (§8.2.4.6)", "Building hazard (§8.2.4.7)"],
        index={"NONE": 0, "PROCESS": 1, "BUILDING": 2}.get(_pre("turbulence_mode", "NONE"), 0),
        label_visibility="collapsed",
    )
    turb_inputs = None
    if "Process" in turb_label:
        turb_mode = TurbulenceMode.PROCESS
        ti = _pre("turb_inputs", {}) or {}

        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Flow rate Q [m³/s]")
        Q_flow = ic.number_input("Flow rate Q [m³/s]", label_visibility="collapsed",
                                 value=float(ti.get("Q", 0.5)), min_value=0.001, step=0.05, format="%.3f")

        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Cross-sect. area A [m²]")
        A_flow = ic.number_input("Cross-sect. area A [m²]", label_visibility="collapsed",
                                 value=float(ti.get("A", 0.5)), min_value=0.001, step=0.05, format="%.3f")

        Ain = None
        ain_prev = ti.get("Ain")
        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Tangential inlet?")
        tangential_inlet = ic.toggle("Tangential inlet?", value=(ain_prev is not None),
                                     label_visibility="collapsed")
        if tangential_inlet:
            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Inlet area Ain [m²]")
            Ain = ic.number_input("Inlet area Ain [m²]", label_visibility="collapsed",
                                  value=float(ain_prev) if ain_prev is not None else 0.1,
                                  min_value=0.001, step=0.01, format="%.3f")
        turb_inputs = TurbulenceInputs(Q=Q_flow, A=A_flow, Ain=Ain)
    elif "Building" in turb_label:
        turb_mode = TurbulenceMode.BUILDING
        st.info("Flat 1.7× factor applied to Av1 (Eq. 8.2.4.7)")
    else:
        turb_mode = TurbulenceMode.NONE

with r3_right:
    st.subheader("Partial Volume")
    st.caption("§8.4 — Optional")

    pvd = _pre("partial_volume", {}) or {}

    def _pv(key, default):
        v = pvd.get(key)
        return default if v is None else v

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Apply partial volume correction?")
    use_pv = ic.toggle("Apply partial volume correction?", label_visibility="collapsed",
                       value=bool(pvd), disabled=(Pinitial > 0.2))
    pv_obj = None

    if use_pv and Pinitial <= 0.2:
        pv_type = st.radio("Method", ["Process enclosure (§8.4.1)", "Building (§8.4.5)"], horizontal=True,
                           index=1 if _pv("use_building", False) else 0)
        if "Process" in pv_type:
            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Suspended dust Me [g]")
            Me = ic.number_input("Suspended dust Me [g]", label_visibility="collapsed",
                                 value=float(_pv("Me", 5000.0)), min_value=0.0, step=100.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Worst-case conc. cw [g/m³]", "Use 200 if not measured (§8.4.2.2)")
            cw = ic.number_input("Worst-case conc. cw [g/m³]", label_visibility="collapsed",
                                 value=float(_pv("cw", 200.0)), min_value=1.0, step=10.0)
            pv_obj = PartialVolumeInputs(Me=Me, cw=cw)
        else:
            st.info("Supply building entrainment data:")

            st.caption("**Floor**")
            f1, f2 = st.columns(2)
            Mf_bar = f1.number_input("Avg floor mass [g]",
                                     value=float(_pv("Mf_bar", 10.0)), min_value=0.0)
            Af_dusty = f2.number_input("Dusty floor area [m²]",
                                       value=float(_pv("Af_dusty", 50.0)), min_value=0.0)
            f3, f4 = st.columns(2)
            eta_Df = f3.number_input("Floor entrainment ηD [—]",
                                     value=float(_pv("eta_Dfloor", 0.5)), min_value=0.0, max_value=1.0)
            Afs = f4.number_input("Floor sample area [m²]",
                                  value=float(_pv("Afs", 0.09)), min_value=0.001, format="%.4f")

            st.caption("**Surface**")
            s1, s2 = st.columns(2)
            Ms_bar = s1.number_input("Avg surface mass [g]",
                                     value=float(_pv("Ms_bar", 5.0)), min_value=0.0)
            Asur = s2.number_input("Total surface area [m²]",
                                   value=float(_pv("Asur", 20.0)), min_value=0.0)
            s3, s4 = st.columns(2)
            eta_Ds = s3.number_input("Surface ηD [—]",
                                     value=float(_pv("eta_Dsur", 0.3)), min_value=0.0, max_value=1.0)
            Ass = s4.number_input("Surface sample area [m²]",
                                  value=float(_pv("Ass", 0.09)), min_value=0.001, format="%.4f")

            st.caption("**Equipment**")
            e1, e2 = st.columns(2)
            Me_eq = e1.number_input("Equipment dust Me [g]",
                                    value=float(_pv("Me_equipment", 0.0)), min_value=0.0)
            cw_b = e2.number_input("Worst-case conc. cw [g/m³]",
                                   value=float(_pv("cw", 200.0)), min_value=1.0,
                                   help="Use 200 if not measured (§8.4.2.2)")

            pv_obj = PartialVolumeInputs(
                use_building=True,
                Mf_bar=Mf_bar, Af_dusty=Af_dusty, eta_Dfloor=eta_Df, Afs=Afs,
                Ms_bar=Ms_bar, Asur=Asur, eta_Dsur=eta_Ds, Ass=Ass,
                Me_equipment=Me_eq, cw=cw_b,
            )

# ── Calculate button ──────────────────────────────────────────────────────────
st.markdown("---")
btn_col, _ = st.columns([1, 4])
run_calc = btn_col.button("⚡ Calculate", type="primary", use_container_width=True)

if run_calc or "last_result" in st.session_state:

    if run_calc:
        enclosure_obj = Enclosure(V=V, LD=LD, Vsolid=Vsolid)
        dust_obj      = Dust(KSt=KSt, Pmax=Pmax, Pinitial=Pinitial)
        vent_obj      = Vent(Pred=Pred, Pstat=Pstat, n=int(n_panels), M=M_panel, Fsh=Fsh)

        try:
            if "Dust collector" in calc_variant:
                result = dust_collector_vent_area(
                    enclosure_obj, dust_obj, vent_obj,
                    duct=duct_obj, turbulence_mode=turb_mode,
                    turb_inputs=turb_inputs, partial_volume=pv_obj,
                    flexible_filters_above_vent=flex_filters,
                    subatm_method=subatm_method,
                )
            else:
                result = vent_area_dust(
                    enclosure_obj, dust_obj, vent_obj,
                    duct=duct_obj, turbulence_mode=turb_mode,
                    turb_inputs=turb_inputs, partial_volume=pv_obj,
                    subatm_method=subatm_method,
                )
            st.session_state["last_result"] = result
            st.session_state["last_inputs"] = (
                enclosure_obj, dust_obj, vent_obj, duct_obj,
                turb_mode, turb_inputs, pv_obj,
                subatm_method, flex_filters, calc_variant,
            )
            st.session_state.pop("calc_error", None)

        except (ValueError, RuntimeError) as e:
            st.session_state["calc_error"] = str(e)
            st.session_state.pop("last_result", None)

    if st.session_state.get("calc_error"):
        st.error(f"**Calculation error:** {st.session_state['calc_error']}")
        st.stop()

    result: DustVentResult = st.session_state["last_result"]

    # ── Results ───────────────────────────────────────────────────────────────
    st.markdown("## Results")

    final_caption = (
        "Final value after all applicable corrections, including the 25% "
        "flexible-filter obstruction increase · NFPA 68 (2023) §8.5, §8.7.2"
        if result.flexible_filters_bump_active else
        "Final value after all applicable corrections · NFPA 68 (2023) §8.5"
    )
    st.markdown(f"""
    <div class="result-banner">
      <div style="font-size:0.82em;opacity:0.65;letter-spacing:0.05em">
        MINIMUM REQUIRED VENT AREA
      </div>
      <div style="font-size:2.4em;font-weight:800;color:#E8503A;line-height:1.1">
        {result.Av_final:.4f}
        <span style="font-size:0.45em;font-weight:400">m²</span>
      </div>
      <div style="font-size:0.8em;opacity:0.55;margin-top:4px">
        {final_caption}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Calculation chain table — merged with per-row correction detail
    st.markdown("### Calculation Chain")

    def _chain_detail(sym: str) -> str:
        if sym == "Av₀":
            regime = result.pressure_regime.name.replace("_", " ").title()
            if result.Peffective is not None:
                return (f"{regime} · Peff={result.Peffective:.4f} bar-g, "
                        f"PEmax={result.PEmax:.4f} bar-g, Π={result.Pi_effective:.4f}")
            return regime
        if sym == "Av₁":
            return "L/D: Active" if result.ld_correction_active else "L/D: Not applied"
        if sym == "Av₂":
            mode = result.turbulence_mode.name
            if mode == "PROCESS":
                vtan_str = f"{result.vtan:.2f} m/s" if result.vtan is not None else "n/a"
                return f"Process · vaxial={result.vaxial:.2f} m/s, vtan={vtan_str}"
            if mode == "BUILDING":
                return "Building (1.7×, §8.2.4.7)"
            return "None"
        if sym == "Av₃":
            state = "Active" if result.panel_inertia_active else "Not applied"
            return f"Panel inertia: {state} (MT={result.MT:.3f} kg/m²)"
        if sym == "Av₄":
            if result.Xr is None:
                return "—"
            state = "Active" if result.partial_volume_active else "Not applied"
            return f"Partial volume: {state} (Xr={result.Xr:.4f})"
        if sym == "Avf":
            if not result.duct_active:
                return "No duct"
            base = f"E1={result.E1:.4f}, E2={result.E2:.4f}"
            if result.ddt_ok:
                return f"{base} · DDT ✓"
            return f"{base} · <b>DDT ✗ FAILED</b> — Leff_max={result.Leff_max:.3f} m"
        if sym == "Av,final":
            return "Avf × 1.25"
        return ""

    steps_data = [
        ("Av₀", result.Av0, "Minimum vent area",               "§8.2.1, Eq. 8.2.1.1"),
        ("Av₁", result.Av1, "After L/D correction",            "§8.2.2, Eq. 8.2.2.3"),
        ("Av₂", result.Av2, "After turbulence correction",     "§8.2.4"),
        ("Av₃", result.Av3, "After panel inertia correction",  "§8.3, Eq. 8.3.4"),
        ("Av₄", result.Av4, "After partial volume correction", "§8.4, Eq. 8.4.3"),
        ("Avf", result.Avf, "Final vent area (with duct §8.5)","§8.5.1, Eq. 8.5.1a"),
    ]
    if result.flexible_filters_bump_active:
        steps_data.append((
            "Av,final", result.Av_final,
            "Flexible filter obstruction increase (+25%)", "§8.7.2",
        ))

    ddt_failed = result.duct_active and not result.ddt_ok
    rows_html = ""
    prev = None
    for i, (sym, val, desc, ref) in enumerate(steps_data):
        if prev is not None and prev > 0:
            pct = (val - prev) / prev * 100
            color = "#C8392B" if pct > 0.01 else ("#1A7A4A" if pct < -0.01 else "#6B7280")
            arrow = "↑" if pct > 0.01 else ("↓" if pct < -0.01 else "=")
            change_html = f"<span style='color:{color}'>{arrow} {pct:+.1f}%</span>"
        else:
            change_html = "—"

        danger = (sym == "Avf" and ddt_failed)
        bg = "#F2D7D5" if danger else ("#F7F8FA" if i % 2 == 0 else "#fff")
        detail_style = "color:#B3261E;font-weight:700" if danger else "color:#374151"

        rows_html += f"""
        <tr style="background:{bg}">
          <td style="padding:6px 10px;font-weight:700">{sym}</td>
          <td style="padding:6px 10px;font-family:monospace">{val:.4f} m²</td>
          <td style="padding:6px 10px">{change_html}</td>
          <td style="padding:6px 10px;font-size:0.9em;{detail_style}">{_chain_detail(sym)}</td>
          <td style="padding:6px 10px;font-size:0.9em">{desc}
            <span style="color:#6B7280;font-size:0.85em">{ref}</span></td>
        </tr>"""
        prev = val

    st.markdown(f"""
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.92em">
      <thead>
        <tr style="border-bottom:2px solid #1B2A3B">
          <th style="padding:6px 10px;text-align:left;width:8%">Symbol</th>
          <th style="padding:6px 10px;text-align:left;width:13%">Value</th>
          <th style="padding:6px 10px;text-align:left;width:10%">Change</th>
          <th style="padding:6px 10px;text-align:left;width:32%">Correction Details</th>
          <th style="padding:6px 10px;text-align:left;width:37%">Description &amp; Reference</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
    </div>
    """, unsafe_allow_html=True)

    # ── Selection ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("## Selection")
    st.caption("Filter the vent panel catalog, then choose the final panel selection")

    fc0, fc1, fc2, fc3 = st.columns([1, 1, 1, 1.1])

    all_manufacturers = list_manufacturers()
    sel_manufacturers = fc0.multiselect(
        "Manufacturer (filter)", all_manufacturers,
        default=[m for m in _pre("selection.filter_manufacturers", all_manufacturers)
                 if m in all_manufacturers] or all_manufacturers,
        key="sel_manufacturers",
    )

    # Panel type's option list depends on the manufacturer selection above, so it
    # can't use the key= shortcut the other two widgets use here (Streamlit only
    # honors `default=` on a keyed widget's very first render) — it needs a fresh
    # default recomputed against the current option list on every rerun instead.
    all_panel_types = sorted({pt for m in (sel_manufacturers or all_manufacturers) for pt in list_vent_panel_types(m)})
    _prev_panel_types = st.session_state.get(
        "sel_panel_types", _pre("selection.filter_panel_types", all_panel_types)
    )
    sel_panel_types = fc1.multiselect(
        "Panel Type (filter)", all_panel_types,
        default=[t for t in _prev_panel_types if t in all_panel_types] or all_panel_types,
    )
    st.session_state["sel_panel_types"] = sel_panel_types

    efficiency_pct = fc2.number_input(
        "Efficiency [%]", min_value=1.0, max_value=100.0,
        value=float(_pre("selection.efficiency_pct", 70.0)),
        step=1.0, format="%.0f",
    )
    efficiency = efficiency_pct / 100.0

    stocked_only = fc3.toggle(
        "Stocked sizes only",
        value=bool(_pre("selection.stocked_only", True)),
        key="sel_stocked_only",
        help="Limit to nominal sizes normally kept in stock. Turn off to see the full manufacturer range.",
    )

    selection_rows = (
        compute_panel_selection(result.Av_final, sel_manufacturers, sel_panel_types, efficiency, stocked_only=stocked_only)
        if sel_manufacturers and sel_panel_types else []
    )
    selection_dict = None

    st.caption(
        f"Design area = {result.Av_final:.4f} m² · Efficiency = {efficiency_pct:.0f}% · "
        f"{'stocked sizes only' if stocked_only else 'full manufacturer range'} · "
        f"sorted by panels required"
    )

    if selection_rows:
        _prev_final = (
            _pre("selection.manufacturer", None),
            _pre("selection.model", None),
            _pre("selection.panel_type", None),
        )
        default_idx = next(
            (i for i, r in enumerate(selection_rows)
             if (r.panel.manufacturer, r.panel.model, r.panel.panel_type) == _prev_final),
            0,
        )

        st.caption("Click a row to make it the final selection.")
        table_state = st.dataframe(
            [
                {
                    "Manufacturer": row.panel.manufacturer,
                    "Model": row.panel.model,
                    "Nominal (metric)": row.panel.nominal_metric,
                    "Nominal (imperial)": row.panel.nominal_imperial,
                    "Vent Area (m²)": round(row.panel.surf_m2, 4),
                    "Panel Density (kg/m²)": round(row.panel.panel_density_kgm2, 3),
                    "Panels Required": row.panels_required,
                    "Total Effective Area (m²)": round(row.total_effective_area_m2, 4),
                }
                for row in selection_rows
            ],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row-required",
            selection_default={"selection": {"rows": [default_idx]}},
            key="selection_table",
        )
        chosen_idx = table_state["selection"]["rows"][0]
        chosen = selection_rows[chosen_idx]

        st.success(
            f"Final selection: **{chosen.panel.manufacturer} {chosen.panel.model} "
            f"{chosen.panel.nominal_metric}** ({chosen.panel.panel_type}) — "
            f"{chosen.panels_required} panel(s), "
            f"{chosen.total_effective_area_m2:.4f} m² total effective area"
        )

        selection_dict = {
            "manufacturer":            chosen.panel.manufacturer,
            "panel_type":              chosen.panel.panel_type,
            "model":                   chosen.panel.model,
            "nominal_metric":          chosen.panel.nominal_metric,
            "nominal_imperial":        chosen.panel.nominal_imperial,
            "vent_area_m2":            chosen.panel.surf_m2,
            "panel_density_kgm2":      chosen.panel.panel_density_kgm2,
            "efficiency_pct":          efficiency_pct,
            "panels_required":         chosen.panels_required,
            "total_effective_area_m2": chosen.total_effective_area_m2,
            "filter_manufacturers":    sel_manufacturers,
            "filter_panel_types":      sel_panel_types,
            "stocked_only":            stocked_only,
        }
    elif sel_manufacturers and sel_panel_types:
        st.info(
            "No panels match this manufacturer/type combination with the current filters. "
            + ("Try turning off \"Stocked sizes only\"." if stocked_only else "")
        )
    else:
        st.info("Select at least one manufacturer and panel type to see vent panel options.")

    # ── Report / Export ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 Report / Export")

    rc0, rc1, rc2 = st.columns(3)
    project_num = rc0.text_input("Project number", value=_pre_meta("project"), placeholder="e.g. J-1234")
    calc_label  = rc1.text_input("Calculation label", value=_pre_meta("label"), placeholder="e.g. DLMC 4/8/15")
    engineer    = rc2.text_input("Engineer", value=_pre_meta("engineer"), placeholder="Name")

    comments = st.text_area(
        "Comments", value=_pre_meta("comments"),
        placeholder="Any comments on this calculation…", height=100,
    )

    enc_o, dust_o, vent_o, duct_o, tm, ti, pv, sm, ff, cv = st.session_state["last_inputs"]
    inp_dict = inputs_to_dict(enc_o, dust_o, vent_o, duct_o, tm, ti, pv, sm, ff, cv, selection=selection_dict, geometry=geometry_dict)
    out_dict = result_to_dict(result)
    payload  = build_run_payload(project_num, calc_label, engineer, inp_dict, out_dict, comments=comments)

    e1, e2 = st.columns(2)

    with e1:
        json_bytes = json.dumps(payload, indent=2).encode()
        filename   = f"{calc_label.replace(' ', '_') or 'calculation'}.json"
        st.download_button(
            label="⬇ Download JSON",
            data=json_bytes,
            file_name=filename,
            mime="application/json",
            use_container_width=True,
        )

    with e2:
        from components.report import WEASYPRINT_OK
        if not WEASYPRINT_OK:
            st.error("WeasyPrint not installed. Run: pip install weasyprint")
        else:
            fields_ok = bool(project_num and calc_label and engineer)
            logo      = LOGO_PATH if Path(LOGO_PATH).exists() else None
            pdf_bytes = _make_pdf(json.dumps(payload), logo) if fields_ok else b""
            pdf_name  = f"{calc_label.replace(' ', '_') or 'calculation'}.pdf"
            st.download_button(
                label="⬇ Download PDF",
                data=pdf_bytes,
                file_name=pdf_name,
                mime="application/pdf",
                use_container_width=True,
                disabled=not fields_ok,
            )
            if not fields_ok:
                missing = [
                    name for name, val in [
                        ("Project number", project_num),
                        ("Calculation label", calc_label),
                        ("Engineer", engineer),
                    ] if not val
                ]
                st.caption(f"Required to download PDF: {', '.join(missing)}")
