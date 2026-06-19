"""
pages/2_Enclosure_Builder.py
============================
Interactive enclosure geometry builder.

Compose an enclosure from stacked elementary shapes, compute total volume and
L/D, then send the values directly to the Dust Vent NFPA 68 calculation page.
All internal calculations and the NFPA 68 handoff always use SI (m, m³).
"""

import math
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from core.geometry import (
    vol_cuboid,
    vol_truncated_rect_pyramid,
    vol_cylinder,
    vol_truncated_cone,
)

# ── Unit conversion constants ─────────────────────────────────────────────────
UNIT_TO_M    = {"m": 1.0,   "ft": 0.3048, "in": 0.0254}
UNIT_STEP    = {"m": 0.05,  "ft": 0.1,    "in": 0.5}
UNIT_MIN_POS = {"m": 0.001, "ft": 0.003,  "in": 0.04}

# Dimension session-state key prefixes that must be rescaled on unit change
_DIM_PREFIXES = ("eb_a_", "eb_b_", "eb_h_", "eb_r_", "eb_R_", "eb_A_", "eb_B_")

# ── Colour palette (cycles through segments) ──────────────────────────────────
_SEG_COLORS = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756",
    "#72B7B2", "#FF9DA7", "#9D755D", "#BAB0AC",
]

# ── 3D mesh generators (always accept SI metres) ──────────────────────────────

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
            args = _mesh_frustum(seg["R"], seg["r"], h, z_base)
        elif stype == "cuboid":
            args = _mesh_box(seg["a"], seg["b"], seg["a"], seg["b"], h, z_base)
        elif stype == "truncated_rect_pyramid":
            args = _mesh_box(seg["A"], seg["B"], seg["a"], seg["b"], h, z_base)
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


# ══════════════════════════════════════════════════════════════════════════════
# Page
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Enclosure Builder",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    logo_path = Path(__file__).parent.parent / "assets" / "logo_capt-air.jpg"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    st.markdown("---")
    st.markdown("### Calculations")
    st.page_link("app.py", label="Home")
    st.page_link("pages/1_Dust_Vent_NFPA68.py", label="💨 Dust Vent — NFPA 68 Ch.8")
    st.page_link("pages/2_Enclosure_Builder.py", label="📐 Enclosure Builder")
    st.markdown("---")
    st.page_link("app.py", label="← Home")

SHAPES = {
    "cuboid":                 "Rectangular Box",
    "cylinder":               "Cylinder",
    "truncated_cone":         "Truncated Cone (Conical Hopper)",
    "truncated_rect_pyramid": "Truncated Rectangular Pyramid (Hopper)",
}
SHAPE_LABELS = {v: k for k, v in SHAPES.items()}

if "eb_seg_types" not in st.session_state:
    st.session_state.eb_seg_types = []

st.title("Enclosure Builder")
st.caption("Compose an enclosure from stacked geometry segments · compute V and L/D · send to NFPA 68 calc")

# ── Unit selector ─────────────────────────────────────────────────────────────
_prev_unit = st.session_state.get("eb_unit", "m")
unit = st.radio(
    "Input unit",
    ["m", "ft", "in"],
    index=["m", "ft", "in"].index(_prev_unit),
    horizontal=True,
)

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

st.markdown("---")

# ── Segment list ──────────────────────────────────────────────────────────────

seg_volumes: list[float] = []   # SI m³
seg_heights: list[float] = []   # SI m
seg_params:  list[dict]  = []   # SI values for 3D mesh
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
            a_si, b_si, h_si = a * factor, b * factor, h * factor
            vol_si = vol_cuboid(a_si, b_si, h_si)
            params.update(a=a_si, b=b_si, h=h_si)

        elif stype == "cylinder":
            c1, c2 = st.columns(2)
            r = c1.number_input(f"Radius r [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_r_{i}", 0.5), step=step, format="%.3f", key=f"eb_r_{i}")
            h = c2.number_input(f"Height h [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
            r_si, h_si = r * factor, h * factor
            vol_si = vol_cylinder(r_si, h_si)
            params.update(r=r_si, h=h_si)

        elif stype == "truncated_cone":
            c1, c2, c3 = st.columns(3)
            R = c1.number_input(f"Large radius R [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_R_{i}", 0.5), step=step, format="%.3f", key=f"eb_R_{i}")
            r = c2.number_input(f"Small radius r [{u_lbl}]", min_value=0.0,  value=st.session_state.get(f"eb_r_{i}", 0.1), step=step, format="%.3f", key=f"eb_r_{i}")
            h = c3.number_input(f"Height h [{u_lbl}]",        min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
            R_si, r_si, h_si = R * factor, r * factor, h * factor
            vol_si = vol_truncated_cone(R_si, r_si, h_si)
            params.update(R=R_si, r=r_si, h=h_si)

        elif stype == "truncated_rect_pyramid":
            c1, c2, c3, c4, c5 = st.columns(5)
            A = c1.number_input(f"Large A [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_A_{i}", 1.0), step=step, format="%.3f", key=f"eb_A_{i}")
            B = c2.number_input(f"Large B [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_B_{i}", 1.0), step=step, format="%.3f", key=f"eb_B_{i}")
            a = c3.number_input(f"Small a [{u_lbl}]", min_value=0.0,  value=st.session_state.get(f"eb_a_{i}", 0.2), step=step, format="%.3f", key=f"eb_a_{i}")
            b = c4.number_input(f"Small b [{u_lbl}]", min_value=0.0,  value=st.session_state.get(f"eb_b_{i}", 0.2), step=step, format="%.3f", key=f"eb_b_{i}")
            h = c5.number_input(f"Height h [{u_lbl}]", min_value=mpos, value=st.session_state.get(f"eb_h_{i}", 1.0), step=step, format="%.3f", key=f"eb_h_{i}")
            A_si, B_si, a_si, b_si, h_si = A*factor, B*factor, a*factor, b*factor, h*factor
            vol_si = vol_truncated_rect_pyramid(A_si, B_si, a_si, b_si, h_si)
            params.update(A=A_si, B=B_si, a=a_si, b=b_si, h=h_si)

        else:
            vol_si = 0.0
            h_si   = 0.0

        params["vol_si"] = vol_si
        vol_disp = vol_si / factor**3
        st.caption(f"Segment volume: **{vol_disp:.4f} {u3}** ({vol_si:.4f} m³)")

        seg_volumes.append(vol_si)
        seg_heights.append(h_si)
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

st.markdown("---")

# ── Summary + 3D view ─────────────────────────────────────────────────────────

if not seg_volumes:
    st.info("Add at least one segment above to compute volume and L/D.")
    st.stop()

V_si    = sum(seg_volumes)
L_si    = sum(seg_heights)
D_eq_si = 2.0 * math.sqrt(V_si / (math.pi * L_si)) if L_si > 0 else 0.0

V_disp    = V_si    / factor**3
L_disp    = L_si    / factor
D_eq_disp = D_eq_si / factor

left_col, right_col = st.columns([1, 1], gap="large")

with left_col:
    st.subheader("Summary")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Volume V",       f"{V_disp:.3f} {u3}")
    m2.metric("Total Height L",       f"{L_disp:.3f} {u_lbl}")
    m3.metric("Equiv. Diameter D_eq", f"{D_eq_disp:.3f} {u_lbl}",
              help="2√(V / πL) — diameter of a cylinder with same V and L")
    if unit != "m":
        m1.caption(f"{V_si:.4f} m³")
        m2.caption(f"{L_si:.3f} m")
        m3.caption(f"{D_eq_si:.3f} m")

    st.markdown("---")
    st.markdown("**L/D Calculation**")
    st.caption(
        "D_eq assumes a circular cross-section. "
        "Override with the actual characteristic diameter for rectangular enclosures."
    )

    D_override_disp = st.number_input(
        f"Override D [{u_lbl}]",
        min_value=mpos,
        value=round(D_eq_disp, 3) if D_eq_disp > 0 else round(1.0 / factor, 3),
        step=step,
        format="%.3f",
        key="eb_D_override",
    )
    D_override_si = D_override_disp * factor
    ld_final = L_si / D_override_si if D_override_si > 0 else 0.0
    st.metric("L/D", f"{ld_final:.2f}")

    if ld_final > 6.0:
        st.warning(
            f"L/D = {ld_final:.2f} exceeds 6.0 — outside NFPA 68 §8.1.1 scope. "
            "Verify applicability with your engineer of record."
        )

    st.markdown("---")
    st.markdown("**Send to Dust Vent Calc**")
    st.caption(f"Will pre-fill V = **{V_si:.4f} m³** and L/D = **{ld_final:.2f}** (always SI).")

    if st.button("→ Use in Dust Vent Calc", type="primary", use_container_width=True):
        st.session_state["eb_to_nfpa68"] = {"V": V_si, "LD": ld_final}
        st.switch_page("pages/1_Dust_Vent_NFPA68.py")

with right_col:
    st.subheader("3D View")
    fig = _build_3d_figure(seg_params)
    st.plotly_chart(fig, use_container_width=True)
