"""
pages/2_Enclosure_Builder.py
============================
Interactive enclosure geometry builder.

Compose an enclosure from stacked elementary shapes, compute total volume and
L/D, then send the values directly to the Dust Vent NFPA 68 calculation page.
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

# ── Colour palette (cycles through segments) ──────────────────────────────────
_SEG_COLORS = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756",
    "#72B7B2", "#FF9DA7", "#9D755D", "#BAB0AC",
]

# ── 3D mesh generators ────────────────────────────────────────────────────────

def _mesh_frustum(R: float, r: float, h: float, z0: float, N: int = 60):
    """
    Triangulated solid mesh for a circular frustum (truncated cone).
    R = bottom radius, r = top radius.
    Returns (x, y, z, i, j, k) for go.Mesh3d.
    """
    theta = np.linspace(0, 2 * math.pi, N, endpoint=False)
    ct, st_ = np.cos(theta), np.sin(theta)

    # vertices: 0..N-1 bottom ring, N..2N-1 top ring, 2N bottom centre, 2N+1 top centre
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
    Triangulated solid mesh for a rectangular frustum.
    Bottom base ax x bx, top base ax2 x bx2, both centred at origin.
    Returns (x, y, z, i, j, k) for go.Mesh3d.
    """
    ha, hb   = ax  / 2, bx  / 2
    ha2, hb2 = ax2 / 2, bx2 / 2

    # vertices 0-3 bottom, 4-7 top
    x = [-ha,  ha,  ha, -ha, -ha2,  ha2,  ha2, -ha2]
    y = [-hb, -hb,  hb,  hb, -hb2, -hb2,  hb2,  hb2]
    z = [z0]*4 + [z0 + h]*4

    ii = [0, 0,  4, 4,  0, 0,  2, 2,  0, 0,  1, 1]
    jj = [3, 2,  5, 6,  1, 5,  3, 7,  4, 7,  2, 6]
    kk = [2, 1,  6, 7,  5, 4,  7, 6,  7, 3,  6, 5]

    return x, y, z, ii, jj, kk


def _build_3d_figure(seg_params: list[dict]) -> go.Figure:
    """Build a Plotly 3D figure from a list of segment parameter dicts."""
    traces = []
    # Segment 1 is the topmost; stack downward so z=0 is the bottom outlet.
    z_base = sum(seg["h"] for seg in seg_params)

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
                f"V = {seg['vol']:.4f} m³<extra></extra>"
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
            camera=dict(
                up=dict(x=0, y=0, z=1),
                eye=dict(x=1.4, y=1.4, z=1.1),
            ),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.02,
            xanchor="left", x=0,
            font=dict(size=11),
        ),
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
st.markdown("---")

# ── Segment list ──────────────────────────────────────────────────────────────

seg_volumes: list[float] = []
seg_heights: list[float] = []
seg_params:  list[dict]  = []
delete_idx = None

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

        vol = 0.0
        h_val = 0.0
        params: dict = {"type": stype}

        if stype == "cuboid":
            c1, c2, c3 = st.columns(3)
            a = c1.number_input("Length a [m]", min_value=0.001, value=st.session_state.get(f"eb_a_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_a_{i}")
            b = c2.number_input("Width b [m]",  min_value=0.001, value=st.session_state.get(f"eb_b_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_b_{i}")
            h = c3.number_input("Height h [m]", min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_h_{i}")
            vol = vol_cuboid(a, b, h)
            h_val = h
            params.update(a=a, b=b, h=h)

        elif stype == "cylinder":
            c1, c2 = st.columns(2)
            r = c1.number_input("Radius r [m]", min_value=0.001, value=st.session_state.get(f"eb_r_{i}", 0.5), step=0.05, format="%.3f", key=f"eb_r_{i}")
            h = c2.number_input("Height h [m]", min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1,  format="%.3f", key=f"eb_h_{i}")
            vol = vol_cylinder(r, h)
            h_val = h
            params.update(r=r, h=h)

        elif stype == "truncated_cone":
            c1, c2, c3 = st.columns(3)
            R = c1.number_input("Large radius R [m]", min_value=0.001, value=st.session_state.get(f"eb_R_{i}", 0.5), step=0.05, format="%.3f", key=f"eb_R_{i}")
            r = c2.number_input("Small radius r [m]", min_value=0.0,   value=st.session_state.get(f"eb_r_{i}", 0.1), step=0.05, format="%.3f", key=f"eb_r_{i}")
            h = c3.number_input("Height h [m]",        min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1,  format="%.3f", key=f"eb_h_{i}")
            vol = vol_truncated_cone(R, r, h)
            h_val = h
            params.update(R=R, r=r, h=h)

        elif stype == "truncated_rect_pyramid":
            c1, c2, c3, c4, c5 = st.columns(5)
            A = c1.number_input("Large A [m]",  min_value=0.001, value=st.session_state.get(f"eb_A_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_A_{i}")
            B = c2.number_input("Large B [m]",  min_value=0.001, value=st.session_state.get(f"eb_B_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_B_{i}")
            a = c3.number_input("Small a [m]",  min_value=0.0,   value=st.session_state.get(f"eb_a_{i}", 0.2), step=0.1, format="%.3f", key=f"eb_a_{i}")
            b = c4.number_input("Small b [m]",  min_value=0.0,   value=st.session_state.get(f"eb_b_{i}", 0.2), step=0.1, format="%.3f", key=f"eb_b_{i}")
            h = c5.number_input("Height h [m]", min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_h_{i}")
            vol = vol_truncated_rect_pyramid(A, B, a, b, h)
            h_val = h
            params.update(A=A, B=B, a=a, b=b, h=h)

        params["vol"] = vol
        st.caption(f"Segment volume: **{vol:.4f} m³**")

        seg_volumes.append(vol)
        seg_heights.append(h_val)
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

V_total = sum(seg_volumes)
L_total = sum(seg_heights)
D_eq    = 2.0 * math.sqrt(V_total / (math.pi * L_total)) if L_total > 0 else 0.0

left_col, right_col = st.columns([1, 1], gap="large")

with left_col:
    st.subheader("Summary")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Volume V",       f"{V_total:.4f} m³")
    m2.metric("Total Height L",       f"{L_total:.3f} m")
    m3.metric("Equiv. Diameter D_eq", f"{D_eq:.3f} m",
              help="2√(V / πL) — diameter of a cylinder with same V and L")

    st.markdown("---")
    st.markdown("**L/D Calculation**")
    st.caption(
        "D_eq assumes a circular cross-section. "
        "Override with the actual characteristic diameter for rectangular enclosures."
    )

    D_override = st.number_input(
        "Override D [m]",
        min_value=0.001,
        value=round(D_eq, 3) if D_eq > 0 else 1.0,
        step=0.01,
        format="%.3f",
        key="eb_D_override",
    )
    ld_final = L_total / D_override if D_override > 0 else 0.0
    st.metric("L/D", f"{ld_final:.2f}")

    if ld_final > 6.0:
        st.warning(
            f"L/D = {ld_final:.2f} exceeds 6.0 — outside NFPA 68 §8.1.1 scope. "
            "Verify applicability with your engineer of record."
        )

    st.markdown("---")
    st.markdown("**Send to Dust Vent Calc**")
    st.caption(f"Will pre-fill V = **{V_total:.4f} m³** and L/D = **{ld_final:.2f}**.")

    if st.button("→ Use in Dust Vent Calc", type="primary", use_container_width=True):
        st.session_state["eb_to_nfpa68"] = {"V": V_total, "LD": ld_final}
        st.switch_page("pages/1_Dust_Vent_NFPA68.py")

with right_col:
    st.subheader("3D View")
    fig = _build_3d_figure(seg_params)
    st.plotly_chart(fig, use_container_width=True)
