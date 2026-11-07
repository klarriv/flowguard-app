"""PSD table -> ParticleSizeDistribution for the Cyclone page.

Pure Python (no Streamlit). Does the row-level validation so the page can show
messages that name the offending row, converts % -> fraction at the boundary,
and builds the distribution through the flowguard constructors. The library's
own ValueError is still caught and returned as an error, so a check missed here
never crashes the page.
"""
import math

from collection_systems.cyclone_muschelknautz_orchestrator import ParticleSizeDistribution

MODE_CUM = "Cumulative % passing"
MODE_SIEVE = "Sieve / % retained"
MODE_BINS = "Bins (laser diffraction channels)"
MODES = [MODE_CUM, MODE_SIEVE, MODE_BINS]

COLUMNS = {
    MODE_CUM: ["Size [µm]", "% passing"],
    MODE_SIEVE: ["Aperture [µm]", "% retained"],
    MODE_BINS: ["Bin low [µm]", "Bin high [µm]", "% in bin"],
}

# Short worked examples (not the workbook's 31 rows).
EXAMPLES = {
    MODE_CUM: [[2.0, 5.0], [5.0, 20.0], [10.0, 45.0], [20.0, 75.0], [35.0, 95.0], [50.0, 100.0]],
    MODE_SIEVE: [[75.0, 5.0], [45.0, 15.0], [25.0, 30.0], [10.0, 30.0]],
    MODE_BINS: [[1.0, 3.0, 10.0], [3.0, 10.0, 30.0], [10.0, 30.0, 40.0], [30.0, 100.0, 20.0]],
}
EXAMPLE_PAN_PCT = 20.0

SUM_TOL_PCT = 0.1  # percentages must total 100 ± 0.1


def _num(v):
    """Float, or None for blank / NaN / non-numeric."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _clean_rows(rows, ncols):
    """Drop fully empty rows. Returns [(row_number, [values])], row numbers 1-based
    on the table as shown. Missing / non-numeric cells come back as None."""
    out = []
    for i, row in enumerate(rows, start=1):
        vals = [_num(row[j]) if j < len(row) else None for j in range(ncols)]
        if all(v is None for v in vals):
            continue
        out.append((i, vals))
    return out


def build_psd(mode, rows, pan_pct=0.0):
    """Validate a PSD table and build the distribution.

    rows: list of row sequences in the column order of ``COLUMNS[mode]``.
    Returns ``(psd, errors)``; ``psd`` is None whenever ``errors`` is non-empty.
    """
    if mode not in COLUMNS:
        return None, [f"Unknown PSD input mode: {mode}"]
    cols = COLUMNS[mode]
    data = _clean_rows(rows, len(cols))
    errors = []

    for n, vals in data:
        for name, v in zip(cols, vals):
            if v is None:
                errors.append(f"Row {n}: '{name}' is empty or not a number.")
    if errors:
        return None, errors

    if mode == MODE_CUM:
        errors += _check_cumulative(data)
    elif mode == MODE_SIEVE:
        errors += _check_sieve(data, pan_pct)
    else:
        errors += _check_bins(data)
    if errors:
        return None, errors

    try:
        if mode == MODE_CUM:
            psd = ParticleSizeDistribution.from_cumulative(
                [v[0] for _, v in data], [v[1] / 100.0 for _, v in data])
        elif mode == MODE_SIEVE:
            psd = ParticleSizeDistribution.from_sieve(
                [v[0] for _, v in data], [v[1] / 100.0 for _, v in data],
                pan_fraction=(pan_pct or 0.0) / 100.0)
        else:
            psd = ParticleSizeDistribution.from_bins(
                [v[0] for _, v in data], [v[1] for _, v in data],
                [v[2] / 100.0 for _, v in data])
    except ValueError as exc:  # a rule the page did not catch
        return None, [str(exc)]
    return psd, []


def _check_cumulative(data):
    errs = []
    if len(data) < 1:
        return ["Enter at least 1 row."]
    prev_n = prev = None
    for n, (size, cum) in data:
        if size <= 0:
            errs.append(f"Row {n}: size must be > 0 µm.")
        if not 0 <= cum <= 100:
            errs.append(f"Row {n}: % passing must be between 0 and 100 (got {cum:g}).")
        if prev is not None:
            if size <= prev[0]:
                errs.append(f"Row {n}: size {size:g} µm must be larger than row {prev_n} "
                            f"({prev[0]:g} µm); sizes must be strictly increasing.")
            if cum < prev[1]:
                errs.append(f"Row {n}: % passing {cum:g} is lower than row {prev_n} "
                            f"({prev[1]:g}); cumulative values must not decrease.")
        prev_n, prev = n, (size, cum)
    return errs


def _check_sieve(data, pan_pct):
    errs = []
    pan = _num(pan_pct)
    if pan is None:
        errs.append("Pan % is empty or not a number.")
        pan = 0.0
    if len(data) < 2:
        errs.append("A sieve stack needs at least 2 rows.")
    if pan < 0:
        errs.append("Pan % must not be negative.")
    for n, (ap, ret) in data:
        if ap <= 0:
            errs.append(f"Row {n}: aperture must be > 0 µm.")
        if ret < 0:
            errs.append(f"Row {n}: % retained must not be negative.")
    # Screens may be listed coarse-to-fine or fine-to-coarse, but not mixed or repeated.
    sizes = [v[0] for _, v in data]
    steps = [b - a for a, b in zip(sizes, sizes[1:])]
    if any(d == 0 for d in steps):
        dup = next(data[i + 1][0] for i, d in enumerate(steps) if d == 0)
        errs.append(f"Row {dup}: duplicate aperture; apertures must be distinct.")
    elif any(d > 0 for d in steps) and any(d < 0 for d in steps):
        errs.append("Apertures must be listed in one direction (all increasing or all decreasing).")
    total = pan + sum(v[1] for _, v in data)
    if abs(total - 100.0) > SUM_TOL_PCT:
        errs.append(f"% retained plus pan sums to {total:.2f}, expected 100 (± {SUM_TOL_PCT}).")
    return errs


def _check_bins(data):
    errs = []
    if len(data) < 1:
        return ["Enter at least 1 row."]
    for n, (lo, hi, pct) in data:
        if lo <= 0:
            errs.append(f"Row {n}: bin low must be > 0 µm.")
        if hi <= lo:
            errs.append(f"Row {n}: bin high {hi:g} µm must exceed bin low {lo:g} µm.")
        if pct < 0:
            errs.append(f"Row {n}: % in bin must not be negative.")
    if errs:
        return errs
    ordered = sorted(data, key=lambda r: r[1][0])
    for (n1, (_, hi1, _)), (n2, (lo2, _, _)) in zip(ordered, ordered[1:]):
        if not math.isclose(hi1, lo2, rel_tol=1e-6):
            word = "overlap" if lo2 < hi1 else "gap"
            errs.append(f"Rows {n1} and {n2}: bins are not contiguous ({word} between "
                        f"{hi1:g} and {lo2:g} µm); add a zero-% bin to cover a gap.")
    total = sum(v[2] for _, v in data)
    if abs(total - 100.0) > SUM_TOL_PCT:
        errs.append(f"% in bin sums to {total:.2f}, expected 100 (± {SUM_TOL_PCT}).")
    return errs
