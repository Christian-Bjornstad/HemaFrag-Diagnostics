from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from core.analyses.flt3.pipeline import (
    _build_peaks_from_rust_flt3_preview,
    _calculate_peak_area_fast,
    _detect_peaks,
)


class Flt3AreaBaselineTests(unittest.TestCase):
    def test_flt3_area_uses_raw_channel_trace_not_overcorrected_detection_trace(self) -> None:
        time = np.arange(401, dtype=int)
        bp = np.linspace(320.0, 340.0, time.size)
        peak = 35.0 * np.exp(-0.5 * ((bp - 330.0) / 0.55) ** 2)
        raw_trace = 150.0 + (time * 0.02) + peak
        overcorrected_trace = peak * 0.20
        detection_trace = peak
        sample_data = pd.DataFrame({"time": time, "basepairs": bp})
        fsa = SimpleNamespace(
            fsa={"DATA1": raw_trace},
            sample_data_with_basepairs=sample_data,
        )

        peaks = _detect_peaks(
            fsa=fsa,
            assay="FLT3-ITD",
            wt_bp=330.0,
            trace=detection_trace,
            corrected_channel_traces={"DATA1": overcorrected_trace},
            area_channel_traces={"DATA1": raw_trace},
        )

        self.assertFalse(peaks.empty)
        wt = peaks[peaks["label"] == "WT"].iloc[0]
        overcorrected_area = _calculate_peak_area_fast(
            overcorrected_trace,
            time,
            bp,
            float(wt["basepairs"]),
            "FLT3-ITD",
            "WT",
        )
        self.assertGreater(float(wt["area_DATA1"]), overcorrected_area * 4.0)
        self.assertEqual(wt["source_channel"], "DATA1")

    def test_rust_preview_peaks_use_raw_per_channel_area_traces(self) -> None:
        time = np.arange(401, dtype=int)
        bp = np.linspace(320.0, 340.0, time.size)
        peak1 = 20.0 * np.exp(-0.5 * ((bp - 330.0) / 0.55) ** 2)
        peak2 = 55.0 * np.exp(-0.5 * ((bp - 330.0) / 0.55) ** 2)
        raw1 = 120.0 + peak1
        raw2 = 180.0 + peak2
        sample_data = pd.DataFrame({"time": time, "basepairs": bp})
        fsa = SimpleNamespace(
            fsa={"DATA1": raw1, "DATA2": raw2},
            sample_data_with_basepairs=sample_data,
            rust_flt3_preview={
                "assay_name": "FLT3-ITD",
                "compatible_channel": True,
                "wt_peak": {"basepair": 330.0, "time": 200, "intensity": 55.0},
                "mutant_peaks": [],
            },
        )

        peaks = _build_peaks_from_rust_flt3_preview(
            fsa=fsa,
            assay="FLT3-ITD",
            primary_channel="DATA1",
            trace=raw1 + raw2,
            peak_channels=["DATA1", "DATA2"],
            area_channel_traces={"DATA1": raw1, "DATA2": raw2},
        )

        self.assertIsNotNone(peaks)
        wt = peaks.iloc[0]
        self.assertEqual(wt["source_channel"], "DATA2")
        self.assertGreater(float(wt["area_DATA2"]), float(wt["area_DATA1"]))
        self.assertEqual(float(wt["area"]), float(wt["area_DATA2"]))


if __name__ == "__main__":
    unittest.main()
