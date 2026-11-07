"""Cyclone page: defaults compute, PSD errors block results, chart renders."""
import pytest

pytest.importorskip("pint")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

from pathlib import Path

HOME = str(Path(__file__).resolve().parent.parent / "app" / "app.py")


@pytest.fixture
def at():
    at = AppTest.from_file(HOME, default_timeout=60).run()
    at.switch_page("pages/2_Cyclone_Muschelknautz.py").run()
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
