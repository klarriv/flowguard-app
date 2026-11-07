"""PSD table validation and construction for the Cyclone page helper."""
import pytest

pytest.importorskip("pint")

from utils.cyclone_psd import (  # noqa: E402
    MODE_BINS, MODE_CUM, MODE_SIEVE, EXAMPLES, EXAMPLE_PAN_PCT, build_psd,
)


def _errs(mode, rows, pan=0.0):
    psd, errors = build_psd(mode, rows, pan)
    assert psd is None
    assert errors
    return " | ".join(errors)


def test_examples_are_valid():
    for mode, rows in EXAMPLES.items():
        psd, errors = build_psd(mode, rows, EXAMPLE_PAN_PCT if mode == MODE_SIEVE else 0.0)
        assert errors == [] and psd is not None, mode


def test_cumulative_percent_converted_to_fraction():
    psd, errors = build_psd(MODE_CUM, [[2, 10], [4, 50], [8, 100]])
    assert errors == []
    assert psd.sizes_um == (2, 4, 8)
    assert psd.cumulative == pytest.approx((0.1, 0.5, 1.0))


def test_cumulative_single_row_allowed():
    psd, errors = build_psd(MODE_CUM, [[3.4, 100]])
    assert errors == [] and psd.sizes_um == (3.4,)


def test_cumulative_blank_rows_ignored_but_blank_cell_reported():
    psd, errors = build_psd(MODE_CUM, [[2, 10], [None, None], [4, 100]])
    assert errors == [] and len(psd.sizes_um) == 2
    assert "Row 2" in _errs(MODE_CUM, [[2, 10], [4, None]]).replace("Row 2", "Row 2")


def test_cumulative_rejects_nan_and_text():
    assert "Row 1" in _errs(MODE_CUM, [[float("nan"), 10], [4, 100]])
    assert "Row 2" in _errs(MODE_CUM, [[2, 10], ["abc", 100]])


def test_cumulative_sizes_strictly_increasing():
    msg = _errs(MODE_CUM, [[2, 10], [2, 20], [4, 100]])
    assert "Row 2" in msg and "strictly increasing" in msg
    assert "Row 3" in _errs(MODE_CUM, [[2, 10], [8, 50], [4, 100]])


def test_cumulative_monotonic_and_range():
    assert "Row 3" in _errs(MODE_CUM, [[2, 10], [4, 60], [8, 50]])
    assert "between 0 and 100" in _errs(MODE_CUM, [[2, 10], [4, 120]])
    assert "between 0 and 100" in _errs(MODE_CUM, [[2, -1], [4, 50]])
    assert "must be > 0" in _errs(MODE_CUM, [[0, 10], [4, 50]])


def test_empty_table():
    assert "at least 1 row" in _errs(MODE_CUM, [])
    assert "at least 1 row" in _errs(MODE_CUM, [[None, None]])


def test_sieve_valid_with_pan_and_either_order():
    rows = [[75, 10], [45, 30], [25, 40]]
    psd, errors = build_psd(MODE_SIEVE, rows, pan_pct=20)
    assert errors == []
    assert psd.cumulative[0] == pytest.approx(0.2)  # pan under the finest screen
    psd2, errors2 = build_psd(MODE_SIEVE, rows[::-1], pan_pct=20)
    assert errors2 == [] and psd2.sizes_um == psd.sizes_um


def test_sieve_rules():
    assert "sums to 90" in _errs(MODE_SIEVE, [[75, 10], [45, 30], [25, 50]], 0)
    assert "at least 2 rows" in _errs(MODE_SIEVE, [[75, 100]], 0)
    assert "must not be negative" in _errs(MODE_SIEVE, [[75, -5], [45, 105]], 0)
    assert "duplicate" in _errs(MODE_SIEVE, [[75, 50], [75, 50]], 0)
    assert "one direction" in _errs(MODE_SIEVE, [[75, 30], [25, 30], [45, 40]], 0)
    assert "Pan" in _errs(MODE_SIEVE, [[75, 50], [45, 50]], None)


def test_bins_valid_and_percent_conversion():
    psd, errors = build_psd(MODE_BINS, [[1, 2, 25], [2, 4, 75]])
    assert errors == []
    assert psd.sizes_um == (1, 2, 4)
    assert psd.cumulative == pytest.approx((0.0, 0.25, 1.0))


def test_bins_rules():
    assert "Row 1" in _errs(MODE_BINS, [[2, 1, 100]])
    gap = _errs(MODE_BINS, [[1, 2, 50], [3, 4, 50]])
    assert "gap" in gap and "Rows 1 and 2" in gap
    assert "overlap" in _errs(MODE_BINS, [[1, 3, 50], [2, 4, 50]])
    assert "sums to 90" in _errs(MODE_BINS, [[1, 2, 40], [2, 4, 50]])
    assert "must not be negative" in _errs(MODE_BINS, [[1, 2, -10], [2, 4, 110]])


def test_unknown_mode():
    psd, errors = build_psd("nope", [[1, 2]])
    assert psd is None and errors
