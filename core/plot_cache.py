"""
HemaFrag Diagnostics — shared plot-caching utilities.

`core.plotting_plotly` historically carried per-FSA / per-entry
cache plumbing inline. This module is the single source of truth
for that.

Two caches:

- FsaPlotCache  : attached to a FsaFile-like object. Stores axis
                   arrays and per-channel trace arrays, keyed off
                   `id()` of the underlying source so that re-loading
                   a fresh fsa invalidates the cache automatically.

- EntryPlotCache : attached to an entry dict. Stores derived
                   display signals keyed off upstream trace identity.

Behaviour is preserved bit-for-bit relative to the inline helpers
they replace; this module is a pure refactor.
"""
from __future__ import annotations

import numpy as np


def _ensure_dict(store) -> dict:
    if isinstance(store, dict):
        return store
    return {}


class FsaPlotCache:
    """Per-FsaFile plot cache."""

    ATTR = "_plotly_report_cache"

    def __init__(self, fsa):
        self.fsa = fsa
        store = getattr(fsa, self.ATTR, None)
        store = _ensure_dict(store)
        setattr(fsa, self.ATTR, store)
        self.store = store

    @classmethod
    def for_fsa(cls, fsa) -> "FsaPlotCache":
        return cls(fsa)

    def get_or_compute_axis_arrays(self, raw_df) -> dict | None:
        """Return cached axis arrays or compute them once.

        Returns None when raw_df is missing or lacks the canonical
        `time` / `basepairs` columns. Cache invalidates when the
        underlying sample_data_with_basepairs binding changes
        (keyed off id() + columns tuple).
        """
        if raw_df is None or raw_df.empty:
            return None
        if "time" not in raw_df.columns or "basepairs" not in raw_df.columns:
            return None

        cache_key = ("axis_arrays", id(raw_df), tuple(raw_df.columns))
        cached = self.store.get("axis_arrays")
        if isinstance(cached, dict) and cached.get("key") == cache_key:
            return cached["value"]

        value = {
            "time_all": raw_df["time"].astype(int).to_numpy(),
            "bp_all": raw_df["basepairs"].to_numpy(),
            "available_channels": tuple(
                k for k in self.fsa.fsa.keys() if k.startswith("DATA")
            ),
        }
        self.store["axis_arrays"] = {"key": cache_key, "value": value}
        return value

    def get_or_compute_trace(self, channel: str) -> np.ndarray:
        """Return cached per-channel numeric trace, computing once.

        Cache invalidates when `id(fsa.fsa[channel])` changes (which
        is the case when a fresh FsaFile is bound).
        """
        trace_arrays = self.store.setdefault("trace_arrays", {})
        cached = trace_arrays.get(channel)
        current = getattr(self.fsa, "fsa", {}).get(channel)
        current_id = id(current)
        if isinstance(cached, dict) and cached.get("source_id") == current_id:
            return cached["value"]

        value = np.asarray(current, dtype=float)
        trace_arrays[channel] = {"source_id": current_id, "value": value}
        return value


class EntryPlotCache:
    """Per-entry plot cache for derived display signals."""

    ATTR = "_entry_plot_cache"
    DISPLAY_KEY = "display_traces"
    NONSPECIFIC_KEY = "nonspecific_traces"

    def __init__(self, entry: dict):
        self.entry = entry
        store = entry.get(self.ATTR)
        store = _ensure_dict(store)
        entry[self.ATTR] = store
        self.store = store

    @classmethod
    def for_entry(cls, entry: dict) -> "EntryPlotCache":
        return cls(entry)

    def get_or_compute_display(
        self,
        channel: str,
        trace: np.ndarray,
        assay_name,
        compute,
    ) -> np.ndarray:
        """Cache the result of `compute(trace, assay_name)` keyed off
        (assay_name, channel, id(trace), trace.shape)."""
        display_cache = self.store.setdefault(self.DISPLAY_KEY, {})
        cache_key = (assay_name, channel, id(trace), trace.shape)
        cached = display_cache.get(channel)
        if isinstance(cached, dict) and cached.get("key") == cache_key:
            return cached["value"]

        value = compute(trace, assay_name)
        display_cache[channel] = {"key": cache_key, "value": value}
        return value

    def get_or_compute_nonspecific(
        self,
        channel: str,
        trace: np.ndarray,
        compute,
    ) -> np.ndarray:
        """Cache the result of `compute(trace)` keyed off
        channel + trace identity + shape."""
        ns_cache = self.store.setdefault(self.NONSPECIFIC_KEY, {})
        cache_key = ("nonspecific", channel, id(trace), trace.shape)
        cached = ns_cache.get(channel)
        if isinstance(cached, dict) and cached.get("key") == cache_key:
            return cached["value"]

        value = compute(trace)
        ns_cache[channel] = {"key": cache_key, "value": value}
        return value


# Back-compat module-level shims for the historical inline helpers.
def get_fsa_axis_arrays(fsa):
    return FsaPlotCache.for_fsa(fsa).get_or_compute_axis_arrays(
        getattr(fsa, "sample_data_with_basepairs", None)
    )


def get_fsa_trace_array(fsa, channel: str):
    return FsaPlotCache.for_fsa(fsa).get_or_compute_trace(channel)
