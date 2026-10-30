"""AppTest checks for the Home page ductulator and converters (workbook cases 1-8)."""
from pathlib import Path

import pytest

pytest.importorskip("pint")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

ROOT = Path(__file__).resolve().parent.parent
HOME = str(ROOT / "app" / "app.py")


def _home():
    return AppTest.from_file(HOME, default_timeout=30).run()


def _val(at, key):
    return at.number_input(key=key).value


def _seg(at, key, value):
    at.button_group(key=key).set_value(value).run()


def _md(at):
    return " ".join(m.value for m in at.markdown)


def test_home_runs_without_exception():
    assert not _home().exception


def test_case1_solve_velocity_in_disabled_input():
    at = _home()
    at.number_input(key="duct_q").set_value(2700.0)
    at.number_input(key="duct_d").set_value(14.0)
    at.run()
    assert at.number_input(key="duct_v").disabled
    assert round(_val(at, "duct_v")) == 2526
    assert "12.83 m/s" in " ".join(c.value for c in at.caption)


def test_case2_solve_duct_id():
    at = _home()
    _seg(at, "duct_solve_for", "Duct ID")
    at.number_input(key="duct_q").set_value(3500.0)
    at.number_input(key="duct_v").set_value(4000.0)
    at.run()
    assert at.number_input(key="duct_d").disabled
    assert not at.number_input(key="duct_v").disabled
    assert round(_val(at, "duct_d"), 1) == 12.7


def test_case3_solve_flow():
    at = _home()
    _seg(at, "duct_solve_for", "Flow")
    at.number_input(key="duct_d").set_value(7.0)
    at.number_input(key="duct_v").set_value(4000.0)
    at.run()
    assert round(_val(at, "duct_q")) == 1069


def test_previous_result_becomes_input():
    at = _home()  # 2700 CFM, 14 in -> 2526 FPM
    _seg(at, "duct_solve_for", "Flow")
    assert round(_val(at, "duct_v")) == 2526
    assert abs(_val(at, "duct_q") - 2700) < 1e-6


def test_units_toggle_converts_values():
    at = _home()
    _seg(at, "duct_units", "SI")
    assert round(_val(at, "duct_q")) == 4587  # 2700 CFM = 4,587.3 m³/h
    assert abs(_val(at, "duct_d") - 355.6) < 1e-6
    assert abs(_val(at, "duct_v") - 12.83) < 0.01
    _seg(at, "duct_units", "Imperial")
    assert abs(_val(at, "duct_q") - 2700) < 1e-6
    assert abs(_val(at, "duct_d") - 14) < 1e-6


def test_zero_input_warns_without_exception():
    at = _home()
    at.number_input(key="duct_q").set_value(0.0).run()
    assert not at.exception
    assert _val(at, "duct_v") is None
    assert "greater than 0" in " ".join(c.value for c in at.caption)


def test_flow_converter_cases_4_5():
    at = _home()
    at.number_input(key="conv_flow_value").set_value(3400.0).run()
    assert "**5,777** m³/h" in _md(at) and "**1.605** m³/s" in _md(at)
    at.selectbox(key="conv_flow_unit").set_value("m³/h").run()
    at.number_input(key="conv_flow_value").set_value(72000.0).run()
    assert "**42,378** CFM" in _md(at) and "**20.000** m³/s" in _md(at)


def test_velocity_converter_cases_6_7():
    at = _home()
    at.number_input(key="conv_velocity_value").set_value(4400.0).run()
    assert "**22.35** m/s" in _md(at)
    at.selectbox(key="conv_velocity_unit").set_value("m/s").run()
    at.number_input(key="conv_velocity_value").set_value(22.68).run()
    assert "**4,465** FPM" in _md(at)


def test_pressure_converter_case_8_library_values():
    at = _home()
    at.number_input(key="conv_pressure_value").set_value(230.0).run()
    md = _md(at)
    for s in ("**16.92** inHg", "**8.31** psi", "**57,290** Pa", "**0.573** bar", "**0.565** atm"):
        assert s in md


def test_dust_vent_page_loads():
    at = _home()
    at.switch_page("pages/1_Dust_Vent_NFPA68.py").run()
    assert not at.exception
