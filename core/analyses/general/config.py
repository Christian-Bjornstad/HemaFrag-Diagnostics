"""General analysis configuration and runtime helpers."""
from __future__ import annotations

import hashlib
import json

from config import APP_SETTINGS
from core.assay_config import DEFAULT_LIZ_LADDER, DEFAULT_ROX_LADDER

GENERAL_ASSAY_NAME = "GENERAL"
LIZ_LADDER = DEFAULT_LIZ_LADDER
ROX_LADDER = DEFAULT_ROX_LADDER
ALLOWED_LADDERS = ("LIZ500_250", "ROX400HD", "GS500ROX")
ALLOWED_TRACE_CHANNELS = ("DATA1", "DATA2", "DATA3")
DEFAULT_TRACE_CHANNELS = ("DATA1",)
DEFAULT_BP_MIN = 50.0
DEFAULT_BP_MAX = 1000.0

ASSAY_CONFIG = {
    GENERAL_ASSAY_NAME: {
        "dye": "ROX",
        "trace_channels": list(ALLOWED_TRACE_CHANNELS),
        "peak_channels": list(ALLOWED_TRACE_CHANNELS),
        "bp_min": DEFAULT_BP_MIN,
        "bp_max": DEFAULT_BP_MAX,
    }
}
ASSAY_DISPLAY_ORDER = [GENERAL_ASSAY_NAME]
ASSAY_REFERENCE_RANGES: dict[str, list[tuple[float, float]]] = {}
ASSAY_REFERENCE_LABEL: dict[str, str] = {}
NONSPECIFIC_PEAKS: dict[str, list[float]] = {}
REFERENCE_SHADE_COLOR = "#ded7a6"
GENERAL_PROFILE_SCHEMA = "hemafrag_general_profile_v1"
GENERAL_PROFILE_REPORT_FIELDS = [
    "source_sha256",
    "profile",
    "ladder_qc",
    "trace_channels",
    "bp_range",
]
GENERAL_PROFILE_LADDER_STEPS = {
    "LIZ500_250": [
        35, 50, 75, 100, 139, 150, 160, 200,
        250, 300, 340, 350, 400, 450, 490, 500,
    ],
    "ROX400HD": [
        50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220,
        240, 260, 280, 290, 300, 320, 340, 360, 380, 400,
    ],
    "GS500ROX": [
        35, 50, 75, 100, 139, 150, 160, 200,
        250, 300, 340, 350, 400, 450, 490, 500,
    ],
}


def _general_profile(settings: dict | None = None) -> dict:
    settings = settings or APP_SETTINGS
    analyses = settings.get("analyses", {})
    profile = analyses.get("general", {})
    return profile if isinstance(profile, dict) else {}


def get_general_pipeline_settings(settings: dict | None = None) -> dict:
    profile = _general_profile(settings)
    pipeline = profile.get("pipeline", {})
    return pipeline if isinstance(pipeline, dict) else {}


def normalize_ladder_name(ladder_name: str | None) -> str:
    if not ladder_name:
        return ROX_LADDER
    cleaned = str(ladder_name).strip().upper().replace("-", "").replace(" ", "")
    mapping = {
        "LIZ500": LIZ_LADDER,
        "LIZ500_250": LIZ_LADDER,
        "ROX400HD": ROX_LADDER,
        "GS500ROX": "GS500ROX",
    }
    return mapping.get(cleaned, ROX_LADDER)


def normalize_trace_channels(trace_channels: object | None) -> list[str]:
    if trace_channels is None:
        return list(DEFAULT_TRACE_CHANNELS)
    if isinstance(trace_channels, str):
        trace_channels = [trace_channels]

    cleaned: list[str] = []
    for channel in trace_channels:
        value = str(channel).strip().upper()
        if value in ALLOWED_TRACE_CHANNELS and value not in cleaned:
            cleaned.append(value)
    return cleaned or list(DEFAULT_TRACE_CHANNELS)


def choose_primary_channel(trace_channels: list[str], preferred: str | None = None) -> str:
    preferred = (preferred or "").strip().upper()
    if preferred and preferred in trace_channels:
        return preferred
    return trace_channels[0] if trace_channels else DEFAULT_TRACE_CHANNELS[0]


def resolve_runtime_config(settings: dict | None = None) -> dict:
    pipeline = get_general_pipeline_settings(settings)
    trace_channels = normalize_trace_channels(pipeline.get("trace_channels"))
    primary_channel = choose_primary_channel(
        trace_channels,
        pipeline.get("primary_peak_channel") or pipeline.get("sample_channel"),
    )
    ladder = normalize_ladder_name(pipeline.get("ladder"))
    try:
        bp_min = float(
            pipeline.get("bp_min", DEFAULT_BP_MIN) or DEFAULT_BP_MIN
        )
    except (TypeError, ValueError):
        bp_min = DEFAULT_BP_MIN
    try:
        bp_max = float(
            pipeline.get("bp_max", DEFAULT_BP_MAX) or DEFAULT_BP_MAX
        )
    except (TypeError, ValueError):
        bp_max = DEFAULT_BP_MAX
    size_standard_channel = str(
        pipeline.get("size_standard_channel")
        or ("DATA105" if ladder == LIZ_LADDER else "DATA4")
    ).strip().upper()
    if size_standard_channel not in {"DATA4", "DATA5", "DATA105"}:
        size_standard_channel = "DATA105" if ladder == LIZ_LADDER else "DATA4"
    report_fields = [
        str(value).strip()
        for value in pipeline.get("report_fields", [])
        if str(value).strip()
    ]
    if not report_fields:
        report_fields = list(GENERAL_PROFILE_REPORT_FIELDS)
    try:
        profile_version = max(
            1,
            int(pipeline.get("profile_version") or 1),
        )
    except (TypeError, ValueError):
        profile_version = 1
    validation_status = str(
        pipeline.get("validation_status") or "unvalidated"
    ).strip().lower()
    if validation_status not in {"unvalidated", "validated", "retired"}:
        validation_status = "unvalidated"
    profile = {
        "schema_version": GENERAL_PROFILE_SCHEMA,
        "profile_id": str(
            pipeline.get("profile_id") or "general_default"
        ).strip(),
        "profile_version": profile_version,
        "validation_status": validation_status,
        "ladder": ladder,
        "ladder_steps": list(GENERAL_PROFILE_LADDER_STEPS[ladder]),
        "size_standard_channel": size_standard_channel,
        "trace_channels": trace_channels,
        "peak_channels": list(trace_channels),
        "primary_peak_channel": primary_channel,
        "sample_channel": primary_channel,
        "bp_min": bp_min,
        "bp_max": bp_max,
        "report_fields": report_fields,
    }
    required = (
        profile["profile_id"]
        and profile["ladder_steps"]
        and profile["size_standard_channel"]
        and profile["report_fields"]
        and profile["validation_status"] in {"unvalidated", "validated", "retired"}
        and bp_max > bp_min
    )
    profile["contract_complete"] = bool(required)
    fingerprint_payload = {
        key: value
        for key, value in profile.items()
        if key != "profile_fingerprint"
    }
    profile["profile_fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return profile
