"""Grade-efficiency chart for the Cyclone page (Plotly rendering only).

One figure, log size axis [µm]:
  * left axis  - grade efficiency curve(s) from ``CycloneResult``; x50 marked
  * right axis - the feed PSD as one bar per ``CycloneResult.psd_intervals``
    entry, stacked collected (dark) / emitted (light red), as % of total feed.

All numbers come from the library; nothing is re-derived here except the
plotting grid and the percent scaling.
"""
import math

import plotly.graph_objects as go

COLLECTED = "#4C78A8"
EMITTED = "#F2A4A0"
CURVE = "#1F2937"
TOTAL_CURVE = "#D97706"


def _bar_geometry(iv):
    """(centre, width) in data units so the bar edges land on lower/upper on a
    log axis (bars are positioned in data space, so centre = arithmetic mid)."""
    if iv.upper_um > iv.lower_um:
        return (iv.lower_um + iv.upper_um) / 2.0, iv.upper_um - iv.lower_um
    return iv.lower_um, iv.lower_um * 0.06  # point mass: narrow bar (~6 % of size)


def size_grid(result, points=200):
    """Log-spaced sizes [µm]: 0.1 µm to 1.5 x the largest PSD size (and at
    least 5 x x50 so the whole S-curve is visible)."""
    top = max([iv.upper_um for iv in result.psd_intervals] + [5.0 * result.x50_um])
    lo, hi = math.log10(0.1), math.log10(1.5 * top)
    return [10 ** (lo + (hi - lo) * i / (points - 1)) for i in range(points)]


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


def build_figure(result):
    sizes = size_grid(result)
    cls = [100.0 * e for e in result.classification_grade_efficiency(sizes)]
    fig = go.Figure()

    ivs = result.psd_intervals
    if ivs:
        centres, widths = zip(*(_bar_geometry(iv) for iv in ivs))
        hatch = ["/" if iv.is_extrapolated else "" for iv in ivs]
        labels = []
        for iv in ivs:
            tag = {"below_range": " (extrapolated below range)",
                   "above_range": " (extrapolated above range)",
                   "point": " (single size)"}.get(iv.kind, "")
            rng = (f"{iv.lower_um:.3g} µm" if iv.upper_um == iv.lower_um
                   else f"{iv.lower_um:.3g} – {iv.upper_um:.3g} µm")
            labels.append(f"{rng}{tag}")
        for name, attr, colour in (
            ("Collected", "collected_fraction", COLLECTED),
            ("Emitted", "emitted_fraction", EMITTED),
        ):
            fig.add_trace(go.Bar(
                x=list(centres), width=list(widths),
                y=[100.0 * getattr(iv, attr) for iv in ivs],
                name=f"{name} (% of feed)", yaxis="y2",
                marker=dict(color=colour, pattern=dict(shape=hatch, fgcolor="white"),
                            line=dict(color="white", width=0.5)),
                customdata=[[lab, 100.0 * iv.feed_fraction] for lab, iv in zip(labels, ivs)],
                hovertemplate=("%{customdata[0]}<br>feed %{customdata[1]:.2f} %"
                               f"<br>{name.lower()} %{{y:.2f}} % of feed<extra></extra>"),
            ))

    fig.add_trace(go.Scatter(
        x=sizes, y=cls, mode="lines", name="Grade efficiency (classification)",
        line=dict(color=CURVE, width=2.5),
        hovertemplate="%{x:.3g} µm<br>η = %{y:.1f} %<extra></extra>"))
    if result.saltation:
        total = [100.0 * e for e in result.total_grade_efficiency(sizes)]
        fig.add_trace(go.Scatter(
            x=sizes, y=total, mode="lines", name="Grade efficiency (total, incl. saltation)",
            line=dict(color=TOTAL_CURVE, width=2.5, dash="dash"),
            hovertemplate="%{x:.3g} µm<br>η total = %{y:.1f} %<extra></extra>"))

    fig.add_vline(x=result.x50_um, line=dict(color="#6B7280", width=1.5, dash="dot"),
                  annotation_text=f"x50 = {result.x50_um:.3g} µm", annotation_position="top left")

    fig.update_layout(
        barmode="stack", height=460, margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(type="log", title="Particle size [µm]", showgrid=True),
        yaxis=dict(title="Grade efficiency [%]", range=[0, 105]),
        yaxis2=dict(title="Share of total feed [%]", overlaying="y", side="right",
                    rangemode="tozero", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="closest",
    )
    return fig
