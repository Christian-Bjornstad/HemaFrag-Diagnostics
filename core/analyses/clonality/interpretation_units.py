"""Stable assay/channel interpretation units for clonality review and ML."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.analyses.clonality.config import ASSAY_CONFIG
from core.analyses.clonality.trace_features import flatten_numeric_features


INTERPRETATION_UNIT_SCHEMA_VERSION = "clonality_interpretation_units_v1"
CHANNELS = ("DATA1", "DATA2", "DATA3")
CHANNEL_COLORS = {
    "DATA1": "#2563eb",
    "DATA2": "#16a34a",
    "DATA3": "#ea580c",
}


@dataclass(frozen=True)
class InterpretationUnit:
    unit_id: str
    assay: str
    channel: str
    target_name: str

    @property
    def label_column(self) -> str:
        return channel_label_column(self.channel)


_UNITS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "FR1": (("FR1_JH", "DATA1", "FR1-JH"),),
    "FR2": (("FR2_JH", "DATA1", "FR2-JH"),),
    "FR3": (("FR3_JH", "DATA2", "FR3-JH"),),
    "DHJHD": (("DHJHD_IGHJ", "DATA2", "IGHD-IGHJ"),),
    "DHJHE": (("DHJHE_IGHJ", "DATA1", "IGHD7-IGHJ"),),
    "IGK": (
        ("IGK_JK5", "DATA1", "Jk5"),
        ("IGK_JK1_4", "DATA2", "Jk1-4"),
    ),
    "KDE": (("KDE_KDE", "DATA3", "Kde"),),
    "TCRBA": (
        ("TCRBA_JB2", "DATA1", "Jb2.X"),
        ("TCRBA_JB1", "DATA2", "Jb1.X"),
    ),
    "TCRBB": (
        ("TCRBB_JB2", "DATA1", "Jb2.X"),
        ("TCRBB_JB1", "DATA2", "Jb1.X"),
    ),
    "TCRBC": (
        ("TCRBC_JB2", "DATA1", "Jb2.X"),
        ("TCRBC_JB1", "DATA2", "Jb1.X"),
    ),
    "TCRGA": (
        ("TCRGA_JG11_21", "DATA1", "Jg1.1/Jg2.1"),
        ("TCRGA_JG13_23", "DATA2", "Jg1.3/Jg2.3"),
    ),
    "TCRGB": (
        ("TCRGB_JG11_21", "DATA1", "Jg1.1/Jg2.1"),
        ("TCRGB_JG13_23", "DATA2", "Jg1.3/Jg2.3"),
    ),
}


def assay_key(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .upper()
    )


def interpretation_units_for_assay(assay: Any) -> tuple[InterpretationUnit, ...]:
    raw_assay = str(assay or "").strip()
    key = assay_key(raw_assay)
    configured = _UNITS.get(key)
    if configured is None:
        config = ASSAY_CONFIG.get(raw_assay) or next(
            (
                value
                for name, value in ASSAY_CONFIG.items()
                if assay_key(name) == key
            ),
            {},
        )
        channels = tuple(
            str(channel).strip().upper()
            for channel in config.get("trace_channels", ())
            if str(channel).strip().upper() in CHANNELS
        )
        configured = tuple(
            (
                f"{key}_{channel}",
                channel,
                channel,
            )
            for channel in channels
        )
    return tuple(
        InterpretationUnit(
            unit_id=unit_id,
            assay=raw_assay,
            channel=channel,
            target_name=target_name,
        )
        for unit_id, channel, target_name in configured
    )


def interpretation_unit_by_id(unit_id: Any) -> InterpretationUnit | None:
    wanted = str(unit_id or "").strip().upper()
    if not wanted:
        return None
    for assay in ASSAY_CONFIG:
        for unit in interpretation_units_for_assay(assay):
            if unit.unit_id.upper() == wanted:
                return unit
    return None


def channel_label_column(channel: Any) -> str:
    normalized = str(channel or "").strip().upper()
    if normalized not in CHANNELS:
        raise ValueError(f"Unsupported clonality trace channel: {channel!r}")
    return f"ClonalityChemistLabel_{normalized}"


CHANNEL_CHEMIST_LABEL_COLUMNS = tuple(
    channel_label_column(channel) for channel in CHANNELS
)


def channel_ml_column(metric: str, channel: Any) -> str:
    normalized = str(channel or "").strip().upper()
    if normalized not in CHANNELS:
        raise ValueError(f"Unsupported clonality trace channel: {channel!r}")
    return f"ClonalityML{str(metric).strip()}_{normalized}"


CHANNEL_ML_METRICS = (
    "Suggestion",
    "Confidence",
    "Threshold",
    "ReviewNeeded",
    "Evidence",
    "ModelVersion",
)
CHANNEL_ML_COLUMNS = tuple(
    channel_ml_column(metric, channel)
    for channel in CHANNELS
    for metric in CHANNEL_ML_METRICS
)


_COMBINED_MORPHOLOGY_PREFIXES = (
    "raw_peak_",
    "peak_count",
    "dominant_",
    "second_peak_",
    "total_peak_",
    "nonspecific_",
    "outside_interpretation_",
    "interpretation_range_",
    "dome_",
    "ref_window_",
    "in_reference_window",
    "dom_distance_",
)


def channel_local_numeric_features(
    features: Mapping[str, Any],
    channel: Any,
) -> dict[str, float]:
    """Project features to one channel without other-channel morphology."""
    normalized = str(channel or "").strip().upper()
    if normalized not in CHANNELS:
        raise ValueError(f"Unsupported clonality trace channel: {channel!r}")

    flat = flatten_numeric_features(features)
    selected_suffix = f".{normalized}"
    projected: dict[str, float] = {}
    for raw_name, value in flat.items():
        name = str(raw_name)
        upper = name.upper()
        channel_suffix = next(
            (f".{candidate}" for candidate in CHANNELS if upper.endswith(f".{candidate}")),
            "",
        )
        if channel_suffix:
            if channel_suffix != selected_suffix:
                continue
            projected[f"{name[:-len(channel_suffix)]}.SELECTED"] = float(value)
            continue
        lower = name.lower()
        if lower.startswith("trace_"):
            # Aggregate trace fields combine channels and would leak the
            # other channel's morphology into this target.
            continue
        if lower.startswith(_COMBINED_MORPHOLOGY_PREFIXES):
            continue
        projected[name] = float(value)
    return projected


def channel_labels_from_row(row: Mapping[str, Any], assay: Any) -> dict[str, str]:
    units = interpretation_units_for_assay(assay)
    labels = {
        unit.channel: _clean_label(row.get(unit.label_column))
        for unit in units
    }
    legacy = _clean_label(row.get("ClonalityChemistLabel"))
    if len(units) == 1 and legacy and not labels[units[0].channel]:
        labels[units[0].channel] = legacy
    return labels


def _clean_label(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


__all__ = [
    "CHANNELS",
    "CHANNEL_COLORS",
    "CHANNEL_CHEMIST_LABEL_COLUMNS",
    "CHANNEL_ML_COLUMNS",
    "CHANNEL_ML_METRICS",
    "INTERPRETATION_UNIT_SCHEMA_VERSION",
    "InterpretationUnit",
    "assay_key",
    "channel_label_column",
    "channel_labels_from_row",
    "channel_local_numeric_features",
    "channel_ml_column",
    "interpretation_unit_by_id",
    "interpretation_units_for_assay",
]
