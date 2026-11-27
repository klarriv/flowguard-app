"""Cyclone page: defaults compute, PSD errors block results, chart renders."""
import json
import math

import pytest

pytest.importorskip("pint")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

from pathlib import Path

from components.cyclone_chart import NAME_SHARE

HOME = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
PAGE = "pages/2_Cyclone_Muschelknautz.py"


@pytest.fixture
def at():
    at = AppTest.from_file(HOME, default_timeout=60).run()
    at.switch_page(PAGE).run()
    return at


def _headers(at):
    return [h.value for h in at.header]


def test_defaults_compute_and_chart(at):
    assert not at.exception
    assert not at.error
    assert "5. Efficiency Chart" in _headers(at)
    assert "4. Results" in _headers(at)


def test_median_only_mode(at):
    at.checkbox(key="cy_median_only").set_value(True).run()
    assert not at.exception and not at.error
    assert "5. Efficiency Chart" in _headers(at)


def test_invalid_geometry_shows_error_not_crash(at):
    at.number_input(key="cy_Dx").set_value(0.3).run()  # Dx >= D
    assert not at.exception
    assert at.error
    assert "5. Efficiency Chart" not in _headers(at)


def test_bad_median_blocks_results(at):
    at.checkbox(key="cy_median_only").set_value(True).run()
    at.number_input(key="cy_xmed").set_value(0.0).run()
    assert at.error
    assert "5. Efficiency Chart" not in _headers(at)


def test_sieve_mode_with_pan_computes(at):
    at.selectbox(key="cy_psd_mode").set_value("Sieve / % retained").run()
    assert not at.exception and not at.error
    at.number_input(key="cy_pan").set_value(5.0).run()  # sums to 85 -> error
    assert at.error
    assert "5. Efficiency Chart" not in _headers(at)


# ── Case file "Emission Cyclones - Flow Guard Case File", tab 40-HE CYCLONE ──
# Non-Stokes, Dd < Dx, saltation; Tyler sieve PSD (coarse to fine) + pan.
CASE_INPUTS = {
    "cy_D": 1.016, "cy_a": 0.8636, "cy_b": 0.254, "cy_Dx": 0.6096, "cy_S": 1.0541,
    "cy_h": 1.8288, "cy_hc": 1.14935, "cy_Dd": 0.40005,
    "cy_Q": 2.655, "cy_mu": 1.8e-5, "cy_rho": 1.2, "cy_dpipe": 537.0, "cy_m": 3.0,
    "cy_rhos": 1300.0, "cy_rhob": 640.0, "cy_co": 1.31, "cy_ks": 0.046,
}
CASE_SIEVE = [[1190.0, 200 / 19], [841.0, 200 / 19], [595.0, 200 / 19], [420.0, 200 / 19],
              [297.0, 200 / 19], [210.0, 100 / 19], [149.0, 200 / 19], [105.0, 200 / 19],
              [74.0, 200 / 19], [53.0, 100 / 19]]
CASE_PAN = 100 / 19
SIEVE_TABLE_KEY = "cy_psd_table_1"
SIEVE_COLS = ["Aperture [µm]", "% retained"]


def _sieve_editor_state(rows, n_example_rows=4):
    """data_editor edit state that turns the 4-row example into ``rows``."""
    edited = {str(i): dict(zip(SIEVE_COLS, rows[i])) for i in range(n_example_rows)}
    added = [dict(zip(SIEVE_COLS, r)) for r in rows[n_example_rows:]]
    return {"edited_rows": edited, "added_rows": added, "deleted_rows": []}


@pytest.fixture
def case(at):
    for key, value in CASE_INPUTS.items():
        at.number_input(key=key).set_value(value)
    at.selectbox(key="cy_psd_mode").set_value("Sieve / % retained").run()
    at.number_input(key="cy_pan").set_value(CASE_PAN)
    at.session_state[SIEVE_TABLE_KEY] = _sieve_editor_state(CASE_SIEVE)
    at.run()
    assert not at.exception and not at.error
    return at


def _texts(at):
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


def _chart_spec(at):
    charts = at.get("plotly_chart")
    assert charts, "no plotly chart rendered"
    return json.loads(charts[0].proto.spec)


def test_case_file_results(case):
    texts = " ".join(_texts(case))
    assert "**Cut size x50** 25.58 µm · non-Stokes" in texts
    assert "kg/kg vs limit 0.0028 kg/kg" in texts
    assert "kg/m³ vs limit" not in texts


_SUP = str.maketrans("⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "-0123456789")


def _value_after(texts, label):
    """Text after ``**label** `` in the first markdown that has it."""
    md = next(t for t in texts if t.startswith(f"**{label}** "))
    return md[len(f"**{label}** "):]


def test_case_file_overall_efficiency_and_penetration(case):
    texts = _texts(case)
    overall = _value_after(texts, "Overall efficiency")
    assert not overall.startswith("100"), overall
    assert overall == "99.9959 %"
    # penetration (scientific notation) × inlet loading reproduces the emission
    mant, exp = _value_after(texts, "Penetration").split(" × 10")
    penetration = float(mant) * 10 ** int(exp.translate(_SUP))
    emission = _value_after(texts, "Emission")
    mg_m3 = float(emission.split(" · ")[1].removesuffix(" mg/m³"))
    loading_kg_m3 = CASE_INPUTS["cy_co"]
    assert math.isclose(penetration * loading_kg_m3 * 1e6, mg_m3, rel_tol=2e-3)
    # Eq. 6.5.1 mass split is shown, with the tooltips on both efficiencies
    split = next(t for t in texts if t.startswith("Mass split"))
    assert "1 − coL/co" in split and "99.9959 %" in split and "98.41 %" in split
    helps = {m.value.split("**")[1]: m.help for m in case.markdown if m.help}
    assert "Eq. 6.5.1" in helps["Overall efficiency"]
    assert "Eq. 6.3.3" in helps["Classification efficiency"]


def test_no_saltation_hides_split(at):
    # defaults, monodisperse 1 µm feed: co 0.00375 < coL 0.0091 kg/kg
    at.checkbox(key="cy_median_only").set_value(True).run()
    at.number_input(key="cy_xmed").set_value(1.0).run()
    assert not at.exception and not at.error
    texts = _texts(at)
    assert not any(t.startswith("Mass split") for t in texts)
    assert any("overall efficiency = classification efficiency" in t for t in texts)


def test_case_file_each_warning_and_note_shown_once(case):
    shown = [w.value for w in case.warning] + [i.value for i in case.info]
    assert any("below the measured range" in s for s in shown)
    assert len(shown) == len(set(shown)), shown


def test_case_file_chart_range_and_emission_panel(case):
    spec = _chart_spec(case)
    layout = spec["layout"]
    lo, hi = layout["xaxis"]["range"]
    assert layout["xaxis"].get("autorange") in (None, False)
    # 1-99 % of the S-curve plus the sieve range, padded x/1.3: about 4 to 1550 µm
    assert math.isclose(10 ** lo, 4.25, rel_tol=0.01)
    assert math.isclose(10 ** hi, 1190 * 1.3, rel_tol=0.01)
    # one filled rectangle per emitting interval, heights summing to 100 %
    share = [t for t in spec["data"] if t.get("name") == NAME_SHARE]
    assert len(share) == 11  # every interval of the case PSD emits something
    assert math.isclose(sum(max(t["y"]) for t in share), 100.0, rel_tol=1e-9)
    assert sum(1 for t in share if t.get("showlegend") is not False) == 1
