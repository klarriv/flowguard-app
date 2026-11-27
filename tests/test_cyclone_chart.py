"""Unit tests for the cyclone chart helpers (size range, emission shares)."""
import math
from types import SimpleNamespace

import pytest

pytest.importorskip("plotly")

from components.cyclone_chart import (
    NAME_CLS, NAME_COLLECTED, NAME_EMITTED, NAME_EXTRAP, NAME_SHARE, NAME_TOTAL, NAME_X50,
    RANGE_PAD, build_figure, emission_shares, size_grid, size_range,
)


def _iv(lo, hi, emitted, kind="measured", feed=0.25):
    return SimpleNamespace(lower_um=lo, upper_um=hi, kind=kind, feed_fraction=feed,
                           collected_fraction=feed - emitted, emitted_fraction=emitted,
                           is_extrapolated=kind in ("below_range", "above_range"))


def _result(x50_um, m, intervals, saltation=False):
    def eta(sizes):
        return [1.0 / (1.0 + (x50_um / x) ** m) for x in sizes]
    return SimpleNamespace(x50_um=x50_um, m=m, psd_intervals=tuple(intervals),
                           saltation=saltation, classification_grade_efficiency=eta,
                           total_grade_efficiency=eta)


def test_range_covers_psd_when_wider_than_curve():
    r = _result(25.0, 3.0, [_iv(38.0, 53.0, 1e-5), _iv(53.0, 1190.0, 1e-6)])
    lo, hi = size_range(r)
    assert math.isclose(lo, 25.0 / 99 ** (1 / 3) / RANGE_PAD)  # curve's 1 % point is lower
    assert math.isclose(hi, 1190.0 * RANGE_PAD)                 # PSD top is higher


def test_range_covers_curve_when_wider_than_psd():
    r = _result(10.0, 2.0, [_iv(9.0, 11.0, 0.1)])
    lo, hi = size_range(r)
    assert math.isclose(lo, 10.0 / math.sqrt(99) / RANGE_PAD)
    assert math.isclose(hi, 10.0 * math.sqrt(99) * RANGE_PAD)


def test_range_with_point_interval_only():
    r = _result(2.0, 5.0, [_iv(3.4, 3.4, 0.01, kind="point", feed=1.0)])
    lo, hi = size_range(r)
    assert lo < 2.0 / 99 ** 0.2 and hi > 3.4
    assert all(lo * 0.999 <= x <= hi * 1.001 for x in size_grid(r))


def test_emission_shares_sum_to_one_and_none_when_zero():
    r = _result(5.0, 3.0, [_iv(1, 2, 3e-6), _iv(2, 4, 1e-6)])
    assert emission_shares(r) == pytest.approx([0.75, 0.25])
    assert emission_shares(_result(5.0, 3.0, [_iv(1, 2, 0.0)])) is None


def test_figure_has_fixed_range_and_no_emission_note():
    r = _result(5.0, 3.0, [_iv(1, 2, 0.0), _iv(2, 4, 0.0)])
    fig = build_figure(r)
    lo, hi = size_range(r)
    assert list(fig.layout.xaxis.range) == pytest.approx([math.log10(lo), math.log10(hi)])
    assert any(a.text == "No emission" for a in fig.layout.annotations)
    assert not any(t.name == NAME_SHARE for t in fig.data)


# ── Legend and bar visibility ────────────────────────────────────────────────

def _legend_entries(fig):
    """name -> number of traces of that name listed in the legend."""
    counts = {}
    for t in fig.data:
        assert t.name, "every trace must be a named series"
        assert t.legendgroup == t.name
        counts.setdefault(t.name, 0)
        if t.showlegend is not False:
            counts[t.name] += 1
    return counts


def test_every_series_listed_in_legend_exactly_once():
    r = _result(25.0, 3.0, [_iv(38.0, 53.0, 1e-5, kind="below_range", feed=0.05),
                            _iv(53.0, 1190.0, 1e-6, feed=0.85),
                            _iv(1190.0, 1190.0, 1e-9, kind="above_range", feed=0.10)],
                saltation=True)
    counts = _legend_entries(build_figure(r))
    assert set(counts) == {NAME_CLS, NAME_TOTAL, NAME_X50, NAME_COLLECTED, NAME_EMITTED,
                           NAME_EXTRAP, NAME_SHARE}
    assert all(n == 1 for n in counts.values()), counts


def test_legend_without_saltation_or_extrapolation():
    r = _result(5.0, 3.0, [_iv(1.0, 2.0, 1e-3), _iv(2.0, 4.0, 1e-4)])
    counts = _legend_entries(build_figure(r))
    assert set(counts) == {NAME_CLS, NAME_X50, NAME_COLLECTED, NAME_EMITTED, NAME_SHARE}
    assert all(n == 1 for n in counts.values()), counts


def _solid_bars(fig, yaxis):
    """(x0, x1, y0, y1) of each solid filled rectangle on ``yaxis``. Visibility
    must not depend on a fill pattern, so the fill colour has to be opaque."""
    bars = []
    for t in fig.data:
        if t.fill != "toself" or t.yaxis != yaxis or t.visible is False:
            continue
        if t.fillcolor is None or t.fillcolor.startswith("rgba") and t.fillcolor.endswith(",0)"):
            continue  # overlay (outline + hatch), not the bar itself
        bars.append((min(t.x), max(t.x), min(t.y), max(t.y)))
    return bars


def _case_result():
    """40-HE case file (same inputs as tests/test_cyclone_page.py)."""
    orch = pytest.importorskip("collection_systems.cyclone_muschelknautz_orchestrator")
    pytest.importorskip("pint")
    from fluid_systems.duct_flow import solve_round_duct
    from utils.cyclone_psd import MODE_SIEVE, build_psd
    sieve = [[1190.0, 200 / 19], [841.0, 200 / 19], [595.0, 200 / 19], [420.0, 200 / 19],
             [297.0, 200 / 19], [210.0, 100 / 19], [149.0, 200 / 19], [105.0, 200 / 19],
             [74.0, 200 / 19], [53.0, 100 / 19]]
    psd, errors = build_psd(MODE_SIEVE, sieve, 100 / 19)
    assert not errors
    return orch.cyclone_performance(
        orch.CycloneGeometry(D=1.016, a=0.8636, b=0.254, Dx=0.6096, S=1.0541,
                             H=1.8288 + 1.14935, Hc=1.14935, Dd=0.40005),
        orch.GasProperties(density=1.2, viscosity=1.8e-5, flow_rate=2.655),
        orch.SolidProperties(particle_density=1300.0, bulk_density=640.0,
                             dust_loading=1.31, wall_roughness=0.046e-3),
        psd=psd, slope_m=3.0,
        upstream_velocity_m_s=solve_round_duct(flow=2.655, diameter=0.537).velocity)


def test_case_file_every_interval_has_a_visible_bar():
    r = _case_result()
    kinds = {iv.kind for iv in r.psd_intervals}
    assert {"below_range", "above_range", "measured"} <= kinds
    fig = build_figure(r)
    top, bottom = _solid_bars(fig, "y"), _solid_bars(fig, "y3")
    shares = emission_shares(r)
    lo, hi = size_range(r)
    for iv, share in zip(r.psd_intervals, shares):
        if iv.feed_fraction <= 0:
            continue
        # the interval's own x-span (a point mass gets a narrow band around it)
        span = [b for b in top if b[0] <= iv.lower_um <= b[1] and b[0] <= iv.upper_um <= b[1]
                and b[1] - b[0] < 2 * max(iv.upper_um - iv.lower_um, 0.1 * iv.upper_um)]
        assert span, f"no top-panel bar for {iv.kind} {iv.lower_um:.3g}-{iv.upper_um:.3g} µm"
        assert lo < min(b[0] for b in span) and max(b[1] for b in span) < hi
        assert max(b[3] for b in span) == pytest.approx(100.0 * iv.feed_fraction)
        assert min(b[2] for b in span) == 0.0
        if iv.emitted_fraction > 0:
            own = [b for b in bottom if b[0] <= iv.lower_um <= b[1] and b[0] <= iv.upper_um <= b[1]
                   and b[1] - b[0] < 2 * max(iv.upper_um - iv.lower_um, 0.1 * iv.upper_um)]
            assert len(own) == 1, f"no emission bar for {iv.kind} {iv.lower_um:.3g} µm"
            assert own[0][3] == pytest.approx(100.0 * share)
    assert sum(b[3] for b in bottom) == pytest.approx(100.0)
    # the 38-53 µm pan extrapolation carries most of the emission
    below = next(iv for iv in r.psd_intervals if iv.kind == "below_range")
    assert max(bottom, key=lambda b: b[3])[0] == pytest.approx(below.lower_um)
