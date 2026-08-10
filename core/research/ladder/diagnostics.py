"""Bounded Rust diagnostic execution and deterministic ladder taxonomy."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .contracts import DIAGNOSTIC_SCHEMA_VERSION, LadderOutcome


GENERIC_REJECTION_REASONS = {"rust_ladder_fit_rejected", "ladder_fit_rejected"}
MISSING_SIGNAL_REASONS = {
    "no_ladder_signal",
    "missing_ladder_signal",
    "no_size_standard_peaks",
}
WRONG_CONFIGURATION_REASONS = {
    "wrong_ladder",
    "wrong_ladder_or_channel",
    "wrong_size_standard_channel",
}


@dataclass(frozen=True)
class DiagnosticRecord:
    schema_version: str
    source_path: str
    transport_status: str
    elapsed_seconds: float
    stderr: str
    configured_ladder: str
    detected_ladder: str
    detected_channel: str
    reviewed_label: str
    candidate_peak_count: int
    fitted_count: int
    preview_scan_indices: tuple[int, ...]
    search_tier: str
    estimated_combinations: int
    evaluated_combinations: int
    qc_metrics: dict[str, Any]
    timings_us: dict[str, Any]
    review_required: bool
    reason_codes: tuple[str, ...]
    accepted: bool
    outcome: LadderOutcome
    issue_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["outcome"] = self.outcome.value
        value["preview_scan_indices"] = list(self.preview_scan_indices)
        value["reason_codes"] = list(self.reason_codes)
        value["issue_codes"] = list(self.issue_codes)
        return value


def _normalize_ladder(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("LIZ"):
        return "LIZ"
    if text.startswith("ROX"):
        return "ROX"
    return text


def classify_ladder_outcome(payload: Mapping[str, Any]) -> LadderOutcome:
    """Classify one normalized or raw diagnostic with explicit precedence."""

    reviewed_label = str(payload.get("reviewed_label") or "").strip().casefold()
    if reviewed_label in {"reviewed_no_change", "fit_correct_review_only"}:
        return LadderOutcome.FIT_CORRECT_REVIEW_ONLY
    if reviewed_label in {"manual_adjusted", "corrected", "fit_accepted_but_wrong"}:
        if bool(payload.get("accepted")):
            return LadderOutcome.FIT_ACCEPTED_BUT_WRONG

    reasons = {
        str(reason).strip().casefold() for reason in payload.get("reason_codes") or []
    }
    if reasons & MISSING_SIGNAL_REASONS:
        return LadderOutcome.MISSING_LADDER_SIGNAL
    if "ladder_peak_count" in payload and payload.get("ladder_peak_count") is not None:
        if int(payload.get("ladder_peak_count") or 0) == 0:
            return LadderOutcome.MISSING_LADDER_SIGNAL

    if reasons & WRONG_CONFIGURATION_REASONS:
        return LadderOutcome.WRONG_LADDER_OR_CHANNEL
    configured = _normalize_ladder(payload.get("configured_ladder"))
    detected = _normalize_ladder(
        payload.get("detected_ladder") or payload.get("ladder")
    )
    if configured and detected and configured != detected:
        return LadderOutcome.WRONG_LADDER_OR_CHANNEL

    candidate_count = int(
        payload.get("candidate_peak_count")
        if payload.get("candidate_peak_count") is not None
        else payload.get("ladder_peak_count") or 0
    )
    fitted_count = int(payload.get("fitted_count") or 0)
    review_required = bool(payload.get("review_required"))
    accepted = bool(payload.get("accepted"))
    if candidate_count > 0 and (fitted_count == 0 or review_required or not accepted):
        return LadderOutcome.FIT_REJECTED_WITH_USABLE_SIGNAL
    return LadderOutcome.UNRESOLVED


def normalize_rust_result(
    payload: Mapping[str, Any],
    *,
    source_path: Path,
    configured_ladder: str,
    reviewed_label: str,
    elapsed_seconds: float = 0.0,
    stderr: str = "",
) -> DiagnosticRecord:
    """Preserve the useful Rust preview even when the final fit is rejected."""

    preview = payload.get("ladder_fit_preview")
    preview = preview if isinstance(preview, Mapping) else {}
    refinement = preview.get("refinement")
    refinement = refinement if isinstance(refinement, Mapping) else {}
    model = preview.get("sizing_model")
    model = model if isinstance(model, Mapping) else {}
    qc = model.get("qc_metrics")
    qc = dict(qc) if isinstance(qc, Mapping) else {}
    review = payload.get("ladder_review_assessment")
    review = review if isinstance(review, Mapping) else {}
    timings = payload.get("timings_us")
    timings = dict(timings) if isinstance(timings, Mapping) else {}

    raw_scans = refinement.get("refined_scan_indices") or preview.get(
        "best_scan_indices"
    ) or []
    scans = tuple(int(round(float(value))) for value in raw_scans)
    reasons = tuple(sorted({str(value) for value in review.get("reason_codes") or []}))
    review_required = bool(review.get("suggested_review"))
    fitted_count = len(scans)
    accepted = fitted_count > 0 and not review_required
    detected_ladder = str(payload.get("ladder") or "")

    normalized_payload = {
        "configured_ladder": configured_ladder,
        "detected_ladder": detected_ladder,
        "ladder_peak_count": int(payload.get("ladder_peak_count") or 0),
        "candidate_peak_count": int(payload.get("ladder_peak_count") or 0),
        "fitted_count": fitted_count,
        "review_required": review_required,
        "reason_codes": reasons,
        "reviewed_label": reviewed_label,
        "accepted": accepted,
    }
    issues: list[str] = []
    if review_required and (not reasons or set(reasons) <= GENERIC_REJECTION_REASONS):
        issues.append("underlying_reason_missing")

    return DiagnosticRecord(
        schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        source_path=str(Path(source_path).resolve()),
        transport_status="ok",
        elapsed_seconds=float(elapsed_seconds),
        stderr=stderr,
        configured_ladder=_normalize_ladder(configured_ladder),
        detected_ladder=detected_ladder,
        detected_channel=str(payload.get("size_standard_channel_guess") or ""),
        reviewed_label=reviewed_label,
        candidate_peak_count=normalized_payload["candidate_peak_count"],
        fitted_count=fitted_count,
        preview_scan_indices=scans,
        search_tier=str(preview.get("search_tier") or ""),
        estimated_combinations=int(preview.get("estimated_combination_count") or 0),
        evaluated_combinations=int(preview.get("evaluated_combination_count") or 0),
        qc_metrics=qc,
        timings_us=timings,
        review_required=review_required,
        reason_codes=reasons,
        accepted=accepted,
        outcome=classify_ladder_outcome(normalized_payload),
        issue_codes=tuple(issues),
    )


def _transport_record(
    source_path: Path,
    configured_ladder: str,
    status: str,
    elapsed_seconds: float,
    stderr: str,
    issue_code: str,
) -> DiagnosticRecord:
    return DiagnosticRecord(
        schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        source_path=str(source_path.resolve()),
        transport_status=status,
        elapsed_seconds=elapsed_seconds,
        stderr=stderr,
        configured_ladder=_normalize_ladder(configured_ladder),
        detected_ladder="",
        detected_channel="",
        reviewed_label="",
        candidate_peak_count=0,
        fitted_count=0,
        preview_scan_indices=(),
        search_tier="",
        estimated_combinations=0,
        evaluated_combinations=0,
        qc_metrics={},
        timings_us={},
        review_required=False,
        reason_codes=(),
        accepted=False,
        outcome=LadderOutcome.UNRESOLVED,
        issue_codes=(issue_code,),
    )


def run_rust_diagnostic(
    cli: Path,
    input_file: Path,
    *,
    configured_ladder: str,
    reviewed_label: str = "",
    timeout_seconds: int = 30,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DiagnosticRecord:
    """Run one deterministic CLI analysis with a hard timeout and isolated output."""

    cli_path = Path(cli).resolve()
    source = Path(input_file).resolve()
    if not cli_path.is_file():
        raise FileNotFoundError(cli_path)
    if not source.is_file():
        raise FileNotFoundError(source)

    with tempfile.TemporaryDirectory(prefix="hemafrag_ladder_diagnostic_") as temp:
        output_dir = Path(temp) / "output"
        command: Sequence[str] = (
            str(cli_path),
            "analyze",
            "--analysis",
            "clonality",
            "--input",
            str(source),
            "--output-dir",
            str(output_dir),
            "--deterministic",
            "--compact-json",
        )
        started = time.perf_counter()
        try:
            completed = run_command(
                list(command),
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            return _transport_record(
                source,
                configured_ladder,
                "timeout",
                elapsed,
                stderr,
                "transport_timeout",
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            elapsed = time.perf_counter() - started
            stderr_value = getattr(exc, "stderr", "") or str(exc)
            stderr = stderr_value.decode() if isinstance(stderr_value, bytes) else str(stderr_value)
            return _transport_record(
                source,
                configured_ladder,
                "error",
                elapsed,
                stderr,
                "transport_error",
            )

        elapsed = time.perf_counter() - started
        summary = output_dir / "analyze_summary.json"
        try:
            payload = json.loads(summary.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, list)
                or len(payload) != 1
                or not isinstance(payload[0], dict)
            ):
                raise ValueError("summary must contain exactly one result object")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return _transport_record(
                source,
                configured_ladder,
                "invalid_summary",
                elapsed,
                f"{completed.stderr or ''}\n{exc}".strip(),
                "invalid_summary",
            )
        return normalize_rust_result(
            payload[0],
            source_path=source,
            configured_ladder=configured_ladder,
            reviewed_label=reviewed_label,
            elapsed_seconds=elapsed,
            stderr=str(completed.stderr or ""),
        )
