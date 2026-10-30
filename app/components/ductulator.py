"""Home-page tools: round-duct ductulator and flow / velocity / pressure converters.

Widget wiring and display formatting only; every number comes from
``fluid_systems.duct_flow`` and ``core.units``. Results are formatted for display
but never rounded before the library is called.
"""

import streamlit as st

from core import units as U
from fluid_systems.duct_flow import solve_round_duct

# Seed values: first row of the workbook ductulator (Imperial).
DEFAULTS = {
    "duct_solve_for": "Velocity",
    "duct_units": "Imperial",
    "duct_q": 2700.0, "duct_d": 14.0, "duct_v": 4000.0,
    "conv_flow_value": 3400.0, "conv_flow_unit": "CFM",
    "conv_velocity_value": 4400.0, "conv_velocity_unit": "FPM",
    "conv_pressure_value": 230.0, "conv_pressure_unit": "inH₂O (inWg)",
}

# Converter units: label -> (core.units key, display decimals)
_FLOW = {"CFM": ("cfm", 0), "m³/h": ("m3h", 0), "m³/s": ("m3s", 3)}
_VELOCITY = {"FPM": ("fpm", 0), "m/s": ("ms", 2)}
_PRESSURE = {
    "inH₂O (inWg)": ("inh2o", 1), "inHg": ("inhg", 2), "psi": ("psi", 2),
    "Pa": ("pa", 0), "bar": ("bar", 3), "atm": ("atm", 3),
}
_PRESSURE_HELP = (
    "inH₂O uses conventional water density, 1000 kg/m³ (249.089 Pa per inch). "
    "inHg: 3386.39 Pa per inch."
)

# Ductulator units per system: quantity -> (label, core.units key, decimals, step)
_SYSTEMS = {
    "Imperial": {
        "flow": ("CFM", "cfm", 0, 100.0),
        "diameter": ("in", "in", 2, 1.0),
        "velocity": ("FPM", "fpm", 0, 100.0),
    },
    "SI": {
        "flow": ("m³/h", "m3h", 0, 100.0),
        "diameter": ("mm", "mm", 0, 10.0),
        "velocity": ("m/s", "ms", 2, 0.5),
    },
}
_QTYS = ("flow", "diameter", "velocity")
_QUANTITY_NAMES = {"flow": "Flow", "diameter": "Duct ID", "velocity": "Velocity"}
_SOLVE_FOR = {"Velocity": "velocity", "Duct ID": "diameter", "Flow": "flow"}
_SHORT = {"flow": "q", "diameter": "d", "velocity": "v"}
_BASE_KEY = {"flow": "m3s", "diameter": "m", "velocity": "ms"}  # SI units the library uses


def _convert(value, src, dst):
    """Convert via a named core.units function; identity when units match."""
    if src == dst:
        return value
    return getattr(U, f"{src}_to_{dst}")(value)


def _restore(keys, defaults):
    """Re-seed widget keys from the shadow copy so values survive page navigation."""
    saved = st.session_state.setdefault("_home_saved", {})
    for k in keys:
        if k not in st.session_state:
            st.session_state[k] = saved.get(k, defaults[k])


def _save(keys):
    saved = st.session_state.setdefault("_home_saved", {})
    for k in keys:
        if k in st.session_state:
            saved[k] = st.session_state[k]


def _fmt(value, decimals):
    return f"{value:,.{decimals}f}"


def _on_units_change(p):
    """Convert the three duct values to the newly selected system."""
    new = st.session_state[f"{p}_units"]
    old = "SI" if new == "Imperial" else "Imperial"
    for qty in _QTYS:
        k = f"{p}_{_SHORT[qty]}"
        v = st.session_state.get(k)
        if v is not None:
            st.session_state[k] = _convert(v, _SYSTEMS[old][qty][1], _SYSTEMS[new][qty][1])


def render_ductulator(key_prefix="duct", fixed_solve_for=None):
    """Two of flow / duct ID / velocity in, the third shown in a disabled input."""
    p = key_prefix
    keys = [f"{p}_solve_for", f"{p}_units"] + [f"{p}_{s}" for s in _SHORT.values()]
    _restore(keys, {f"{p}_{k.split('_', 1)[1]}": v
                    for k, v in DEFAULTS.items() if k.startswith("duct_")})

    with st.container(border=True):
        st.markdown("**Ductulator** · round duct")
        c_solve, c_units = st.columns([3, 2])
        if fixed_solve_for is None:
            solve_label = c_solve.segmented_control(
                "Solve for", list(_SOLVE_FOR), required=True, key=f"{p}_solve_for",
            )
        else:
            solve_label = fixed_solve_for
        system = c_units.segmented_control(
            "Units", list(_SYSTEMS), required=True, key=f"{p}_units",
            on_change=_on_units_change, args=(p,),
        )
        solve = _SOLVE_FOR[solve_label]
        units = _SYSTEMS[system]

        # Solve before drawing, so the disabled box can show the result this run.
        inputs = {q: st.session_state.get(f"{p}_{_SHORT[q]}") for q in _QTYS if q != solve}
        solved_key = f"{p}_{_SHORT[solve]}"
        result, problem = None, None
        if any(v is None or v <= 0 for v in inputs.values()):
            problem = "Inputs must be greater than 0."
        else:
            try:
                result = solve_round_duct(**{
                    q: _convert(v, units[q][1], _BASE_KEY[q]) for q, v in inputs.items()
                })
            except ValueError as exc:
                problem = str(exc)
        st.session_state[solved_key] = (
            None if result is None
            else _convert(getattr(result, solve), _BASE_KEY[solve], units[solve][1])
        )

        for col, qty in zip(st.columns(3), _QTYS):
            label, _, dec, step = units[qty]
            is_solved = qty == solve
            col.number_input(
                f"{_QUANTITY_NAMES[qty]} [{label}]" + (" — result" if is_solved else ""),
                min_value=0.0, step=step, format=f"%.{dec}f",
                key=f"{p}_{_SHORT[qty]}", disabled=is_solved,
            )

        if problem:
            st.caption(f":orange[{problem}]")
        else:
            other_name = "SI" if system == "Imperial" else "Imperial"
            other = _SYSTEMS[other_name]
            parts = [
                f"{_fmt(_convert(getattr(result, q), _BASE_KEY[q], other[q][1]), other[q][2])}"
                f" {other[q][0]}"
                for q in _QTYS
            ]
            parts.insert(1, f"{_fmt(result.flow, 3)} m³/s")
            st.caption(f"{other_name}: " + " · ".join(parts))

        # Slot reserved for the future "Pressure loss per length" output; not implemented.

    _save(keys)


def _converter(qty, table, allow_negative=False, help_text=None):
    labels = list(table)
    c_val, c_unit = st.columns([3, 2])
    value = c_val.number_input(
        "Value", min_value=None if allow_negative else 0.0, format="%g",
        key=f"conv_{qty}_value", label_visibility="collapsed",
    )
    unit = c_unit.selectbox(
        "Unit", labels, key=f"conv_{qty}_unit", label_visibility="collapsed", help=help_text,
    )
    if value is None or (not allow_negative and value <= 0):
        st.caption(":orange[Value must be greater than 0.]")
        return
    src = table[unit][0]
    parts = []
    for label in labels:
        if label == unit:
            continue
        key, dec = table[label]
        out = U.convert_pressure(value, src, key) if qty == "pressure" else _convert(value, src, key)
        parts.append(f"**{_fmt(out, dec)}** {label}")
    st.markdown(" &nbsp;·&nbsp; ".join(parts))
    if help_text:
        st.caption(help_text)


def render_converters():
    """Flow, velocity and pressure converters in one tabbed card."""
    keys = [k for k in DEFAULTS if k.startswith("conv_")]
    _restore(keys, DEFAULTS)
    with st.container(border=True):
        st.markdown("**Unit converter**")
        t_flow, t_vel, t_press = st.tabs(["Flow", "Velocity", "Pressure"])
        with t_flow:
            _converter("flow", _FLOW)
        with t_vel:
            _converter("velocity", _VELOCITY)
        with t_press:
            _converter("pressure", _PRESSURE, allow_negative=True, help_text=_PRESSURE_HELP)
    _save(keys)
