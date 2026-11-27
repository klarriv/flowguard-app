"""Grade-efficiency chart for the Cyclone page (Plotly rendering only).

One figure, two rows sharing a log size axis [µm]:
  * top, left axis  - grade efficiency curve(s) from ``CycloneResult``; x50 marked
    (drawn above the bars)
  * top, right axis - the feed PSD as one bar per ``CycloneResult.psd_intervals``
    entry, stacked collected (dark) / emitted (light red), as % of total feed
  * bottom          - share of the emission per interval [%]: each interval's
    ``emitted_fraction`` normalised by their sum, so the emission makeup stays
    readable even when the emission is a tiny fraction of the feed

The size axis has an explicit range (see ``size_range``) instead of autorange,
which does not cope with data-unit bar widths on a log axis.

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

RANGE_PAD = 1.3  # x/÷ padding around the useful size range


def _bar_geometry(iv):
    """(centre, width) in data units so the bar edges land on lower/upper on a
    log axis (bars are positioned in data space, so centre = arithmetic mid)."""
    if iv.upper_um > iv.lower_um:
        return (iv.lower_um + iv.upper_um) / 2.0, iv.upper_um - iv.lower_um
    return iv.lower_um, iv.lower_um * 0.06  # point mass: narrow bar (~6 % of size)


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

    ivs = result.psd_intervals
    if ivs:
        centres, widths = zip(*(_bar_geometry(iv) for iv in ivs))
        hatch = ["/" if iv.is_extrapolated else "" for iv in ivs]
        labels = _interval_labels(ivs)
        for name, attr, colour in (
            ("Collected", "collected_fraction", COLLECTED),
            ("Emitted", "emitted_fraction", EMITTED),
        ):
            fig.add_trace(go.Bar(
                x=list(centres), width=list(widths),
                y=[100.0 * getattr(iv, attr) for iv in ivs],
                name=f"{name} (% of feed)",
                marker=dict(color=colour, pattern=dict(shape=hatch, fgcolor="white"),
                            line=dict(color="white", width=0.5)),
                customdata=[[lab, 100.0 * iv.feed_fraction] for lab, iv in zip(labels, ivs)],
                hovertemplate=("%{customdata[0]}<br>feed %{customdata[1]:.2f} %"
                               f"<br>{name.lower()} %{{y:.3g}} % of feed<extra></extra>"),
            ), row=1, col=1, secondary_y=False)

        shares = emission_shares(result)
        if shares is not None:
            fig.add_trace(go.Bar(
                x=list(centres), width=list(widths), y=[100.0 * s for s in shares],
                name="Share of emission",
                marker=dict(color=EMISSION_SHARE, pattern=dict(shape=hatch, fgcolor="white"),
                            line=dict(color="white", width=0.5)),
                customdata=labels,
                hovertemplate="%{customdata}<br>%{y:.1f} % of emission<extra></extra>",
            ), row=2, col=1)
        else:
            fig.add_annotation(text="No emission", showarrow=False,
                               xref="x2 domain", yref="y3 domain", x=0.5, y=0.5)

    fig.add_trace(go.Scatter(
        x=sizes, y=cls, mode="lines", name="Grade efficiency (classification)",
        line=dict(color=CURVE, width=2.5),
        hovertemplate="%{x:.3g} µm<br>η = %{y:.1f} %<extra></extra>"),
        row=1, col=1, secondary_y=True)
    if result.saltation:
        total = [100.0 * e for e in result.total_grade_efficiency(sizes)]
        fig.add_trace(go.Scatter(
            x=sizes, y=total, mode="lines", name="Grade efficiency (total, incl. saltation)",
            line=dict(color=TOTAL_CURVE, width=2.5, dash="dash"),
            hovertemplate="%{x:.3g} µm<br>η total = %{y:.1f} %<extra></extra>"),
            row=1, col=1, secondary_y=True)

    fig.add_vline(x=result.x50_um, line=X50_LINE, row=1, col=1)
    fig.add_vline(x=result.x50_um, line=X50_LINE, row=2, col=1)
    # Explicit annotation: on a log axis Plotly expects log10(x) here, and
    # add_vline's own annotation_text gets that wrong.
    fig.add_annotation(x=math.log10(result.x50_um), xref="x", y=1.0, yref="y domain",
                       text=f"x50 = {result.x50_um:.3g} µm", showarrow=False,
                       xanchor="right", yanchor="top", bgcolor="rgba(255,255,255,0.7)")

    fig.update_xaxes(type="log", range=x_range, showgrid=True)
    fig.update_xaxes(title_text="Particle size [µm]", row=2, col=1)
    # Curves sit on the overlaying (secondary) axis so they draw above the
    # bars; the axes are swapped to keep efficiency on the left.
    fig.update_yaxes(title_text="Grade efficiency [%]", range=[0, 105], side="left",
                     row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Share of total feed [%]", rangemode="tozero", showgrid=False,
                     side="right", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Share of emission [%]", rangemode="tozero", row=2, col=1)
    fig.update_layout(
        barmode="stack", height=620, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="closest",
    )
    return fig
