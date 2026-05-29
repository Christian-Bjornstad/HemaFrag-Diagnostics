from pathlib import Path

from scripts.run_flt3_liz500_qc_all_injections import (
    _apply_user_good_override,
    _apply_user_review_override,
    _filter_candidate_files,
    _is_operator_error_flt3_file,
    _matches_user_good_override,
    _matches_user_review_override,
)


def test_mp1_operator_error_files_are_excluded_from_rox500_qc():
    assert _is_operator_error_flt3_file(Path("MP1_A05_C990RI16.fsa"))
    assert _is_operator_error_flt3_file(Path("mp1_h12_C990RI16.fsa"))
    assert _is_operator_error_flt3_file(Path("25OUM04778_p1_RATIO__250324_A04_H9C0VADZ.fsa"))
    assert _is_operator_error_flt3_file(Path("25OUM11534_p2_TKD-kutting__240725_B05_H9C0VC6E.fsa"))
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2025/2025_08_11_FLT3_ef_H9C0ZIZ2_2025-08-11_0067/25OUM12104_p1_ITD-ufort__080825_A01_H9C0ZIZ2.fsa")
    )
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2026/2026_04_23_FLT3_JO_H9H1DIAH_2026-04-24_0720/25OUMXXX_A07_H9H1DIAH.fsa")
    )
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2026/2026_04_28_FLT3_JO_C99174FF_2026-04-28_0727/25OUMXXX_A06_C99174FF.fsa")
    )
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2026/2026_04_30_FLT3_JO_C99174FA_2026-04-30_0736/25OUMXXX_A08_C99174FA.fsa")
    )
    assert not _is_operator_error_flt3_file(
        Path("/data/flt3/2026/2026_05_12_FLT3_PR_C99174J5_2026-05-13_0772/26OUM07484_D835__120526_A05_C99174J5.fsa")
    )
    assert not _is_operator_error_flt3_file(
        Path("/data/flt3/2026/2026_05_22_FLT3_PR_H9H1DHU1_2026-05-22_0800/26OUM07981_D835__210526_A05_H9H1DHU1.fsa")
    )
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2025/2025_08_01_FLT3_ef_H9C0ZIZJ_2025-08-01_0039/25OUM11314_p2_RATIO__310725_F04_H9C0ZIZJ.fsa")
    )
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2025/2025_09_03_FLT3_NPM1_PR_H9C0ZJEZ_2025-09-03_0121/25OUM13314_NPM1_X10_020925_F04_H9C0ZJEZ.fsa")
    )
    assert _is_operator_error_flt3_file(
        Path("/data/flt3/2025/2025_08_27_FLT3_ra_C990WO66_2025-08-27_0101/25OUM12881_itd-Ratio__250825_F04_C990WO66.fsa")
    )
    assert not _is_operator_error_flt3_file(Path("25OUM04778_p1_ITD_ufort__250324_A01_H9C0VADY.fsa"))
    assert not _is_operator_error_flt3_file(
        Path("/data/flt3/2025/2025_08_11_FLT3_ef2_C990WO69_2025-08-11_0068/25OUM12104_p1_ITD-ufort__080825_A01_C990WO69.fsa")
    )


def test_operator_error_filter_runs_before_limit():
    root = Path("/data/flt3")
    paths = [
        root / "2024" / "run" / "MP1_A05_C990RI16.fsa",
        root / "2024" / "run" / "25OUM04778_p1_ITD_ufort__250324_A01_H9C0VADY.fsa",
    ]

    assert _filter_candidate_files(paths, root, years=["2024"], limit=1) == [paths[1]]


def test_user_good_overrides_pass_without_excluding_file():
    path = Path(
        "/data/flt3/2025/2025_08_11_FLT3_ef2_C990WO69_2025-08-11_0068/NTC_ITD-ufort__080825_F01_C990WO69.fsa"
    )
    assert not _is_operator_error_flt3_file(path)
    reason = _matches_user_good_override(path)
    assert reason == "user_good_review_2026-05-26"

    row = _apply_user_good_override(
        {
            "QCStatus": "REVIEW",
            "QCReason": "peak_qc_failed",
            "LadderQC": "review_required",
            "ReviewReason": "proposal noise",
        },
        reason,
    )

    assert row["QCStatus"] == "PASS"
    assert row["QCReason"] == "user_good_review_2026-05-26"
    assert row["LadderQC"] == "ok"
    assert row["ReviewReason"] == ""


def test_user_review_overrides_convert_analysis_failed_to_review():
    path = Path(
        "/data/flt3/2026/2026_04_22_FLT3_PR_H9H1DIAK_2026-04-22_0710/26OUM06102_D835__200426_A05_H9H1DIAK.fsa"
    )
    assert not _is_operator_error_flt3_file(path)
    reason = _matches_user_review_override(path)
    assert reason == "user_minor_review_2026-05-26"

    row = _apply_user_review_override(
        {
            "QCStatus": "FAIL",
            "QCReason": "analysis_failed",
            "LadderQC": "analysis_failed",
            "ReviewReason": "",
        },
        reason,
    )

    assert row["QCStatus"] == "REVIEW"
    assert row["QCReason"] == "user_minor_review_2026-05-26"
    assert row["LadderQC"] == "review_required"
    assert row["ReviewReason"] == "user_minor_review_2026-05-26"


def test_user_review_override_for_26oum07484_keeps_file_in_review():
    path = Path(
        "/data/flt3/2026/2026_05_12_FLT3_PR_C99174J5_2026-05-13_0772/26OUM07484_D835__120526_A05_C99174J5.fsa"
    )
    assert not _is_operator_error_flt3_file(path)
    assert _matches_user_review_override(path) == "user_minor_review_2026-05-29"

    duplicate_injection = Path(
        "/data/flt3/2026/2026_05_12_FLT3_PR_C99174J5_2026-05-13_0773/26OUM07484_D835__120526_A05_C99174J5.fsa"
    )
    assert not _is_operator_error_flt3_file(duplicate_injection)
    assert _matches_user_review_override(duplicate_injection) == "user_minor_review_2026-05-29"


def test_26oum07981_is_not_excluded_after_manual_review():
    path = Path(
        "/data/flt3/2026/2026_05_22_FLT3_PR_H9H1DHU1_2026-05-22_0800/26OUM07981_D835__210526_A05_H9H1DHU1.fsa"
    )
    assert not _is_operator_error_flt3_file(path)
    assert _matches_user_review_override(path) == ""
