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
    "primary":    "#070E5E",   # template navy (headings, table headers)
    "accent":     "#FF6F38",   # template orange (minor sub-heads, footer rule)
    "accent_lt":  "#FFE9DF",
    "rule":       "#DDDDDD",
    "pass":       "#1A7A4A",
    "fail":       "#C8392B",
    "bg_alt":     "#E8EAF6",   # Brand Table banding
    "text":       "#333333",
    "muted":      "#777777",
    "footer":     "#AAAAAA",
}

FOOTER_TEXT = "Capt-Air \u2022 Confidential"
EXPORT_TITLE = "NFPA 68 Dust Vent Calculation"
_FORBIDDEN_FILENAME_CHARS = set('/\\:*?"<>|')


def _safe_filename_part(text) -> str:
    """Replace characters forbidden in file names with '_' (1:1, runs kept)."""
    out = "".join(
        "_" if (c in _FORBIDDEN_FILENAME_CHARS or ord(c) < 32) else c
        for c in str(text or "")
    )
    return out.strip().strip(".").strip()


def export_basename(meta: dict) -> str:
    """'[date] - [project] - [calc label] - NFPA 68 Dust Vent Calculation'.
    Date is the export date (meta.timestamp is stamped when the payload is built)."""
    try:
        date = datetime.fromisoformat(meta.get("timestamp", "")).strftime("%Y-%m-%d")
    except ValueError:
        date = datetime.now().strftime("%Y-%m-%d")
    project = _safe_filename_part(meta.get("project")) or "NoProject"
    label = _safe_filename_part(meta.get("label")) or "calculation"
    return f"{date} - {project} - {label} - {EXPORT_TITLE}"


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
        f'<td style="font-weight:700;color:{P["primary"]};width:38%">{label}</td>'
        f'<td style="font-weight:{fw};font-family:monospace;width:42%">{value}</td>'
        f'<td style="color:{P["muted"]};font-size:0.85em;width:20%">{ref}</td>'
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
        f'<td style="font-weight:700;color:{P["primary"]};width:28%">{label}</td>'
        f'<td style="font-weight:{fw};font-family:monospace;width:12%">{value}</td>'
        f'<td style="font-size:0.85em;width:35%">{detail}</td>'
        f'<td style="color:{P["muted"]};font-size:0.85em;width:25%">{ref}</td>'
        f'</tr>'
    )


def _subhead(text: str) -> str:
    return (
        f'<tr><td colspan="3" style="font-weight:700;background:{P["primary"]};'
        f'color:#fff">{text}</td></tr>'
    )


def _table(title: str, rows: str) -> str:
    """Titled input sub-table (template Heading 2 style), kept on one page."""
    return f'<div class="sub"><h3>{title}</h3><table>{rows}</table></div>'


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
    # sections (Geometry, Vent Panel Selection) don't leave a gap in
    # the numbering when omitted (e.g. Manual Input has no geometry). This list
    # mirrors the actual section order the sections are spliced into below, so
    # the numbering can't drift out of sync with where a section is rendered.
    has_selection = bool(sel and sel.get("model"))
    section_order = [
        ("geometry",   bool(geo)),
        ("input",      True),
        ("chain",      True),
        ("selection",  has_selection),
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
        f'<img src="{logo_b64}" style="height:44px;object-fit:contain">'
        if logo_b64 else
        f'<span style="font-size:1.3em;font-weight:800;color:{P["primary"]}">'
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
        duct_section = _table("Vent Duct — §8.5", dr)

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
        <div class="sub"><table>{geo_summary_rows}</table></div>
        <div class="sub"><table>{geo_seg_rows}</table></div>
        """

    # ── Optional vent panel selection section (final pick only) ───────────────
    selection_section = ""
    if sel and sel.get("model"):
        sr = (
            _row("Manufacturer",              sel.get("manufacturer", "—"), "") +
            _row("Model",                     sel.get("model", "—"),        "", alt=True) +
            _row("Rated vacuum (§100mbar)",   f"{_fmt(sel.get('rated_vacuum_mbar'), 0)} mbar" if sel.get("rated_vacuum_mbar") is not None else "—", "") +
            _row("Panel type",                sel.get("panel_type", "—"),   "", alt=True) +
            _row("Nominal (metric)",          sel.get("nominal_metric", "—"),   "") +
            _row("Nominal (imperial)",        sel.get("nominal_imperial", "—"), "", alt=True) +
            _row("Exterior (metric)",         sel.get("exterior_metric", "—"),   "") +
            _row("Exterior (imperial)",       sel.get("exterior_imperial", "—"), "", alt=True) +
            _row("Vent area",                 f"{_fmt(sel.get('vent_area_m2'), 4)} m²",        "") +
            _row("Panel density",             f"{_fmt(sel.get('panel_density_kgm2'), 3)} kg/m²","", alt=True) +
            _row("Efficiency",                f"{_fmt(sel.get('efficiency_pct'), 0)}%",         "") +
            _row("Panels required",           f"{sel.get('panels_required', '—')} —",           "", highlight=True) +
            _row("Total effective vent area", f"{_fmt(sel.get('total_effective_area_m2'), 4)} m²", "", highlight=True)
        )
        selection_section = f"""
        <h2>{selection_num} &middot; Vent Panel Selection</h2>
        <div class="sub"><table>{sr}</table></div>
        """

    # ── Comments (shown in the top meta band, next to the seal box) ───────────
    comments = meta.get("comments")
    comments_html = ""
    if comments:
        comments_html = (
            '<div class="meta-item" style="margin-top:6px"><span class="lbl">Comments</span>'
            f'<span class="val" style="font-weight:400;white-space:pre-wrap">'
            f'{html_lib.escape(comments)}</span></div>'
        )

    # ── Input sub-tables — same grouping and contents as the calc page ────────
    def _striped(rows) -> str:
        """Render (label, value, ref) tuples with alternating banding."""
        return "".join(_row(l, v, r, alt=(i % 2 == 1)) for i, (l, v, r) in enumerate(rows))

    def _unit(v, dec, unit):
        return f"{_fmt(v, dec)} {unit}" if v is not None else "—"

    calc_variant = str(inp.get("calc_variant") or "Standard enclosure")
    is_collector = "collector" in calc_variant.lower()
    enc_rows = [("Enclosure type", html_lib.escape(calc_variant), "§8.7" if is_collector else "§8.1.1")]
    if is_collector:
        enc_rows.append(("Flexible filters above vent, no restraints",
                         _fmt(bool(inp.get("flexible_filters"))), "§8.7.2"))
    enc_rows += [
        ("Volume V",              _unit(enc.get("V"), 2, "m³"),               "§8.2.1"),
        ("L/D ratio",             _unit(enc.get("LD"), 2, "—"),               "§8.1.1"),
        ("Solid volume Vsolid",   _unit(enc.get("Vsolid"), 2, "m³"),          "§8.4.1"),
        ("Reduced pressure Pred", _unit(vent.get("Pred"), 3, "bar-g"),        "§8.2.1"),
        ("Initial pressure Pi",   _unit(dust.get("Pinitial"), 3, "bar-g"),    "§8.2.1"),
        ("Pressure regime",       regime,                                     "§8.2.1"),
    ]
    if out.get("pressure_regime") == "SUBATMOSPHERIC":
        simplified = inp.get("subatm_method") == "SIMPLIFIED"
        enc_rows.append(("Subatmospheric method",
                         "Simplified" if simplified else "General",
                         "Eq. 8.2.1.2.2" if simplified else "Eq. 8.2.1.2"))
    enclosure_section = _table("Enclosure — §8.1.1", _striped(enc_rows))

    dust_section = _table("Dust Characteristics — §8.1.2", _striped([
        ("Deflagration index KSt", _unit(dust.get("KSt"), 1, "bar·m/s"), "§8.1.2"),
        ("Maximum pressure Pmax",  _unit(dust.get("Pmax"), 2, "bar-g"),  "§8.2.1"),
    ]))

    turb_rows = [("Mode", turb, "§8.2.4")]
    ti = inp.get("turb_inputs") or {}
    if out.get("turbulence_mode") == "PROCESS" and ti:
        turb_rows += [
            ("Flow rate Q",             _unit(ti.get("Q"), 3, "m³/s"), "§8.2.4.1"),
            ("Cross-sectional area A",  _unit(ti.get("A"), 3, "m²"),   "§8.2.4.1"),
        ]
        if ti.get("Ain") is not None:
            turb_rows.append(("Tangential inlet area Ain", _unit(ti.get("Ain"), 3, "m²"), "§8.2.4.2"))
    turb_rows += [
        ("Axial velocity vaxial", _unit(out.get("vaxial"), 2, "m/s"), "§8.2.4.1"),
        ("Tangential vel. vtan",  _unit(out.get("vtan"), 2, "m/s"),   "§8.2.4.2"),
    ]
    turb_section = _table("Turbulence — §8.2.4", _striped(turb_rows))

    vent_section = _table("Vent Panel — §8.3", _striped([
        ("Static burst Pstat", _unit(vent.get("Pstat"), 3, "bar-g"), "§8.2.1"),
        ("Number of panels n", f"{vent.get('n', '—')} —",             "§8.3.2"),
        ("Areal mass M",       _unit(vent.get("M"), 2, "kg/m²"),      "§8.3"),
        ("Shape factor Fsh",   _unit(vent.get("Fsh"), 2, "—"),        "§8.3.4"),
    ]))

    pv_section = ""
    if out.get("Xr") is not None:
        pv = inp.get("partial_volume") or {}
        pv_rows = [("Active", _fmt(bool(out.get("partial_volume_active"))), "§8.4")]
        if pv.get("use_building"):
            pv_rows += [
                ("Method",                   "Building",                            "§8.4.5"),
                ("Avg floor mass",           _unit(pv.get("Mf_bar"), 1, "g"),       "§8.4.5"),
                ("Dusty floor area",         _unit(pv.get("Af_dusty"), 2, "m²"),    "§8.4.5"),
                ("Floor entrainment ηD",     _unit(pv.get("eta_Dfloor"), 2, "—"),   "§8.4.5"),
                ("Floor sample area",        _unit(pv.get("Afs"), 4, "m²"),         "§8.4.5"),
                ("Avg surface mass",         _unit(pv.get("Ms_bar"), 1, "g"),       "§8.4.5"),
                ("Total surface area",       _unit(pv.get("Asur"), 2, "m²"),        "§8.4.5"),
                ("Surface entrainment ηD",   _unit(pv.get("eta_Dsur"), 2, "—"),     "§8.4.5"),
                ("Surface sample area",      _unit(pv.get("Ass"), 4, "m²"),         "§8.4.5"),
                ("Equipment dust Me",        _unit(pv.get("Me_equipment"), 1, "g"), "§8.4.5"),
                ("Worst-case conc. cw",      _unit(pv.get("cw"), 1, "g/m³"),        "§8.4.2.2"),
            ]
        elif pv:
            pv_rows += [
                ("Method",              "Process enclosure",            "§8.4.1"),
                ("Suspended dust Me",   _unit(pv.get("Me"), 1, "g"),    "§8.4.1"),
                ("Worst-case conc. cw", _unit(pv.get("cw"), 1, "g/m³"), "§8.4.2.2"),
            ]
        pv_rows.append(("Reduction factor Xr", f"{_fmt(out.get('Xr'))} —", "§8.4.3"))
        pv_section = _table("Partial Volume — §8.4", _striped(pv_rows))

    # ── Full HTML document ────────────────────────────────────────────────────
    # Styling follows docs_for_claude_code/2026-06-16 Template Document Capt-Air.dotx
    # (Arial, navy/orange, "Brand Table", orange footer rule, 12.7/15.9 mm margins).
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11pt;
    color: {P['text']};
    background: #fff;
    line-height: 1.1;
  }}
  @page {{
    size: Letter;
    margin: 12.7mm 15.9mm 16mm 15.9mm;
    @bottom-left {{
      content: "{FOOTER_TEXT}";
      font-family: Arial, Helvetica, sans-serif;
      font-size: 8pt;
      color: {P['footer']};
      border-top: 1pt solid {P['accent']};
      padding-top: 2mm;
      width: 100%;
    }}
    @bottom-right {{
      content: "Page " counter(page) " of " counter(pages);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 8pt;
      color: {P['footer']};
      border-top: 1pt solid {P['accent']};
      padding-top: 2mm;
      width: 100%;
      text-align: right;
    }}
  }}
  .header {{ width:100%; border-collapse:collapse; margin-bottom:6pt; table-layout:auto; }}
  .header td {{ border:none; padding:0; vertical-align:middle; }}
  .header .title {{ font-size:15pt; font-weight:700; color:{P['primary']}; }}
  .header .sub-title {{ font-size:9pt; color:{P['accent']}; font-weight:700; margin-top:2pt; }}
  .meta-band {{
    display: flex;
    justify-content: space-between;
    gap: 16pt;
    border-top: 1pt solid #AAAAAA;
    border-bottom: 1pt solid #AAAAAA;
    padding: 6pt 0;
    margin-bottom: 8pt;
    break-inside: avoid;
  }}
  .meta-left {{ flex: 1; }}
  .meta-item {{ margin-bottom: 3pt; }}
  .meta-item .lbl {{ color:{P['primary']}; font-size:8pt; font-weight:700; display:block; }}
  .meta-item .val {{ font-size:10pt; }}
  .seal {{
    width: 40mm; height: 40mm; flex: none;
    border: 1pt solid {P['primary']};
    position: relative;
  }}
  .seal .cap {{
    position:absolute; top:2mm; left:3mm; font-size:7.5pt; font-weight:700; color:{P['primary']};
  }}
  h2 {{
    font-size: 13pt;
    font-weight: 700;
    color: {P['primary']};
    border-bottom: 1pt solid #AAAAAA;
    padding-bottom: 2pt;
    margin: 13pt 0 6pt;
    break-after: avoid;
  }}
  h3 {{
    font-size: 11pt;
    font-weight: 700;
    color: {P['primary']};
    margin: 10pt 0 4pt;
    break-after: avoid;
  }}
  .sub {{ break-inside: avoid; margin-bottom: 6pt; }}
  table {{ width:100%; border-collapse:collapse; font-size:9pt; table-layout:fixed; }}
  td {{ padding:3pt 5.5pt; vertical-align:top; border:0.25pt solid {P['rule']}; }}
  .result-box {{
    border: 1.5pt solid {P['accent']};
    padding: 8pt 12pt;
    background: {P['accent_lt']};
    margin: 0 0 4pt;
    break-inside: avoid;
  }}
  .result-box .lbl {{ font-size:9pt; font-weight:700; color:{P['primary']}; }}
  .result-box .val {{
    font-size: 20pt;
    font-weight: 700;
    color: {P['primary']};
    font-family: monospace;
    line-height: 1.1;
  }}
  .result-box .sub-cap {{ font-size:8pt; color:{P['muted']}; margin-top:2pt; }}
</style>
</head>
<body>

<table class="header"><tr>
  <td>{logo_html}</td>
  <td style="text-align:right">
    <div class="title">Deflagration Vent Sizing<br>Combustible Dusts</div>
    <div class="sub-title">NFPA 68 &middot; 2023 &middot; Chapter 8 &middot; &sect;8.2 &ndash; &sect;8.5</div>
  </td>
</tr></table>

<div class="meta-band">
  <div class="meta-left">
    <div class="meta-item"><span class="lbl">Project</span><span class="val">{html_lib.escape(str(meta.get('project','—')))}</span></div>
    <div class="meta-item"><span class="lbl">Calculation</span><span class="val">{html_lib.escape(str(meta.get('label','—')))}</span></div>
    <div class="meta-item"><span class="lbl">Engineer</span><span class="val">{html_lib.escape(str(meta.get('engineer','—')))}</span></div>
    <div class="meta-item"><span class="lbl">Date</span><span class="val">{ts_fmt}</span></div>
    {comments_html}
  </div>
  <div class="seal">
    <div class="cap">Engineer&rsquo;s seal / stamp</div>  </div>
</div>

<div class="result-box">
  <div class="lbl">MINIMUM REQUIRED VENT AREA</div>
  <div class="val">{_fmt(out.get('Av_final'), 4)} m²</div>
  <div class="sub-cap">{av_final_caption}</div>
</div>

{geometry_section}

<h2>{input_num} &middot; Input Parameters</h2>
{enclosure_section}
{dust_section}
{turb_section}
{vent_section}
{pv_section}
{duct_section}

<h2>{chain_num} &middot; Calculation Chain</h2>
<table>{chain_rows}</table>

{selection_section}

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
