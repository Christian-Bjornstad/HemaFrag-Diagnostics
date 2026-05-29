"""User-reviewed FLT3 ROX500 files/runs to skip before validation QC.

These are human/operator/data-quality failures, not ladder-fitting training
cases. The runner applies them before `--limit` so they do not consume future
validation slots or reappear in review panels.
"""

from __future__ import annotations


FLT3_ROX500_REVIEW_EXCLUSIONS: tuple[tuple[str, str, str], ...] = (
    ("2025_08_01_FLT3_ef_H9C0ZIZJ_2025-08-01_0039", "25OUM11314_p2_RATIO__310725_F04_H9C0ZIZJ.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_01_FLT3_ef_H9C0ZIZJ_2025-08-01_0040", "25OUM11314_p2_RATIO__310725_F04_H9C0ZIZJ.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_04_FLT3_ITD_TKD_ef_pr_H9C0ZIZF_2025-08-04_0041", "NTC_TKD_kutting__010825_F04_H9C0ZIZF.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_04_FLT3_ITD_TKD_ef_pr_H9C0ZIZF_2025-08-04_0042", "NTC_TKD_kutting__010825_F04_H9C0ZIZF.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_07_FLT3_ITD_TKD_pr_ef_H9C0ZIZ8_2025-08-07_0059", "IVS-P001_TKD_kutting__060825_F04_H9C0ZIZ8.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_07_FLT3_ITD_TKD_pr_ef_H9C0ZIZ8_2025-08-07_0060", "IVS-P001_TKD_kutting__060825_F04_H9C0ZIZ8.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_11_FLT3_ef2_C990WO69_2025-08-11_0068", "NTC_TKD_KUTTING__080825_F04_C990WO69.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_11_FLT3_ef_H9C0ZIZ2_2025-08-11_0067", "*", "rox_tail_missing_after_3500_review_2026-05-26"),
    ("2025_08_14_FLT3_PR_C990WO65_2025-08-14_0074", "25OUM12253_RATIO__130825_A03_C990WO65.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_14_FLT3_PR_C990WO65_2025-08-14_0075", "25OUM12253_RATIO__130825_A03_C990WO65.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_27_FLT3_ra_C990WO66_2025-08-27_0100", "25OUM12881_itd-Ratio__250825_F04_C990WO66.fsa", "operator_data_review_2026-05-26"),
    ("2025_08_27_FLT3_ra_C990WO66_2025-08-27_0101", "25OUM12881_itd-Ratio__250825_F04_C990WO66.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_01_FLT3_ra_H9C0ZJF6_2025-09-01_0112", "25OUM13249_Itd_Ratio__290825_F04_H9C0ZJF6.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_03_FLT3_NPM1_PR_H9C0ZJEZ_2025-09-03_0121", "25OUM13314_ITD__020925_B01_H9C0ZJEZ.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_03_FLT3_NPM1_PR_H9C0ZJEZ_2025-09-03_0121", "25OUM13314_NPM1_X10_020925_F04_H9C0ZJEZ.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_03_FLT3_NPM1_PR_H9C0ZJEZ_2025-09-03_0122", "25OUM13314_NPM1_X10_020925_F04_H9C0ZJEZ.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_05_FLT3_PR4_C990WOJA_2025-09-05_0128", "25OUM13468_D835__050925_F04_C990WOJA.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_05_FLT3_PR4_C990WOJA_2025-09-05_0129", "25OUM13468_D835__050925_F04_C990WOJA.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_17_FLT3_ra_C990WOCK_2025-09-17_0151", "25OUM13823_Itd-Ratio__160925_F04_C990WOCK.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_17_FLT3_ra_C990WOCK_2025-09-17_0152", "25OUM13823_Itd-Ratio__160925_F04_C990WOCK.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_29_FLT3_ef_H9C0VCLS_2025-09-29_0185", "25OUM14617_p2_RATIO__260925_F04_H9C0VCLS.fsa", "operator_data_review_2026-05-26"),
    ("2025_09_29_FLT3_ef_H9C0VCLS_2025-09-29_0186", "25OUM14617_p2_RATIO__260925_F04_H9C0VCLS.fsa", "operator_data_review_2026-05-26"),
    ("2026_04_23_FLT3_JO_H9H1DIAH_2026-04-24_0720", "*", "operator_data_review_2026-05-26"),
    ("2026_04_23_FLT3_JO_H9H1DIAH_2026-04-24_0721", "*", "operator_data_review_2026-05-26"),
    ("2026_04_28_FLT3_JO_C99174FF_2026-04-28_0727", "*", "operator_data_review_2026-05-29"),
    ("2026_04_28_FLT3_JO_C99174FF_2026-04-28_0728", "*", "operator_data_review_2026-05-29"),
    ("2026_04_30_FLT3_JO_C99174FA_2026-04-30_0735", "*", "operator_data_review_2026-05-29"),
    ("2026_04_30_FLT3_JO_C99174FA_2026-04-30_0736", "*", "operator_data_review_2026-05-29"),
)


FLT3_ROX500_USER_GOOD_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    ("2026_04_22_FLT3_PR_H9H1DIAK_2026-04-22_0711", "26OUM06102_D835__200426_A05_H9H1DIAK.fsa", "user_good_review_2026-05-26"),
    ("2025_08_11_FLT3_ef2_C990WO69_2025-08-11_0068", "NTC_ITD-ufort__080825_F01_C990WO69.fsa", "user_good_review_2026-05-26"),
    ("2025_08_27_FLT3_ra_C990WO66_2025-08-27_0100", "25OUM12394_ITD__250825_A01_C990WO66.fsa", "user_good_review_2026-05-26"),
    ("2025_11_07_FLT3_EF_PR2_H920FZZ0_2025-11-10_0317", "25OUM17217_p2_ITD_X25__061125_D03_H920FZZ0.fsa", "user_good_review_2026-05-26"),
    ("2025_11_17_FLT3_EF_PR_C92141S0_2025-11-17_0336", "25OUM17294_ITD_X25__171125_A05_C92141S0.fsa", "user_good_review_2026-05-26"),
    ("2025_12_23_FLT3_NH_H9C0VCER_2025-12-23_0436", "25OUM20129_p2_ITD_10__231225_A04_H9C0VCER.fsa", "user_good_review_2026-05-26"),
    ("2026_04_16_FLT3_JO_H9H1DIB3_2026-04-16_0699", "26OUM05975_NPM1_B04_H9H1DIB3.fsa", "user_good_review_2026-05-26"),
)


FLT3_ROX500_USER_REVIEW_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    ("2026_04_22_FLT3_PR_H9H1DIAK_2026-04-22_0710", "26OUM06102_D835__200426_A05_H9H1DIAK.fsa", "user_minor_review_2026-05-26"),
    ("2026_05_12_FLT3_PR_C99174J5_2026-05-13_0772", "26OUM07484_D835__120526_A05_C99174J5.fsa", "user_minor_review_2026-05-29"),
    ("2026_05_12_FLT3_PR_C99174J5_2026-05-13_0773", "26OUM07484_D835__120526_A05_C99174J5.fsa", "user_minor_review_2026-05-29"),
)
