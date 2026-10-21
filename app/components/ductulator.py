"""Home-page tools: round-duct ductulator and flow / velocity / pressure converters.

Widget wiring and display formatting only; every number comes from
``fluid_systems.duct_flow`` and ``core.units``. Results are formatted for display
but never rounded before the library is called.
"""

import streamlit as st

from core import units as U
from fluid_systems.duct_flow import solve_round_duct

# Seed values: first row of the workbook ductulator (SI values are readable equivalents).
DEFAULTS = {
    "duct_solve_for": "Velocity",
    "duct_units": "Imperial",
    "duct_q_imp": 2700.0, "duct_d_imp": 14.0, "duct_v_imp": 4000.0,
    "duct_q_si": 4588.0, "duct_d_si": 356.0, "duct_v_si": 20.3,
    "conv_flow_value": 3400.0, "conv_flow_unit": "CFM",
    "conv_velocity_value": 4400.0, "conv_velocity_unit": "FPM",
    "conv_pressure_value": 230.0, "conv_pressure_unit": "inH₂O (inWg)",
}

# (label, core.units key, display decimals)
_FLOW = {"CFM": ("cfm", 0), "m³/h": ("m3h", 0), "m³/s": ("m3s", 3)}
_VELOCITY = {"FPM": ("fpm", 0), "m/s": ("ms", 2)}
_PRESSURE = {
    "inH₂O (inWg)": ("inh2o", 1), "inHg": ("inhg", 2), "psi": ("psi", 2),
    "Pa": ("pa", 0), "bar": ("bar", 3), "atm": ("atm", 3),
}

_PRESSURE_HELP = "inH₂O uses conventional water density, 1000 kg/m³ (249.089 Pa per inch)."

# Ductulator units per system: quantity -> (label, key, decimals)
_SYSTEMS = {
    "Imperial": {"flow": ("CFM", "cfm", 0), "diameter": ("in", "in", 1), "velocity": ("FPM", "fpm", 0)},
    "SI": {"flow": ("m³/h", "m3h", 0), "diameter": ("mm", "mm", 0), "velocity": ("m/s", "ms", 2)},
}
_QUANTITY_NAMES = {"flow": "Flow", "diameter": "Duct ID", "velocity": "Velocity"}
_SOLVE_FOR = {"Flow": "flow", "Duct ID": "diameter", "Velocity": "velocity"}
_BASE_KEY = {"flow": "m3s", "diameter": "m", "velocity": "ms"}  # SI units the library uses


def _convert(value, src, dst):
    """Convert via a named core.units function; identity when units match."""
    if src == dst:
        return value
    return getattr(U, f"{src}_to_{dst}")(value)


def _restore(keys):
    """Re-seed widget keys from the shadow copy so values survive page navigation."""
    saved = st.session_state.setdefault("_home_saved", {})
    for k in keys:
        if k not in st.session_state:
            st.session_state[k] = saved.get(k, DEFAULTS[k])


def _save(keys):
    saved = st.session_state.setdefault("_home_saved", {})
    for k in keys:
        if k in st.session_state:
            saved[k] = st.session_state[k]


def _fmt(value, decimals):
    return f"{value:,.{decimals}f}"


def render_ductulator(key_prefix="duct", fixed_solve_for=None):
    """Solve-for card: two of flow / duct ID / velocity in, the third out."""
    p = key_prefix
    keys = [f"{p}_solve_for", f"{p}_units"] + [
        f"{p}_{q}_{s}" for q in ("q", "d", "v") for s in ("imp", "si")
    ]
    defaults = {f"{p}_{k.split('_', 1)[1]}": v for k, v in DEFAULTS.items() if k.startswith("duct_")}
    saved = st.session_state.setdefault("_home_saved", {})
    for k in keys:
        if k not in st.session_state:
            st.session_state[k] = saved.get(k, defaults[k])

    with st.container(border=True):
        st.subheader("Ductulator — round duct")
        c_solve, c_units = st.columns(2)
        if fixed_solve_for is None:
            solve_label = c_solve.radio(
                "Solve for", list(_SOLVE_FOR), horizontal=True, key=f"{p}_solve_for"
            )
        else:
            solve_label = fixed_solve_for
        system = c_units.radio("Units", list(_SYSTEMS), horizontal=True, key=f"{p}_units")
        solve = _SOLVE_FOR[solve_label]
        units = _SYSTEMS[system]
        suffix = "imp" if system == "Imperial" else "si"
        other = _SYSTEMS["SI" if system == "Imperial" else "Imperial"]
        short = {"flow": "q", "diameter": "d", "velocity": "v"}

        cols = st.columns(3)
        values = {}
        for col, qty in zip(cols, ("flow", "diameter", "velocity")):
            label, unit_key, _ = units[qty]
            if qty == solve:
                continue
            with col:
                values[qty] = st.number_input(
                    f"{_QUANTITY_NAMES[qty]} [{label}]",
                    min_value=0.0,
                    format="%g",
                    key=f"{p}_{short[qty]}_{suffix}",
                )

        # Solved quantity: read-only metric in the solved quantity's column.
        solved_col = cols[("flow", "diameter", "velocity").index(solve)]
        with solved_col:
            if any(v <= 0 for v in values.values()):
                st.warning("Inputs must be greater than 0.")
            else:
                try:
                    si_args = {
                        qty: _convert(v, units[qty][1], _BASE_KEY[qty]) for qty, v in values.items()
                    }
                    result = solve_round_duct(**si_args)
                except ValueError as exc:
                    st.warning(str(exc))
                else:
                    si_value = getattr(result, solve)
                    label, unit_key, dec = units[solve]
                    st.metric(f"{_QUANTITY_NAMES[solve]} [{label}]",
                              _fmt(_convert(si_value, _BASE_KEY[solve], unit_key), dec))
                    o_label, o_key, o_dec = other[solve]
                    secondary = (
                        f"{_fmt(_convert(si_value, _BASE_KEY[solve], o_key), o_dec)} {o_label}"
                    )
                    if solve == "flow":
                        # m³/s is the secondary flow line; CFM is primary in Imperial.
                        s_key, s_label = ("m3s", "m³/s")
                        if system == "Imperial":
                            secondary += f" ({_fmt(si_value, 3)} {s_label})"
                        else:
                            secondary = f"{_fmt(si_value, 3)} {s_label} · " + secondary
                    st.caption(secondary)

        # Slot reserved for the future "Pressure loss per length" output (right of the
        # solved metric) and its options expander; intentionally not implemented.

    _save(keys)


def _converter(title, qty, table, allow_negative=False, help_text=None, caption=None):
    labels = list(table)
    with st.container(border=True):
        st.markdown(f"**{title}**")
        value = st.number_input(
            "Value",
            min_value=None if allow_negative else 0.0,
            format="%g",
            key=f"conv_{qty}_value",
            label_visibility="collapsed",
        )
        unit = st.selectbox("Unit", labels, key=f"conv_{qty}_unit", help=help_text)
        src = table[unit][0]
        if not allow_negative and value <= 0:
            st.warning("Value must be greater than 0.")
            return
        for label in labels:
            if label == unit:
                continue
            key, dec = table[label]
            if qty == "pressure":
                out = U.convert_pressure(value, src, key)
            else:
                out = _convert(value, src, key)
            st.metric(label, _fmt(out, dec))
        if caption:
            st.caption(caption)


def render_converters():
    """Flow, velocity and pressure converters side by side."""
    keys = [k for k in DEFAULTS if k.startswith("conv_")]
    _restore(keys)
    st.subheader("Unit converters")
    c1, c2, c3 = st.columns(3)
    with c1:
        _converter("Flow", "flow", _FLOW)
    with c2:
        _converter("Velocity", "velocity", _VELOCITY)
    with c3:
        _converter("Pressure", "pressure", _PRESSURE, allow_negative=True,
                   help_text=_PRESSURE_HELP, caption="inHg: 3386.39 Pa per inch.")
    _save(keys)
