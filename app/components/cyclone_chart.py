"""Grade-efficiency chart for the Cyclone page (Plotly rendering only).

One figure, two rows sharing a log size axis [µm]:
  * top, left axis  - grade efficiency curve(s) from ``CycloneResult``; x50 marked
    (drawn above the bars)
  * top, right axis - the feed PSD as one bar per ``CycloneResult.psd_intervals``
    entry, stacked collected (dark) / emitted (light red), as % of total feed
  * bottom          - share of the emission per interval [%]: each interval's
    ``emitted_fraction`` normalised by their sum, so the emission makeup stays
    readable even when the emission is a tiny fraction of the feed

Bars are filled rectangles (``go.Scatter`` with ``fill="toself"``) whose corners
are in data coordinates, so their edges land exactly on the interval bounds on
the log axis. Visibility never depends on a fill pattern: in the browser
(Streamlit's Plotly), per-point hatch patterns can fail to render and the bar
then disappears. Extrapolated intervals get a separate overlay (dashed outline
plus hatch) on top of their solid bar.

Every series is one legend entry (``legendgroup``; ``showlegend`` on the first
trace of each group only), so toggling it in the legend toggles all its parts.

The size axis has an explicit range (see ``size_range``) instead of autorange.

All numbers come from the library; nothing is re-derived here except the
plotting range/grid, the percent scaling and the emission normalisation.
"""
import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots

COLLECTED = "#4C78A8"
EMITTED = "#F2A4A0"
EMISSION_SHARE = "#E45756"
CURVE = "#1F2937"
TOTAL_CURVE = "#D97706"
X50_LINE = dict(color="#6B7280", width=1.5, dash="dot")

EXTRAPOLATED = "#374151"

RANGE_PAD = 1.3  # x/÷ padding around the useful size range
POINT_HALF_WIDTH = 1.03  # point-mass rectangle spans size ×/÷ this (~6 % wide)

# Legend names (each appears in the legend exactly once).
NAME_CLS = "Grade efficiency (classification)"
NAME_TOTAL = "Grade efficiency (total, incl. saltation)"
NAME_X50 = "x50 (cut size)"
NAME_COLLECTED = "Collected (% of feed)"
NAME_EMITTED = "Emitted (% of feed)"
NAME_EXTRAP = "Extrapolated outside measured range (hatched)"
NAME_SHARE = "Share of emission (% of emission)"


def size_range(result):
    """(low, high) [µm] of the useful size range: where the classification
    grade efficiency goes from 1 % to 99 % (x50 · 99^(∓1/m)) plus where the
    feed lies (PSD interval edges), padded x/÷ 1.3."""
    spread = 99.0 ** (1.0 / result.m)
    lows = [result.x50_um / spread] + [iv.lower_um for iv in result.psd_intervals]
    highs = [result.x50_um * spread] + [iv.upper_um for iv in result.psd_intervals]
    return min(lows) / RANGE_PAD, max(highs) * RANGE_PAD


def size_grid(result, points=200):
    """Log-spaced sizes [µm] across ``size_range``."""
    lo, hi = (math.log10(v) for v in size_range(result))
    return [10 ** (lo + (hi - lo) * i / (points - 1)) for i in range(points)]


def emission_shares(result):
    """Each interval's share of the total emission [0-1], or None when nothing
    is emitted."""
    total = sum(iv.emitted_fraction for iv in result.psd_intervals)
    if total <= 0:
        return None
    return [iv.emitted_fraction / total for iv in result.psd_intervals]


def emission_by_band(result):
    """(share of emission below x50, share at or above x50) from the library's
    per-interval emitted fractions; an interval straddling x50 is counted by
    its upper edge. None when nothing is emitted."""
    total = sum(iv.emitted_fraction for iv in result.psd_intervals)
    if total <= 0:
        return None
    below = sum(iv.emitted_fraction for iv in result.psd_intervals
                if iv.upper_um <= result.x50_um)
    return below / total, 1.0 - below / total


def _edges(iv):
    """(left, right) [µm] of an interval's rectangle; a point mass gets a narrow
    band of ×/÷ POINT_HALF_WIDTH around its size."""
    if iv.upper_um > iv.lower_um:
        return iv.lower_um, iv.upper_um
    return iv.lower_um / POINT_HALF_WIDTH, iv.lower_um * POINT_HALF_WIDTH


def _rect(x0, x1, y0, y1):
    return [x0, x0, x1, x1, x0], [y0, y1, y1, y0, y0]


def _interval_labels(ivs):
    labels = []
    for iv in ivs:
        tag = {"below_range": " (extrapolated below range)",
               "above_range": " (extrapolated above range)",
               "point": " (single size)"}.get(iv.kind, "")
        rng = (f"{iv.lower_um:.3g} µm" if iv.upper_um == iv.lower_um
               else f"{iv.lower_um:.3g} – {iv.upper_um:.3g} µm")
        labels.append(f"{rng}{tag}")
    return labels


def build_figure(result):
    sizes = size_grid(result)
    lo, hi = size_range(result)
    x_range = [math.log10(lo), math.log10(hi)]
    cls = [100.0 * e for e in result.classification_grade_efficiency(sizes)]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
        vertical_spacing=0.06, specs=[[{"secondary_y": True}], [{}]],
    )

    shown = set()  # legend groups that already have their legend entry

    def add(name, row, secondary_y=None, **kw):
        """Add a trace in legend group ``name``; only the first one is listed."""
        kw.setdefault("hoverlabel", dict(namelength=0))
        fig.add_trace(go.Scatter(name=name, legendgroup=name, showlegend=name not in shown, **kw),
                      row=row, col=1, secondary_y=secondary_y)
        shown.add(name)

    def add_bar(name, colour, x0, x1, y0, y1, label, row, secondary_y=None):
        xs, ys = _rect(x0, x1, y0, y1)
        add(name, row, secondary_y, x=xs, y=ys, mode="lines", fill="toself",
            fillcolor=colour, line=dict(color="white", width=0.5),
            hoveron="fills", hoverinfo="text", text=label)

    ivs = result.psd_intervals
    shares = emission_shares(result) if ivs else None
    labels = _interval_labels(ivs)
    for i, iv in enumerate(ivs):
        x0, x1 = _edges(iv)
        feed = 100.0 * iv.feed_fraction
        col = 100.0 * iv.collected_fraction
        emi = 100.0 * iv.emitted_fraction
        base = f"{labels[i]}<br>feed {feed:.2f} %"
        add_bar(NAME_COLLECTED, COLLECTED, x0, x1, 0.0, col,
                f"{base}<br>collected {col:.4g} % of feed", 1, False)
        add_bar(NAME_EMITTED, EMITTED, x0, x1, col, col + emi,
                f"{base}<br>emitted {emi:.3g} % of feed", 1, False)
        if shares is not None and shares[i] > 0:
            add_bar(NAME_SHARE, EMISSION_SHARE, x0, x1, 0.0, 100.0 * shares[i],
                    f"{labels[i]}<br>{100.0 * shares[i]:.1f} % of emission", 2)

    # Extrapolated intervals: dashed outline + hatch drawn over the solid bars.
    # If the hatch fails to render, the bar and outline are still there.
    for i, iv in enumerate(ivs):
        if not iv.is_extrapolated:
            continue
        x0, x1 = _edges(iv)
        tops = [(1, False, 100.0 * iv.feed_fraction)]
        if shares is not None and shares[i] > 0:
            tops.append((2, None, 100.0 * shares[i]))
        for row, sec, top in tops:
            xs, ys = _rect(x0, x1, 0.0, top)
            add(NAME_EXTRAP, row, sec, x=xs, y=ys, mode="lines", fill="toself",
                fillcolor="rgba(0,0,0,0)",
                fillpattern=dict(shape="/", fgcolor="white", bgcolor="rgba(0,0,0,0)",
                                 solidity=0.25),
                line=dict(color=EXTRAPOLATED, width=1.2, dash="dash"),
                hoverinfo="skip")

    if ivs and shares is None:
        fig.add_annotation(text="No emission", showarrow=False,
                           xref="x2 domain", yref="y3 domain", x=0.5, y=0.5)

    add(NAME_CLS, 1, True, x=sizes, y=cls, mode="lines",
        line=dict(color=CURVE, width=2.5),
        hovertemplate="%{x:.3g} µm<br>η = %{y:.1f} %<extra></extra>")
    if result.saltation:
        total = [100.0 * e for e in result.total_grade_efficiency(sizes)]
        add(NAME_TOTAL, 1, True, x=sizes, y=total, mode="lines",
            line=dict(color=TOTAL_CURVE, width=2.5, dash="dash"),
            hovertemplate="%{x:.3g} µm<br>η total = %{y:.1f} %<extra></extra>")

    # x50 as a trace (not a shape) so it has a legend entry; one per row.
    share_top = 100.0 * max(shares) * 1.08 if shares else 1.0
    x50 = result.x50_um
    x50_hover = f"x50 = {x50:.3g} µm<extra></extra>"
    add(NAME_X50, 1, True, x=[x50, x50], y=[0.0, 105.0], mode="lines", line=X50_LINE,
        hovertemplate=x50_hover)
    add(NAME_X50, 2, None, x=[x50, x50], y=[0.0, share_top], mode="lines", line=X50_LINE,
        hovertemplate=x50_hover)
    # Explicit annotation: on a log axis Plotly expects log10(x) here.
    fig.add_annotation(x=math.log10(x50), xref="x", y=1.0, yref="y domain",
                       text=f"x50 = {x50:.3g} µm", showarrow=False,
                       xanchor="right", yanchor="top", bgcolor="rgba(255,255,255,0.7)")

    fig.update_xaxes(type="log", range=x_range, showgrid=True)
    fig.update_xaxes(title_text="Particle size [µm]", row=2, col=1)
    # Curves sit on the overlaying (secondary) axis so they draw above the
    # bars; the axes are swapped to keep efficiency on the left.
    fig.update_yaxes(title_text="Grade efficiency [%]", range=[0, 105], side="left",
                     row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Share of total feed [%]", rangemode="tozero", showgrid=False,
                     side="right", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Share of emission [%]", range=[0, share_top], row=2, col=1)
    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="closest",
    )
    return fig
