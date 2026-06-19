"""
serializer.py
=============
Round-trip conversion between NFPA 68 Ch.8 dataclasses and plain dicts
suitable for JSON storage and form pre-population.
"""

from typing import Any
from dataclasses import asdict


def _clean(v: Any) -> Any:
    """Recursively make a value JSON-serialisable."""
    if hasattr(v, "name"):                          # Enum
        return v.name
    if hasattr(v, "__dataclass_fields__"):          # dataclass
        return {k: _clean(val) for k, val in asdict(v).items()}
    if isinstance(v, dict):
        return {k: _clean(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(i) for i in v]
    return v


def inputs_to_dict(
    enclosure,
    dust,
    vent,
    duct=None,
    turbulence_mode=None,
    turb_inputs=None,
    partial_volume=None,
    subatm_method=None,
    flexible_filters: bool = False,
    calc_variant: str = "standard",
) -> dict:
    """Serialize all calculation inputs to a JSON-safe dict."""
    return {
        "calc_variant":     calc_variant,
        "enclosure":        _clean(enclosure),
        "dust":             _clean(dust),
        "vent":             _clean(vent),
        "duct":             _clean(duct) if duct else None,
        "turbulence_mode":  turbulence_mode.name if turbulence_mode else "NONE",
        "turb_inputs":      _clean(turb_inputs) if turb_inputs else None,
        "partial_volume":   _clean(partial_volume) if partial_volume else None,
        "subatm_method":    subatm_method.name if subatm_method else "GENERAL",
        "flexible_filters": flexible_filters,
    }


def result_to_dict(result) -> dict:
    """Serialize a DustVentResult to a JSON-safe dict."""
    return _clean(result)


def build_run_payload(
    project: str,
    label: str,
    engineer: str,
    inputs: dict,
    outputs: dict,
    calc_type: str = "dust_vent_nfpa68_ch8",
) -> dict:
    """Assemble the full run payload (meta + inputs + outputs)."""
    from datetime import datetime
    return {
        "meta": {
            "label":     label,
            "project":   project,
            "calc_type": calc_type,
            "standard":  "NFPA 68 (2023)",
            "engineer":  engineer,
            "timestamp": datetime.now().isoformat(),
        },
        "inputs":  inputs,
        "outputs": outputs,
    }
