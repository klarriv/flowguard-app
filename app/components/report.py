"""
report.py
=========
PDF report generation for NFPA 68 Ch.8 dust vent calculations.
Renders an HTML template with WeasyPrint.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional
import base64
import html as html_lib

try:
    from weasyprint import HTML as WP_HTML
    WEASYPRINT_OK = True
except ImportError:
    WEASYPRINT_OK = False

# ── Colour palette ─────────────────────────────────────────────────────────────
P = {
    "primary":    "#1B2A3B",
    "accent":     "#C8392B",
    "accent_lt":  "#F2D7D5",
    "rule":       "#D0D5DD",
    "pass":       "#1A7A4A",
    "fail":       "#C8392B",
    "bg_alt":     "#F7F8FA",
    "text":       "#1B2A3B",
    "muted":      "#6B7280",
}


def _logo_b64(logo_path: Optional[str]) -> Optional[str]:
    if logo_path and Path(logo_path).exists():
        with open(logo_path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        ext = Path(logo_path).suffix.lstrip(".")
        return f"data:image/{ext};base64,{data}"
    return None


def _fmt(v, dec=4) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:.{dec}f}"
    return str(v)


def _row(label: str, value: str, ref: str = "", alt: bool = False, highlight: bool = False) -> str:
    bg = P["accent_lt"] if highlight else (P["bg_alt"] if alt else "#fff")
    fw = "700" if highlight else "400"
    return (
        f'<tr style="background:{bg}">'
        f'<td style="padding:6px 10px;font-weight:{fw};width:38%">{label}</td>'
        f'<td style="padding:6px 10px;font-weight:{fw};font-family:monospace">{value}</td>'
        f'<td style="padding:6px 10px;color:{P["muted"]};font-size:0.82em">{ref}</td>'
        f'</tr>'
    )


def _chain_row(label: str, value: str, detail: str, ref: str,
                alt: bool = False, highlight: bool = False, danger: bool = False) -> str:
    """Row for the Calculation Chain table — like _row() but with a 4th
    "Correction Details" column, and a `danger` state (DDT failure) distinct
    from the plain `highlight` state (final-row emphasis)."""
    if danger:
        bg, border, fw = "#F5C6C2", f"border-left:4px solid {P['fail']};", "700"
    elif highlight:
        bg, border, fw = P["accent_lt"], "", "700"
    else:
        bg, border, fw = (P["bg_alt"] if alt else "#fff"), "", "400"
    return (
        f'<tr style="background:{bg};{border}">'
        f'<td style="padding:6px 10px;font-weight:{fw};width:28%">{label}</td>'
        f'<td style="padding:6px 10px;font-weight:{fw};font-family:monospace;width:12%">{value}</td>'
        f'<td style="padding:6px 10px;font-size:0.85em;width:35%">{detail}</td>'
        f'<td style="padding:6px 10px;color:{P["muted"]};font-size:0.82em;width:25%">{ref}</td>'
        f'</tr>'
    )


def _subhead(text: str) -> str:
    return (
        f'<tr><td colspan="3" style="font-weight:700;background:{P["primary"]};'
        f'color:#fff;padding:5px 10px">{text}</td></tr>'
    )


_SHAPE_LABELS = {
    "cuboid":                 "Rectangular Box",
    "cylinder":               "Cylinder",
    "truncated_cone":         "Truncated Cone (Conical Hopper)",
    "truncated_rect_pyramid": "Truncated Rectangular Pyramid (Hopper)",
}

_CROSS_SECTION_LABELS = {"circular": "Circular", "square": "Square", "rectangular": "Rectangular"}


def _seg_dims(seg: dict) -> str:
    t = seg.get("type")
    if t == "cuboid":
        return f"a={_fmt(seg.get('a'), 3)} m, b={_fmt(seg.get('b'), 3)} m, h={_fmt(seg.get('h'), 3)} m"
    if t == "cylinder":
        return f"r={_fmt(seg.get('r'), 3)} m, h={_fmt(seg.get('h'), 3)} m"
    if t == "truncated_cone":
        return f"R={_fmt(seg.get('R'), 3)} m, r={_fmt(seg.get('r'), 3)} m, h={_fmt(seg.get('h'), 3)} m"
    if t == "truncated_rect_pyramid":
        return (f"A={_fmt(seg.get('A'), 3)} m, B={_fmt(seg.get('B'), 3)} m, "
                f"a={_fmt(seg.get('a'), 3)} m, b={_fmt(seg.get('b'), 3)} m, h={_fmt(seg.get('h'), 3)} m")
    return "—"


def _build_html(run: dict, logo_path: Optional[str] = None) -> str:
    """Build the HTML string for the calculation report."""
    meta  = run.get("meta", {})
    inp   = run.get("inputs", {})
    out   = run.get("outputs", {})
    enc   = inp.get("enclosure", {})
    dust  = inp.get("dust", {})
    vent  = inp.get("vent", {})
    duct  = inp.get("duct")
    sel   = inp.get("selection")
    geo   = inp.get("geometry")

    # Section numbers are computed rather than hardcoded so the optional
    # sections (Geometry, Vent Panel Selection, Comments) don't leave a gap in
    # the numbering when omitted (e.g. Manual Input has no geometry). This list
    # mirrors the actual section order the sections are spliced into below, so
    # the numbering can't drift out of sync with where a section is rendered.
    has_selection = bool(sel and sel.get("model"))
    has_comments  = bool(meta.get("comments"))
    section_order = [
        ("geometry",   bool(geo)),
        ("input",      True),
        ("chain",      True),
        ("selection",  has_selection),
        ("comments",   has_comments),
    ]
    section_num = {}
    _n = 0
    for _key, _present in section_order:
        if _present:
            _n += 1
            section_num[_key] = _n
    geom_num       = section_num.get("geometry")
    input_num      = section_num["input"]
    chain_num      = section_num["chain"]
    selection_num  = section_num.get("selection")
    comments_num   = section_num.get("comments")

    ts     = meta.get("timestamp", datetime.now().isoformat())
    ts_fmt = datetime.fromisoformat(ts).strftime("%B %d, %Y  %H:%M")
    regime = out.get("pressure_regime", "NEAR_ATMOSPHERIC").replace("_", " ").title()
    turb   = out.get("turbulence_mode", "NONE").replace("_", " ").title()
    flex_filters_bump = bool(out.get("flexible_filters_bump_active"))
    av_final_caption = (
        "Final value after all applicable corrections, including the 25% "
        "flexible-filter obstruction increase · NFPA 68 (2023) §8.5, §8.7.2"
        if flex_filters_bump else
        "Final value after all applicable corrections · NFPA 68 (2023) §8.5"
    )

    logo_b64  = _logo_b64(logo_path)
    logo_html = (
        f'<img src="{logo_b64}" style="height:52px;object-fit:contain">'
        if logo_b64 else
        f'<span style="font-size:1.3em;font-weight:800;color:#fff">'
        f'{meta.get("project","")}</span>'
    )

    # ── Calculation chain rows — each row carries its own correction detail ────
    def _chain_detail(sym: str) -> str:
        if sym == "Av₀":
            if out.get("Peffective") is not None:
                return (f"{regime} · Peff={_fmt(out.get('Peffective'))} bar-g, "
                        f"PEmax={_fmt(out.get('PEmax'))} bar-g, Π={_fmt(out.get('Pi_effective'))}")
            return regime
        if sym == "Av₁":
            return "L/D: Active" if out.get("ld_correction_active") else "L/D: Not applied"
        if sym == "Av₂":
            mode = out.get("turbulence_mode", "NONE")
            if mode == "PROCESS":
                vtan_val = out.get("vtan")
                vtan_str = f"{_fmt(vtan_val, 2)} m/s" if vtan_val is not None else "n/a"
                return f"Process · vaxial={_fmt(out.get('vaxial'), 2)} m/s, vtan={vtan_str}"
            if mode == "BUILDING":
                return "Building (1.7×, §8.2.4.7)"
            return "None"
        if sym == "Av₃":
            state = "Active" if out.get("panel_inertia_active") else "Not applied"
            return f"Panel inertia: {state} (MT={_fmt(out.get('MT'), 3)} kg/m²)"
        if sym == "Av₄":
            if out.get("Xr") is None:
                return "—"
            state = "Active" if out.get("partial_volume_active") else "Not applied"
            return f"Partial volume: {state} (Xr={_fmt(out.get('Xr'))})"
        if sym == "Avf":
            if not out.get("duct_active"):
                return "No duct"
            base = f"E1={_fmt(out.get('E1'))}, E2={_fmt(out.get('E2'))}"
            if out.get("ddt_ok"):
                return f"{base} · DDT ✓"
            return f"{base} · <b>DDT ✗ FAILED</b> — Leff_max={_fmt(out.get('Leff_max'), 2)} m"
        if sym == "Av,final":
            return "Avf × 1.25"
        return ""

    ddt_failed = bool(out.get("duct_active")) and out.get("ddt_ok") is False

    chain_rows = ""
    steps = [
        ("Av₀", "Av0", "Minimum vent area",               "§8.2.1, Eq. 8.2.1.1"),
        ("Av₁", "Av1", "After L/D correction",            "§8.2.2, Eq. 8.2.2.3"),
        ("Av₂", "Av2", "After turbulence correction",     "§8.2.4"),
        ("Av₃", "Av3", "After panel inertia correction",  "§8.3, Eq. 8.3.4"),
        ("Av₄", "Av4", "After partial volume correction", "§8.4, Eq. 8.4.3"),
        ("Avf", "Avf", "Final vent area (with duct)",     "§8.5.1, Eq. 8.5.1a"),
    ]
    if flex_filters_bump:
        steps.append((
            "Av,final", "Av_final",
            "Flexible filter obstruction increase (+25%)", "§8.7.2",
        ))
    for i, (sym, key, desc, ref) in enumerate(steps):
        chain_rows += _chain_row(
            f"{sym} &nbsp;<span style='font-weight:400;color:{P['muted']}'>{desc}</span>",
            f"{_fmt(out.get(key))} m²",
            _chain_detail(sym),
            ref,
            alt=(i % 2 == 0),
            highlight=(key == ("Av_final" if flex_filters_bump else "Avf")),
            danger=(sym == "Avf" and ddt_failed),
        )

    # ── Optional duct section (physical geometry only — E1/E2/DDT now live in
    #    the Avf row's Correction Details cell above) ──────────────────────────
    duct_section = ""
    if duct and out.get("duct_active"):
        dr = (
            _row("Duct length Lduct",          f"{_fmt(duct.get('Lduct'), 2)} m",  "§8.5") +
            _row("Hydraulic diameter Dh",      f"{_fmt(duct.get('Dh'), 3)} m",     "§8.5", alt=True) +
            _row("Inlet coefficient Kinlet",   f"{_fmt(duct.get('Kinlet'), 2)} —", "Fig. A.8.5(a)") +
            _row("Elbow losses Kelbows",       f"{_fmt(duct.get('Kelbows'), 2)} —","Fig. A.8.5(b)", alt=True) +
            _row("Outlet coefficient Koutlet", f"{_fmt(duct.get('Koutlet'), 2)} —","Fig. A.8.5(a)")
        )
        duct_section = f"""
        <h3 style="margin-top:24px;margin-bottom:8px;color:{P['primary']};
                   font-size:0.9em;letter-spacing:0.06em;text-transform:uppercase">
            Vent Duct Parameters — §8.5
        </h3>
        <table style="width:100%;border-collapse:collapse;font-size:0.88em">{dr}</table>
        """

    # ── Optional enclosure geometry section (skipped for Manual Input) ────────
    geometry_section = ""
    if geo:
        mode = geo.get("mode", "—")
        if mode == "Donaldson":
            method_label = f"Donaldson — {geo.get('donaldson_family', '—')} · {geo.get('donaldson_model', '—')}"
        else:
            method_label = mode
        shape_label = _CROSS_SECTION_LABELS.get(geo.get("cross_section_family"), geo.get("cross_section_family", "—"))

        geo_summary_rows = (
            _row("Method",                 method_label,                    "") +
            _row("Volume V",               f"{_fmt(geo.get('V'), 2)} m³",   "", alt=True) +
            _row("Height L",               f"{_fmt(geo.get('L'), 2)} m",    "") +
            _row("Hydraulic diameter Dhe", f"{_fmt(geo.get('Dhe'), 2)} m",  "§6.4.3.6", alt=True) +
            _row("L/D",                    f"{_fmt(geo.get('LD'), 2)} —",   "§8.1.1") +
            _row("Cross-section shape",    shape_label,                     "", alt=True)
        )

        geo_seg_rows = ""
        for i, seg in enumerate(geo.get("segments", [])):
            copies = seg.get("cols", 1) * seg.get("rows", 1)
            copies_str = f" × {copies} copies" if copies > 1 else ""
            geo_seg_rows += _row(
                f"Segment {i + 1} — {_SHAPE_LABELS.get(seg.get('type'), seg.get('type'))}{copies_str}",
                _seg_dims(seg),
                f"V = {_fmt(seg.get('vol_si'), 4)} m³",
                alt=(i % 2 == 0),
            )

        geometry_section = f"""
        <h2>{geom_num} &middot; Enclosure Geometry</h2>
        <table>{geo_summary_rows}</table>
        <table style="margin-top:10px">{geo_seg_rows}</table>
        """

    # ── Optional vent panel selection section (final pick only) ───────────────
    selection_section = ""
    if sel and sel.get("model"):
        sr = (
            _row("Manufacturer",              sel.get("manufacturer", "—"), "") +
            _row("Model",                     sel.get("model", "—"),        "", alt=True) +
            _row("Panel type",                sel.get("panel_type", "—"),   "") +
            _row("Nominal (metric)",          sel.get("nominal_metric", "—"),   "", alt=True) +
            _row("Nominal (imperial)",        sel.get("nominal_imperial", "—"), "") +
            _row("Vent area",                 f"{_fmt(sel.get('vent_area_m2'), 4)} m²",        "", alt=True) +
            _row("Panel density",             f"{_fmt(sel.get('panel_density_kgm2'), 3)} kg/m²","") +
            _row("Efficiency",                f"{_fmt(sel.get('efficiency_pct'), 0)}%",         "", alt=True) +
            _row("Panels required",           f"{sel.get('panels_required', '—')} —",           "", highlight=True) +
            _row("Total effective vent area", f"{_fmt(sel.get('total_effective_area_m2'), 4)} m²", "", highlight=True)
        )
        selection_section = f"""
        <h2>{selection_num} &middot; Vent Panel Selection</h2>
        <table>{sr}</table>
        """

    # ── Optional comments section ──────────────────────────────────────────────
    comments_section = ""
    comments = meta.get("comments")
    if comments:
        comments_html = html_lib.escape(comments).replace("\n", "<br>")
        comments_section = f"""
        <h2>{comments_num} &middot; Comments</h2>
        <p style="font-size:0.88em;line-height:1.6;white-space:pre-wrap">{comments_html}</p>
        """

    # ── Full HTML document ────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 10pt;
    color: {P['text']};
    background: #fff;
    line-height: 1.55;
  }}
  @page {{
    size: Letter;
    margin: 18mm 18mm 22mm 18mm;
    @bottom-center {{
      content: "NFPA 68 (2023) — Deflagration Vent Sizing  |  Page " counter(page) " of " counter(pages);
      font-size: 7.5pt;
      color: {P['muted']};
    }}
  }}
  .cover-bar {{
    background: {P['primary']};
    color: #fff;
    padding: 20px 24px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .cover-bar .title {{ font-size:1.15em; font-weight:700; margin-top:8px; }}
  .badge {{
    background: {P['accent']};
    color: #fff;
    padding: 4px 12px;
    border-radius: 3px;
    font-size: 0.78em;
    font-weight: 600;
    letter-spacing: 0.05em;
  }}
  .meta-band {{
    background: {P['bg_alt']};
    border-bottom: 2px solid {P['rule']};
    padding: 10px 24px;
    display: flex;
    gap: 32px;
    flex-wrap: wrap;
  }}
  .meta-item .lbl {{ color:{P['muted']}; font-size:0.8em; display:block; margin-bottom:1px; }}
  .meta-item .val {{ font-weight:600; font-size:0.9em; }}
  .body {{ padding: 20px 24px; }}
  h2 {{
    font-size: 1em;
    font-weight: 700;
    color: {P['primary']};
    border-bottom: 2px solid {P['accent']};
    padding-bottom: 4px;
    margin: 22px 0 12px;
  }}
  table {{ width:100%; border-collapse:collapse; font-size:0.87em; }}
  td {{ padding:5px 10px; vertical-align:top; border-bottom:1px solid {P['rule']}; }}
  .result-box {{
    border: 2.5px solid {P['accent']};
    border-radius: 5px;
    padding: 14px 18px;
    background: {P['accent_lt']};
    margin: 18px 0 4px;
  }}
  .result-box .lbl {{ font-size:0.82em; color:{P['muted']}; }}
  .result-box .val {{
    font-size: 2em;
    font-weight: 700;
    color: {P['accent']};
    font-family: monospace;
    line-height: 1.1;
  }}
  .result-box .sub {{ font-size:0.78em; color:{P['muted']}; margin-top:3px; }}
  .two-col {{ display:flex; gap:24px; }}
  .two-col > div {{ flex:1; }}
</style>
</head>
<body>

<div class="cover-bar">
  <div>
    {logo_html}
    <div class="title">Deflagration Vent Sizing — Combustible Dusts</div>
  </div>
  <div style="text-align:right">
    <span class="badge">NFPA 68 · 2023</span>
    <div style="font-size:0.75em;margin-top:6px;opacity:0.7">Chapter 8 · §8.2 – §8.5</div>
  </div>
</div>

<div class="meta-band">
  <div class="meta-item"><span class="lbl">Project</span><span class="val">{meta.get('project','—')}</span></div>
  <div class="meta-item"><span class="lbl">Calculation</span><span class="val">{meta.get('label','—')}</span></div>
  <div class="meta-item"><span class="lbl">Engineer</span><span class="val">{meta.get('engineer','—')}</span></div>
  <div class="meta-item"><span class="lbl">Date</span><span class="val">{ts_fmt}</span></div>
</div>

<div class="body">

  <div class="result-box">
    <div class="lbl">MINIMUM REQUIRED VENT AREA</div>
    <div class="val">{_fmt(out.get('Av_final'), 4)} m²</div>
    <div class="sub">{av_final_caption}</div>
  </div>

  {geometry_section}

  <h2>{input_num} · Input Parameters</h2>
  <div class="two-col">
    <div>
      <table>
        {_subhead("Enclosure — §8.1.1")}
        {_row("Volume V",            f"{_fmt(enc.get('V'),2)} m³",     "§8.2.1")}
        {_row("L/D ratio",           f"{_fmt(enc.get('LD'),2)} —",     "§8.1.1", alt=True)}
        {_row("Solid volume Vsolid", f"{_fmt(enc.get('Vsolid'),2)} m³","§8.4.1")}
      </table>
      <table style="margin-top:10px">
        {_subhead("Vent Panel — §8.3")}
        {_row("Reduced pressure Pred", f"{_fmt(vent.get('Pred'),3)} bar-g",  "§8.2.1")}
        {_row("Static burst Pstat",    f"{_fmt(vent.get('Pstat'),3)} bar-g", "§8.2.1", alt=True)}
        {_row("Number of panels n",    f"{vent.get('n','—')} —",             "§8.3.2")}
        {_row("Areal mass M",          f"{_fmt(vent.get('M'),2)} kg/m²",     "§8.3", alt=True)}
        {_row("Shape factor Fsh",      f"{_fmt(vent.get('Fsh'),2)} —",       "§8.3.4")}
      </table>
    </div>
    <div>
      <table>
        {_subhead("Dust Characteristics — §8.1.2")}
        {_row("Deflagration index KSt", f"{_fmt(dust.get('KSt'),1)} bar·m/s","§8.1.2")}
        {_row("Maximum pressure Pmax",  f"{_fmt(dust.get('Pmax'),2)} bar-g", "§8.2.1", alt=True)}
        {_row("Initial pressure Pi",    f"{_fmt(dust.get('Pinitial'),3)} bar-g","§8.2.1")}
        {_row("Pressure regime",        regime,                                 "§8.2.1", alt=True)}
      </table>
      <table style="margin-top:10px">
        {_subhead("Turbulence — §8.2.4")}
        {_row("Mode",                 turb,                                                                              "§8.2.4")}
        {_row("Axial velocity vaxial",f"{_fmt(out.get('vaxial'),2)} m/s" if out.get('vaxial') is not None else "—",     "§8.2.4.1", alt=True)}
        {_row("Tangential vel. vtan", f"{_fmt(out.get('vtan'),2)} m/s"   if out.get('vtan')   is not None else "—",     "§8.2.4.2")}
      </table>
    </div>
  </div>

  <h2>{chain_num} · Calculation Chain</h2>
  <table>{chain_rows}</table>
  {duct_section}

  {selection_section}

  {comments_section}

</div>
</body>
</html>"""

    return html


def generate_pdf_bytes(run: dict, logo_path: Optional[str] = None) -> bytes:
    """Generate a PDF report and return it as bytes (no file written)."""
    if not WEASYPRINT_OK:
        raise RuntimeError("WeasyPrint is not installed. Run: pip install weasyprint")
    html = _build_html(run, logo_path)
    return WP_HTML(string=html).write_pdf()


def generate_pdf(run: dict, pdf_path: Path, logo_path: Optional[str] = None) -> Path:
    """Generate a PDF report and write it to pdf_path."""
    if not WEASYPRINT_OK:
        raise RuntimeError("WeasyPrint is not installed. Run: pip install weasyprint")
    html = _build_html(run, logo_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    WP_HTML(string=html).write_pdf(str(pdf_path))
    return pdf_path
