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
    segment_volume, enclosure_volume_and_length, equivalent_diameter, ld_ratio,
)
from core.enclosure_catalog import (
    circular_enclosure_default, rectangular_enclosure_default,
    list_families, list_models, get_model,
)
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


def _build_3d_figure(seg_params: list[dict]) -> go.Figure:
    """Build a Plotly 3D figure. seg_params dicts carry SI values."""
    traces = []
    z_base = sum(seg["h"] for seg in seg_params)   # top of the stack

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

        xv, yv, zv, iv, jv, kv = args
        traces.append(go.Mesh3d(
            x=xv, y=yv, z=zv,
            i=iv, j=jv, k=kv,
            color=color,
            opacity=0.88,
            flatshading=True,
            name=f"Seg {idx + 1} — {label}",
            showlegend=True,
            hovertemplate=(
                f"<b>Segment {idx + 1}</b><br>{label}<br>"
                f"V = {seg['vol_si']:.4f} m³<extra></extra>"
            ),
        ))

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
    st.session_state.eb_seg_types = [s["type"] for s in segments]
    for i, seg in enumerate(segments):
        for k, v in seg.items():
            if k != "type":
                st.session_state[f"eb_{k}_{i}"] = float(v)


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
    if uploaded is not None:
        try:
            data = json.loads(uploaded.read())
            st.session_state["loaded_run"] = data
            st.rerun()
        except Exception:
            st.error("Could not parse JSON file.")
    st.markdown("---")
    st.page_link("app.py", label="← Home")

# ── Pre-fill from loaded run ───────────────────────────────────────────────────
loaded = st.session_state.pop("loaded_run", None)

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

if loaded:
    st.success(f"Loaded: **{loaded.get('meta', {}).get('label', '—')}** — form pre-filled.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ENCLOSURE GEOMETRY — defines V and L/D consumed by the Enclosure section below
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("Enclosure Geometry")
st.caption("Define the protected enclosure's volume and L/D ratio")

GEOM_MODES = ["Circular Enclosure", "Rectangular Enclosure", "Donaldson", "Custom", "Manual Input"]
_prev_geom_mode = st.session_state.get("eg_mode", "Manual Input")
geom_mode = st.selectbox(
    "Enclosure geometry method",
    GEOM_MODES,
    index=GEOM_MODES.index(_prev_geom_mode) if _prev_geom_mode in GEOM_MODES else len(GEOM_MODES) - 1,
)

_reseed = geom_mode != _prev_geom_mode

if geom_mode == "Donaldson":
    families = list_families()
    _prev_family = st.session_state.get("eg_family", families[0])
    family = st.selectbox(
        "Family", families,
        index=families.index(_prev_family) if _prev_family in families else 0,
    )
    if family != _prev_family:
        _reseed = True

    models = list_models(family)
    _prev_model = st.session_state.get("eg_model", models[0])
    model_name = st.selectbox(
        "Model", models,
        index=models.index(_prev_model) if _prev_model in models else 0,
    )
    if model_name != _prev_model:
        _reseed = True

    st.session_state["eg_family"] = family
    st.session_state["eg_model"]  = model_name

    if _reseed:
        _seed_segments(get_model(family, model_name).segments)

elif geom_mode == "Circular Enclosure" and _reseed:
    _seed_segments(circular_enclosure_default())
elif geom_mode == "Rectangular Enclosure" and _reseed:
    _seed_segments(rectangular_enclosure_default())
elif geom_mode == "Custom" and _reseed:
    st.session_state.eb_seg_types = []

st.session_state["eg_mode"] = geom_mode

if _reseed:
    st.rerun()

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
    if LD > 6.0:
        st.warning(f"L/D = {LD:.2f} exceeds 6.0 — outside NFPA 68 §8.1.1 scope. "
                   "Verify applicability with your engineer of record.")

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
        if isinstance(st.session_state.get("eb_D_override"), float):
            st.session_state["eb_D_override"] *= ratio
        st.session_state["eb_unit"] = unit
        st.rerun()

    st.session_state["eb_unit"] = unit
    factor = UNIT_TO_M[unit]
    u_lbl  = unit
    u3     = f"{unit}³" if unit != "in" else "in³"

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

            vol_si = segment_volume(params)
            params["vol_si"] = vol_si
            vol_disp = vol_si / factor**3
            st.caption(f"Segment volume: **{vol_disp:.4f} {u3}** ({vol_si:.4f} m³)")

            seg_params.append(params)

    if delete_idx is not None:
        st.session_state.eb_seg_types.pop(delete_idx)
        for suffix in ("a", "b", "h", "r", "R", "A", "B", "type_sel"):
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
        V_si, L_si = enclosure_volume_and_length(seg_params)
        D_eq_si    = equivalent_diameter(V_si, L_si)
        V_disp, L_disp, D_eq_disp = V_si / factor**3, L_si / factor, D_eq_si / factor

        geom_left, geom_right = st.columns([1, 1], gap="large")

        with geom_left:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Volume V",       f"{V_disp:.2f} {u3}")
            m2.metric("Total Height L",       f"{L_disp:.2f} {u_lbl}")
            m3.metric("Equiv. Diameter D_eq", f"{D_eq_disp:.2f} {u_lbl}",
                      help="2√(V / πL) — diameter of a cylinder with same V and L")
            if unit != "m":
                m1.caption(f"{V_si:.2f} m³")
                m2.caption(f"{L_si:.2f} m")
                m3.caption(f"{D_eq_si:.2f} m")

            st.caption(
                "D_eq assumes a circular cross-section. "
                "Override with the actual characteristic diameter for rectangular enclosures."
            )
            D_override_disp = st.number_input(
                f"Override D [{u_lbl}]",
                min_value=mpos,
                value=round(D_eq_disp, 3) if D_eq_disp > 0 else round(1.0 / factor, 3),
                step=step,
                format="%.2f",
                key="eb_D_override",
            )
            D_override_si = D_override_disp * factor
            ld_final = ld_ratio(L_si, D_override_si)
            st.metric("L/D", f"{ld_final:.2f}")

            if ld_final > 6.0:
                st.warning(
                    f"L/D = {ld_final:.2f} exceeds 6.0 — outside NFPA 68 §8.1.1 scope. "
                    "Verify applicability with your engineer of record."
                )

        with geom_right:
            fig = _build_3d_figure(seg_params)
            st.plotly_chart(fig, use_container_width=True)

        V, LD = V_si, ld_final

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 1 — Enclosure · Dust / Hybrid Mixture
# ══════════════════════════════════════════════════════════════════════════════

r1_left, r1_right = st.columns(2, gap="large")

with r1_left:
    st.subheader("Enclosure")
    st.caption("§8.1.1 — Scope: L/D ≤ 6")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Calculation type")
    calc_variant = ic.selectbox(
        "Calculation type",
        ["Standard enclosure", "Dust collector (§8.7)"],
        index=0 if _pre("calc_variant", "standard") == "standard" else 1,
        label_visibility="collapsed",
    )

    flex_filters = False
    if "Dust collector" in calc_variant:
        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Flexible filters above vent free end, no internal restraints?",
               "Applies 25% area increase per §8.7.2")
        flex_filters = ic.checkbox("Flexible filters above vent free end, no internal restraints?",
                                   label_visibility="collapsed")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Volume V [m³]", "Set above in Enclosure Geometry")
    ic.markdown(f"`{V:.4f} m³`")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "L/D ratio [—]", "Set above in Enclosure Geometry")
    ic.markdown(f"`{LD:.2f}`")

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

        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Flow rate Q [m³/s]")
        Q_flow = ic.number_input("Flow rate Q [m³/s]", label_visibility="collapsed",
                                 value=0.5, min_value=0.001, step=0.05, format="%.3f")

        lc, ic = st.columns([1, 1], gap="small")
        _label(lc, "Cross-sect. area A [m²]")
        A_flow = ic.number_input("Cross-sect. area A [m²]", label_visibility="collapsed",
                                 value=0.5, min_value=0.001, step=0.05, format="%.3f")

        Ain = None
        if st.checkbox("Tangential inlet?"):
            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Inlet area Ain [m²]")
            Ain = ic.number_input("Inlet area Ain [m²]", label_visibility="collapsed",
                                  value=0.1, min_value=0.001, step=0.01, format="%.3f")
        turb_inputs = TurbulenceInputs(Q=Q_flow, A=A_flow, Ain=Ain)
    elif "Building" in turb_label:
        turb_mode = TurbulenceMode.BUILDING
        st.info("Flat 1.7× factor applied to Av1 (Eq. 8.2.4.7)")
    else:
        turb_mode = TurbulenceMode.NONE

with r3_right:
    st.subheader("Partial Volume")
    st.caption("§8.4 — Optional")

    lc, ic = st.columns([1, 1], gap="small")
    _label(lc, "Apply partial volume correction?")
    use_pv = ic.toggle("Apply partial volume correction?", label_visibility="collapsed",
                       value=False, disabled=(Pinitial > 0.2))
    pv_obj = None

    if use_pv and Pinitial <= 0.2:
        pv_type = st.radio("Method", ["Process enclosure (§8.4.1)", "Building (§8.4.5)"], horizontal=True)
        if "Process" in pv_type:
            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Suspended dust Me [g]")
            Me = ic.number_input("Suspended dust Me [g]", label_visibility="collapsed",
                                 value=5000.0, min_value=0.0, step=100.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Worst-case conc. cw [g/m³]", "Use 200 if not measured (§8.4.2.2)")
            cw = ic.number_input("Worst-case conc. cw [g/m³]", label_visibility="collapsed",
                                 value=200.0, min_value=1.0, step=10.0)
            pv_obj = PartialVolumeInputs(Me=Me, cw=cw)
        else:
            st.info("Supply building entrainment data:")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Avg floor mass [g]")
            Mf_bar = ic.number_input("Avg floor mass [g]", label_visibility="collapsed",
                                     value=10.0, min_value=0.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Dusty floor area [m²]")
            Af_dusty = ic.number_input("Dusty floor area [m²]", label_visibility="collapsed",
                                       value=50.0, min_value=0.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Floor entrainment ηD [—]")
            eta_Df = ic.number_input("Floor entrainment ηD [—]", label_visibility="collapsed",
                                     value=0.5, min_value=0.0, max_value=1.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Floor sample area [m²]")
            Afs = ic.number_input("Floor sample area [m²]", label_visibility="collapsed",
                                  value=0.09, min_value=0.001, format="%.4f")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Avg surface mass [g]")
            Ms_bar = ic.number_input("Avg surface mass [g]", label_visibility="collapsed",
                                     value=5.0, min_value=0.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Total surface area [m²]")
            Asur = ic.number_input("Total surface area [m²]", label_visibility="collapsed",
                                   value=20.0, min_value=0.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Surface ηD [—]")
            eta_Ds = ic.number_input("Surface ηD [—]", label_visibility="collapsed",
                                     value=0.3, min_value=0.0, max_value=1.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Surface sample area [m²]")
            Ass = ic.number_input("Surface sample area [m²]", label_visibility="collapsed",
                                  value=0.09, min_value=0.001, format="%.4f")

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Equipment dust Me [g]")
            Me_eq = ic.number_input("Equipment dust Me [g]", label_visibility="collapsed",
                                    value=0.0, min_value=0.0)

            lc, ic = st.columns([1, 1], gap="small")
            _label(lc, "Worst-case conc. cw [g/m³]", "Use 200 if not measured (§8.4.2.2)")
            cw_b = ic.number_input("Worst-case conc. cw [g/m³]", label_visibility="collapsed",
                                   value=200.0, min_value=1.0)

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

    st.markdown(f"""
    <div class="result-banner">
      <div style="font-size:0.82em;opacity:0.65;letter-spacing:0.05em">
        MINIMUM REQUIRED VENT AREA  A<sub>vf</sub>
      </div>
      <div style="font-size:2.4em;font-weight:800;color:#E8503A;line-height:1.1">
        {result.Avf:.4f}
        <span style="font-size:0.45em;font-weight:400">m²</span>
      </div>
      <div style="font-size:0.8em;opacity:0.55;margin-top:4px">
        Final value after all applicable corrections · NFPA 68 (2023) §8.5
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Calculation chain table
    st.markdown("### Calculation Chain")
    headers = st.columns([1.5, 2, 2, 3])
    headers[0].markdown("**Symbol**")
    headers[1].markdown("**Value**")
    headers[2].markdown("**Change**")
    headers[3].markdown("**Description & Reference**")

    steps_data = [
        ("Av₀", result.Av0, "Minimum vent area",               "§8.2.1, Eq. 8.2.1.1"),
        ("Av₁", result.Av1, "After L/D correction",            "§8.2.2, Eq. 8.2.2.3"),
        ("Av₂", result.Av2, "After turbulence correction",     "§8.2.4"),
        ("Av₃", result.Av3, "After panel inertia correction",  "§8.3, Eq. 8.3.4"),
        ("Av₄", result.Av4, "After partial volume correction", "§8.4, Eq. 8.4.3"),
        ("Avf", result.Avf, "Final vent area (with duct §8.5)","§8.5.1, Eq. 8.5.1a"),
    ]
    prev = None
    for sym, val, desc, ref in steps_data:
        c0, c1, c2, c3 = st.columns([1.5, 2, 2, 3])
        c0.markdown(f"**{sym}**")
        c1.markdown(f"`{val:.4f} m²`")
        if prev is not None and prev > 0:
            pct = (val - prev) / prev * 100
            color = "#C8392B" if pct > 0.01 else ("#1A7A4A" if pct < -0.01 else "#6B7280")
            arrow = "↑" if pct > 0.01 else ("↓" if pct < -0.01 else "=")
            c2.markdown(f"<span style='color:{color}'>{arrow} {pct:+.1f}%</span>", unsafe_allow_html=True)
        else:
            c2.markdown("—")
        c3.markdown(f"{desc}  <span class='ref-tag'>{ref}</span>", unsafe_allow_html=True)
        prev = val

    # Detail metrics
    st.markdown("### Correction Details")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pressure Regime",  result.pressure_regime.name.replace("_", " ").title())
    m2.metric("L/D Correction",   "Active" if result.ld_correction_active else "Not applied")
    m3.metric("Panel Inertia MT", f"{result.MT:.3f} kg/m²")
    m4.metric("Panel Inertia",    "Active" if result.panel_inertia_active else "Not applied")

    if result.Xr is not None:
        x1, x2, _, _ = st.columns(4)
        x1.metric("Fill Fraction Xr", f"{result.Xr:.4f}")
        x2.metric("Partial Volume",    "Active" if result.partial_volume_active else "Not applied")

    if result.duct_active:
        st.markdown("**Duct correction (§8.5):**")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("E1",           f"{result.E1:.4f}")
        d2.metric("E2",           f"{result.E2:.4f}")
        d3.metric("Leff_max",     f"{result.Leff_max:.3f} m")
        d4.metric("DDT (§8.5.9)", "✓ Pass" if result.ddt_ok else "✗ FAIL")
        if not result.ddt_ok:
            st.error("DDT limit exceeded. Reduce duct length or increase Pred. (§8.5.9)")

    if result.Peffective is not None:
        st.markdown("**Elevated/subatmospheric intermediates (§8.2.1.2):**")
        e1, e2, e3 = st.columns(3)
        e1.metric("Peffective",  f"{result.Peffective:.4f} bar-g")
        e2.metric("PEmax",       f"{result.PEmax:.4f} bar-g")
        e3.metric("Π effective", f"{result.Pi_effective:.4f}")

    # ── Report / Export ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 Report / Export")

    rc0, rc1, rc2 = st.columns(3)
    project_num = rc0.text_input("Project number", value=_pre_meta("project"), placeholder="e.g. J-1234")
    calc_label  = rc1.text_input("Calculation label", value=_pre_meta("label"), placeholder="e.g. DLMC 4/8/15")
    engineer    = rc2.text_input("Engineer", value=_pre_meta("engineer"), placeholder="Name")

    enc_o, dust_o, vent_o, duct_o, tm, ti, pv, sm, ff, cv = st.session_state["last_inputs"]
    inp_dict = inputs_to_dict(enc_o, dust_o, vent_o, duct_o, tm, ti, pv, sm, ff, cv)
    out_dict = result_to_dict(result)
    payload  = build_run_payload(project_num, calc_label, engineer, inp_dict, out_dict)

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
