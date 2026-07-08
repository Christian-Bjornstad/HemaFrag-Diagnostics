"""HemaFrag GUI Qt — pure helpers for `tab_ladder`.

Phase 12.1 — extracted from the previously-monolithic
`gui_qt/tabs/tab_ladder/_legacy.py` so they can be unit-tested
without spinning up a `QApplication` or constructing a `TabLadder`.

Pure functions only; no Qt widgets, no instance-state reads/writes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import APP_SETTINGS


def resolve_cache_key(file_path: Path) -> Path:
    """Resolve a (possibly not-yet-existing) path into a canonical key.

    Falls back to expanduser() if resolve() raises on Windows for
    relative paths. Mirrors the prior inline implementation in
    TabLadder so existing callers and persisted cache entries keep
    matching.
    """
    try:
        return file_path.expanduser().resolve()
    except Exception:
        return file_path.expanduser()


def entry_original_path(entry: dict) -> Path | None:
    """Find the canonical FSA path attached to a clonality batch entry.

    Tries `original_file_path` then `full_path` then falls back to
    the FSA object's `.file` / `.path` / `.file_path` /
    `.filepath`. Returns `None` when nothing resolvable exists so
    the caller can drop the row instead of crashing.
    """
    raw_path = str(
        entry.get("original_file_path") or entry.get("full_path") or ""
    ).strip()
    if not raw_path:
        fsa = entry.get("fsa")
        raw_path = str(
            getattr(fsa, "file", "")
            or getattr(fsa, "path", "")
            or getattr(fsa, "file_path", "")
            or getattr(fsa, "filepath", "")
            or ""
        ).strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def entry_cache_key(entry: dict) -> Path | None:
    """Wrap: `entry_original_path` then through `resolve_cache_key`."""
    original_path = entry_original_path(entry)
    if original_path is None:
        return None
    return resolve_cache_key(original_path)


def metadata_from_entry(file_path: Path, entry: dict) -> dict:
    """Build the metadata dict passed to the dialog when a row is queued.

    Mirrors the prior TabLadder._metadata_from_entry exactly.
    """
    trace_channels = entry.get("trace_channels") or []
    if not isinstance(trace_channels, list):
        trace_channels = list(trace_channels)
    primary_peak_channel = str(
        entry.get("primary_peak_channel")
        or (trace_channels[0] if trace_channels else "DATA1")
    )
    return {
        "analysis": APP_SETTINGS.get("active_analysis", "clonality"),
        "assay": str(entry.get("assay") or ""),
        "group": str(entry.get("group") or ""),
        "ladder": str(entry.get("ladder") or ""),
        "trace_channels": trace_channels,
        "peak_channels": list(trace_channels),
        "primary_peak_channel": primary_peak_channel,
        "sample_channel": primary_peak_channel,
        "bp_min": float(entry.get("bp_min") or 0.0),
        "bp_max": float(entry.get("bp_max") or 0.0),
        "file_path": file_path,
        "raw": {},
    }


def format_file_item(file_path: Path, case: dict | None) -> str:
    """One-line display string for a file-list row.

    Falls back to the bare filename when `case` is None (the file
    was scanned but isn't a bundle row). Otherwise the row carries
    assay / well / ladder / linear stats / qc to make triage at a
    glance usable without opening the dialog.
    """
    if not case:
        return file_path.name

    parts = [file_path.name]
    assay = str(case.get("assay", "") or "").strip()
    well = str(case.get("well", "") or "").strip()
    ladder = str(case.get("ladder", "") or "").strip()
    if assay:
        parts.append(assay)
    if well:
        parts.append(well)
    if ladder:
        parts.append(ladder)
    linear_max = case.get("linear_max")
    linear_r2 = case.get("linear_r2")
    qc = str(case.get("ladder_qc", "") or "").strip()
    if linear_max not in (None, ""):
        try:
            parts.append(f"max {float(linear_max):.2f}")
        except Exception:
            parts.append(f"max {linear_max}")
    if linear_r2 not in (None, ""):
        try:
            parts.append(f"r2 {float(linear_r2):.5f}")
        except Exception:
            parts.append(f"r2 {linear_r2}")
    if qc:
        parts.append(qc)
    return " · ".join(parts)


# Phase 12.3 — chip-strip state labels + precedence.
CHIP_STATE_LABELS = {
    "reviewed",
    "needs_review",
    "file_unreachable",
    "untouched",
}

# Color contract for the four chip-state precedence. The convention
# matches `core/analyses/clonality/clonality_qc` semantics:
# - reviewed         → green (chemist has cleared the row)
# - needs_review     → amber (bad ladder fit or pending review)
# - file_unreachable → red (path doesn't resolve on disk)
# - untouched        → gray (row loaded but chemist hasn't touched it)
CHIP_STATE_COLORS = {
    "reviewed": "#16a34a",         # green
    "needs_review": "#d97706",     # amber
    "file_unreachable": "#dc2626", # red
    "untouched": "#94a3b8",        # gray
}


def chip_state(row: dict, *, check_filesystem: bool = False) -> str:
    """Return one of: 'reviewed' | 'needs_review' | 'file_unreachable' | 'untouched'.

    The state of a row is the *highest* priority in this order —
    file_unreachable (most actionable for the chemist) wins over
    needs_review, which wins over touched-but-not-saved, which
    wins over untouched.

    The `check_filesystem` kwarg forces a `Path.exists()` check
    rather than relying on the row's `_path_unreachable` tag,
    which is useful when callers don't trust the cached tag.

    Tests pin the precedence contract — see
    `tests/test_tab_ladder_submodules.py::ChipStateHelperTests`.
    """
    # 1. File unreachable — Phase 12.0 tags row["_path_unreachable"].
    if check_filesystem:
        raw_path = str(row.get("full_path", "") or "")
        if raw_path and not Path(raw_path).expanduser().exists():
            return "file_unreachable"
    elif str(row.get("_path_unreachable", "")).lower() == "true":
        return "file_unreachable"

    # 2. Label resolved → reviewed (manual_adjusted or reviewed_no_change).
    label = str(row.get("label", "") or "").strip().lower()
    if label in {"manual_adjusted", "reviewed_no_change"}:
        return "reviewed"

    # 3. Open tooltip reasons flag a needs_review row.
    ladder_qc_status = str(row.get("ladder_qc_status", "") or "").strip().lower()
    review_required_raw = str(row.get("ladder_review_required", "") or "").strip().lower()
    review_required = review_required_raw in {"true", "1", "yes"}
    if ladder_qc_status in {"review_required", "missing_ladder", "ladder_qc_failed"} or review_required:
        return "needs_review"

    return "untouched"


def count_chip_states(rows: list[dict], *, check_filesystem: bool = False) -> dict:
    """Tally how many rows fall into each chip-state bucket.

    Returns {reviewed: int, needs_review: int, file_unreachable: int,
    untouched: int}. Used by the chip-strip legend + bundle summary banner.
    """
    counts = {key: 0 for key in CHIP_STATE_LABELS}
    for row in rows or []:
        try:
            state = chip_state(row, check_filesystem=check_filesystem)
        except Exception:
            state = "untouched"
        if state in counts:
            counts[state] += 1
        else:
            counts["untouched"] += 1
    return counts


# Phase 12.7 — chip-state filter helpers.
# -----------------------------------------------------------------------
#
# The chip-strip widget exposes ``set_filter(allowed_states)`` which
# dims chips whose state isn't in the set (Phase 12.3). These helpers
# give the GUI a clean way to compute that set and to inspect the
# effect of the filter without round-tripping through Qt.
#
# Alias for ``count_chip_states`` so gui code that prefers a shorter
# name can stay terse without forking the implementation.

count_states = count_chip_states


def apply_filter_rows(rows, allowed_states):
    """Return rows whose chip state is in ``allowed_states``.

    ``allowed_states`` may be:
      * a collection (set/list/tuple) of state names.
      * ``None`` — equivalent to "no filter"; every row is returned.
      * an empty collection — strict "match nothing"; returns ``[]``.

    Each row is returned as ``dict(row)`` (shallow copy) so downstream
    callers can mutate without disturbing the input list. Errors during
    state evaluation (e.g. unexpected keys) downgrade to ``untouched``,
    matching ``count_chip_states``'s permissive fallback.
    """
    if allowed_states is None:
        return [dict(r) for r in rows or []]
    allowed = set(allowed_states)
    out: list[dict] = []
    for row in rows or []:
        try:
            state = chip_state(row)
        except Exception:
            state = "untouched"
        if state in allowed:
            out.append(dict(row))
    return out


def is_chip_state_allowed(state, allowed_states):
    """Decide whether a single chip state passes the filter.

    Returns True when ``allowed_states`` is None (no filter), or when
    the state appears in the allowed set. Empty allowed set → always
    False (a strip-wide filter that hides everything). Used by the
    GUI filter widget to decide whether to dim a chip on each
    state-toggle without recomputing the chip's row.
    """
    if allowed_states is None:
        return True
    try:
        return str(state) in set(allowed_states)
    except Exception:
        return False


# Phase 12.6 — keyboard navigation helpers.
# -----------------------------------------------------------------------
#
# Alt+J / Alt+K walk chips one-by-one (prev / next). Ctrl+. jumps to
# the next "relevant" chip — one whose state is in RELEVANT_CHIP_STATES
# — skipping reviewed and untouched. "relevant" is anything the
# chemist still owes attention to: an amber needs_review row or a
# red file_unreachable row.

RELEVANT_CHIP_STATES = {"needs_review", "file_unreachable"}


def next_chip_index(
    rows: list[dict],
    current_index: int,
    direction: int = 1,
    *,
    only_relevant: bool = False,
    check_filesystem: bool = False,
    wrap: bool = True,
) -> int:
    """Return the index of the next chip to focus.

    direction=+1 → next (Alt+K), direction=-1 → prev (Alt+J).

    When ``only_relevant=True`` (Ctrl+.), the scan skips chips in
    ``{"reviewed", "untouched"}`` and lands on the first
    needs_review or file_unreachable chip after ``current_index``.

    Returns -1 when ``rows`` is empty or when ``wrap=False`` and no
    suitable chip is found in a single full cycle. With wrap=True
    and a non-empty ``rows``, never returns -1 — it falls back to
    ``current_index`` if nothing else qualifies.
    """
    if not rows:
        return -1
    n = len(rows)
    # Clamp the starting point into the [-n, n) range so callers
    # passing a stale current_index (e.g. after row replacement)
    # still get a deterministic walk.
    cur = current_index % n
    for offset in range(1, n + 1):
        idx = (cur + direction * offset) % n
        if only_relevant:
            state = chip_state(rows[idx], check_filesystem=check_filesystem)
            if state in RELEVANT_CHIP_STATES:
                return idx
        else:
            return idx
    # Scan completed without a match (only possible when
    # only_relevant=True and no row qualifies). wrap=False lets
    # callers signal "stay put" vs "loop forever".
    return cur if wrap else -1


# Phase 12.8 — bulk-mark-reviewed helper.
# -----------------------------------------------------------------------
#
# The "Mark Visible Reviewed (no change)" button on the chip frame
# needs a pure helper that produces the new-row annotations for
# each visible case. The IO layer (`bulk_save_review_bundle_annotations`
# in `_io.py`) consumes those annotations; this helper just shapes
# the input.

REVIEWED_NO_CHANGE_LABEL = "reviewed_no_change"


def bulk_mark_reviewed_no_change(
    rows, paths, *, now_iso=None
):
    """Return row annotations marking each ``paths`` entry as reviewed_no_change.

    Parameters
    ----------
    rows : list[dict]
        Bundle rows (so the helper can confirm a path is in the
        current bundle before emitting an annotation — silent skip
        rather than phantom-write).
    paths : iterable
        Full paths (str or Path) to mark reviewed.
    now_iso : str, optional
        UTC ISO timestamp. Defaults to a fresh
        ``datetime.now(timezone.utc).isoformat()``; overridden
        in tests for determinism.

    Returns a list of annotation dicts keyed by ``full_path`` plus
    ``label``, ``label_note``, ``reviewed_at_utc``,
    ``adjustment_path``. Always ``label_note = ""`` and
    ``adjustment_path = ""`` — "no change" means exactly that:
    no manual adjustment, just an explicit "I've looked at this."
    """
    if not paths:
        return []
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).isoformat()

    # Build a set membership check keyed by full_path text so
    # callers can pass Path objects or str without surprise.
    in_bundle = set()
    for row in rows or []:
        try:
            in_bundle.add(str(row.get("full_path", "") or ""))
        except Exception:
            continue

    out = []
    for raw in paths:
        if raw is None:
            continue
        text = str(raw)
        if text and text not in in_bundle:
            # Path not in current bundle — skip silently. The
            # button is "visible" only; phantom-annotation would
            # corrupt the audit log.
            continue
        out.append(
            {
                "full_path": text,
                "label": REVIEWED_NO_CHANGE_LABEL,
                "label_note": "",
                "reviewed_at_utc": now_iso,
                "adjustment_path": "",
            }
        )
    return out


# Phase 12.11 — DIT prefix filter helper.
# -----------------------------------------------------------------------
#
# The "Filter by DIT" input above the chip strip dims every chip
# whose DIT identifier doesn't start with the user's prefix. The
# helper extracts DITs (\d{2}OUM\d{5}) from `full_path` first,
# falls back to `source_run_dir` (T7 Shield rename fallback),
# then matches case-insensitively.
#
# Returns the matching indices *and* the matched DITs so the
# GUI can render the matched prefix set without re-extracting.

_DIT_REGEX = re.compile(r"(\d{2}OUM\d{5})", re.IGNORECASE)


def _row_dit(row: dict) -> str:
    """Best-effort DIT extraction for a bundle row.

    Reads DIT (regex \d{2}OUM\d{5}) from `full_path` first;
    if that yields nothing, falls back to `source_run_dir`.
    The returned text is uppercase (DIT convention).
    Returns "" when no DIT can be extracted.
    """
    full_path = str(row.get("full_path", "") or "")
    dit = _DIT_REGEX.search(full_path)
    if dit is None:
        run_dir = str(row.get("source_run_dir", "") or "")
        dit = _DIT_REGEX.search(run_dir)
    if dit is None:
        return ""
    return dit.group(1).upper()


def extract_dit_candidates(
    rows, prefix: str
) -> tuple[list[int], list[str]]:
    """Return ``(indices, dits)`` of rows whose DIT starts with ``prefix``.

    - case-insensitive matching (so "24" hits "24OUM...");
    - empty prefix returns ([], []) — "no filter applied";
    - rows where the DIT could not be extracted never match;
    - the dict order of ``rows`` is preserved in the output.

    The returned DITs are uppercase; the prefix is compared
    uppercase so the chemist's input is case-tolerant.
    """
    if not prefix or not rows:
        return [], []
    upper_prefix = prefix.strip().upper()
    if not upper_prefix:
        return [], []
    indices: list[int] = []
    dits: list[str] = []
    for i, row in enumerate(rows or []):
        dit = _row_dit(row)
        if dit and dit.startswith(upper_prefix):
            indices.append(i)
            dits.append(dit)
    return indices, dits


def dit_filter_keep(indices: list[int]) -> set[int] | None:
    """Convert the helper's index list into the GUI's allowed-set shape.

    Returns ``None`` when no indices (no filter applied / empty
    prefix / no matches) so the GUI can short-circuit and
    clear the dim. Otherwise returns a plain ``set[int]`` that
    the chip strip can pass through to its `set_filter`
    pathway via AND-composition with `set_filter(allowed_states)`.

    Why the conversion helper: every GUI consumer wants to
    AND a chip-state filter AND a DIT filter. Returning
    ``set[int]`` from one helper + ``set[str]`` (states)
    from another is more expressive than a single combined
    filter, but only after the third "shader" (indices →
    set[int]) does the consumer code stay readable.
    """
    if not indices:
        return None
    return set(indices)


# Phase 12.12 — bundle summary banner helpers.
# -----------------------------------------------------------------------
#
# The chip-strip's legend (one line of color counts) is too terse
# for a 750-row bundle — the chemist loses the totals when the
# strip scrolls off-screen. A small `QLabel` banner sits directly
# below the strip and renders live state counts plus the
# most-recent save timestamp. Two pure helpers below keep the GUI
# rendering path small and unit-testable.

NEVER_SAVED_LABEL = "never"


def most_recent_save_timestamp(
    rows, *, now_iso: str | None = None
) -> str:
    """Return the largest ``reviewed_at_utc`` ISO string, or ``"never"``.

    ISO-8601 timestamps sort lexicographically (left-to-right
    YYYY-MM-DD-HH-MM-SS...), so the max-of-strs yields the
    most-recent save without parsing into ``datetime``. Empty
    rows, or rows without a ``reviewed_at_utc`` value, fall back
    to :data:`NEVER_SAVED_LABEL`.

    `now_iso` is unused today; pre-parameterized to keep tests
    deterministic if a future phase injects a fresh-timestamp
    helper for "saved within last X minutes" derivations.
    """
    candidates: list[str] = []
    for row in rows or []:
        try:
            ts = str(row.get("reviewed_at_utc", "") or "")
        except Exception:
            ts = ""
        if ts:
            candidates.append(ts)
    if not candidates:
        return NEVER_SAVED_LABEL
    return max(candidates)


def format_summary_banner(
    rows,
    *,
    visible_count: int | None = None,
    total_count: int | None = None,
) -> str:
    """Render the bundle summary banner.

    Layout (matches the skill, single line):
        ``visible N of T | N needs review | M unreachable | K reviewed |
        U untouched | last saved: <timestamp>``

    Pass ``visible_count=...`` when the chip filter is active
    so the chemist sees that the dim path is taking a slice
    out of the totals. ``total_count`` overrides the
    zero-on-empty-row computation when callers know the
    bundle size independent of the in-memory row list.

    Empty input returns the "0 / 0 / never" string so the
    banner always renders something during a fresh load
    before the cases arrive.
    """
    counts = count_chip_states(rows)
    if total_count is None:
        total_count = sum(counts.values())
    if visible_count is None:
        visible_count = total_count
    ts = most_recent_save_timestamp(rows)

    parts = [
        f"visible {visible_count} of {total_count}",
        f"{counts['needs_review']} needs review",
        f"{counts['file_unreachable']} unreachable",
        f"{counts['reviewed']} reviewed",
        f"{counts['untouched']} untouched",
        f"last saved: {ts}",
    ]
    return " | ".join(parts)
