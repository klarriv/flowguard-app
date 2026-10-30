"""Pred is filled from the Donaldson catalog's maximum when a model is picked."""
import pytest

pytest.importorskip("pint")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

from pathlib import Path

HOME = str(Path(__file__).resolve().parent.parent / "app" / "app.py")


@pytest.fixture
def at():
    at = AppTest.from_file(HOME, default_timeout=60).run()
    at.switch_page("pages/1_Dust_Vent_NFPA68.py").run()
    return at


def _sb(at, label):
    return next(s for s in at.selectbox if s.label == label)


def _pred(at):
    return at.number_input(key="in_Pred").value


def test_pred_filled_on_model_pick_and_kept_on_hopper_change(at):
    assert _pred(at) == 0.2
    _sb(at, "Enclosure geometry method").set_value("Donaldson").run()
    assert _pred(at) == 0.37  # DLMC 1/2/15
    _sb(at, "Model").set_value("DLMC 4/8/15").run()
    assert _pred(at) == 0.25
    at.number_input(key="in_Pred").set_value(0.20).run()
    _sb(at, "Hopper").set_value("four outlets").run()
    assert _pred(at) == 0.20
    next(r for r in at.radio if r.label == "Input unit").set_value("in").run()
    assert _pred(at) == 0.20
    assert not at.exception


def test_pred_above_max_flagged(at):
    _sb(at, "Enclosure geometry method").set_value("Donaldson").run()
    at.number_input(key="in_Pred").set_value(0.50).run()
    assert any("exceeded" in c.value for c in at.caption)


def test_donaldson_sets_dust_collector_and_flexible_filters(at):
    enc = _sb(at, "Enclosure type")
    assert enc.value == "Standard enclosure"
    _sb(at, "Enclosure geometry method").set_value("Donaldson").run()
    assert _sb(at, "Enclosure type").value.startswith("Dust collector")
    assert at.checkbox(key="in_flex_filters").value is True
    # The user's choice is kept when only the model changes.
    at.checkbox(key="in_flex_filters").uncheck().run()
    _sb(at, "Model").set_value("DLMC 4/8/15").run()
    assert at.checkbox(key="in_flex_filters").value is False
    assert _sb(at, "Enclosure type").value.startswith("Dust collector")
    assert not at.exception
