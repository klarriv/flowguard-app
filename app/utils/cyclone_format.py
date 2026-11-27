"""Display formatting for the Cyclone page (no physics: rounding and notation only)."""
import math

_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def efficiency_pct(eta, min_decimals=2, max_decimals=12):
    """Efficiency [0-1] as a percent string that never rounds up to 100 % unless
    eta is exactly 1: enough decimals that 1 − eta shows with two significant
    figures (e.g. 0.99995883 -> "99.9959 %")."""
    if eta >= 1.0:
        return "100 %"
    gap_pct = 100.0 * (1.0 - eta)
    # the 1e-6 keeps a gap at a power of ten (with float noise, e.g.
    # 9.9999997e-8) from gaining an extra digit
    decimals = max(min_decimals, math.ceil(-math.log10(gap_pct) - 1e-6) + 1)
    decimals = min(decimals, max_decimals)
    while decimals < max_decimals and float(f"{100.0 * eta:.{decimals}f}") >= 100.0:
        decimals += 1
    return f"{100.0 * eta:.{decimals}f} %"


def sci(value, sig=3):
    """Scientific notation with a Unicode exponent: 4.117e-05 -> "4.12 × 10⁻⁵"."""
    if value == 0:
        return "0"
    exp = math.floor(math.log10(abs(value)))
    mant = value / 10 ** exp
    if float(f"{mant:.{sig - 1}f}") >= 10.0:  # 9.996e-5 rounds to 10.0
        exp, mant = exp + 1, mant / 10.0
    if exp == 0:
        return f"{mant:.{sig - 1}f}"
    return f"{mant:.{sig - 1}f} × 10{str(exp).translate(_SUPERSCRIPT)}"
