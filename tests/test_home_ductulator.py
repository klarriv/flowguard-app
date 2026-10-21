"""AppTest checks for the Home page ductulator and converters (workbook cases 1-8)."""
from pathlib import Path

import pytest

pytest.importorskip("pint")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

ROOT = Path(__file__).resolve().parent.parent
HOME = str(ROOT / "app" / "app.py")
DUST_VENT = str(ROOT / "app" / "pages" / "1_Dust_Vent_NFPA68.py")


def _home():
    return AppTest.from_file(HOME, default_timeout=30).run()


def _metrics(at):
    return {m.label: m.value for m in at.metric}


def test_home_runs_without_exception():
    assert not _home().exception


def test_case1_solve_velocity():
    at = _home()
    at.number_input(key="duct_q_imp").set_value(2700.0)
    at.number_input(key="duct_d_imp").set_value(14.0)
    at.run()
    assert _metrics(at)["Velocity [FPM]"] == "2,526"
    assert "12.83 m/s" in [c.value for c in at.caption]


def test_case2_solve_duct_id():
    at = _home()
    at.radio(key="duct_solve_for").set_value("Duct ID").run()
    at.number_input(key="duct_q_imp").set_value(3500.0)
    at.number_input(key="duct_v_imp").set_value(4000.0)
    at.run()
    assert _metrics(at)["Duct ID [in]"] == "12.7"


def test_case3_solve_flow():
    at = _home()
    at.radio(key="duct_solve_for").set_value("Flow").run()
    at.number_input(key="duct_d_imp").set_value(7.0)
    at.number_input(key="duct_v_imp").set_value(4000.0)
    at.run()
    assert _metrics(at)["Flow [CFM]"] == "1,069"


def test_si_toggle_same_physical_result():
    at = _home()
    at.radio(key="duct_units").set_value("SI").run()
    at.number_input(key="duct_q_si").set_value(4588.0)
    at.number_input(key="duct_d_si").set_value(356.0)
    at.run()
    assert abs(float(_metrics(at)["Velocity [m/s]"]) - 12.83) < 0.05


def test_zero_input_warns_without_exception():
    at = _home()
    at.number_input(key="duct_q_imp").set_value(0.0).run()
    assert not at.exception
    assert at.warning


def test_flow_converter_cases_4_5():
    at = _home()
    at.number_input(key="conv_flow_value").set_value(3400.0).run()
    m = _metrics(at)
    assert m["m³/h"] == "5,777" and m["m³/s"] == "1.605"
    at.selectbox(key="conv_flow_unit").set_value("m³/h").run()
    at.number_input(key="conv_flow_value").set_value(72000.0).run()
    m = _metrics(at)
    assert m["CFM"] == "42,378" and m["m³/s"] == "20.000"


def test_velocity_converter_cases_6_7():
    at = _home()
    at.number_input(key="conv_velocity_value").set_value(4400.0).run()
    assert _metrics(at)["m/s"] == "22.35"
    at.selectbox(key="conv_velocity_unit").set_value("m/s").run()
    at.number_input(key="conv_velocity_value").set_value(22.68).run()
    assert _metrics(at)["FPM"] == "4,465"


def test_pressure_converter_case_8_library_values():
    at = _home()
    at.number_input(key="conv_pressure_value").set_value(230.0).run()
    m = _metrics(at)
    assert (m["inHg"], m["psi"], m["Pa"]) == ("16.92", "8.31", "57,290")
    assert (m["bar"], m["atm"]) == ("0.573", "0.565")


def test_dust_vent_page_loads():
    at = AppTest.from_file(DUST_VENT, default_timeout=60).run()
    assert not at.exception
