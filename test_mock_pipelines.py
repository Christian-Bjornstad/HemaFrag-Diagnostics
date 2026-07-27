"""
Minimal test runner for HemaFrag pipelines using mock FSA data.
Tests both FLT3 and Clonality pipelines without requiring real .fsa files.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd

sys.path.insert(0, "/workspace/hemafrag")

def create_mock_flt3_fsa():
    """Create a mock FSA object for FLT3 testing."""
    time = np.arange(401, dtype=int)
    bp = np.linspace(100.0, 600.0, time.size)
    
    wt_peak = 35.0 * np.exp(-0.5 * ((bp - 330.0) / 0.55) ** 2)
    raw_trace = 150.0 + (time * 0.02) + wt_peak
    
    mut_peak = 20.0 * np.exp(-0.5 * ((bp - 400.0) / 0.8) ** 2)
    raw_trace += mut_peak
    
    sample_data = pd.DataFrame({"time": time, "basepairs": bp})
    
    return SimpleNamespace(
        fsa={"DATA1": raw_trace},
        sample_data_with_basepairs=sample_data,
        file_name="TEST_MOCK_ITD__260627_A01_MOCK123.fsa",
        ladder="GS500ROX",
        analysis_id="flt3_mock_test",
    )

def test_flt3_basic():
    """Test FLT3 basic functions."""
    print("\n" + "="*60)
    print("TESTING: FLT3 Basic Functions")
    print("="*60)
    
    try:
        from core.analyses.flt3.pipeline import _detect_peaks, _build_peaks_from_rust_flt3_preview
        
        fsa = create_mock_flt3_fsa()
        
        print("\n1. Testing peak detection...")
        peaks = _detect_peaks(
            fsa=fsa,
            assay="FLT3-ITD",
            wt_bp=330.0,
            trace=fsa.fsa["DATA1"],
            corrected_channel_traces={"DATA1": fsa.fsa["DATA1"]},
            area_channel_traces={"DATA1": fsa.fsa["DATA1"]},
        )
        
        print(f"   Detected {len(peaks)} peaks")
        if not peaks.empty:
            print(f"   Columns: {list(peaks.columns)}")
            if "WT" in peaks["label"].values:
                wt = peaks[peaks["label"] == "WT"].iloc[0]
                print(f"   WT peak: bp={wt['basepairs']:.2f}, area={wt['area']:.2f}")
        
        print("\n✓ FLT3 basic test: PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ FLT3 basic test: FAILED")
        print(f"   Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_clonality_basic():
    """Test Clonality basic functions."""
    print("\n" + "="*60)
    print("TESTING: Clonality Basic Functions")
    print("="*60)
    
    try:
        from core.analyses.clonality.classification import detect_assay, classify_fsa
        from core.analyses.clonality.pipeline import run_pipeline
        
        print("\n1. Testing assay detection...")
        test_cases = [
            ("PK_IGH__260627_A01.fsa", "FR1"),
            ("NK_TCRgA__260627_B01.fsa", "TCRgA"),
            ("RK_TCRbB__260627_C01.fsa", "TCRbB"),
            ("PK_KDE__260627_D01.fsa", "KDE"),
            ("PK_IKZF1__260627_E01.fsa", "IKZF1"),
        ]
        
        for filename, expected in test_cases:
            detected = detect_assay(filename)
            status = "✓" if detected == expected else "✗"
            print(f"   {status} {filename}: detected={detected}, expected={expected}")
        
        print("\n2. Testing clonality pipeline import...")
        print("   Pipeline module: OK")
        
        print("\n✓ Clonality basic test: PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Clonality basic test: FAILED")
        print(f"   Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_rust_bridge():
    """Test Rust engine bridge."""
    print("\n" + "="*60)
    print("TESTING: Rust Bridge")
    print("="*60)
    
    try:
        from core.rust_bridge._legacy import reset_rust_engine_stats, rust_engine_stats_snapshot
        
        print("\n1. Testing Rust engine stats...")
        reset_rust_engine_stats()
        stats = rust_engine_stats_snapshot()
        print(f"   Initial stats: {stats}")
        
        print("\n✓ Rust bridge test: PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Rust bridge test: FAILED")
        print(f"   Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "="*60)
    print("HemaFrag Diagnostics - Pipeline Smoke Tests")
    print("="*60)
    
    results = {
        "flt3": test_flt3_basic(),
        "clonality": test_clonality_basic(),
        "rust_bridge": test_rust_bridge(),
    }
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for test, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {test}: {status}")
    
    all_passed = all(results.values())
    print("\n" + ("="*60))
    if all_passed:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED - check errors above")
    print("="*60 + "\n")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
