"""Unit tests for the cyclone chart helpers (size range, emission shares)."""
import math
from types import SimpleNamespace

import pytest

pytest.importorskip("plotly")

from components.cyclone_chart import (
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
    assert not any(t.name == "Share of emission" for t in fig.data)
