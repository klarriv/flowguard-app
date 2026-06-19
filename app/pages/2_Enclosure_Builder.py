"""
pages/2_Enclosure_Builder.py
============================
Interactive enclosure geometry builder.

Compose an enclosure from stacked elementary shapes, compute total volume and
L/D, then send the values directly to the Dust Vent NFPA 68 calculation page.
"""

import math
from pathlib import Path

import streamlit as st

from core.geometry import (
    vol_cuboid,
    vol_truncated_rect_pyramid,
    vol_cylinder,
    vol_truncated_cone,
)

st.set_page_config(
    page_title="Enclosure Builder",
    page_icon="📐",
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
    st.page_link("pages/2_Enclosure_Builder.py", label="📐 Enclosure Builder")
    st.markdown("---")
    st.page_link("app.py", label="← Home")

# ── Constants ─────────────────────────────────────────────────────────────────
SHAPES = {
    "cuboid":                  "Rectangular Box",
    "cylinder":                "Cylinder",
    "truncated_cone":          "Truncated Cone (Conical Hopper)",
    "truncated_rect_pyramid":  "Truncated Rectangular Pyramid (Hopper)",
}

SHAPE_LABELS = {v: k for k, v in SHAPES.items()}

# ── Session state init ────────────────────────────────────────────────────────
if "eb_seg_types" not in st.session_state:
    st.session_state.eb_seg_types = []

# ── Page header ───────────────────────────────────────────────────────────────
st.title("Enclosure Builder")
st.caption("Compose an enclosure from stacked geometry segments · compute V and L/D · send to NFPA 68 calc")
st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# Segment list
# ══════════════════════════════════════════════════════════════════════════════

seg_volumes: list[float] = []
seg_heights: list[float] = []

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

        # Dimension inputs — keys persist values in session_state automatically
        vol = 0.0
        h_val = 0.0

        if stype == "cuboid":
            c1, c2, c3 = st.columns(3)
            a = c1.number_input("Length a [m]", min_value=0.001, value=st.session_state.get(f"eb_a_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_a_{i}")
            b = c2.number_input("Width b [m]",  min_value=0.001, value=st.session_state.get(f"eb_b_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_b_{i}")
            h = c3.number_input("Height h [m]", min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_h_{i}")
            vol = vol_cuboid(a, b, h)
            h_val = h

        elif stype == "cylinder":
            c1, c2 = st.columns(2)
            r = c1.number_input("Radius r [m]", min_value=0.001, value=st.session_state.get(f"eb_r_{i}", 0.5), step=0.05, format="%.3f", key=f"eb_r_{i}")
            h = c2.number_input("Height h [m]", min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1,  format="%.3f", key=f"eb_h_{i}")
            vol = vol_cylinder(r, h)
            h_val = h

        elif stype == "truncated_cone":
            c1, c2, c3 = st.columns(3)
            R = c1.number_input("Large radius R [m]", min_value=0.001, value=st.session_state.get(f"eb_R_{i}", 0.5),  step=0.05, format="%.3f", key=f"eb_R_{i}")
            r = c2.number_input("Small radius r [m]", min_value=0.0,   value=st.session_state.get(f"eb_r_{i}", 0.1),  step=0.05, format="%.3f", key=f"eb_r_{i}")
            h = c3.number_input("Height h [m]",        min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0),  step=0.1,  format="%.3f", key=f"eb_h_{i}")
            vol = vol_truncated_cone(R, r, h)
            h_val = h

        elif stype == "truncated_rect_pyramid":
            c1, c2, c3, c4, c5 = st.columns(5)
            A  = c1.number_input("Large A [m]", min_value=0.001, value=st.session_state.get(f"eb_A_{i}", 1.0),  step=0.1, format="%.3f", key=f"eb_A_{i}")
            B  = c2.number_input("Large B [m]", min_value=0.001, value=st.session_state.get(f"eb_B_{i}", 1.0),  step=0.1, format="%.3f", key=f"eb_B_{i}")
            a  = c3.number_input("Small a [m]", min_value=0.0,   value=st.session_state.get(f"eb_a_{i}", 0.2),  step=0.1, format="%.3f", key=f"eb_a_{i}")
            b  = c4.number_input("Small b [m]", min_value=0.0,   value=st.session_state.get(f"eb_b_{i}", 0.2),  step=0.1, format="%.3f", key=f"eb_b_{i}")
            h  = c5.number_input("Height h [m]", min_value=0.001, value=st.session_state.get(f"eb_h_{i}", 1.0), step=0.1, format="%.3f", key=f"eb_h_{i}")
            vol = vol_truncated_rect_pyramid(A, B, a, b, h)
            h_val = h

        st.caption(f"Segment volume: **{vol:.4f} m³**")

        seg_volumes.append(vol)
        seg_heights.append(h_val)

# Apply any pending delete after the loop to avoid index mutation mid-render
if delete_idx is not None:
    st.session_state.eb_seg_types.pop(delete_idx)
    # Clear widget keys for deleted segment to avoid stale values
    for suffix in ("a", "b", "h", "r", "R", "A", "B", f"type_sel"):
        st.session_state.pop(f"eb_{suffix}_{delete_idx}", None)
    st.rerun()

# ── Add segment button ────────────────────────────────────────────────────────
col_add, _ = st.columns([1, 4])
if col_add.button("＋ Add segment", use_container_width=True):
    st.session_state.eb_seg_types.append("cuboid")
    st.rerun()

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("Summary")

if not seg_volumes:
    st.info("Add at least one segment above to compute volume and L/D.")
    st.stop()

V_total = sum(seg_volumes)
L_total = sum(seg_heights)

# Equivalent diameter: diameter of a cylinder with equal V and same L
if L_total > 0:
    D_eq = 2.0 * math.sqrt(V_total / (math.pi * L_total))
else:
    D_eq = 0.0

m1, m2, m3 = st.columns(3)
m1.metric("Total Volume V", f"{V_total:.4f} m³")
m2.metric("Total Height L", f"{L_total:.3f} m")
m3.metric("Equiv. Diameter D_eq", f"{D_eq:.3f} m", help="2√(V / πL) — equivalent circular diameter of a cylinder with same V and L")

st.markdown("---")
st.markdown("**L/D Calculation**")

lc, ic = st.columns([2, 1])
lc.markdown(
    "The equivalent diameter above assumes a circular cross-section. "
    "Override with your actual characteristic diameter if the cross-section is rectangular or differs."
)
D_override = ic.number_input(
    "Override D [m] (leave as D_eq to auto-compute)",
    min_value=0.001,
    value=round(D_eq, 3) if D_eq > 0 else 1.0,
    step=0.01,
    format="%.3f",
    key="eb_D_override",
)

ld_final = L_total / D_override if D_override > 0 else 0.0

ld_col, _ = st.columns([1, 2])
ld_display = f"{ld_final:.2f}"
if ld_final > 6.0:
    ld_col.metric("L/D", ld_display)
    st.warning(
        f"⚠ L/D = {ld_final:.2f} exceeds 6.0 — outside the scope of NFPA 68 §8.1.1. "
        "Values can still be sent but verify applicability with your engineer of record."
    )
else:
    ld_col.metric("L/D", ld_display)

# ══════════════════════════════════════════════════════════════════════════════
# Handoff to NFPA 68 Calc
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.markdown("### Send to Dust Vent Calc")
st.caption(f"Will pre-fill **V = {V_total:.4f} m³** and **L/D = {ld_final:.2f}** on the NFPA 68 page.")

send_col, _ = st.columns([1, 3])
if send_col.button("→ Use in Dust Vent Calc", type="primary", use_container_width=True):
    st.session_state["eb_to_nfpa68"] = {"V": V_total, "LD": ld_final}
    st.switch_page("pages/1_Dust_Vent_NFPA68.py")
