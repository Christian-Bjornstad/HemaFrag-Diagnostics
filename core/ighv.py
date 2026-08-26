"""HemaFrag — IGHV-analyse (Mix 1 / Mix 2 på ROX400HD-stige).

Spesifikasjon (lab):
- Referanseområder: Mix 1 DNA 500–570 bp / RNA 415–485 bp; Mix 2 310–380 bp.
- Alle topper i referanseområdet med signal > 5000 RFU listes i topptabellen
  (markeres manuelt av bruker — ingen automatisk «klonal topp»-verdict).
- QC (PK/NK): 300 bp stigetopp måles for begge mikser; PK-fragment måles i
  vinduet Mix 1 535–550 bp / Mix 2 357–358 bp. NK skal være tom/baseline.
"""
from __future__ import annotations

from typing import Any

import numpy as np

try:  # pandas er lazy-lastet i appen; her brukes kun DataFrame-typen
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]

from core.analyses.clonality.config import (
    IGHV_PK_WINDOWS_BP,
    IGHV_QC_LADDER_TARGET_BP,
    IGHV_QC_LADDER_WINDOW_BP,
    IGHV_QC_MIN_HEIGHT_RFU,
    IGHV_REFERENCE_RANGES,
    IGHV_RFU_PEAK_THRESHOLD,
)

# Minste avstand mellom godkjente topper (bp) – undertrykker skuldre.
_MIN_PEAK_SEPARATION_BP = 2.0
# Vindu (bp) rundt en topp som integreres for areal.
_PEAK_AREA_WINDOW_BP = 4.0


def is_ighv(assay: str | None) -> bool:
    return str(assay or "").startswith("IGHV")


# Aktuell prøvetype per miks (styrt fra GUI-knappen; DNA er standard).
_CURRENT_SAMPLE_TYPES: dict[str, str] = {
    "IGHV Mix 1": "DNA",
    "IGHV Mix 2": "DNA",
}


def normalize_sample_type(sample_type: str) -> str:
    return "RNA" if str(sample_type or "").upper().startswith("RNA") else "DNA"


def get_sample_type(assay: str) -> str:
    """Aktiv prøvetype for miksen (GUI-valg; DNA er standard)."""
    return _CURRENT_SAMPLE_TYPES.get(assay, "DNA")


def set_sample_type(assay: str, sample_type: str) -> tuple[float, float]:
    """Sett prøvetype og aktiver tilhørende referanserange."""
    key = normalize_sample_type(sample_type)
    _CURRENT_SAMPLE_TYPES[assay] = key
    return apply_sample_type(assay, key)


def ighv_reference_range(assay: str, sample_type: str = "DNA") -> tuple[float, float]:
    """Returner referanseområdet for en IGHV-miks og prøvetype (DNA/RNA)."""
    ranges = IGHV_REFERENCE_RANGES.get(assay)
    if not ranges:
        raise KeyError(f"Ukjent IGHV-assay: {assay!r}")
    key = "RNA" if str(sample_type).upper().startswith("RNA") else "DNA"
    lo, hi = ranges[key]
    return (float(lo), float(hi))


def ighv_pk_window(assay: str) -> tuple[float, float]:
    lo, hi = IGHV_PK_WINDOWS_BP[assay]
    return (float(lo), float(hi))


def apply_sample_type(assay: str, sample_type: str) -> tuple[float, float]:
    """Sett aktiv referanserange for miksen (GUI DNA/RNA-knapp).

    Plotteren leser ``ASSAY_REFERENCE_RANGES`` fra config-modulen ved hver
    rendering, så vi muterer kilden – da får både beige-shading, zoom og
    tolkningsvinduer med seg valget.
    """
    lo, hi = ighv_reference_range(assay, sample_type)
    from core.analyses.clonality import config as clonality_config

    clonality_config.ASSAY_REFERENCE_RANGES[assay] = [(lo, hi)]
    return (lo, hi)


def _trace_arrays(fsa: Any, channel: str = "DATA1") -> tuple[np.ndarray, np.ndarray]:
    """Returner (signal_rfus, basepairs) justert mot samme lengde."""
    signal = np.asarray(fsa.fsa[channel], dtype=float)
    raw_df = getattr(fsa, "sample_data_with_basepairs", None)
    if raw_df is None or getattr(raw_df, "empty", True) or "basepairs" not in raw_df.columns:
        raise ValueError("sample_data_with_basepairs mangler basepairs – kan ikke lokalisere topper.")
    bp = raw_df["basepairs"].to_numpy(dtype=float)
    n = min(len(signal), len(bp))
    return signal[:n], bp[:n]


def find_peaks_in_window(
    bp: np.ndarray,
    signal: np.ndarray,
    x_min: float,
    x_max: float,
    *,
    rfu_threshold: float = 0.0,
    max_peaks: int = 20,
) -> list[dict[str, float]]:
    """Finn lokale maksimer i [x_min, x_max] med signal >= rfu_threshold.

    Greedy: høyeste punkt først, deretter punkter minst
    ``_MIN_PEAK_SEPARATION_BP`` unna allerede aksepterte topper.
    """
    mask = (bp >= float(x_min)) & (bp <= float(x_max)) & (signal >= float(rfu_threshold))
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    order = idx[np.argsort(signal[idx])[::-1]]
    accepted: list[int] = []
    for i in order:
        if all(abs(bp[i] - bp[j]) >= _MIN_PEAK_SEPARATION_BP for j in accepted):
            accepted.append(int(i))
        if len(accepted) >= max_peaks:
            break
    return [
        {
            "bp": float(bp[i]),
            "height": float(signal[i]),
            "index": int(i),
        }
        for i in sorted(accepted, key=lambda k: bp[k])
    ]


def _peak_area_near(
    fsa: Any,
    bp_center: float,
    channel: str = "DATA1",
    window_bp: float = _PEAK_AREA_WINDOW_BP,
) -> float:
    """Integralet rundt toppen ved *bp_center* (gjenbruker Gaussian-area)."""
    from core.area import compute_peak_area_gaussian

    signal, bp = _trace_arrays(fsa, channel)
    time_arr = np.arange(len(signal), dtype=int)
    try:
        return float(compute_peak_area_gaussian(signal, time_arr, bp, float(bp_center), window_bp))
    except Exception:
        return float("nan")


def detect_clonal_peaks(
    fsa: Any,
    assay: str,
    sample_type: str | None = None,
    *,
    channel: str = "DATA1",
    rfu_threshold: float = IGHV_RFU_PEAK_THRESHOLD,
) -> list[dict[str, float]]:
    """Alle topper > *rfu_threshold* RFU i referanseområdet til miksen.

    ``sample_type=None`` følger GUI-valget (``set_sample_type``).
    Hver rad: {"bp", "height", "area"} sortert etter bp.
    """
    effective = normalize_sample_type(sample_type) if sample_type else get_sample_type(assay)
    lo, hi = ighv_reference_range(assay, effective)
    signal, bp = _trace_arrays(fsa, channel)
    peaks = find_peaks_in_window(bp, signal, lo, hi, rfu_threshold=rfu_threshold)
    for p in peaks:
        p["area"] = _peak_area_near(fsa, p["bp"], channel=channel)
    return peaks



def qc_control_rows(
    fsa: Any,
    assay: str,
    *,
    channel: str = "DATA1",
) -> dict[str, dict[str, float]]:
    """Mål 300 bp stigetopp og PK-fragmentet for en IGHV-kontroll.

    Returnerer {\"ladder_300\": {...}, \"pk\": {...}} der hver rad har
    bp/height/area, eller manglende verdier (NaN) hvis toppen ikke finnes.
    """
    signal, bp = _trace_arrays(fsa, channel)

    ladder_lo = IGHV_QC_LADDER_TARGET_BP - IGHV_QC_LADDER_WINDOW_BP
    ladder_hi = IGHV_QC_LADDER_TARGET_BP + IGHV_QC_LADDER_WINDOW_BP
    ladder_hits = find_peaks_in_window(bp, signal, ladder_lo, ladder_hi)
    pk_lo, pk_hi = ighv_pk_window(assay)
    pk_hits = find_peaks_in_window(bp, signal, pk_lo, pk_hi)

    def _strongest(hits: list[dict[str, float]]) -> dict[str, float] | None:
        """Høyeste topp over støygulvet (ikke laveste bp)."""
        real = [h for h in hits if h.get("height", 0.0) >= IGHV_QC_MIN_HEIGHT_RFU]
        if not real:
            return None
        return max(real, key=lambda p: p.get("height", float("nan")))

    def _row(hit: dict[str, float] | None) -> dict[str, float]:
        if not hit:
            return {
                "bp": float("nan"),
                "height": float("nan"),
                "area": float("nan"),
                "found": 0.0,
            }
        hit = dict(hit)
        hit.pop("index", None)
        hit["area"] = _peak_area_near(fsa, hit["bp"], channel=channel)
        hit["found"] = 1.0
        return hit

    pk_row = _row(_strongest(pk_hits))
    if pk_row.get("found") == 1.0:
        # Vindu følger med på raden slik at rapporten kan flagge avvik
        # («utenfor …») — delta trackes kun når toppen ligger utenfor.
        pk_row["window_lo"] = float(pk_lo)
        pk_row["window_hi"] = float(pk_hi)

    return {"ladder_300": _row(_strongest(ladder_hits)),
            "pk": pk_row}


def attach_ighv_results(
    entry: dict[str, Any],
    sample_type: str | None = None,
) -> dict[str, Any]:
    """Beregn og fest IGHV-resultater på et pipeline-entry (in place).

    Passe for pasientprøver (klonale topper) OG kontroller (PK/NK-tabell):
    kontroller får samme topptablell men uten «klonal»-tolkning.
    """
    assay = str(entry.get("assay") or "")
    if not is_ighv(assay):
        return entry
    fsa = entry.get("fsa")
    if fsa is None:
        return entry
    effective = normalize_sample_type(sample_type) if sample_type else get_sample_type(assay)
    # Filnavn-trumf: en eksplisitt RNA/cDNA-markør i filnavnet overstyrer
    # GUI-standard (DNA), slik at rapporten viser riktig prøvetype uten app-valg.
    try:
        from core.analyses.clonality.classification import filename_suggests_rna

        if effective != "RNA" and filename_suggests_rna(getattr(fsa, "file_name", "")):
            effective = "RNA"
            apply_sample_type(assay, "RNA")
            entry["ighv_sample_type_from_filename"] = True
    except Exception:
        pass
    entry["ighv_sample_type"] = effective
    try:
        entry["ighv_clonal_peaks"] = detect_clonal_peaks(fsa, assay, sample_type=effective)
    except Exception:
        entry["ighv_clonal_peaks"] = []
    # NB: ingen automatisk «Klonal topp … detektert.»-verdict lenger —
    # topper markeres manuelt i rapporten.
    group = str(entry.get("group") or "")
    if group in {"positive", "negative", "reactive"}:
        try:
            entry["ighv_qc_rows"] = qc_control_rows(fsa, assay)
        except Exception:
            entry["ighv_qc_rows"] = {}
    return entry
