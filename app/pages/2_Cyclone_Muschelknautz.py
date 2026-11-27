"""
pages/2_Cyclone_Muschelknautz.py
=================================
Cyclone performance by the Muschelknautz method (Hoffmann & Stein, Ch. 6).

UI only: widgets, unit conversion at the boundary, PSD table handling and
Plotly rendering. All calculations are in the flowguard package
(collection_systems.cyclone_muschelknautz_orchestrator).
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from collection_systems.cyclone_muschelknautz_orchestrator import (
    CycloneGeometry, GasProperties, SolidProperties, cyclone_performance,
)
from core.units import convert_pressure, mm_to_m
from fluid_systems.duct_flow import solve_round_duct

from components.cyclone_chart import build_figure, emission_by_band
from utils.cyclone_psd import (
    COLUMNS, EXAMPLES, EXAMPLE_PAN_PCT, MODE_CUM, MODE_SIEVE, MODES, build_psd,
)

st.set_page_config(
    page_title="Cyclone — Muschelknautz",
    page_icon="🌪️",
    layout="wide",
    initial_sidebar_state="expanded",
)
# Hide Streamlit's auto page list; config.toml only applies when launched from the repo root.
st.set_option("client.showSidebarNavigation", False)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    logo_path = Path(__file__).parent.parent / "assets" / "logo_capt-air.jpg"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    st.markdown("---")
    st.markdown("### Calculations")
    st.page_link("app.py", label="Home")
    st.page_link("pages/1_Dust_Vent_NFPA68.py", label="💨 Dust Vent — NFPA 68 Ch.8")
    st.page_link("pages/2_Cyclone_Muschelknautz.py", label="🌪️ Cyclone — Muschelknautz")
    st.markdown("---")
    st.page_link("app.py", label="← Home")

st.title("Cyclone — Muschelknautz Method")
st.caption("Hoffmann & Stein, *Gas Cyclones and Swirl Tubes*, 2nd ed., Ch. 6 · "
           ":orange[Slot-type inlet only (Rin = R − b/2); scroll inlets are not supported.]")


def _num(label, key, value, fmt, step, min_value=0.0, help=None):
    return st.number_input(label, value=value, format=fmt, step=step,
                           min_value=min_value, key=key, help=help)


# ── 1. Cyclone geometry ───────────────────────────────────────────────────────
st.header("1. Cyclone Geometry")
c = st.columns(8)
with c[0]: D = _num("Body diameter D [m]", "cy_D", 0.2, "%.3f", 0.01)
with c[1]: a = _num("Inlet height a [m]", "cy_a", 0.1, "%.3f", 0.01)
with c[2]: b = _num("Inlet width b [m]", "cy_b", 0.04, "%.3f", 0.005)
with c[3]: Dx = _num("Vortex finder Dx [m]", "cy_Dx", 0.075, "%.3f", 0.005)
with c[4]: S = _num("Finder length S [m]", "cy_S", 0.1, "%.3f", 0.01)
with c[5]: h = _num("Barrel length h [m]", "cy_h", 0.3, "%.3f", 0.01)
with c[6]: hc = _num("Cone height hc [m]", "cy_hc", 0.5, "%.3f", 0.01)
with c[7]: Dd = _num("Dust outlet Dd [m]", "cy_Dd", 0.075, "%.3f", 0.005)

# ── 2. Gas and operating conditions ───────────────────────────────────────────
st.header("2. Gas and Operating Conditions")
c = st.columns(5)
with c[0]: Q = _num("Gas flow [m³/s]", "cy_Q", 0.04, "%.4f", 0.005)
with c[1]: mu = _num("Gas viscosity [Pa·s]", "cy_mu", 1.8e-5, "%.2e", 1e-6)
with c[2]: rho = _num("Gas density [kg/m³]", "cy_rho", 1.2, "%.3f", 0.05)
with c[3]: d_in = _num("Inlet pipe diameter [mm]", "cy_dpipe", 200.0, "%.0f", 10.0,
                       help="Used only for the velocity upstream of the inlet (acceleration loss).")
with c[4]: m_slope = _num("Grade-efficiency slope m [-]", "cy_m", 5.0, "%.1f", 0.5,
                          help="2 to 7, typical 3 (H&S p. 121); 5 is used in the book's examples.")

# ── 3. Dust and PSD ───────────────────────────────────────────────────────────
st.header("3. Dust and PSD")
c = st.columns(4)
with c[0]: rho_s = _num("Particle density [kg/m³]", "cy_rhos", 2730.0, "%.0f", 10.0)
with c[1]: rho_b = _num("Bulk density [kg/m³]", "cy_rhob", 1365.0, "%.0f", 10.0)
with c[2]: co = _num("Dust loading [kg/m³]", "cy_co", 0.0045, "%.4f", 0.0005)
with c[3]: ks = _num("Wall roughness ks [mm]", "cy_ks", 0.046, "%.3f", 0.01,
                     help="0.046 mm for commercial steel (H&S p. 115).")

median_only = st.checkbox("No PSD — median size only (monodisperse feed)", key="cy_median_only")
psd, psd_errors, x_med_um = None, [], None
if median_only:
    x_med_um = _num("Mass median size [µm]", "cy_xmed", 3.4, "%.2f", 0.1, min_value=0.0)
    if not x_med_um > 0:
        psd_errors = ["Mass median size must be > 0 µm."]
else:
    mode = st.selectbox("PSD input", MODES, key="cy_psd_mode")
    st.caption({
        MODE_CUM: "Particle size and cumulative % passing (finer than).",
        MODE_SIEVE: "Sieve aperture and % retained on each screen, plus the pan (Tyler series).",
    }.get(mode, "Laser-diffraction channels: bin edges and % of mass in each bin (bins contiguous)."))
    df = pd.DataFrame(EXAMPLES[mode], columns=COLUMNS[mode])
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, hide_index=True,
        key=f"cy_psd_table_{MODES.index(mode)}",
        column_config={col: st.column_config.NumberColumn(col, format="%.3f", min_value=0.0)
                       for col in COLUMNS[mode]},
    )
    pan = 0.0
    if mode == MODE_SIEVE:
        pan = _num("Pan [% retained]", "cy_pan", EXAMPLE_PAN_PCT, "%.2f", 1.0)
    psd, psd_errors = build_psd(mode, edited.values.tolist(), pan)

for msg in psd_errors:
    st.error(msg)

# ── 4. Results ────────────────────────────────────────────────────────────────
st.header("4. Results")
result = None
if psd_errors:
    st.caption(":orange[Fix the PSD errors above to calculate.]")
else:
    try:
        inlet_d_m = mm_to_m(d_in)
        v_up = solve_round_duct(flow=Q, diameter=inlet_d_m).velocity if d_in > 0 else None
        result = cyclone_performance(
            CycloneGeometry(D=D, a=a, b=b, Dx=Dx, S=S, H=h + hc, Hc=hc, Dd=Dd),
            GasProperties(density=rho, viscosity=mu, flow_rate=Q),
            SolidProperties(particle_density=rho_s, bulk_density=rho_b,
                            dust_loading=co, wall_roughness=mm_to_m(ks)),
            psd=psd, slope_m=m_slope, x_med_um=x_med_um, upstream_velocity_m_s=v_up,
        )
    except ValueError as exc:
        st.error(str(exc))

if result is not None:
    dp_in = lambda pa: convert_pressure(pa, "pa", "inh2o")
    r = st.columns(4)
    r[0].markdown(f"**Cut size x50** {result.x50_um:.2f} µm · "
                  f"{'Stokes' if result.stokes_regime else 'non-Stokes'}")
    r[1].markdown(f"**Overall efficiency** {100 * result.eta_overall:.2f} %")
    r[2].markdown(f"**Penetration** {100 * result.penetration:.3f} %")
    r[3].markdown(f"**Emission** {result.emission_kg_h:.4f} kg/h · {result.emission_mg_m3:.1f} mg/m³")
    r = st.columns(4)
    r[0].markdown(f"**Inlet velocity** {result.v_in:.2f} m/s")
    r[1].markdown(f"**Classification efficiency** {100 * result.eta_classification:.2f} %")
    r[2].markdown(f"**Loading** {result.co:.4f} kg/kg vs limit {result.co_L:.4f} kg/kg"
                  + (" · :orange[saltation]" if result.saltation else ""))
    r[3].markdown(f"**Δp total** {result.dp_total:.0f} Pa · {dp_in(result.dp_total):.2f} inWg")
    st.caption(
        f"Δp split — body {result.dp_body:.0f} Pa ({dp_in(result.dp_body):.2f} inWg) · "
        f"core {result.dp_core:.0f} Pa ({dp_in(result.dp_core):.2f} inWg) · "
        f"acceleration {result.dp_acc:.0f} Pa ({dp_in(result.dp_acc):.2f} inWg) · "
        f"iterations {result.iterations}, "
        + ("converged" if result.converged else ":orange[NOT converged]"))
    for w in result.warnings:
        st.warning(w)
    # The library repeats "Warning…" PSD notes in warnings; show each once.
    for n in result.psd_notes:
        if n not in result.warnings:
            st.info(n)

    # ── 5. Efficiency chart ───────────────────────────────────────────────────
    st.header("5. Efficiency Chart")
    st.plotly_chart(build_figure(result), use_container_width=True)
    band = emission_by_band(result)
    if band:
        st.caption(f"Emission makeup: {100 * band[0]:.1f} % from particles below x50, "
                   f"{100 * band[1]:.1f} % from larger particles. "
                   "Hatched bars are extrapolated outside the measured size range.")
