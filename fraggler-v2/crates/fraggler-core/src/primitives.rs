use std::collections::BTreeMap;
use std::time::Instant;

use camino::Utf8Path;
use serde::{Deserialize, Serialize};

use crate::abif::AbifRecord;
use crate::contract::AnalysisKind;
use crate::engine::EngineError;
use crate::ladders::LadderKind;
use crate::signal::{
    Peak, baseline_correct_guarded_nonnegative, baseline_correct_min_window_nonnegative,
    baseline_correct_morph_open_nonnegative, baseline_correct_quantile_nonnegative,
    baseline_correct_snip_nonnegative, find_peaks, moving_average_smooth,
};

const MAX_CANDIDATE_COMBINATIONS: usize = 2_000_000;
const BEAM_SEARCH_TRIGGER_COMBINATIONS: usize = 100_000;
const LIZ_BEAM_SEARCH_TRIGGER_COMBINATIONS: usize = 4_000;
const LIZ_EXACT_AUDIT_ENV: &str = "HEMAFRAG_LADDER_AUDIT_EXACT_LIZ";
const LIZ_FULL_REPAIR_AUDIT_ENV: &str = "HEMAFRAG_LADDER_AUDIT_FULL_LIZ_REPAIRS";
const CAPPED_FULL_POOL_BEAM_AUDIT_ENV: &str = "HEMAFRAG_LADDER_AUDIT_CAPPED_FULL_POOL_BEAM";
const BEAM_SEARCH_WIDTH: usize = 192;
const LIZ_BEAM_SEARCH_WIDTH: usize = 512;
const BEAM_SEARCH_FINAL_CAP: usize = 4096;
const LIZ_EXACT_RERUN_MAX_COMBINATIONS: usize = 10_000;
const LIZ_SUSPICIOUS_LINEAR_MAX_BP: f64 = 13.5;
const LIZ_SUSPICIOUS_LINEAR_MEAN_BP: f64 = 6.8;
const LIZ_SUSPICIOUS_LINEAR_R2_MIN: f64 = 0.9973;
const LADDER_MAX_GAP_EXPANSIONS: usize = 30;
const LADDER_GAP_EXPANSION_STEP: usize = 10;
const MAX_REFINEMENT_STEPS: usize = 3;
const MAX_REFINEMENT_OPTIONS_PER_STEP: usize = 5;
const MIN_REFINEMENT_TRIGGER_BP: f64 = 0.75;
const MAX_REFINEMENT_RADIUS_SCANS: f64 = 120.0;
const LADDER_DOMAIN_TIME_WEIGHT: f64 = 3.00;
const LADDER_DOMAIN_GAP_WEIGHT: f64 = 0.15;
const LADDER_DOMAIN_INTENSITY_WEIGHT: f64 = 0.10;
const LADDER_DOMAIN_FIRST_ANCHOR_WEIGHT: f64 = 1.50;
const ROX_HARD_TIME_MIN: f64 = 1300.0;
const ROX_HARD_TIME_MAX: f64 = 4300.0;
const ROX_PREFERRED_TIME_MIN: f64 = 1500.0;
const ROX_PREFERRED_TIME_MAX: f64 = 4000.0;
const ROX_MAX_FIRST_ANCHOR: f64 = 1900.0;
const GS500ROX_HARD_TIME_MIN: f64 = 1380.0;
const GS500ROX_HARD_TIME_MAX: f64 = 4550.0;
const GS500ROX_ABSOLUTE_TIME_MIN: f64 = 1300.0;
const GS500ROX_ABSOLUTE_TIME_MAX: f64 = 6000.0;
const GS500ROX_PREFERRED_TIME_MIN: f64 = 1490.0;
const GS500ROX_PREFERRED_TIME_MAX: f64 = 4425.0;
const GS500ROX_MAX_FIRST_ANCHOR: f64 = 1700.0;
const LIZ_HARD_TIME_MIN: f64 = 1150.0;
const LIZ_HARD_TIME_MAX: f64 = 5000.0;
const LIZ_SELECTED_LATE_REVIEW_SCAN: usize = 5000;
const LIZ_DEFAULT_LANE_TIME_MAX: usize = 4380;
const LIZ_BLOB_LANE_TIME_MAX: usize = 5000;
const LIZ_PREFERRED_TIME_MIN: f64 = 1250.0;
const LIZ_PREFERRED_TIME_MAX: f64 = 4100.0;
const LIZ_MAX_FIRST_ANCHOR: f64 = 1700.0;
const COMPLETE_FIT_REVIEW_WAIVER_MIN_R2: f64 = 0.9999;
const COMPLETE_FIT_REVIEW_WAIVER_MAX_MEAN_ABS_ERROR_BP: f64 = 0.25;
const COMPLETE_FIT_REVIEW_WAIVER_MAX_ABS_ERROR_BP: f64 = 0.50;
const LINEAR_TREND_MEAN_TARGET_BP: f64 = 1.50;
const LINEAR_TREND_MAX_TARGET_BP: f64 = 4.00;
const LINEAR_TREND_MEAN_WEIGHT: f64 = 0.18;
const LINEAR_TREND_MAX_WEIGHT: f64 = 0.10;
const LINEAR_TREND_R2_TARGET: f64 = 0.9990;
const LINEAR_TREND_R2_WEIGHT: f64 = 120.0;
const ROX_REVIEW_LINEAR_MEAN_BP: f64 = 3.0;
const ROX_REVIEW_LINEAR_MAX_BP: f64 = 8.0;
const ROX_REVIEW_LINEAR_R2_MIN: f64 = 0.9980;
const GS500ROX_REVIEW_LINEAR_MEAN_BP: f64 = 3.0;
const GS500ROX_REVIEW_LINEAR_MAX_BP: f64 = 6.0;
const GS500ROX_REVIEW_LINEAR_R2_MIN: f64 = 0.9985;
const ROX_COMPLETE_FIT_WAIVER_LINEAR_MEAN_BP: f64 = 3.6;
const ROX_COMPLETE_FIT_WAIVER_LINEAR_MAX_BP: f64 = 7.6;
const ROX_COMPLETE_FIT_WAIVER_LINEAR_R2_MIN: f64 = 0.9985;
const ROX_NONLINEAR_COMPLETE_WAIVER_LINEAR_MEAN_BP: f64 = 5.7;
const ROX_NONLINEAR_COMPLETE_WAIVER_LINEAR_MAX_BP: f64 = 13.0;
const ROX_NONLINEAR_COMPLETE_WAIVER_LINEAR_R2_MIN: f64 = 0.9963;
const ROX_NONLINEAR_COMPLETE_WAIVER_QUAD_MEAN_BP: f64 = 1.25;
const ROX_NONLINEAR_COMPLETE_WAIVER_QUAD_MAX_BP: f64 = 2.6;
const ROX_NONLINEAR_COMPLETE_WAIVER_QUAD_R2_MIN: f64 = 0.99980;
const LIZ_REVIEW_LINEAR_MEAN_BP: f64 = 4.5;
const LIZ_REVIEW_LINEAR_MAX_BP: f64 = 10.0;
const LIZ_REVIEW_LINEAR_R2_MIN: f64 = 0.9985;
const ROX_LINEAR_HARDCASE_MEAN_WEIGHT: f64 = 0.80;
const ROX_LINEAR_HARDCASE_MAX_WEIGHT: f64 = 0.55;
const ROX_LINEAR_HARDCASE_R2_WEIGHT: f64 = 450.0;
const BLOCK_REPAIR_LINEAR_MEAN_TRIGGER_BP: f64 = 2.50;
const BLOCK_REPAIR_LINEAR_MAX_TRIGGER_BP: f64 = 6.00;
const BLOCK_REPAIR_MAX_CANDIDATES: usize = 12;
const BLOCK_REPAIR_EARLY_LIZ_RADIUS_SCANS: f64 = 260.0;
const BLOCK_REPAIR_TAIL_LIZ_RADIUS_SCANS: f64 = 220.0;
const BLOCK_REPAIR_DEFAULT_RADIUS_SCANS: f64 = 180.0;
const BLOCK_REPAIR_MAX_COMBINATIONS: usize = 4096;
const LIZ_LINEAR_FIRST_START_REPAIR_MAX_COMBINATIONS: usize = 12000;
const LIZ_LINEAR_FIRST_START_REPAIR_MAX_EARLY_PEAKS: usize = 20;
const LIZ_STRONG_MEDIAN_FAMILY_BEAM: usize = 800;
const LIZ_STRONG_MEDIAN_FAMILY_FINALISTS: usize = 200;
const LIZ_BLOB_START_FAMILY_BEAM: usize = 800;
const LIZ_BLOB_START_FAMILY_FINALISTS: usize = 240;
const ROX_STRONG_MEDIAN_FAMILY_BEAM: usize = 800;
const ROX_STRONG_MEDIAN_FAMILY_FINALISTS: usize = 200;
const APEX_RECENTER_LINEAR_MAX_GUARD_BP: f64 = 6.0;
const APEX_RECENTER_LINEAR_MEAN_GUARD_BP: f64 = 5.0;
const LIZ_APEX_RECENTER_LINEAR_MAX_GUARD_BP: f64 = 8.5;
const LIZ_APEX_RECENTER_LINEAR_MEAN_GUARD_BP: f64 = 3.8;
const LIZ_APEX_RECENTER_RADIUS_SCANS: usize = 32;
const ROX_APEX_RECENTER_RADIUS_SCANS: usize = 28;
const LIZ_APEX_GAP_MEDIAN: [f64; 15] = [
    76.0, 148.0, 139.0, 223.0, 56.0, 57.0, 234.0, 283.0, 312.0, 231.0, 59.0, 303.0, 278.0, 226.0,
    46.0,
];
const LIZ_APEX_GAP_P10: [f64; 15] = [
    73.0, 142.0, 136.0, 217.0, 55.0, 56.0, 227.0, 277.0, 300.0, 224.0, 56.0, 290.2, 268.0, 219.0,
    45.0,
];
const LIZ_APEX_GAP_P90: [f64; 15] = [
    81.0, 156.0, 148.0, 236.0, 60.0, 60.0, 247.8, 301.0, 328.0, 243.8, 62.0, 318.8, 295.8, 240.0,
    50.0,
];
const LIZ_BROAD_GAP_MEDIAN: [f64; 15] = [
    77.0, 147.0, 140.0, 224.0, 57.0, 58.0, 236.0, 289.0, 315.0, 235.0, 59.0, 306.0, 280.0, 228.0,
    47.0,
];
const LIZ_BROAD_GAP_P10: [f64; 15] = [
    74.0, 142.0, 137.0, 218.0, 55.0, 56.0, 228.0, 278.0, 302.0, 225.0, 57.0, 293.0, 270.0, 220.0,
    45.0,
];
const LIZ_BROAD_GAP_P90: [f64; 15] = [
    80.0, 154.0, 145.0, 233.0, 59.0, 60.0, 245.0, 299.0, 329.0, 244.0, 62.0, 319.0, 291.0, 237.0,
    49.0,
];
const ROX_BROAD_GAP_MEDIAN: [f64; 20] = [
    53.0, 161.0, 57.0, 108.0, 170.0, 57.0, 113.0, 57.0, 57.0, 118.0, 115.0, 118.0, 119.0, 59.0,
    59.0, 118.0, 117.5, 118.0, 116.0, 115.0,
];
const SAMPLE_ASSAY_GROUP_DISTANCE_BP: f64 = 12.0;
const SAMPLE_ASSAY_MIN_RATIO: f64 = 0.40;
const SAMPLE_PEAK_PREVIEW_LIMIT: usize = 32;
const CLONAL_MAX_LABELLED_PEAKS: usize = 3;
const CLONAL_DOMINANCE_RATIO: f64 = 1.7;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LadderFitPreview {
    pub search_tier: String,
    pub max_allowed_peak_gap: usize,
    pub gap_expansions: usize,
    pub estimated_combination_count: usize,
    pub candidate_generation_capped: bool,
    pub evaluated_combination_count: usize,
    pub best_scan_indices: Vec<usize>,
    pub best_curvature_score: Option<f64>,
    pub best_quadratic_r2: Option<f64>,
    pub sizing_model: Option<SizingModelPreview>,
    pub refinement: Option<RefinementPreview>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SizingModelPreview {
    pub strategy: String,
    pub degree: usize,
    pub coefficients: Vec<f64>,
    pub predicted_ladder_basepairs: Vec<f64>,
    pub qc_metrics: LadderQcMetrics,
    pub sample_mapping: Option<SampleMappingPreview>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RefinementPreview {
    pub changed_step_indices: Vec<usize>,
    pub original_scan_indices: Vec<usize>,
    pub refined_scan_indices: Vec<usize>,
    pub refined_curvature_score: f64,
    pub refined_quadratic_r2: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SampleMappingPreview {
    pub points_retained: usize,
    pub min_basepair: f64,
    pub max_basepair: f64,
    pub monotonic_unique: bool,
    pub preview: Vec<SampleMappingPoint>,
    pub sample_peak_preview: Vec<SamplePeakPreview>,
    pub assay_group_preview: Vec<SamplePeakGroupPreview>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SampleMappingPoint {
    pub time: usize,
    pub intensity: f64,
    pub basepair: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SamplePeakPreview {
    pub time: usize,
    pub intensity: f64,
    pub basepair: f64,
    pub area: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SamplePeakGroupPreview {
    pub group_id: usize,
    pub start_basepair: f64,
    pub end_basepair: f64,
    pub cluster_width_bp: f64,
    pub max_intensity: f64,
    pub dominant_peak_basepair: f64,
    pub dominant_peak_intensity: f64,
    pub dominant_peak_area: f64,
    pub dominant_ratio_vs_second: Option<f64>,
    pub kept_peak_count: usize,
    pub clonal_candidate: bool,
    pub peaks: Vec<SamplePeakPreview>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LadderQcMetrics {
    pub r2: f64,
    pub mean_abs_error_bp: f64,
    pub max_abs_error_bp: f64,
    pub linear_trend_mean_abs_error_bp: f64,
    pub linear_trend_max_abs_error_bp: f64,
    pub linear_trend_r2: f64,
    pub quadratic_trend_mean_abs_error_bp: f64,
    pub quadratic_trend_max_abs_error_bp: f64,
    pub quadratic_trend_r2: f64,
    pub monotonic_on_ladder: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LadderReviewAssessment {
    pub suggested_review: bool,
    pub primary_reason: Option<String>,
    pub reason_codes: Vec<String>,
    pub summary: String,
    pub first_anchor_time: Option<f64>,
    pub last_anchor_time: Option<f64>,
    pub anchor_span: Option<f64>,
    pub estimated_combination_count: Option<usize>,
    pub evaluated_combination_count: Option<usize>,
    pub best_curvature_score: Option<f64>,
    pub max_abs_error_bp: Option<f64>,
    pub selected_baseline_like_anchor_count: usize,
    pub selected_cleaner_neighbor_count: usize,
    pub selected_strong_baseline_anchor_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PrimitiveAnalysisResult {
    pub file_name: String,
    pub scan_count: usize,
    pub data_channels: Vec<String>,
    pub dye_names: BTreeMap<String, String>,
    pub ladder: String,
    pub sample_channel_guess: String,
    pub size_standard_channel_guess: String,
    pub ladder_peak_count: usize,
    pub ladder_peak_preview: Vec<Peak>,
    pub ladder_fit_preview: Option<LadderFitPreview>,
    pub ladder_review_assessment: LadderReviewAssessment,
    pub clonality_preview: Option<ClonalityPreview>,
    pub flt3_preview: Option<Flt3Preview>,
    pub timings_us: BTreeMap<String, u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ClonalityPreview {
    pub sample_channel: String,
    pub ranked_assays: Vec<ClonalityAssayMatch>,
    pub channel_peak_previews: BTreeMap<String, Vec<SamplePeakPreview>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ClonalityAssayMatch {
    pub assay_name: String,
    pub channels: Vec<String>,
    pub assay_bp_min: f64,
    pub assay_bp_max: f64,
    pub matched_by_filename: bool,
    pub compatible_channel: bool,
    pub score: f64,
    pub clonal_group_count: usize,
    pub best_dominant_ratio: Option<f64>,
    pub matched_groups: Vec<ClonalityGroupMatch>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ClonalityGroupMatch {
    pub group_id: usize,
    pub overlap_start_bp: f64,
    pub overlap_end_bp: f64,
    pub peak_count: usize,
    pub cluster_width_bp: f64,
    pub dominant_peak_basepair: f64,
    pub dominant_peak_intensity: f64,
    pub dominant_peak_area: f64,
    pub dominant_ratio_vs_second: Option<f64>,
    pub clonal_candidate: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Flt3Preview {
    pub assay_name: String,
    pub matched_by_filename: bool,
    pub compatible_channel: bool,
    pub assay_bp_min: f64,
    pub assay_bp_max: f64,
    pub wt_peak: Option<SamplePeakPreview>,
    pub mutant_peaks: Vec<SamplePeakPreview>,
    pub strongest_mutant_ratio: Option<f64>,
    pub positive_call: bool,
}

#[derive(Debug, Clone, Copy)]
struct Flt3AssayDef {
    name: &'static str,
    channels: &'static [&'static str],
    bp_min: f64,
    bp_max: f64,
    wt_bp: f64,
    wt_tolerance_bp: f64,
    mutant_bp_min: f64,
    mutant_bp_max: f64,
    positive_ratio: f64,
    aliases: &'static [&'static str],
}

pub fn analyze_fsa_primitives(
    path: &Utf8Path,
    analysis_kind: Option<&AnalysisKind>,
) -> Result<PrimitiveAnalysisResult, EngineError> {
    let total_started = Instant::now();
    let parse_started = Instant::now();
    let record = AbifRecord::from_path(path)?;
    let abif_parse_us = elapsed_micros_u64(parse_started);

    let channel_setup_started = Instant::now();
    let file_name = record.file_name.clone();
    let data_channels = record.data_channels();
    let size_standard_channel = select_size_standard_channel(&record, &file_name, analysis_kind)
        .ok_or_else(|| EngineError::PrimitiveAnalysis {
            message: "no usable size-standard channel was found in the ABIF record".to_owned(),
        })?;
    let sample_channel = preferred_sample_channel(
        &data_channels,
        &size_standard_channel,
        &file_name,
        analysis_kind,
    )
    .unwrap_or_else(|| {
        data_channels
            .iter()
            .find(|channel| channel.as_str() != size_standard_channel)
            .cloned()
            .unwrap_or_else(|| size_standard_channel.clone())
    });

    let ladder = suggested_ladder_kind(&record, &file_name, &size_standard_channel, analysis_kind);
    let raw_min_height = match ladder {
        LadderKind::Liz500250 => 150.0,
        // ROX traces in clonality are prone to dense late noise clusters.
        // A stricter floor keeps true ladder peaks while suppressing blob tails.
        LadderKind::Rox400Hd => 180.0,
        LadderKind::Gs500Rox => 120.0,
    };
    // Baseline correction compresses peak amplitudes, so use a softer floor
    // on the corrected trace while still keeping obvious baseline chatter out.
    let corrected_min_height = (raw_min_height * 0.55_f64).max(50.0_f64);
    let min_distance = match ladder {
        LadderKind::Liz500250 => 15,
        LadderKind::Rox400Hd => 14,
        LadderKind::Gs500Rox => 15,
    };

    let size_standard_trace = record
        .channel_values(&size_standard_channel)
        .ok_or_else(|| EngineError::PrimitiveAnalysis {
            message: format!(
                "size-standard channel {size_standard_channel} is missing numeric data"
            ),
        })?;
    let sample_trace =
        record
            .channel_values(&sample_channel)
            .ok_or_else(|| EngineError::PrimitiveAnalysis {
                message: format!("sample channel {sample_channel} is missing numeric data"),
            })?;
    let channel_trace_setup_us = elapsed_micros_u64(channel_setup_started);

    let baseline_started = Instant::now();
    let corrected =
        baseline_correct_guarded_nonnegative(&size_standard_trace, 0.99, 100.0, 1000, 200, 0.10)?;
    let quantile_corrected = baseline_correct_quantile_nonnegative(&size_standard_trace, 200, 0.10);
    let morph_corrected = if matches!(ladder, LadderKind::Liz500250 | LadderKind::Gs500Rox) {
        baseline_correct_morph_open_nonnegative(&size_standard_trace, 151)
    } else {
        Vec::new()
    };
    let snip_corrected = if matches!(ladder, LadderKind::Liz500250 | LadderKind::Gs500Rox) {
        baseline_correct_snip_nonnegative(&size_standard_trace, 40)
    } else {
        Vec::new()
    };
    let baseline_correction_us = elapsed_micros_u64(baseline_started);

    let candidate_detection_started = Instant::now();
    let mut default_ladder_peaks = select_ladder_peaks(
        &size_standard_trace,
        &corrected,
        &quantile_corrected,
        &morph_corrected,
        &snip_corrected,
        raw_min_height,
        corrected_min_height,
        min_distance,
        ladder.expected_peak_count() * 2 + 15,
        ladder.expected_peak_count(),
        ladder,
    );
    if ladder == LadderKind::Rox400Hd {
        let minwin_corrected = baseline_correct_min_window_nonnegative(&size_standard_trace, 51);
        let minwin_light_corrected = moving_average_smooth(&minwin_corrected, 2);
        let tail_rescue = rox_minwin_tail_extension_candidates(
            &minwin_light_corrected,
            ladder.expected_peak_count(),
        );
        if !tail_rescue.is_empty() {
            default_ladder_peaks = merge_candidate_sets(
                &[default_ladder_peaks, tail_rescue],
                5,
                ladder.expected_peak_count() * 2 + 20,
            );
        }
    }
    let alternative_lanes = if ladder == LadderKind::Liz500250 {
        Vec::new()
    } else {
        build_alternative_ladder_peak_lanes(
            &size_standard_trace,
            &corrected,
            &quantile_corrected,
            &morph_corrected,
            &snip_corrected,
            raw_min_height,
            corrected_min_height,
            min_distance,
            ladder,
        )
    };
    let candidate_detection_us = elapsed_micros_u64(candidate_detection_started);

    let dye_names = dye_names(&record);
    let ladder_fit_started = Instant::now();
    let (ladder_peaks, ladder_fit_preview) = build_ladder_fit_preview_with_arbiter(
        default_ladder_peaks,
        alternative_lanes,
        &sample_trace,
        &size_standard_trace,
        ladder,
    );
    let ladder_fit_us = elapsed_micros_u64(ladder_fit_started);

    let review_started = Instant::now();
    let ladder_review_assessment =
        build_ladder_review_assessment(ladder, &ladder_peaks, ladder_fit_preview.as_ref());
    let review_assessment_us = elapsed_micros_u64(review_started);

    let downstream_preview_started = Instant::now();
    let clonality_preview = if matches!(analysis_kind, Some(AnalysisKind::Clonality)) {
        ladder_fit_preview.as_ref().and_then(|preview| {
            preview
                .sizing_model
                .as_ref()
                .and_then(|model| model.sample_mapping.as_ref())
                .map(|mapping| {
                    let channel_peak_previews = build_channel_peak_previews(
                        &record,
                        &data_channels,
                        &size_standard_channel,
                        ladder,
                        preview,
                    );
                    build_clonality_preview(
                        &file_name,
                        &sample_channel,
                        &mapping.assay_group_preview,
                        channel_peak_previews,
                    )
                })
        })
    } else {
        None
    };
    let flt3_preview = if matches!(analysis_kind, Some(AnalysisKind::Flt3)) {
        ladder_fit_preview.as_ref().and_then(|preview| {
            preview
                .sizing_model
                .as_ref()
                .and_then(|model| model.sample_mapping.as_ref())
                .map(|mapping| {
                    build_flt3_preview(&file_name, &sample_channel, &mapping.sample_peak_preview)
                })
        })
    } else {
        None
    };
    let downstream_preview_us = elapsed_micros_u64(downstream_preview_started);
    let total_us = elapsed_micros_u64(total_started);
    let timings_us = BTreeMap::from([
        ("abif_parse".to_owned(), abif_parse_us),
        ("baseline_correction".to_owned(), baseline_correction_us),
        ("candidate_detection".to_owned(), candidate_detection_us),
        ("channel_trace_setup".to_owned(), channel_trace_setup_us),
        ("downstream_preview".to_owned(), downstream_preview_us),
        ("ladder_fit".to_owned(), ladder_fit_us),
        ("review_assessment".to_owned(), review_assessment_us),
        ("total".to_owned(), total_us),
    ]);

    Ok(PrimitiveAnalysisResult {
        file_name,
        scan_count: size_standard_trace.len(),
        data_channels,
        dye_names,
        ladder: ladder.display_name().to_owned(),
        sample_channel_guess: sample_channel,
        size_standard_channel_guess: size_standard_channel,
        ladder_peak_count: ladder_peaks.len(),
        ladder_peak_preview: ladder_peaks,
        ladder_fit_preview,
        ladder_review_assessment,
        clonality_preview,
        flt3_preview,
        timings_us,
    })
}

fn elapsed_micros_u64(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn build_ladder_review_assessment(
    ladder: LadderKind,
    ladder_peaks: &[Peak],
    preview: Option<&LadderFitPreview>,
) -> LadderReviewAssessment {
    let (preferred_min, preferred_max, max_first_anchor, tail_margin, curvature_warn) = match ladder
    {
        LadderKind::Rox400Hd => (
            ROX_PREFERRED_TIME_MIN,
            ROX_PREFERRED_TIME_MAX,
            ROX_MAX_FIRST_ANCHOR,
            260.0,
            0.85,
        ),
        LadderKind::Gs500Rox => (
            GS500ROX_PREFERRED_TIME_MIN,
            GS500ROX_PREFERRED_TIME_MAX,
            GS500ROX_MAX_FIRST_ANCHOR,
            240.0,
            0.80,
        ),
        LadderKind::Liz500250 => (
            LIZ_PREFERRED_TIME_MIN,
            LIZ_PREFERRED_TIME_MAX,
            LIZ_MAX_FIRST_ANCHOR,
            220.0,
            0.75,
        ),
    };

    let expected_peak_count = ladder.expected_peak_count();
    let mut reason_codes: Vec<String> = Vec::new();
    let mut summary_parts: Vec<String> = Vec::new();

    let Some(preview) = preview else {
        reason_codes.push("no_fit_preview".to_owned());
        summary_parts.push("Rust did not produce a ladder fit preview.".to_owned());
        return LadderReviewAssessment {
            suggested_review: true,
            primary_reason: reason_codes.first().cloned(),
            reason_codes,
            summary: summary_parts.join(" "),
            first_anchor_time: None,
            last_anchor_time: None,
            anchor_span: None,
            estimated_combination_count: None,
            evaluated_combination_count: None,
            best_curvature_score: None,
            max_abs_error_bp: None,
            selected_baseline_like_anchor_count: 0,
            selected_cleaner_neighbor_count: 0,
            selected_strong_baseline_anchor_count: 0,
        };
    };

    let scan_indices = if let Some(refinement) = preview.refinement.as_ref() {
        if !refinement.refined_scan_indices.is_empty() {
            refinement.refined_scan_indices.clone()
        } else {
            preview.best_scan_indices.clone()
        }
    } else {
        preview.best_scan_indices.clone()
    };

    let first_anchor_time = scan_indices.first().map(|value| *value as f64);
    let last_anchor_time = scan_indices.last().map(|value| *value as f64);
    let anchor_span = match (first_anchor_time, last_anchor_time) {
        (Some(first), Some(last)) if last >= first => Some(last - first),
        _ => None,
    };
    let max_abs_error_bp = preview
        .sizing_model
        .as_ref()
        .map(|model| model.qc_metrics.max_abs_error_bp);
    let high_confidence_complete_fit =
        is_high_confidence_complete_fit(preview, scan_indices.len(), expected_peak_count);
    let mut selected_baseline_like_anchor_count = 0usize;
    let mut selected_cleaner_neighbor_count = 0usize;
    let mut selected_strong_baseline_anchor_count = 0usize;

    if preview.candidate_generation_capped {
        reason_codes.push("candidate_space_capped".to_owned());
        summary_parts.push("Candidate generation reached the configured cap.".to_owned());
    }
    if scan_indices.is_empty() {
        reason_codes.push("insufficient_candidate_coverage".to_owned());
        summary_parts.push("No ladder anchor sequence survived candidate selection.".to_owned());
    }
    if ladder_peaks.len() < expected_peak_count {
        reason_codes.push("insufficient_candidate_coverage".to_owned());
        summary_parts.push(format!(
            "Only {} ladder candidates were found for {} expected steps.",
            ladder_peaks.len(),
            expected_peak_count
        ));
    }

    if let Some(first_anchor) = first_anchor_time {
        if ladder == LadderKind::Gs500Rox && first_anchor < GS500ROX_ABSOLUTE_TIME_MIN {
            reason_codes.push("anchor_before_scan_limit".to_owned());
            summary_parts.push(format!(
                "First GS500ROX anchor landed at {:.0}, before the 1300 scan limit.",
                first_anchor
            ));
        }

        if !high_confidence_complete_fit && first_anchor > max_first_anchor {
            reason_codes.push("weak_start_region".to_owned());
            summary_parts.push(format!(
                "First anchor landed late at {:.0}, beyond the preferred start region.",
                first_anchor
            ));
        }

        let early_blob_peaks = ladder_peaks
            .iter()
            .filter(|peak| {
                let scan = peak.index as f64;
                scan < preferred_min
                    && scan <= first_anchor + 120.0
                    && peak.prominence >= 45.0
                    && peak.height >= 80.0
            })
            .count();
        if first_anchor < preferred_min && early_blob_peaks >= 2 {
            reason_codes.push("blob_dominated_start".to_owned());
            summary_parts.push("Early blob-like peaks dominate the start region.".to_owned());
        }

        let selected_prominences = scan_indices
            .iter()
            .filter_map(|scan| ladder_peaks.iter().find(|peak| peak.index == *scan))
            .map(|peak| peak.prominence)
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>();
        if !selected_prominences.is_empty() {
            let mut sorted = selected_prominences.clone();
            sorted.sort_by(|left, right| {
                left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal)
            });
            let median_prominence = sorted[sorted.len() / 2].max(1.0);
            if let Some(first_peak) = ladder_peaks
                .iter()
                .find(|peak| Some(peak.index as f64) == first_anchor_time)
            {
                if !high_confidence_complete_fit
                    && first_peak.prominence < (median_prominence * 0.40).max(25.0)
                {
                    reason_codes.push("weak_start_region".to_owned());
                    summary_parts.push(
                        "The first selected anchor is weak relative to the rest of the ladder."
                            .to_owned(),
                    );
                }
            }
        }
    }

    if ladder == LadderKind::Gs500Rox {
        if scan_indices.len() == expected_peak_count {
            if let Some(span) = anchor_span {
                if span < 2300.0 {
                    reason_codes.push("short_gs500rox_anchor_span".to_owned());
                    summary_parts.push(format!(
                        "Complete GS500ROX fit is too compressed with anchor span {:.0}.",
                        span
                    ));
                }
            }
            if let Some(last_anchor) = last_anchor_time {
                if last_anchor < 3900.0 {
                    reason_codes.push("tail_missing".to_owned());
                    summary_parts.push(format!(
                        "Complete GS500ROX fit has an early tail ending at {:.0}.",
                        last_anchor
                    ));
                }
            }
        }
        if let Some(last_anchor) = last_anchor_time {
            if last_anchor > GS500ROX_ABSOLUTE_TIME_MAX {
                reason_codes.push("anchor_beyond_scan_limit".to_owned());
                summary_parts.push(format!(
                    "Last GS500ROX anchor landed at {:.0}, beyond the 6000 scan limit.",
                    last_anchor
                ));
            }
        }
    }

    if scan_indices.len() < expected_peak_count {
        if let Some(last_anchor) = last_anchor_time {
            if last_anchor < preferred_max - tail_margin {
                reason_codes.push("tail_missing".to_owned());
                summary_parts.push(format!(
                    "The selected ladder tail stops early at {:.0}.",
                    last_anchor
                ));
            }
        }
    }

    if scan_indices.len() == expected_peak_count {
        if let Some(curvature) = preview.best_curvature_score {
            if !high_confidence_complete_fit && curvature > curvature_warn {
                reason_codes.push("high_curvature_complete_fit".to_owned());
                summary_parts.push(format!(
                    "All ladder steps were fitted, but curvature is high at {:.3}.",
                    curvature
                ));
            }
        }
    }

    if let Some(max_error) = max_abs_error_bp {
        if max_error > 3.5 {
            reason_codes.push("high_residual_fit".to_owned());
            summary_parts.push(format!(
                "Maximum ladder residual is elevated at {:.2} bp.",
                max_error
            ));
        }
    }
    if let Some(model) = preview.sizing_model.as_ref() {
        let qc = &model.qc_metrics;
        if scan_indices.len() == expected_peak_count
            && matches!(ladder, LadderKind::Rox400Hd | LadderKind::Liz500250)
        {
            let (baseline_like_count, cleaner_neighbor_count, strong_baseline_count) =
                selected_baseline_like_anchor_counts(ladder, &scan_indices, ladder_peaks);
            selected_baseline_like_anchor_count = baseline_like_count;
            selected_cleaner_neighbor_count = cleaner_neighbor_count;
            selected_strong_baseline_anchor_count = strong_baseline_count;
            let suspicious_selected_peaks = strong_baseline_count >= 1
                || baseline_like_count >= 2
                || (baseline_like_count >= 1 && cleaner_neighbor_count >= 1);
            if suspicious_selected_peaks {
                reason_codes.push("selected_baseline_like_ladder_peaks".to_owned());
                summary_parts.push(format!(
                    "{} selected ladder anchors look baseline-/foot-like despite a complete fit; {} have cleaner nearby alternatives.",
                    baseline_like_count, cleaner_neighbor_count
                ));
            }
            if ladder == LadderKind::Liz500250 {
                let (weak_liz_count, has_very_weak_tail) =
                    selected_weak_liz_anchor_counts(&scan_indices, ladder_peaks);
                if weak_liz_count >= 2 || has_very_weak_tail {
                    reason_codes.push("selected_weak_liz_ladder_peaks".to_owned());
                    summary_parts.push(format!(
                        "{} selected LIZ anchors are weak outliers relative to the ladder family.",
                        weak_liz_count
                    ));
                }
                let late_liz_count = scan_indices
                    .iter()
                    .filter(|scan| **scan > LIZ_SELECTED_LATE_REVIEW_SCAN)
                    .count();
                let clean_late_tail_waiver = late_liz_count <= 2
                    && liz_late_tail_is_clean(&scan_indices, ladder_peaks)
                    && qc.linear_trend_max_abs_error_bp <= 10.0
                    && qc.linear_trend_mean_abs_error_bp <= 4.05
                    && qc.linear_trend_r2 >= 0.99870;
                if late_liz_count > 0 && !clean_late_tail_waiver {
                    reason_codes.push("selected_late_liz_ladder_peaks".to_owned());
                    summary_parts.push(format!(
                        "{} selected LIZ anchors are beyond the expected tail window (> {} scans).",
                        late_liz_count, LIZ_SELECTED_LATE_REVIEW_SCAN
                    ));
                }
            }
        }
        if ladder == LadderKind::Rox400Hd {
            if qc.linear_trend_max_abs_error_bp > ROX_REVIEW_LINEAR_MAX_BP
                || qc.linear_trend_mean_abs_error_bp > ROX_REVIEW_LINEAR_MEAN_BP
                || qc.linear_trend_r2 < ROX_REVIEW_LINEAR_R2_MIN
            {
                reason_codes.push("poor_linear_rox_fit".to_owned());
                summary_parts.push(format!(
                    "ROX lineær QC er dårlig (max {:.2} bp, mean {:.2} bp, R2 {:.5}).",
                    qc.linear_trend_max_abs_error_bp,
                    qc.linear_trend_mean_abs_error_bp,
                    qc.linear_trend_r2
                ));
            }
            if scan_indices.len() == expected_peak_count {
                let first_anchor = scan_indices.first().copied().unwrap_or(0);
                let last_anchor = scan_indices.last().copied().unwrap_or(0);
                let span = last_anchor.saturating_sub(first_anchor);
                let suspicious_compressed_family = qc.linear_trend_max_abs_error_bp >= 6.0
                    && qc.linear_trend_mean_abs_error_bp >= 1.65
                    && (first_anchor > 1900 || last_anchor > 3900 || span > 2250);
                if suspicious_compressed_family {
                    reason_codes.push("suspicious_compressed_rox_family".to_owned());
                    summary_parts.push(format!(
                        "ROX fit is complete but visually suspicious: first {:.0}, last {:.0}, span {:.0}, linear max {:.2} bp.",
                        first_anchor as f64,
                        last_anchor as f64,
                        span as f64,
                        qc.linear_trend_max_abs_error_bp
                    ));
                }
            }
        } else if ladder == LadderKind::Gs500Rox {
            if qc.linear_trend_max_abs_error_bp > GS500ROX_REVIEW_LINEAR_MAX_BP
                || qc.linear_trend_mean_abs_error_bp > GS500ROX_REVIEW_LINEAR_MEAN_BP
                || qc.linear_trend_r2 < GS500ROX_REVIEW_LINEAR_R2_MIN
            {
                reason_codes.push("poor_gs500rox_linear_fit".to_owned());
                summary_parts.push(format!(
                    "GS500ROX lineær QC er dårlig (max {:.2} bp, mean {:.2} bp, R2 {:.5}).",
                    qc.linear_trend_max_abs_error_bp,
                    qc.linear_trend_mean_abs_error_bp,
                    qc.linear_trend_r2
                ));
            }
        } else if ladder == LadderKind::Liz500250
            && (qc.linear_trend_max_abs_error_bp > LIZ_REVIEW_LINEAR_MAX_BP
                || qc.linear_trend_mean_abs_error_bp > LIZ_REVIEW_LINEAR_MEAN_BP
                || qc.linear_trend_r2 < LIZ_REVIEW_LINEAR_R2_MIN)
        {
            reason_codes.push("poor_linear_liz_fit".to_owned());
            summary_parts.push(format!(
                "LIZ lineær QC er dårlig (max {:.2} bp, mean {:.2} bp, R2 {:.5}).",
                qc.linear_trend_max_abs_error_bp,
                qc.linear_trend_mean_abs_error_bp,
                qc.linear_trend_r2
            ));
        }
    }

    if ladder == LadderKind::Rox400Hd
        && reason_codes
            .iter()
            .any(|reason| reason == "blob_dominated_start")
        && scan_indices.len() == expected_peak_count
        && preview.sizing_model.as_ref().is_some_and(|model| {
            let qc = &model.qc_metrics;
            qc.linear_trend_max_abs_error_bp <= 4.5
                && qc.linear_trend_mean_abs_error_bp <= 1.8
                && qc.linear_trend_r2 >= 0.9995
        })
    {
        reason_codes.retain(|reason| reason != "blob_dominated_start");
        summary_parts.retain(|part| !part.contains("Early blob-like peaks dominate"));
    }
    if ladder == LadderKind::Gs500Rox
        && reason_codes
            .iter()
            .any(|reason| reason == "blob_dominated_start")
        && scan_indices.len() == expected_peak_count
        && preview.sizing_model.as_ref().is_some_and(|model| {
            let qc = &model.qc_metrics;
            qc.linear_trend_max_abs_error_bp <= 4.8
                && qc.linear_trend_mean_abs_error_bp <= 2.25
                && qc.linear_trend_r2 >= 0.99965
        })
    {
        reason_codes.retain(|reason| reason != "blob_dominated_start");
        summary_parts.retain(|part| !part.contains("Early blob-like peaks dominate"));
    }
    if ladder == LadderKind::Rox400Hd
        && scan_indices.len() == expected_peak_count
        && !reason_codes.is_empty()
        && reason_codes.iter().all(|reason| {
            reason == "poor_linear_rox_fit" || reason == "suspicious_compressed_rox_family"
        })
        && reason_codes
            .iter()
            .any(|reason| reason == "poor_linear_rox_fit")
        && preview.sizing_model.as_ref().is_some_and(|model| {
            let qc = &model.qc_metrics;
            qc.linear_trend_max_abs_error_bp <= ROX_COMPLETE_FIT_WAIVER_LINEAR_MAX_BP
                && qc.linear_trend_mean_abs_error_bp <= ROX_COMPLETE_FIT_WAIVER_LINEAR_MEAN_BP
                && qc.linear_trend_r2 >= ROX_COMPLETE_FIT_WAIVER_LINEAR_R2_MIN
        })
    {
        reason_codes.retain(|reason| reason != "poor_linear_rox_fit");
        summary_parts.retain(|part| !part.contains("ROX lineær QC er dårlig"));
    }
    if ladder == LadderKind::Rox400Hd
        && scan_indices.len() == expected_peak_count
        && !reason_codes.is_empty()
        && reason_codes.iter().all(|reason| {
            reason == "poor_linear_rox_fit" || reason == "suspicious_compressed_rox_family"
        })
        && preview.sizing_model.as_ref().is_some_and(|model| {
            let qc = &model.qc_metrics;
            qc.linear_trend_max_abs_error_bp <= ROX_NONLINEAR_COMPLETE_WAIVER_LINEAR_MAX_BP
                && qc.linear_trend_mean_abs_error_bp <= ROX_NONLINEAR_COMPLETE_WAIVER_LINEAR_MEAN_BP
                && qc.linear_trend_r2 >= ROX_NONLINEAR_COMPLETE_WAIVER_LINEAR_R2_MIN
                && qc.quadratic_trend_max_abs_error_bp <= ROX_NONLINEAR_COMPLETE_WAIVER_QUAD_MAX_BP
                && qc.quadratic_trend_mean_abs_error_bp
                    <= ROX_NONLINEAR_COMPLETE_WAIVER_QUAD_MEAN_BP
                && qc.quadratic_trend_r2 >= ROX_NONLINEAR_COMPLETE_WAIVER_QUAD_R2_MIN
        })
    {
        reason_codes.retain(|reason| reason != "poor_linear_rox_fit");
        reason_codes.retain(|reason| reason != "suspicious_compressed_rox_family");
        summary_parts.retain(|part| !part.contains("ROX lineær QC er dårlig"));
        summary_parts.retain(|part| !part.contains("ROX fit is complete but visually suspicious"));
    }

    reason_codes.sort();
    reason_codes.dedup();

    let suggested_review = !reason_codes.is_empty();
    let summary = if summary_parts.is_empty() {
        "Rust ladder fit looks internally consistent.".to_owned()
    } else {
        summary_parts.join(" ")
    };

    LadderReviewAssessment {
        suggested_review,
        primary_reason: reason_codes.first().cloned(),
        reason_codes,
        summary,
        first_anchor_time,
        last_anchor_time,
        anchor_span,
        estimated_combination_count: Some(preview.estimated_combination_count),
        evaluated_combination_count: Some(preview.evaluated_combination_count),
        best_curvature_score: preview.best_curvature_score,
        max_abs_error_bp,
        selected_baseline_like_anchor_count,
        selected_cleaner_neighbor_count,
        selected_strong_baseline_anchor_count,
    }
}

fn selected_baseline_like_anchor_counts(
    ladder: LadderKind,
    scan_indices: &[usize],
    ladder_peaks: &[Peak],
) -> (usize, usize, usize) {
    let selected = scan_indices
        .iter()
        .filter_map(|scan| ladder_peaks.iter().find(|peak| peak.index == *scan))
        .collect::<Vec<_>>();
    if selected.is_empty() {
        return (0, 0, 0);
    }

    let prominence_ref = median(
        &selected
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let height_ref = median(
        &selected
            .iter()
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let neighbor_radius = if ladder == LadderKind::Liz500250 {
        28usize
    } else {
        22usize
    };

    let mut baseline_like_count = 0usize;
    let mut cleaner_neighbor_count = 0usize;
    let mut strong_baseline_count = 0usize;
    for peak in selected {
        let height = peak.height.max(1.0);
        let prominence = peak.prominence.max(0.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 2.0);
        let purity = (prominence / height).clamp(0.0, 1.5);
        let prominence_ratio = prominence / prominence_ref;
        let height_ratio = height / height_ref;

        let strong_baseline_signal = baseline_ratio >= 0.52 && purity <= 0.50;
        let weak_foot_signal = baseline_ratio >= 0.34 && purity <= 0.58 && prominence_ratio <= 0.72;

        let nearby_cleaner_peak = ladder_peaks.iter().any(|other| {
            if other.index == peak.index {
                return false;
            }
            let distance = other.index.abs_diff(peak.index);
            if distance == 0 || distance > neighbor_radius {
                return false;
            }
            let other_height = other.height.max(1.0);
            let other_prominence = other.prominence.max(0.0);
            let other_baseline_ratio =
                (other.local_baseline.max(0.0) / other_height).clamp(0.0, 2.0);
            let other_purity = (other_prominence / other_height).clamp(0.0, 1.5);
            other_prominence >= (prominence * 1.65).max(prominence_ref * 0.38).max(25.0)
                && other_height >= (height * 1.20).max(height_ref * 0.25)
                && (other_baseline_ratio <= baseline_ratio - 0.12 || other_purity >= purity + 0.18)
        });

        if nearby_cleaner_peak {
            cleaner_neighbor_count += 1;
        }
        if strong_baseline_signal
            || (weak_foot_signal && nearby_cleaner_peak && height_ratio < 1.35)
        {
            baseline_like_count += 1;
        }
        if strong_baseline_signal {
            strong_baseline_count += 1;
        }
    }

    (
        baseline_like_count,
        cleaner_neighbor_count,
        strong_baseline_count,
    )
}

fn selected_weak_liz_anchor_counts(scan_indices: &[usize], ladder_peaks: &[Peak]) -> (usize, bool) {
    let selected = scan_indices
        .iter()
        .filter_map(|scan| ladder_peaks.iter().find(|peak| peak.index == *scan))
        .collect::<Vec<_>>();
    if selected.is_empty() {
        return (0, false);
    }

    let prominence_ref = median(
        &selected
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let strong_prominences = selected
        .iter()
        .map(|peak| peak.prominence.max(1.0))
        .filter(|prominence| *prominence >= prominence_ref)
        .collect::<Vec<_>>();
    let family_prominence_ref = median(&strong_prominences).max(prominence_ref);
    if family_prominence_ref < 250.0 {
        return (0, false);
    }

    let weak_floor = (family_prominence_ref * 0.15).max(45.0);
    let very_weak_floor = (family_prominence_ref * 0.09).max(35.0);
    let weak_count = selected
        .iter()
        .filter(|peak| peak.prominence.max(0.0) < weak_floor)
        .count();
    let has_very_weak_tail = selected.iter().rev().take(2).any(|peak| {
        peak.prominence.max(0.0) < very_weak_floor
            && peak.height.max(1.0) < family_prominence_ref * 0.18
    });

    (weak_count, has_very_weak_tail)
}

fn liz_late_tail_is_clean(scan_indices: &[usize], ladder_peaks: &[Peak]) -> bool {
    let selected = scan_indices
        .iter()
        .filter_map(|scan| ladder_peaks.iter().find(|peak| peak.index == *scan))
        .collect::<Vec<_>>();
    if selected.len() != scan_indices.len() || selected.len() < 4 {
        return false;
    }

    let prominence_ref = median(
        &selected
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let late = selected
        .iter()
        .filter(|peak| peak.index > LIZ_SELECTED_LATE_REVIEW_SCAN)
        .collect::<Vec<_>>();
    if late.is_empty() || late.len() > 2 {
        return false;
    }
    late.iter().all(|peak| {
        let height = peak.height.max(1.0);
        let prominence = peak.prominence.max(0.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (prominence / height).clamp(0.0, 1.5);
        prominence >= (prominence_ref * 0.09).max(90.0)
            && baseline_ratio <= 0.12
            && purity >= 0.85
            && peak.width >= 3.0
    })
}

fn is_high_confidence_complete_fit(
    preview: &LadderFitPreview,
    fitted_step_count: usize,
    expected_peak_count: usize,
) -> bool {
    if fitted_step_count != expected_peak_count {
        return false;
    }

    let Some(model) = preview.sizing_model.as_ref() else {
        return false;
    };
    let qc = &model.qc_metrics;
    qc.monotonic_on_ladder
        && qc.r2 >= COMPLETE_FIT_REVIEW_WAIVER_MIN_R2
        && qc.mean_abs_error_bp <= COMPLETE_FIT_REVIEW_WAIVER_MAX_MEAN_ABS_ERROR_BP
        && qc.max_abs_error_bp <= COMPLETE_FIT_REVIEW_WAIVER_MAX_ABS_ERROR_BP
}

fn dye_names(record: &AbifRecord) -> BTreeMap<String, String> {
    let mut dyes = BTreeMap::new();
    for index in 1..=8 {
        let key = format!("DyeN{index}");
        if let Some(value) = record.string_value(&key) {
            dyes.insert(key, value.to_owned());
        }
    }
    dyes
}

fn select_size_standard_channel(
    record: &AbifRecord,
    file_name: &str,
    analysis_kind: Option<&AnalysisKind>,
) -> Option<String> {
    match analysis_kind {
        Some(AnalysisKind::Clonality) => match expected_clonality_ladder_kind(file_name) {
            Some(LadderKind::Liz500250) => {
                if record.tags.contains_key("DATA105") {
                    return Some("DATA105".to_owned());
                }
                if record.tags.contains_key("DATA4") {
                    return Some("DATA4".to_owned());
                }
            }
            _ => {
                if record.tags.contains_key("DATA4") {
                    return Some("DATA4".to_owned());
                }
                if record.tags.contains_key("DATA105") {
                    return Some("DATA105".to_owned());
                }
            }
        },
        Some(AnalysisKind::Flt3) => {
            if record.tags.contains_key("DATA105") {
                return Some("DATA105".to_owned());
            }
            if record.tags.contains_key("DATA4") {
                return Some("DATA4".to_owned());
            }
        }
        _ => {}
    }

    for preferred in ["DATA105", "DATA4"] {
        if record.tags.contains_key(preferred) {
            return Some(preferred.to_owned());
        }
    }

    let mut best_channel = None;
    let mut best_score = f64::NEG_INFINITY;
    for channel in record.data_channels() {
        let Some(trace) = record.channel_values(&channel) else {
            continue;
        };
        let peaks = find_peaks(&trace, 100.0, 8);
        if peaks.len() < 12 {
            continue;
        }
        let score = quadratic_fit_r2(
            &(0..peaks.len()).map(|idx| idx as f64).collect::<Vec<_>>(),
            &peaks
                .iter()
                .map(|peak| peak.index as f64)
                .collect::<Vec<_>>(),
        );
        if score > best_score {
            best_score = score;
            best_channel = Some(channel);
        }
    }
    best_channel
}

fn quadratic_fit_r2(x: &[f64], y: &[f64]) -> f64 {
    if x.len() != y.len() || x.len() < 3 {
        return f64::NEG_INFINITY;
    }
    let mut s0 = 0.0;
    let mut s1 = 0.0;
    let mut s2 = 0.0;
    let mut s3 = 0.0;
    let mut s4 = 0.0;
    let mut t0 = 0.0;
    let mut t1 = 0.0;
    let mut t2 = 0.0;
    for (&xv, &yv) in x.iter().zip(y.iter()) {
        let x2 = xv * xv;
        s0 += 1.0;
        s1 += xv;
        s2 += x2;
        s3 += x2 * xv;
        s4 += x2 * x2;
        t0 += yv;
        t1 += xv * yv;
        t2 += x2 * yv;
    }

    let det = determinant3([[s4, s3, s2], [s3, s2, s1], [s2, s1, s0]]);
    if det.abs() <= f64::EPSILON {
        return f64::NEG_INFINITY;
    }
    let a = determinant3([[t2, s3, s2], [t1, s2, s1], [t0, s1, s0]]) / det;
    let b = determinant3([[s4, t2, s2], [s3, t1, s1], [s2, t0, s0]]) / det;
    let c = determinant3([[s4, s3, t2], [s3, s2, t1], [s2, s1, t0]]) / det;

    let mean_y = y.iter().sum::<f64>() / y.len() as f64;
    let mut ss_tot = 0.0;
    let mut ss_res = 0.0;
    for (&xv, &yv) in x.iter().zip(y.iter()) {
        let predicted = a * xv * xv + b * xv + c;
        let diff_tot = yv - mean_y;
        let diff_res = yv - predicted;
        ss_tot += diff_tot * diff_tot;
        ss_res += diff_res * diff_res;
    }
    if ss_tot <= f64::EPSILON {
        return f64::NEG_INFINITY;
    }
    1.0 - (ss_res / ss_tot)
}

fn determinant3(matrix: [[f64; 3]; 3]) -> f64 {
    matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
}

fn suggested_ladder_kind(
    record: &AbifRecord,
    file_name: &str,
    size_standard_channel: &str,
    analysis_kind: Option<&AnalysisKind>,
) -> LadderKind {
    match analysis_kind {
        Some(AnalysisKind::Flt3) => LadderKind::Gs500Rox,
        Some(AnalysisKind::Clonality) => {
            expected_clonality_ladder_kind(file_name).unwrap_or_else(|| {
                if size_standard_channel == "DATA105" {
                    LadderKind::Liz500250
                } else {
                    LadderKind::Rox400Hd
                }
            })
        }
        _ if record.tags.contains_key("DATA105") => LadderKind::Liz500250,
        _ => LadderKind::Rox400Hd,
    }
}

fn expected_clonality_ladder_kind(file_name: &str) -> Option<LadderKind> {
    let token = normalize_assay_token(file_name);
    if [
        "IGK", "KDE", "TCRGA", "TCRGB", "TCRG", "TRGA", "TRGB", "TRG", "TRGMIXA", "TRGMIXB",
        "TRGMIX",
    ]
    .iter()
    .any(|alias| token.contains(&normalize_assay_token(alias)))
    {
        return Some(LadderKind::Liz500250);
    }
    if [
        "FR1",
        "FR2",
        "FR3",
        "SL",
        "DHJH",
        "IKZF1",
        "KTRALBUMIN",
        "TCRBA",
        "TCRBB",
        "TCRBC",
        "TCRB",
    ]
    .iter()
    .any(|alias| token.contains(&normalize_assay_token(alias)))
    {
        return Some(LadderKind::Rox400Hd);
    }
    None
}

fn preferred_sample_channel(
    data_channels: &[String],
    size_standard_channel: &str,
    file_name: &str,
    analysis_kind: Option<&AnalysisKind>,
) -> Option<String> {
    if matches!(analysis_kind, Some(AnalysisKind::Flt3)) {
        if let Some(assay) = detect_flt3_assay(file_name) {
            return assay
                .channels
                .iter()
                .find_map(|channel| {
                    data_channels
                        .iter()
                        .find(|candidate| candidate.as_str() == *channel)
                        .cloned()
                })
                .or_else(|| {
                    data_channels
                        .iter()
                        .find(|channel| channel.as_str() != size_standard_channel)
                        .cloned()
                });
        }
    }
    None
}

fn select_ladder_peaks(
    raw_trace: &[f64],
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    raw_min_height: f64,
    corrected_min_height: f64,
    min_distance: usize,
    max_peaks: usize,
    expected_peak_count: usize,
    ladder: LadderKind,
) -> Vec<Peak> {
    let target_candidate_count = expected_peak_count.min(8).max(4);
    let is_liz = ladder == LadderKind::Liz500250;
    let uses_baseline_candidate_supplements =
        matches!(ladder, LadderKind::Liz500250 | LadderKind::Gs500Rox);
    let is_rox_family = matches!(ladder, LadderKind::Rox400Hd | LadderKind::Gs500Rox);
    let min_candidate_span = if is_rox_family { 1100 } else { 850 };
    let mut raw_candidates = adaptive_top_peak_candidates(
        raw_trace,
        raw_min_height,
        min_distance,
        max_peaks,
        target_candidate_count,
        min_candidate_span,
    );
    let mut corrected_candidates = adaptive_top_peak_candidates(
        corrected_trace,
        corrected_min_height,
        min_distance,
        max_peaks,
        target_candidate_count,
        min_candidate_span,
    );
    let mut quantile_candidates = adaptive_top_peak_candidates(
        quantile_corrected_trace,
        corrected_min_height,
        min_distance,
        max_peaks,
        target_candidate_count,
        min_candidate_span,
    );
    if ladder == LadderKind::Gs500Rox {
        raw_candidates = filter_gs500rox_candidate_scan_window(&raw_candidates);
        corrected_candidates = filter_gs500rox_candidate_scan_window(&corrected_candidates);
        quantile_candidates = filter_gs500rox_candidate_scan_window(&quantile_candidates);
    }

    let morph_candidates = if uses_baseline_candidate_supplements {
        let candidates = adaptive_top_peak_candidates(
            morph_corrected_trace,
            corrected_min_height,
            min_distance,
            max_peaks,
            target_candidate_count,
            min_candidate_span,
        );
        if ladder == LadderKind::Gs500Rox {
            filter_gs500rox_candidate_scan_window(&candidates)
        } else {
            candidates
        }
    } else {
        Vec::new()
    };
    let snip_candidates = if uses_baseline_candidate_supplements {
        let candidates = adaptive_top_peak_candidates(
            snip_corrected_trace,
            corrected_min_height,
            min_distance,
            max_peaks,
            target_candidate_count,
            min_candidate_span,
        );
        if ladder == LadderKind::Gs500Rox {
            filter_gs500rox_candidate_scan_window(&candidates)
        } else {
            candidates
        }
    } else {
        Vec::new()
    };

    let mut base_sets = vec![
        raw_candidates.clone(),
        corrected_candidates.clone(),
        quantile_candidates.clone(),
    ];
    if uses_baseline_candidate_supplements {
        base_sets.push(morph_candidates.clone());
        base_sets.push(snip_candidates.clone());
    }
    let merged_candidates = merge_candidate_sets(&base_sets, min_distance, max_peaks);
    let coverage_candidates = coverage_peak_candidates(
        quantile_corrected_trace,
        min_distance,
        max_peaks,
        expected_peak_count,
        ladder,
    );
    let merged_with_coverage = merge_candidate_sets(
        &[merged_candidates.clone(), coverage_candidates],
        min_distance,
        max_peaks,
    );
    let ladder_specific_supplemented = if is_rox_family {
        let rox_window_candidates = rox_window_peak_candidates(
            corrected_trace,
            quantile_corrected_trace,
            min_distance,
            max_peaks,
        );
        let rox_early_window_candidates =
            rox_early_window_peak_candidates(corrected_trace, quantile_corrected_trace, max_peaks);
        let rox_window_candidates = if ladder == LadderKind::Gs500Rox {
            filter_gs500rox_candidate_scan_window(&rox_window_candidates)
        } else {
            rox_window_candidates
        };
        let rox_early_window_candidates = if ladder == LadderKind::Gs500Rox {
            filter_gs500rox_candidate_scan_window(&rox_early_window_candidates)
        } else {
            rox_early_window_candidates
        };
        merge_candidate_sets(
            &[
                merged_with_coverage.clone(),
                rox_window_candidates,
                rox_early_window_candidates,
            ],
            min_distance,
            max_peaks,
        )
    } else if is_liz {
        let liz_window_candidates = liz_window_peak_candidates(
            corrected_trace,
            quantile_corrected_trace,
            morph_corrected_trace,
            snip_corrected_trace,
            max_peaks,
        );
        let liz_blob_candidates = liz_blob_suspect_peak_candidates(
            corrected_trace,
            quantile_corrected_trace,
            morph_corrected_trace,
            snip_corrected_trace,
            max_peaks,
        );
        let (selected_liz_lane, used_blob_lane) = select_liz_candidate_lane(
            &merged_with_coverage,
            &liz_window_candidates,
            &liz_blob_candidates,
            expected_peak_count,
        );
        if selected_liz_lane.is_empty() {
            merged_with_coverage.clone()
        } else if used_blob_lane {
            selected_liz_lane
        } else {
            merge_candidate_sets(
                &[merged_with_coverage.clone(), selected_liz_lane],
                min_distance,
                max_peaks,
            )
        }
    } else {
        merged_with_coverage.clone()
    };
    let liz_anchor_rescue_needed = is_liz
        && liz_hardcase_anchor_rescue_needed(&ladder_specific_supplemented, expected_peak_count);
    let liz_mid_200_rescue_needed = is_liz
        && liz_mid_200_anchor_rescue_needed(&ladder_specific_supplemented, expected_peak_count);
    let ladder_filtered = if is_rox_family {
        filter_rox_peak_pool_for_fit(&ladder_specific_supplemented, expected_peak_count)
    } else if is_liz {
        let filtered =
            filter_liz_peak_pool_for_fit(&ladder_specific_supplemented, expected_peak_count);
        let filtered = if liz_anchor_rescue_needed {
            preserve_liz_hardcase_anchor_candidates(
                &filtered,
                corrected_trace,
                quantile_corrected_trace,
                morph_corrected_trace,
                snip_corrected_trace,
                expected_peak_count,
            )
        } else {
            filtered
        };
        if liz_mid_200_rescue_needed {
            preserve_liz_mid_200_anchor_candidates(
                &filtered,
                corrected_trace,
                quantile_corrected_trace,
                morph_corrected_trace,
                snip_corrected_trace,
                expected_peak_count,
            )
        } else {
            filtered
        }
    } else {
        ladder_specific_supplemented.clone()
    };

    if ladder == LadderKind::Rox400Hd {
        if let Some(post_blob_pool) =
            rox_post_blob_pool_override(&merged_candidates, &ladder_filtered, expected_peak_count)
        {
            return post_blob_pool;
        }
    }

    let min_viable_raw = expected_peak_count.min(6).max(3);
    let raw_tail_ok = candidate_has_tail_coverage(&raw_candidates, ladder);
    if candidate_pool_rank(&ladder_filtered) >= candidate_pool_rank(&merged_candidates) {
        return ladder_filtered;
    }
    if merged_candidates.len() >= raw_candidates.len().max(min_viable_raw) && !raw_tail_ok {
        return merged_candidates;
    }
    if merged_candidates.len() >= raw_candidates.len().max(min_viable_raw) {
        return merged_candidates;
    }
    if raw_candidates.len() >= min_viable_raw && raw_tail_ok {
        return raw_candidates;
    }
    if corrected_candidates.len() >= quantile_candidates.len()
        && corrected_candidates.len() > raw_candidates.len()
    {
        return corrected_candidates;
    }
    if quantile_candidates.len() > raw_candidates.len() {
        return quantile_candidates;
    }
    raw_candidates
}

fn rox_post_blob_pool_override(
    merged_candidates: &[Peak],
    ladder_filtered: &[Peak],
    expected_peak_count: usize,
) -> Option<Vec<Peak>> {
    if expected_peak_count < 20 {
        return None;
    }

    let merged_post_blob_count = merged_candidates
        .iter()
        .filter(|peak| peak.index >= 1520)
        .count();
    if merged_post_blob_count >= expected_peak_count {
        return None;
    }

    let mut post_blob = ladder_filtered
        .iter()
        .filter(|peak| peak.index >= 1520)
        .cloned()
        .collect::<Vec<_>>();
    if post_blob.len() < expected_peak_count {
        return None;
    }
    post_blob.sort_by_key(|peak| peak.index);

    let first = post_blob.first().map(|peak| peak.index).unwrap_or(0);
    let last = post_blob.last().map(|peak| peak.index).unwrap_or(first);
    let span = last.saturating_sub(first);
    if !(1750..=2700).contains(&span) {
        return None;
    }

    let strong_family_count = post_blob
        .iter()
        .filter(|peak| {
            peak.index <= 3650
                && peak.height >= 45.0
                && peak.prominence >= 40.0
                && peak.score >= 55.0
        })
        .count();
    if strong_family_count + 2 < expected_peak_count {
        return None;
    }

    Some(post_blob)
}

fn select_liz_candidate_lane(
    merged_with_coverage: &[Peak],
    default_lane: &[Peak],
    blob_lane: &[Peak],
    expected_peak_count: usize,
) -> (Vec<Peak>, bool) {
    if blob_lane.is_empty() {
        return (default_lane.to_vec(), false);
    }
    if default_lane.is_empty() {
        return (blob_lane.to_vec(), true);
    }
    let default_early = count_peaks_in_range(default_lane, 1300, 1650);
    let blob_early = count_peaks_in_range(blob_lane, 1300, 1650);
    let default_very_early = count_peaks_in_range(default_lane, 1300, 1525);
    let blob_very_early = count_peaks_in_range(blob_lane, 1300, 1525);
    let blob_span_ok = candidate_span(blob_lane) >= 1800;
    let blob_tail_ok = candidate_has_tail_coverage(blob_lane, LadderKind::Liz500250);
    let blob_min_count = blob_lane.len() >= expected_peak_count.min(10).max(6);
    let default_is_blob_heavy = default_early >= 8 || default_very_early >= 4;
    let blob_is_meaningfully_cleaner =
        blob_early + 3 <= default_early || blob_very_early + 2 <= default_very_early;
    let merged_early = count_peaks_in_range(merged_with_coverage, 1300, 1650);

    if default_is_blob_heavy
        && blob_is_meaningfully_cleaner
        && blob_span_ok
        && blob_tail_ok
        && blob_min_count
        && merged_early >= default_early
    {
        return (blob_lane.to_vec(), true);
    }
    (default_lane.to_vec(), false)
}

fn liz_fit_is_high_confidence_stable(best: &CombinationScore) -> bool {
    best.linear_max_abs_error_bp <= 6.0
        && best.linear_mean_abs_error_bp <= 2.25
        && best.linear_r2 >= 0.99960
}

fn liz_initial_fit_can_skip_repairs(
    best: &CombinationScore,
    repair_peak_features: &[Peak],
) -> bool {
    if best.indices.len() != LadderKind::Liz500250.expected_peak_count()
        || !liz_fit_is_high_confidence_stable(best)
        || ladder_gap_template_penalty(LadderKind::Liz500250, &best.indices) > 0.35
    {
        return false;
    }
    let (baseline_like, cleaner_neighbors, strong_baseline) = selected_baseline_like_anchor_counts(
        LadderKind::Liz500250,
        &best.indices,
        repair_peak_features,
    );
    let (weak_count, very_weak_tail) =
        selected_weak_liz_anchor_counts(&best.indices, repair_peak_features);
    baseline_like == 0
        && cleaner_neighbors == 0
        && strong_baseline == 0
        && weak_count == 0
        && !very_weak_tail
}

fn count_peaks_in_range(peaks: &[Peak], start: usize, end: usize) -> usize {
    peaks
        .iter()
        .filter(|peak| (start..=end).contains(&peak.index))
        .count()
}

fn snap_peak_to_local_apex(values: &[f64], index: usize, radius: usize) -> usize {
    if values.is_empty() {
        return index;
    }
    let start = index.saturating_sub(radius);
    let end = (index + radius + 1).min(values.len());
    let mut best = index.min(values.len().saturating_sub(1));
    let mut best_value = values[best];
    for candidate in start..end {
        if values[candidate] > best_value {
            best = candidate;
            best_value = values[candidate];
        }
    }
    best
}

fn liz_blob_suspect_peak_candidates(
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    max_peaks: usize,
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    let window_distance = 6usize;
    for values in [
        corrected_trace,
        quantile_corrected_trace,
        morph_corrected_trace,
        snip_corrected_trace,
    ] {
        // `find_peaks(values, values[snapped], 1)` below used to rescan the
        // complete trace for every smoothed candidate. Peak shape does not
        // depend on the height threshold, and distance=1 retains every local
        // maximum, so one indexed pass is exactly equivalent for candidates
        // whose snapped height is at least 6.
        let apex_peaks_by_index = find_peaks(values, 6.0, 1)
            .into_iter()
            .map(|peak| (peak.index, peak))
            .collect::<BTreeMap<_, _>>();
        for radius in [2usize, 4usize, 6usize] {
            let smooth = moving_average_smooth(values, radius);
            let mut peaks = find_peaks(&smooth, 6.0, window_distance);
            for peak in &mut peaks {
                let snapped = snap_peak_to_local_apex(values, peak.index, 8);
                if snapped != peak.index && snapped < values.len() {
                    if let Some(candidate) = apex_peaks_by_index.get(&snapped) {
                        *peak = candidate.clone();
                    } else {
                        peak.index = snapped;
                        peak.height = values[snapped];
                    }
                }
            }
            pooled.extend(
                peaks
                    .into_iter()
                    .filter(|peak| (1400..=LIZ_BLOB_LANE_TIME_MAX).contains(&peak.index)),
            );
        }
        pooled.extend(liz_micro_anchor_candidates(values));
    }
    if pooled.is_empty() {
        return Vec::new();
    }

    pooled.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.45 - left_baseline_ratio * 1400.0 + left_purity * 90.0;
        let right_rank = right.score + right.prominence * 0.45 - right_baseline_ratio * 1400.0
            + right_purity * 90.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });

    let very_early = pooled
        .iter()
        .filter(|peak| (1400..=1605).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let early = pooled
        .iter()
        .filter(|peak| (1606..=2050).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let middle = pooled
        .iter()
        .filter(|peak| (2051..=3050).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let tail = pooled
        .iter()
        .filter(|peak| (3051..=LIZ_BLOB_LANE_TIME_MAX).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();

    let very_early = select_diverse_peak_subset_with_buckets(very_early, 8, 4);
    let early = select_diverse_peak_subset_with_buckets(early, 12, 6);
    let middle = select_diverse_peak_subset_with_buckets(middle, 16, 8);
    let tail = select_diverse_peak_subset_with_buckets(tail, 16, 8);
    merge_candidate_sets(
        &[very_early, early, middle, tail],
        window_distance,
        max_peaks.min(44),
    )
}

fn liz_window_peak_candidates(
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    max_peaks: usize,
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    let window_distance = 4usize;
    for values in [
        corrected_trace,
        quantile_corrected_trace,
        morph_corrected_trace,
        snip_corrected_trace,
    ] {
        let peaks = find_peaks(values, 6.0, window_distance);
        pooled.extend(
            peaks
                .iter()
                .cloned()
                .filter(|peak| (1400..=LIZ_DEFAULT_LANE_TIME_MAX).contains(&peak.index)),
        );
        pooled.extend(
            peaks
                .into_iter()
                .filter(|peak| (4381..=4600).contains(&peak.index)),
        );
        pooled.extend(liz_micro_anchor_candidates(values));
        let windows = [
            (1420usize, 1605usize),
            (1480, 1750),
            (1650, 2050),
            (1980, 2450),
            (2350, 3050),
            (3000, LIZ_DEFAULT_LANE_TIME_MAX),
            (4381, 4600),
        ];
        for (start, end) in windows {
            if end <= start + 2 || start >= values.len() {
                continue;
            }
            let bounded_end = end.min(values.len());
            let slice = &values[start..bounded_end];
            let mut local = find_peaks(slice, 6.0, 4)
                .into_iter()
                .map(|mut peak| {
                    peak.index += start;
                    peak
                })
                .collect::<Vec<_>>();
            local.sort_by(|left, right| {
                let left_height = left.height.max(1.0);
                let right_height = right.height.max(1.0);
                let left_baseline_ratio =
                    (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
                let right_baseline_ratio =
                    (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
                let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
                let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
                let left_rank = left.score + left.prominence * 0.35 - left_baseline_ratio * 1200.0
                    + left_purity * 60.0;
                let right_rank = right.score + right.prominence * 0.35
                    - right_baseline_ratio * 1200.0
                    + right_purity * 60.0;
                right_rank
                    .partial_cmp(&left_rank)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| left.index.cmp(&right.index))
            });
            if local.len() > 4 {
                local.truncate(4);
            }
            pooled.extend(local);
        }
    }
    if pooled.is_empty() {
        return Vec::new();
    }

    pooled.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.35 - left_baseline_ratio * 1200.0 + left_purity * 60.0;
        let right_rank = right.score + right.prominence * 0.35 - right_baseline_ratio * 1200.0
            + right_purity * 60.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });

    let very_early = pooled
        .iter()
        .filter(|peak| (1400..=1650).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let early = pooled
        .iter()
        .filter(|peak| (1651..=2150).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let middle = pooled
        .iter()
        .filter(|peak| (2151..=3050).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let tail = pooled
        .iter()
        .filter(|peak| (3051..=LIZ_DEFAULT_LANE_TIME_MAX).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let late_tail = pooled
        .iter()
        .filter(|peak| (4381..=LIZ_BLOB_LANE_TIME_MAX).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();

    let very_early = select_diverse_peak_subset_with_buckets(very_early, 12, 6);
    let early = select_diverse_peak_subset_with_buckets(early, 14, 7);
    let middle = select_diverse_peak_subset_with_buckets(middle, 18, 9);
    let tail = select_diverse_peak_subset_with_buckets(tail, 18, 9);
    let late_tail = select_diverse_peak_subset_with_buckets(late_tail, 12, 6);
    merge_candidate_sets(
        &[very_early, early, middle, tail, late_tail],
        window_distance,
        max_peaks.min(50),
    )
}

fn liz_micro_anchor_candidates(values: &[f64]) -> Vec<Peak> {
    let windows = [
        (1470usize, 1508usize),
        (1508usize, 1542usize),
        (1542usize, 1582usize),
        (1582usize, 1618usize),
        (1618usize, 1688usize),
    ];
    let mut pooled = Vec::new();
    for (start, end) in windows {
        if end <= start + 2 || start >= values.len() {
            continue;
        }
        let bounded_end = end.min(values.len());
        let slice = &values[start..bounded_end];
        let mut local = find_peaks(slice, 8.0, 1)
            .into_iter()
            .map(|mut peak| {
                peak.index += start;
                peak
            })
            .collect::<Vec<_>>();
        local.sort_by(|left, right| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    right
                        .prominence
                        .partial_cmp(&left.prominence)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| {
                    right
                        .height
                        .partial_cmp(&left.height)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| left.index.cmp(&right.index))
        });
        if local.len() > 3 {
            local.truncate(3);
        }
        pooled.extend(local);
    }
    pooled
}

fn liz_hardcase_anchor_rescue_needed(peaks: &[Peak], expected_peak_count: usize) -> bool {
    if expected_peak_count != LadderKind::Liz500250.expected_peak_count() || peaks.is_empty() {
        return false;
    }
    let post_blob_plausible_count = peaks
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.index >= 1400
                && peak.index <= LIZ_BLOB_LANE_TIME_MAX
                && peak.height >= 10.0
                && peak.prominence >= 8.0
                && (baseline_ratio <= 0.75 || purity >= 0.30)
        })
        .count();
    let has_pre_blob_noise = post_blob_plausible_count >= expected_peak_count
        && peaks.iter().any(|peak| peak.index < 1350);
    let strong_blob_before_micro = peaks.iter().any(|peak| {
        let height = peak.height.max(1.0);
        let purity = (peak.prominence / height).clamp(0.0, 1.0);
        (1350..1470).contains(&peak.index)
            && peak.height >= 250.0
            && (peak.prominence >= 80.0 || purity >= 0.35)
    });
    let micro_coverage = peaks
        .iter()
        .filter(|peak| (1470..=1625).contains(&peak.index))
        .count();
    let weak_late_start_anchor = strong_blob_before_micro
        && peaks.iter().any(|peak| {
            (1640..=1710).contains(&peak.index) && peak.height < 150.0 && peak.prominence >= 25.0
        });
    has_pre_blob_noise || (strong_blob_before_micro && micro_coverage < 2) || weak_late_start_anchor
}

fn liz_mid_200_anchor_rescue_needed(peaks: &[Peak], expected_peak_count: usize) -> bool {
    if expected_peak_count != LadderKind::Liz500250.expected_peak_count() || peaks.is_empty() {
        return false;
    }

    let giant_mid_outlier = peaks.iter().any(|peak| {
        (2580..=2705).contains(&peak.index) && peak.height >= 800.0 && peak.prominence >= 600.0
    });
    if !giant_mid_outlier {
        return false;
    }

    let has_strong_pre_mid_anchor = peaks.iter().any(|peak| {
        (2460..=2575).contains(&peak.index) && peak.height >= 90.0 && peak.prominence >= 70.0
    });
    if !has_strong_pre_mid_anchor {
        return false;
    }

    let has_left_family = peaks.iter().any(|peak| {
        (2140..=2355).contains(&peak.index) && peak.height >= 70.0 && peak.prominence >= 45.0
    });
    let has_right_family = peaks.iter().any(|peak| {
        (2760..=3250).contains(&peak.index) && peak.height >= 70.0 && peak.prominence >= 45.0
    });

    has_left_family && has_right_family
}

fn preserve_liz_hardcase_anchor_candidates(
    base: &[Peak],
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    expected_peak_count: usize,
) -> Vec<Peak> {
    if expected_peak_count != LadderKind::Liz500250.expected_peak_count() {
        return base.to_vec();
    }

    let mut preserved = base.to_vec();
    let mut supplements = Vec::new();
    for values in [
        corrected_trace,
        quantile_corrected_trace,
        morph_corrected_trace,
        snip_corrected_trace,
    ] {
        supplements.extend(liz_micro_anchor_candidates(values));
        supplements.extend(liz_local_anchor_rescue_candidates(
            values,
            &[
                (1450, 1625, 4.0, 10usize),
                (1618, 1688, 4.0, 8usize),
                (4050, 4185, 5.0, 6usize),
            ],
        ));
    }
    if supplements.is_empty() {
        preserved.sort_by_key(|peak| peak.index);
        return preserved;
    }

    supplements.sort_by(|left, right| {
        let left_region = liz_anchor_rescue_region_rank(left.index);
        let right_region = liz_anchor_rescue_region_rank(right.index);
        left_region
            .partial_cmp(&right_region)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                let left_height = left.height.max(1.0);
                let right_height = right.height.max(1.0);
                let left_baseline_ratio =
                    (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
                let right_baseline_ratio =
                    (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
                let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
                let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
                let left_rank = left.score + left.prominence * 0.45 + left_purity * 35.0
                    - left_baseline_ratio * 180.0;
                let right_rank = right.score + right.prominence * 0.45 + right_purity * 35.0
                    - right_baseline_ratio * 180.0;
                right_rank
                    .partial_cmp(&left_rank)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let max_preserved = expected_peak_count * 3 + 12;
    for peak in supplements {
        if preserved.len() >= max_preserved {
            break;
        }
        if preserved
            .iter()
            .any(|existing| existing.index.abs_diff(peak.index) <= 2)
        {
            continue;
        }
        preserved.push(peak);
    }
    preserved.sort_by_key(|peak| peak.index);
    preserved
}

fn preserve_liz_mid_200_anchor_candidates(
    base: &[Peak],
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    expected_peak_count: usize,
) -> Vec<Peak> {
    if expected_peak_count != LadderKind::Liz500250.expected_peak_count() {
        return base.to_vec();
    }

    let mut preserved = base.to_vec();
    let mut supplements = Vec::new();
    for values in [
        corrected_trace,
        quantile_corrected_trace,
        morph_corrected_trace,
        snip_corrected_trace,
    ] {
        supplements.extend(liz_local_anchor_rescue_candidates(
            values,
            &[(2460, 2625, 5.0, 10usize)],
        ));
    }
    if supplements.is_empty() {
        preserved.sort_by_key(|peak| peak.index);
        return preserved;
    }

    supplements.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.60 + left_purity * 50.0 - left_baseline_ratio * 240.0;
        let right_rank = right.score + right.prominence * 0.60 + right_purity * 50.0
            - right_baseline_ratio * 240.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });

    let max_preserved = expected_peak_count * 3 + 14;
    for peak in supplements {
        if preserved.len() >= max_preserved {
            break;
        }
        if preserved
            .iter()
            .any(|existing| existing.index.abs_diff(peak.index) <= 2)
        {
            continue;
        }
        preserved.push(peak);
    }
    preserved.sort_by_key(|peak| peak.index);
    preserved
}

fn preserve_liz_local_anchor_grid_candidates(
    base: &[Peak],
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    expected_peak_count: usize,
) -> Vec<Peak> {
    if expected_peak_count != LadderKind::Liz500250.expected_peak_count() {
        return base.to_vec();
    }

    let mut preserved = base.to_vec();
    let mut supplements = Vec::new();
    for values in [
        corrected_trace,
        quantile_corrected_trace,
        morph_corrected_trace,
        snip_corrected_trace,
    ] {
        supplements.extend(liz_local_anchor_rescue_candidates(
            values,
            &[
                (1600, 1688, 6.0, 8usize),
                (2235, 2278, 6.0, 6usize),
                (3060, 3125, 6.0, 6usize),
            ],
        ));
    }
    if supplements.is_empty() {
        preserved.sort_by_key(|peak| peak.index);
        return preserved;
    }

    supplements.sort_by(|left, right| {
        let left_region = liz_local_anchor_grid_region_rank(left.index);
        let right_region = liz_local_anchor_grid_region_rank(right.index);
        left_region
            .partial_cmp(&right_region)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                let left_height = left.height.max(1.0);
                let right_height = right.height.max(1.0);
                let left_baseline_ratio =
                    (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
                let right_baseline_ratio =
                    (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
                let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
                let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
                let left_rank = left.score + left.prominence * 0.55 + left_purity * 45.0
                    - left_baseline_ratio * 220.0;
                let right_rank = right.score + right.prominence * 0.55 + right_purity * 45.0
                    - right_baseline_ratio * 220.0;
                right_rank
                    .partial_cmp(&left_rank)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let max_preserved = expected_peak_count * 3 + 20;
    for peak in supplements {
        if preserved.len() >= max_preserved {
            break;
        }
        if preserved
            .iter()
            .any(|existing| existing.index.abs_diff(peak.index) <= 2)
        {
            continue;
        }
        preserved.push(peak);
    }
    preserved.sort_by_key(|peak| peak.index);
    preserved
}

fn liz_local_anchor_grid_region_rank(index: usize) -> f64 {
    if (2235..=2278).contains(&index) {
        0.0
    } else if (3060..=3125).contains(&index) {
        1.0
    } else if (1600..=1688).contains(&index) {
        2.0
    } else {
        3.0
    }
}

fn liz_anchor_rescue_region_rank(index: usize) -> f64 {
    if (1470..=1618).contains(&index) {
        0.0
    } else if (4050..=4185).contains(&index) {
        1.0
    } else if (1450..1470).contains(&index) || (1619..=1625).contains(&index) {
        2.0
    } else {
        3.0
    }
}

fn liz_local_anchor_rescue_candidates(
    values: &[f64],
    windows: &[(usize, usize, f64, usize)],
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    for (start, end, min_height, max_keep) in windows.iter().copied() {
        if end <= start + 2 || start >= values.len() {
            continue;
        }
        let bounded_end = end.min(values.len());
        let mut local = find_peaks(&values[start..bounded_end], min_height, 1)
            .into_iter()
            .map(|mut peak| {
                peak.index += start;
                peak
            })
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                peak.height >= min_height
                    && peak.prominence >= min_height
                    && (baseline_ratio <= 0.72 || purity >= 0.32)
            })
            .collect::<Vec<_>>();
        local.sort_by(|left, right| {
            let left_height = left.height.max(1.0);
            let right_height = right.height.max(1.0);
            let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
            let right_baseline_ratio =
                (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
            let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
            let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
            let left_rank = left.score + left.prominence * 0.45 + left_purity * 35.0
                - left_baseline_ratio * 180.0;
            let right_rank = right.score + right.prominence * 0.45 + right_purity * 35.0
                - right_baseline_ratio * 180.0;
            right_rank
                .partial_cmp(&left_rank)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.index.cmp(&right.index))
        });
        if local.len() > max_keep {
            local.truncate(max_keep);
        }
        pooled.extend(local);
    }
    pooled
}

fn liz_tail_extension_candidates(
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    max_peaks: usize,
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    for values in [corrected_trace, quantile_corrected_trace] {
        let peaks = find_peaks(values, 6.0, 4);
        pooled.extend(
            peaks
                .into_iter()
                .filter(|peak| (4200..=LIZ_BLOB_LANE_TIME_MAX).contains(&peak.index)),
        );
        for (start, end) in [(4200usize, 4450usize), (4420, 4700), (4680, 5000)] {
            if start >= values.len() {
                continue;
            }
            let bounded_end = end.min(values.len());
            if bounded_end <= start + 2 {
                continue;
            }
            let slice = &values[start..bounded_end];
            let mut local = find_peaks(slice, 5.0, 3)
                .into_iter()
                .map(|mut peak| {
                    peak.index += start;
                    peak
                })
                .collect::<Vec<_>>();
            local.sort_by(|left, right| {
                right
                    .score
                    .partial_cmp(&left.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| {
                        right
                            .prominence
                            .partial_cmp(&left.prominence)
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .then_with(|| {
                        right
                            .height
                            .partial_cmp(&left.height)
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .then_with(|| left.index.cmp(&right.index))
            });
            if local.len() > 8 {
                local.truncate(8);
            }
            pooled.extend(local);
        }
    }
    if pooled.is_empty() {
        return Vec::new();
    }
    let tail = pooled
        .iter()
        .filter(|peak| (4200..=LIZ_BLOB_LANE_TIME_MAX).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    merge_candidate_sets(&[tail], 6, max_peaks.min(20))
}

fn liz_broad_peak_candidates(
    raw_trace: &[f64],
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    max_peaks: usize,
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    for values in [raw_trace, corrected_trace, quantile_corrected_trace] {
        let mut peaks = find_peaks(values, 20.0, 15);
        peaks.retain(|peak| (1400..=5000).contains(&peak.index));
        peaks.sort_by(|left, right| {
            let left_height = left.height.max(1.0);
            let right_height = right.height.max(1.0);
            let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
            let right_baseline_ratio =
                (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
            let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
            let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
            let left_rank = left.prominence + left.score * 0.55 - left_baseline_ratio * 1400.0
                + left_purity * 80.0;
            let right_rank = right.prominence + right.score * 0.55 - right_baseline_ratio * 1400.0
                + right_purity * 80.0;
            right_rank
                .partial_cmp(&left_rank)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.index.cmp(&right.index))
        });
        if peaks.len() > 24 {
            peaks.truncate(24);
        }
        pooled.extend(peaks);
    }
    if pooled.is_empty() {
        return Vec::new();
    }

    let very_early = pooled
        .iter()
        .filter(|peak| (1400..=1650).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let early = pooled
        .iter()
        .filter(|peak| (1651..=2150).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let middle = pooled
        .iter()
        .filter(|peak| (2151..=3150).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let tail = pooled
        .iter()
        .filter(|peak| (3151..=5000).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();

    let very_early = select_diverse_peak_subset_with_buckets(very_early, 10, 5);
    let early = select_diverse_peak_subset_with_buckets(early, 12, 6);
    let middle = select_diverse_peak_subset_with_buckets(middle, 14, 7);
    let tail = select_diverse_peak_subset_with_buckets(tail, 14, 7);
    merge_candidate_sets(&[very_early, early, middle, tail], 8, max_peaks.min(44))
}

fn rox_window_peak_candidates(
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    _min_distance: usize,
    max_peaks: usize,
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    let window_distance = 5usize;
    for values in [corrected_trace, quantile_corrected_trace] {
        let peaks = find_peaks(values, 12.0, window_distance);
        pooled.extend(
            peaks
                .into_iter()
                .filter(|peak| (1900..=4300).contains(&peak.index)),
        );
    }
    if pooled.is_empty() {
        return Vec::new();
    }

    pooled.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let mut start = pooled
        .iter()
        .filter(|peak| (1900..=2350).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let mut tail = pooled
        .iter()
        .filter(|peak| (3900..=4300).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let middle = pooled
        .iter()
        .filter(|peak| (2351..=3899).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    start = select_diverse_peak_subset_with_buckets(start, 10, 5);
    tail = select_diverse_peak_subset_with_buckets(tail, 10, 5);
    let middle = select_diverse_peak_subset_with_buckets(middle, 28, 12);

    merge_candidate_sets(&[start, middle, tail], window_distance, max_peaks.min(48))
}

fn rox_early_window_peak_candidates(
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    max_peaks: usize,
) -> Vec<Peak> {
    let mut pooled = Vec::new();
    let window_distance = 5usize;
    for values in [corrected_trace, quantile_corrected_trace] {
        let peaks = find_peaks(values, 10.0, window_distance);
        pooled.extend(
            peaks
                .into_iter()
                .filter(|peak| (1450..=2350).contains(&peak.index)),
        );
        pooled.extend(rox_expected_window_peak_candidates(values));
    }
    if pooled.is_empty() {
        return Vec::new();
    }

    pooled.sort_by(|left, right| {
        let left_baseline_ratio =
            (left.local_baseline.max(0.0) / left.height.max(1.0)).clamp(0.0, 1.5);
        let right_baseline_ratio =
            (right.local_baseline.max(0.0) / right.height.max(1.0)).clamp(0.0, 1.5);
        let left_rank = left.score + left.prominence * 0.35 - left_baseline_ratio * 900.0;
        let right_rank = right.score + right.prominence * 0.35 - right_baseline_ratio * 900.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let very_early = pooled
        .iter()
        .filter(|peak| (1450..=1700).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let early = pooled
        .iter()
        .filter(|peak| (1701..=2000).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();
    let bridge = pooled
        .iter()
        .filter(|peak| (2001..=2350).contains(&peak.index))
        .cloned()
        .collect::<Vec<_>>();

    let very_early = select_diverse_peak_subset_with_buckets(very_early, 10, 5);
    let early = select_diverse_peak_subset_with_buckets(early, 10, 5);
    let bridge = select_diverse_peak_subset_with_buckets(bridge, 10, 5);
    merge_candidate_sets(
        &[very_early, early, bridge],
        window_distance,
        max_peaks.min(30),
    )
}

fn rox_minwin_tail_extension_candidates(values: &[f64], expected_peak_count: usize) -> Vec<Peak> {
    if values.len() < 3900 {
        return Vec::new();
    }
    let mut pooled = Vec::new();
    let peaks = find_peaks(values, 8.0, 4);
    pooled.extend(
        peaks
            .into_iter()
            .filter(|peak| (3900..=4400).contains(&peak.index)),
    );
    for (start, end) in [(3900usize, 4085usize), (4070, 4235), (4210, 4400)] {
        if start >= values.len() {
            continue;
        }
        let bounded_end = end.min(values.len());
        if bounded_end <= start + 2 {
            continue;
        }
        let mut local = find_peaks(&values[start..bounded_end], 6.0, 3)
            .into_iter()
            .map(|mut peak| {
                peak.index += start;
                peak
            })
            .collect::<Vec<_>>();
        local.sort_by(|left, right| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    right
                        .prominence
                        .partial_cmp(&left.prominence)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| {
                    right
                        .height
                        .partial_cmp(&left.height)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| left.index.cmp(&right.index))
        });
        if local.len() > 5 {
            local.truncate(5);
        }
        pooled.extend(local);
    }
    if pooled.is_empty() {
        return Vec::new();
    }
    pooled.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });
    if pooled.len() > expected_peak_count.min(12).max(8) {
        pooled.truncate(expected_peak_count.min(12).max(8));
    }
    merge_candidate_sets(&[pooled], 4, expected_peak_count.min(12).max(8))
}

fn rox_expected_window_peak_candidates(values: &[f64]) -> Vec<Peak> {
    let windows = [
        (1450usize, 1685usize),
        (1570, 1815),
        (1710, 2015),
        (1835, 2145),
        (2060, 2405),
    ];
    let mut pooled = Vec::new();
    for (start, end) in windows {
        if end <= start + 2 || start >= values.len() {
            continue;
        }
        let bounded_end = end.min(values.len());
        let slice = &values[start..bounded_end];
        let mut local = find_peaks(slice, 8.0, 4)
            .into_iter()
            .map(|mut peak| {
                peak.index += start;
                peak
            })
            .collect::<Vec<_>>();
        local.sort_by(|left, right| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    right
                        .prominence
                        .partial_cmp(&left.prominence)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| {
                    right
                        .height
                        .partial_cmp(&left.height)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| left.index.cmp(&right.index))
        });
        if local.len() > 3 {
            local.truncate(3);
        }
        pooled.extend(local);
    }
    pooled
}

fn coverage_peak_candidates(
    values: &[f64],
    min_distance: usize,
    max_peaks: usize,
    expected_peak_count: usize,
    ladder: LadderKind,
) -> Vec<Peak> {
    if values.len() < 500 {
        return Vec::new();
    }

    let (window_start, window_end) = match ladder {
        LadderKind::Liz500250 => (1150usize, LIZ_DEFAULT_LANE_TIME_MAX),
        LadderKind::Rox400Hd => (1300usize, 4300usize),
        LadderKind::Gs500Rox => (
            GS500ROX_HARD_TIME_MIN as usize,
            GS500ROX_HARD_TIME_MAX as usize,
        ),
    };
    let hard_start = window_start.min(values.len().saturating_sub(1));
    let hard_end = window_end.min(values.len());
    if hard_end <= hard_start + 2 {
        return Vec::new();
    }

    let low_threshold = match ladder {
        LadderKind::Liz500250 => 10.0,
        LadderKind::Rox400Hd | LadderKind::Gs500Rox => 12.0,
    };
    let all_peaks = find_peaks(values, low_threshold, min_distance);
    if all_peaks.is_empty() {
        return Vec::new();
    }

    let bucket_count = expected_peak_count.min(12).max(6);
    let bucket_width = ((hard_end - hard_start) as f64 / bucket_count as f64)
        .ceil()
        .max(1.0) as usize;
    let mut selected: Vec<Peak> = Vec::new();

    for bucket in 0..bucket_count {
        let start = hard_start.saturating_add(bucket * bucket_width);
        let end = if bucket + 1 >= bucket_count {
            hard_end
        } else {
            hard_start
                .saturating_add((bucket + 1) * bucket_width)
                .min(hard_end)
        };
        let best = all_peaks
            .iter()
            .filter(|peak| peak.index >= start && peak.index < end)
            .max_by(|left, right| {
                left.score
                    .partial_cmp(&right.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .cloned();
        if let Some(peak) = best {
            selected.push(peak);
        }
    }

    if selected.is_empty() {
        return Vec::new();
    }
    selected = select_diverse_peak_subset(selected, max_peaks.min(bucket_count + 4));
    selected.sort_by_key(|peak| peak.index);
    selected
}

fn adaptive_top_peak_candidates(
    values: &[f64],
    min_height: f64,
    min_distance: usize,
    max_peaks: usize,
    target_candidate_count: usize,
    min_candidate_span: usize,
) -> Vec<Peak> {
    let mut best = Vec::new();
    let mut thresholds = vec![
        min_height,
        (min_height * 0.80).max(20.0),
        (min_height * 0.60).max(20.0),
        (min_height * 0.45).max(20.0),
        20.0,
    ];
    thresholds.dedup_by(|left, right| (*left - *right).abs() < f64::EPSILON);

    for threshold in thresholds {
        let candidates = top_peak_candidates(values, threshold, min_distance, max_peaks);
        if candidate_pool_rank(&candidates) > candidate_pool_rank(&best) {
            best = candidates.clone();
        }
        if candidates.len() >= target_candidate_count
            && candidate_span(&candidates) >= min_candidate_span
        {
            return candidates;
        }
    }
    best
}

fn candidate_span(peaks: &[Peak]) -> usize {
    match (peaks.first(), peaks.last()) {
        (Some(first), Some(last)) => last.index.saturating_sub(first.index),
        _ => 0,
    }
}

fn candidate_pool_rank(peaks: &[Peak]) -> usize {
    peaks
        .len()
        .saturating_mul(10_000)
        .saturating_add(candidate_span(peaks))
}

fn filter_gs500rox_candidate_scan_window(peaks: &[Peak]) -> Vec<Peak> {
    peaks
        .iter()
        .filter(|peak| {
            let scan = peak.index as f64;
            (GS500ROX_ABSOLUTE_TIME_MIN..=GS500ROX_ABSOLUTE_TIME_MAX).contains(&scan)
        })
        .cloned()
        .collect()
}

fn candidate_has_tail_coverage(peaks: &[Peak], ladder: LadderKind) -> bool {
    let Some(last) = peaks.last() else {
        return false;
    };
    match ladder {
        LadderKind::Liz500250 => last.index >= 4500 && candidate_span(peaks) >= 2600,
        LadderKind::Rox400Hd => last.index >= 3300 && candidate_span(peaks) >= 1850,
        LadderKind::Gs500Rox => last.index >= 3900 && candidate_span(peaks) >= 2400,
    }
}

fn top_peak_candidates(
    values: &[f64],
    min_height: f64,
    min_distance: usize,
    max_peaks: usize,
) -> Vec<Peak> {
    let mut peaks = find_peaks(values, min_height, min_distance);
    peaks = select_diverse_peak_subset(peaks, max_peaks);
    peaks.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });
    if peaks.len() > max_peaks {
        peaks.truncate(max_peaks);
    }
    peaks.sort_by_key(|peak| peak.index);
    peaks
}

fn select_diverse_peak_subset(peaks: Vec<Peak>, max_peaks: usize) -> Vec<Peak> {
    select_diverse_peak_subset_with_buckets(peaks, max_peaks, max_peaks.clamp(4, 8))
}

fn select_diverse_peak_subset_with_buckets(
    peaks: Vec<Peak>,
    max_peaks: usize,
    bucket_count: usize,
) -> Vec<Peak> {
    if peaks.len() <= max_peaks {
        return peaks;
    }

    let mut ranked = peaks;
    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let min_index = ranked.iter().map(|peak| peak.index).min().unwrap_or(0);
    let max_index = ranked
        .iter()
        .map(|peak| peak.index)
        .max()
        .unwrap_or(min_index);
    let span = max_index.saturating_sub(min_index);
    if span == 0 {
        ranked.truncate(max_peaks);
        return ranked;
    }

    let bucket_count = bucket_count.clamp(4, max_peaks.max(4));
    let bucket_width = ((span as f64) / bucket_count as f64).ceil().max(1.0) as usize;
    let mut selected: Vec<Peak> = Vec::new();

    for bucket in 0..bucket_count {
        let start = min_index.saturating_add(bucket * bucket_width);
        let end = if bucket + 1 >= bucket_count {
            max_index.saturating_add(1)
        } else {
            min_index.saturating_add((bucket + 1) * bucket_width)
        };
        if let Some(best) = ranked
            .iter()
            .filter(|peak| peak.index >= start && peak.index < end)
            .min_by(|left, right| {
                right
                    .score
                    .partial_cmp(&left.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .cloned()
        {
            if !selected.iter().any(|peak| peak.index == best.index) {
                selected.push(best);
            }
        }
    }

    for peak in ranked {
        if selected.len() >= max_peaks {
            break;
        }
        if selected.iter().any(|kept| kept.index == peak.index) {
            continue;
        }
        selected.push(peak);
    }

    selected
}

fn merge_candidate_sets(
    candidate_sets: &[Vec<Peak>],
    min_distance: usize,
    max_peaks: usize,
) -> Vec<Peak> {
    let mut combined = candidate_sets
        .iter()
        .flat_map(|peaks| peaks.iter().cloned())
        .collect::<Vec<_>>();
    combined.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let merge_distance = ((min_distance as f64) * 0.25).floor() as usize;
    let mut merged: Vec<Peak> = Vec::new();
    'candidate: for candidate in combined {
        for kept in &merged {
            if candidate.index.abs_diff(kept.index) <= merge_distance {
                continue 'candidate;
            }
        }
        merged.push(candidate);
    }

    if candidate_span(&merged) < 1500 {
        merged = select_diverse_peak_subset(merged, max_peaks);
    } else if merged.len() > max_peaks {
        merged = select_diverse_peak_subset(merged, max_peaks);
    }
    merged.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });
    if merged.len() > max_peaks {
        merged.truncate(max_peaks);
    }
    merged.sort_by_key(|peak| peak.index);
    merged
}

fn filter_peak_pool_for_ladder_fit(
    ladder_peaks: &[Peak],
    ladder: LadderKind,
    target_len: usize,
) -> Vec<Peak> {
    match ladder {
        LadderKind::Liz500250 => filter_liz_peak_pool_for_fit(ladder_peaks, target_len),
        LadderKind::Rox400Hd => filter_rox_peak_pool_for_fit(ladder_peaks, target_len),
        _ => ladder_peaks.to_vec(),
    }
}

fn build_alternative_ladder_peak_lanes(
    raw_trace: &[f64],
    corrected_trace: &[f64],
    quantile_corrected_trace: &[f64],
    morph_corrected_trace: &[f64],
    snip_corrected_trace: &[f64],
    raw_min_height: f64,
    corrected_min_height: f64,
    min_distance: usize,
    ladder: LadderKind,
) -> Vec<Vec<Peak>> {
    let max_peaks = ladder.expected_peak_count() * 2 + 15;
    let expected_peak_count = ladder.expected_peak_count();
    let mut lanes = Vec::new();

    if ladder == LadderKind::Liz500250 {
        let morph_lane = select_ladder_peaks(
            raw_trace,
            morph_corrected_trace,
            morph_corrected_trace,
            morph_corrected_trace,
            morph_corrected_trace,
            raw_min_height,
            corrected_min_height,
            min_distance,
            max_peaks,
            expected_peak_count,
            ladder,
        );
        if morph_lane.len() >= expected_peak_count {
            lanes.push(morph_lane);
        }

        let snip_lane = select_ladder_peaks(
            raw_trace,
            snip_corrected_trace,
            snip_corrected_trace,
            snip_corrected_trace,
            snip_corrected_trace,
            raw_min_height,
            corrected_min_height,
            min_distance,
            max_peaks,
            expected_peak_count,
            ladder,
        );
        if snip_lane.len() >= expected_peak_count {
            lanes.push(snip_lane);
        }
    } else if matches!(ladder, LadderKind::Rox400Hd | LadderKind::Gs500Rox) {
        let minwin_corrected = baseline_correct_min_window_nonnegative(raw_trace, 51);
        let minwin_light_corrected = moving_average_smooth(&minwin_corrected, 2);
        let minwin_lane = select_ladder_peaks(
            raw_trace,
            &minwin_light_corrected,
            &minwin_light_corrected,
            &minwin_light_corrected,
            &minwin_light_corrected,
            raw_min_height,
            corrected_min_height,
            min_distance,
            max_peaks,
            expected_peak_count,
            ladder,
        );
        if minwin_lane.len() >= expected_peak_count {
            lanes.push(minwin_lane);
        }

        let arpls_cap_lane = select_ladder_peaks(
            raw_trace,
            corrected_trace,
            quantile_corrected_trace,
            corrected_trace,
            quantile_corrected_trace,
            raw_min_height,
            corrected_min_height,
            min_distance,
            max_peaks,
            expected_peak_count,
            ladder,
        );
        if arpls_cap_lane.len() >= expected_peak_count {
            lanes.push(arpls_cap_lane);
        }

        if ladder == LadderKind::Gs500Rox {
            let morph_lane = select_ladder_peaks(
                raw_trace,
                morph_corrected_trace,
                morph_corrected_trace,
                morph_corrected_trace,
                morph_corrected_trace,
                raw_min_height,
                corrected_min_height,
                min_distance,
                max_peaks,
                expected_peak_count,
                ladder,
            );
            if morph_lane.len() >= expected_peak_count {
                lanes.push(morph_lane);
            }

            let snip_lane = select_ladder_peaks(
                raw_trace,
                snip_corrected_trace,
                snip_corrected_trace,
                snip_corrected_trace,
                snip_corrected_trace,
                raw_min_height,
                corrected_min_height,
                min_distance,
                max_peaks,
                expected_peak_count,
                ladder,
            );
            if snip_lane.len() >= expected_peak_count {
                lanes.push(snip_lane);
            }
        }
    }

    lanes
}

fn build_ladder_fit_preview_with_arbiter(
    default_ladder_peaks: Vec<Peak>,
    alternative_lanes: Vec<Vec<Peak>>,
    sample_trace: &[f64],
    ladder_trace: &[f64],
    ladder: LadderKind,
) -> (Vec<Peak>, Option<LadderFitPreview>) {
    let mut best_peaks = default_ladder_peaks;
    let mut best_preview =
        build_ladder_fit_preview(&best_peaks, sample_trace, ladder_trace, ladder, false);
    let default_peaks_for_guard = best_peaks.clone();
    let default_preview_for_guard = best_preview.clone();
    if should_try_alternative_ladder_lanes(best_preview.as_ref(), ladder) {
        for lane_peaks in alternative_lanes {
            let target_len = ladder.expected_peak_count();
            if lane_peaks.len() < target_len {
                continue;
            }
            let keep_limit = if ladder == LadderKind::Liz500250 {
                target_len + 12
            } else {
                target_len + 10
            };
            let fit_lane_peaks = if lane_peaks.len() > keep_limit {
                thin_peak_pool_for_ladder(&lane_peaks, target_len, 18, keep_limit)
            } else {
                lane_peaks
            };
            if fit_lane_peaks.len() < target_len {
                continue;
            }
            let candidate_preview = build_ladder_fit_preview(
                &fit_lane_peaks,
                sample_trace,
                ladder_trace,
                ladder,
                false,
            );
            let should_promote = match (best_preview.as_ref(), candidate_preview.as_ref()) {
                (Some(current), Some(candidate)) => arbiter_prefers_candidate_lane(
                    current,
                    candidate,
                    &best_peaks,
                    &fit_lane_peaks,
                    ladder,
                ),
                (None, Some(_)) => true,
                _ => false,
            };
            if should_promote {
                best_peaks = fit_lane_peaks;
                best_preview = candidate_preview;
            }
        }
    }

    // The final pass only enables ROX visual-start repair. Re-running the
    // complete deterministic LIZ search here cannot change LIZ output and
    // doubles all of its candidate and repair work.
    let final_preview = if ladder == LadderKind::Liz500250 {
        None
    } else {
        build_ladder_fit_preview(&best_peaks, sample_trace, ladder_trace, ladder, true)
    };
    if final_preview.is_some() {
        best_preview = final_preview;
    }

    if ladder == LadderKind::Rox400Hd {
        if let (Some(default_preview), Some(candidate_preview)) =
            (default_preview_for_guard.as_ref(), best_preview.as_ref())
        {
            let default_scans = selected_preview_scans(default_preview);
            let candidate_scans = selected_preview_scans(candidate_preview);
            let default_metrics = preview_linear_metrics(default_preview);
            let candidate_first = candidate_scans.first().copied().unwrap_or(0);
            let default_first = default_scans.first().copied().unwrap_or(0);
            let default_is_good_normal_start = (1520..=1850).contains(&default_first)
                && default_metrics.is_some_and(|(linear_max, linear_mean, linear_r2, _)| {
                    linear_max <= 6.0 && linear_mean <= 2.8 && linear_r2 >= 0.9988
                });
            if default_is_good_normal_start
                && candidate_first > default_first.saturating_add(220)
                && candidate_first > 1850
            {
                best_peaks = default_peaks_for_guard;
                best_preview =
                    build_ladder_fit_preview(&best_peaks, sample_trace, ladder_trace, ladder, true)
                        .or(default_preview_for_guard);
            }
        }
    }

    (best_peaks, best_preview)
}

fn should_try_alternative_ladder_lanes(
    preview: Option<&LadderFitPreview>,
    ladder: LadderKind,
) -> bool {
    let Some(preview) = preview else {
        return true;
    };
    let Some((linear_max, linear_mean, linear_r2, _)) = preview_linear_metrics(preview) else {
        return true;
    };
    match ladder {
        // LIZ side-lanes improved aggregate residuals, but the current live
        // implementation can exceed the per-file worker timeout on blob-heavy
        // hardcases. Keep LIZ baseline methods as candidate supplements until
        // the side-lane search is made bounded enough for production.
        LadderKind::Liz500250 => false,
        LadderKind::Rox400Hd => linear_max > 6.0 || linear_mean > 2.6 || linear_r2 < 0.9990,
        LadderKind::Gs500Rox => linear_max > 6.0 || linear_mean > 3.0 || linear_r2 < 0.9985,
    }
}

#[derive(Debug, Clone, Copy)]
struct PreviewPeakPlausibility {
    penalty: f64,
    selected_below_floor: usize,
    baseline_like: usize,
    missing_features: usize,
}

fn preview_peak_plausibility(
    preview: &LadderFitPreview,
    lane_peaks: &[Peak],
    ladder: LadderKind,
) -> PreviewPeakPlausibility {
    let peak_by_index = lane_peaks
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let scans = selected_preview_scans(preview);
    let mut heights = scans
        .iter()
        .filter_map(|scan| peak_by_index.get(scan).map(|peak| peak.height))
        .filter(|height| height.is_finite() && *height > 0.0)
        .collect::<Vec<_>>();
    let height_ref = median(&heights).max(1.0);
    heights.clear();

    let floor = if ladder == LadderKind::Rox400Hd {
        50.0
    } else {
        8.0
    };
    let mut penalty = 0.0;
    let mut selected_below_floor = 0usize;
    let mut baseline_like = 0usize;
    let mut missing_features = 0usize;

    for scan in scans {
        let Some(peak) = peak_by_index.get(&scan) else {
            missing_features += 1;
            penalty += 8.0;
            continue;
        };
        let height = peak.height.max(1.0);
        let purity = (peak.prominence / height).clamp(0.0, 1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        if peak.height < floor {
            selected_below_floor += 1;
            penalty += if ladder == LadderKind::Rox400Hd {
                3.0
            } else {
                1.0
            };
        }
        if baseline_ratio > 0.35 && purity < 0.50 {
            baseline_like += 1;
            penalty += 2.5;
        }
        if height < height_ref * 0.25 && purity < 0.55 {
            penalty += 1.5;
        }
    }

    PreviewPeakPlausibility {
        penalty,
        selected_below_floor,
        baseline_like,
        missing_features,
    }
}

fn selected_preview_scans(preview: &LadderFitPreview) -> Vec<usize> {
    preview
        .refinement
        .as_ref()
        .map(|refinement| refinement.refined_scan_indices.clone())
        .unwrap_or_else(|| preview.best_scan_indices.clone())
}

fn arbiter_prefers_candidate_lane(
    current: &LadderFitPreview,
    candidate: &LadderFitPreview,
    current_peaks: &[Peak],
    candidate_peaks: &[Peak],
    ladder: LadderKind,
) -> bool {
    let (Some(current_metrics), Some(candidate_metrics)) = (
        preview_linear_metrics(current),
        preview_linear_metrics(candidate),
    ) else {
        return candidate.sizing_model.is_some() && current.sizing_model.is_none();
    };

    let (current_linear_max, current_linear_mean, current_linear_r2, current_spline_max) =
        current_metrics;
    let (candidate_linear_max, candidate_linear_mean, candidate_linear_r2, candidate_spline_max) =
        candidate_metrics;

    if candidate_linear_r2 + 0.0015 < current_linear_r2 {
        return false;
    }
    if candidate_spline_max > current_spline_max + 1.25 && candidate_linear_max > 6.0 {
        return false;
    }

    let current_plausibility = preview_peak_plausibility(current, current_peaks, ladder);
    let candidate_plausibility = preview_peak_plausibility(candidate, candidate_peaks, ladder);
    if candidate_plausibility.missing_features > current_plausibility.missing_features {
        return false;
    }
    if candidate_plausibility.baseline_like > current_plausibility.baseline_like + 1 {
        return false;
    }
    if ladder == LadderKind::Rox400Hd
        && candidate_plausibility.selected_below_floor > current_plausibility.selected_below_floor
    {
        return false;
    }
    if ladder == LadderKind::Rox400Hd && current_linear_max <= 5.0 {
        let candidate_scans = selected_preview_scans(candidate);
        if candidate_scans
            .first()
            .is_some_and(|first_anchor| *first_anchor > 1900)
        {
            return false;
        }
    }
    if candidate_plausibility.penalty > current_plausibility.penalty + 3.0 {
        return false;
    }

    let strong_residual_win = candidate_linear_max + 1.50 < current_linear_max
        && candidate_linear_mean <= current_linear_mean + 0.35;
    let hardcase_rescue = current_linear_max > 6.0
        && candidate_linear_max <= 6.0
        && candidate_linear_mean <= 5.0
        && candidate_plausibility.penalty <= current_plausibility.penalty + 1.5;
    let plausibility_win = candidate_plausibility.penalty + 2.0 < current_plausibility.penalty
        && candidate_linear_max <= current_linear_max + 0.75
        && candidate_linear_mean <= current_linear_mean + 0.45;

    strong_residual_win || hardcase_rescue || plausibility_win
}

fn liz_has_nearby_stronger_alternative(
    ladder_peaks: &[Peak],
    peak: &Peak,
    height_floor: f64,
    prominence_floor: f64,
) -> bool {
    ladder_peaks.iter().any(|other| {
        if other.index == peak.index || other.index.abs_diff(peak.index) > 120 {
            return false;
        }

        let other_height = other.height.max(1.0);
        let other_prominence = other.prominence.max(1.0);
        let other_baseline_ratio = (other.local_baseline.max(0.0) / other_height).clamp(0.0, 1.5);
        let other_purity = (other_prominence / other_height).clamp(0.0, 1.0);

        other.height >= height_floor
            && other.prominence >= prominence_floor
            && other.height >= peak.height * 1.8
            && other.prominence >= peak.prominence * 1.8
            && (other_baseline_ratio <= 0.38 || other_purity >= 0.62)
    })
}

fn filter_liz_peak_pool_for_fit(ladder_peaks: &[Peak], target_len: usize) -> Vec<Peak> {
    if ladder_peaks.len() <= target_len + 2 {
        return ladder_peaks.to_vec();
    }

    let mut reference = ladder_peaks
        .iter()
        .filter(|peak| {
            peak.index >= LIZ_PREFERRED_TIME_MIN as usize
                && peak.index <= LIZ_PREFERRED_TIME_MAX as usize
                && peak.prominence >= 35.0
                && peak.score >= 35.0
        })
        .cloned()
        .collect::<Vec<_>>();
    if reference.is_empty() {
        reference = ladder_peaks.to_vec();
    }
    reference.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    reference.truncate(target_len.clamp(5, 8));

    let reference_heights = reference.iter().map(|peak| peak.height).collect::<Vec<_>>();
    let reference_prominences = reference
        .iter()
        .map(|peak| peak.prominence)
        .collect::<Vec<_>>();
    let reference_scores = reference.iter().map(|peak| peak.score).collect::<Vec<_>>();
    let height_ref = median(&reference_heights).max(1.0);
    let prominence_ref = median(&reference_prominences).max(1.0);
    let score_ref = median(&reference_scores).max(1.0);
    let dynamic_height_floor = (height_ref * 0.22).clamp(80.0, 150.0);
    let dynamic_prominence_floor = (prominence_ref * 0.18).clamp(28.0, 95.0);
    let dynamic_score_floor = (score_ref * 0.16).clamp(18.0, 120.0);
    let post_blob_plausible_count = ladder_peaks
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.index >= 1400
                && peak.index <= LIZ_BLOB_LANE_TIME_MAX
                && peak.height >= 10.0
                && peak.prominence >= 8.0
                && (baseline_ratio <= 0.75 || purity >= 0.30)
        })
        .count();
    let reject_pre_blob_noise = post_blob_plausible_count >= target_len;

    let mut filtered = Vec::with_capacity(ladder_peaks.len());
    let mut salvageable = Vec::new();
    for peak in ladder_peaks {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence / height).clamp(0.0, 1.0);
        let strong_enough = peak.height >= dynamic_height_floor
            || peak.prominence >= dynamic_prominence_floor
            || peak.score >= dynamic_score_floor;

        let quality_ok = if peak.height < height_ref * 0.38 {
            baseline_ratio <= 0.34 && purity >= 0.48
        } else if peak.height < height_ref * 0.55 {
            baseline_ratio <= 0.42 && purity >= 0.40
        } else {
            baseline_ratio <= 0.78 || purity >= 0.26
        };

        let early_blob_like = peak.index < 1500
            && peak.height > height_ref * 2.6
            && baseline_ratio > 0.16
            && purity < 0.78;
        let early_shoulder_blob_like = peak.index < 1700
            && peak.height > height_ref * 1.45
            && baseline_ratio > 0.42
            && purity < 0.52;
        let weak_baseline_like = peak.height < dynamic_height_floor * 0.85
            && baseline_ratio > 0.45
            && purity < 0.48
            && peak.prominence < dynamic_prominence_floor.max(45.0);
        let local_low_outlier = peak.height < (height_ref * 0.35).max(dynamic_height_floor)
            && peak.prominence < (prominence_ref * 0.35).max(dynamic_prominence_floor)
            && liz_has_nearby_stronger_alternative(
                ladder_peaks,
                peak,
                (height_ref * 0.52).max(dynamic_height_floor * 1.25),
                (prominence_ref * 0.50).max(dynamic_prominence_floor * 1.20),
            );
        let pre_blob_noise = reject_pre_blob_noise && peak.index < 1350;

        let hard_reject = pre_blob_noise
            || early_blob_like
            || early_shoulder_blob_like
            || weak_baseline_like
            || local_low_outlier;
        if strong_enough && quality_ok && !hard_reject {
            filtered.push(peak.clone());
        } else if !hard_reject {
            salvageable.push(peak.clone());
        }
    }

    let mut early_anchor_rescue = ladder_peaks
        .iter()
        .filter(|peak| (1470..=1610).contains(&peak.index))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.prominence >= 10.0
                && peak.score >= 10.0
                && peak.height >= 10.0
                && (baseline_ratio <= 0.55 || purity >= 0.44)
        })
        .cloned()
        .collect::<Vec<_>>();
    early_anchor_rescue.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });
    if early_anchor_rescue.len() > 6 {
        early_anchor_rescue.truncate(6);
    }
    for peak in early_anchor_rescue {
        if filtered.iter().any(|existing| existing.index == peak.index) {
            continue;
        }
        filtered.push(peak);
    }

    let mut mid_triplet_rescue = ladder_peaks
        .iter()
        .filter(|peak| (2050..=2245).contains(&peak.index))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.prominence >= 14.0
                && peak.score >= 12.0
                && peak.height >= 18.0
                && (baseline_ratio <= 0.62 || purity >= 0.38)
        })
        .cloned()
        .collect::<Vec<_>>();
    mid_triplet_rescue.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.40 + left_purity * 45.0 - left_baseline_ratio * 260.0;
        let right_rank = right.score + right.prominence * 0.40 + right_purity * 45.0
            - right_baseline_ratio * 260.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if mid_triplet_rescue.len() > 8 {
        mid_triplet_rescue.truncate(8);
    }
    for peak in mid_triplet_rescue {
        if filtered.iter().any(|existing| existing.index == peak.index) {
            continue;
        }
        filtered.push(peak);
    }

    let mut tail_pair_rescue = ladder_peaks
        .iter()
        .filter(|peak| (4380..=4565).contains(&peak.index))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.prominence >= dynamic_prominence_floor.max(35.0)
                && peak.height >= dynamic_height_floor.max(60.0)
                && (baseline_ratio <= 0.45 || purity >= 0.50)
        })
        .cloned()
        .collect::<Vec<_>>();
    tail_pair_rescue.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.45 + left_purity * 35.0 - left_baseline_ratio * 180.0;
        let right_rank = right.score + right.prominence * 0.45 + right_purity * 35.0
            - right_baseline_ratio * 180.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if tail_pair_rescue.len() > 8 {
        tail_pair_rescue.truncate(8);
    }
    for peak in tail_pair_rescue {
        if filtered.iter().any(|existing| existing.index == peak.index) {
            continue;
        }
        filtered.push(peak);
    }

    let has_giant_mid_200_outlier = ladder_peaks.iter().any(|peak| {
        (2580..=2705).contains(&peak.index) && peak.height >= 800.0 && peak.prominence >= 600.0
    });
    let has_strong_mid_200_rescue_anchor = ladder_peaks.iter().any(|peak| {
        (2460..=2575).contains(&peak.index) && peak.height >= 90.0 && peak.prominence >= 70.0
    });
    if has_giant_mid_200_outlier && has_strong_mid_200_rescue_anchor {
        let mut mid_200_rescue = ladder_peaks
            .iter()
            .filter(|peak| (2460..=2625).contains(&peak.index))
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                peak.prominence >= 18.0
                    && peak.score >= 14.0
                    && peak.height >= 22.0
                    && (baseline_ratio <= 0.70 || purity >= 0.36)
            })
            .cloned()
            .collect::<Vec<_>>();
        mid_200_rescue.sort_by(|left, right| {
            let left_height = left.height.max(1.0);
            let right_height = right.height.max(1.0);
            let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
            let right_baseline_ratio =
                (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
            let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
            let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
            let left_rank = left.score + left.prominence * 0.55 + left_purity * 45.0
                - left_baseline_ratio * 240.0;
            let right_rank = right.score + right.prominence * 0.55 + right_purity * 45.0
                - right_baseline_ratio * 240.0;
            right_rank
                .partial_cmp(&left_rank)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.index.cmp(&right.index))
        });
        if mid_200_rescue.len() > 8 {
            mid_200_rescue.truncate(8);
        }
        for peak in mid_200_rescue {
            if filtered.iter().any(|existing| existing.index == peak.index) {
                continue;
            }
            filtered.push(peak);
        }
    }

    if filtered.len() >= target_len {
        filtered.sort_by_key(|peak| peak.index);
        return filtered;
    }

    salvageable.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    for peak in salvageable {
        if filtered.iter().any(|existing| existing.index == peak.index) {
            continue;
        }
        filtered.push(peak);
        if filtered.len() >= target_len {
            break;
        }
    }

    if filtered.len() >= target_len {
        filtered.sort_by_key(|peak| peak.index);
        filtered
    } else {
        ladder_peaks.to_vec()
    }
}

fn rox_has_nearby_stronger_alternative(
    ladder_peaks: &[Peak],
    peak: &Peak,
    min_height: f64,
    min_prominence: f64,
) -> bool {
    ladder_peaks.iter().any(|other| {
        if other.index == peak.index {
            return false;
        }
        let distance = other.index.abs_diff(peak.index);
        if distance > 75 {
            return false;
        }
        let other_height = other.height.max(1.0);
        let other_baseline_ratio = (other.local_baseline.max(0.0) / other_height).clamp(0.0, 1.5);
        let other_purity = (other.prominence / other_height).clamp(0.0, 1.0);
        other.height >= min_height
            && other.prominence >= min_prominence
            && other.height >= peak.height * 1.7
            && other.prominence >= peak.prominence * 1.7
            && (other_baseline_ratio <= 0.28 || other_purity >= 0.58)
    })
}

fn filter_rox_peak_pool_for_fit(ladder_peaks: &[Peak], target_len: usize) -> Vec<Peak> {
    if ladder_peaks.len() <= target_len + 3 {
        return ladder_peaks.to_vec();
    }

    let mut reference = ladder_peaks
        .iter()
        .filter(|peak| {
            peak.index >= 1600
                && peak.index <= 3600
                && peak.prominence >= 45.0
                && peak.score >= 60.0
                && peak.height >= 50.0
        })
        .cloned()
        .collect::<Vec<_>>();
    if reference.is_empty() {
        reference = ladder_peaks.to_vec();
    }
    reference.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    reference.truncate(target_len.clamp(6, 10));

    let reference_heights = reference.iter().map(|peak| peak.height).collect::<Vec<_>>();
    let reference_prominences = reference
        .iter()
        .map(|peak| peak.prominence)
        .collect::<Vec<_>>();
    let reference_scores = reference.iter().map(|peak| peak.score).collect::<Vec<_>>();
    let height_ref = median(&reference_heights).max(1.0);
    let prominence_ref = median(&reference_prominences).max(1.0);
    let score_ref = median(&reference_scores).max(1.0);
    let dynamic_height_floor = (height_ref * 0.18).clamp(45.0, 140.0);
    let dynamic_prominence_floor = (prominence_ref * 0.18).clamp(28.0, 120.0);
    let dynamic_score_floor = (score_ref * 0.16).clamp(22.0, 140.0);

    let filtered = ladder_peaks
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            let strong_enough = peak.height >= dynamic_height_floor
                || peak.prominence >= dynamic_prominence_floor
                || peak.score >= dynamic_score_floor;

            let quality_ok = if peak.height < height_ref * 0.30 {
                baseline_ratio <= 0.24 && purity >= 0.52
            } else if peak.height < height_ref * 0.50 {
                baseline_ratio <= 0.32 && purity >= 0.42
            } else {
                baseline_ratio <= 0.68 || purity >= 0.24
            };

            let early_blob_like = peak.index < 1605
                && peak.height > height_ref * 3.4
                && (baseline_ratio > 0.10 || purity < 0.40);
            let weak_baseline_like = peak.height < dynamic_height_floor * 0.90
                && baseline_ratio > 0.30
                && purity < 0.52
                && peak.prominence < dynamic_prominence_floor.max(35.0);
            let tail_low_outlier = peak.index >= 3600
                && peak.height < (height_ref * 0.24).max(dynamic_height_floor)
                && peak.prominence < (prominence_ref * 0.22).max(dynamic_prominence_floor);
            let local_low_outlier = peak.height < (height_ref * 0.34).max(dynamic_height_floor)
                && peak.prominence < (prominence_ref * 0.34).max(dynamic_prominence_floor)
                && rox_has_nearby_stronger_alternative(
                    ladder_peaks,
                    peak,
                    (height_ref * 0.48).max(dynamic_height_floor * 1.20),
                    (prominence_ref * 0.46).max(dynamic_prominence_floor * 1.20),
                );

            strong_enough
                && quality_ok
                && !early_blob_like
                && !weak_baseline_like
                && !tail_low_outlier
                && !local_low_outlier
        })
        .cloned()
        .collect::<Vec<_>>();

    if filtered.len() >= target_len {
        filtered
    } else {
        ladder_peaks.to_vec()
    }
}

fn build_ladder_fit_preview(
    ladder_peaks: &[Peak],
    sample_trace: &[f64],
    ladder_trace: &[f64],
    ladder: LadderKind,
    allow_visual_start_repair: bool,
) -> Option<LadderFitPreview> {
    let primary_beam_search_trigger =
        if ladder == LadderKind::Liz500250 && !liz_exact_audit_enabled() {
            LIZ_BEAM_SEARCH_TRIGGER_COMBINATIONS
        } else {
            BEAM_SEARCH_TRIGGER_COMBINATIONS
        };
    let baseline_preview = build_ladder_fit_preview_with_candidate_pool(
        ladder_peaks,
        ladder_peaks,
        sample_trace,
        ladder_trace,
        ladder,
        primary_beam_search_trigger,
        allow_visual_start_repair,
    );
    if ladder != LadderKind::Liz500250 {
        return baseline_preview;
    }

    let target_len = ladder.expected_peak_count();
    let fit_ladder_peaks = filter_peak_pool_for_ladder_fit(ladder_peaks, ladder, target_len);
    let baseline_preview = maybe_rerun_exact_liz_preview(
        baseline_preview,
        ladder_peaks,
        ladder_peaks,
        sample_trace,
        ladder_trace,
    );
    let mut best_preview =
        if fit_ladder_peaks.len() >= target_len && fit_ladder_peaks.len() < ladder_peaks.len() {
            let filtered_preview = maybe_rerun_exact_liz_preview(
                build_ladder_fit_preview_with_candidate_pool(
                    ladder_peaks,
                    &fit_ladder_peaks,
                    sample_trace,
                    ladder_trace,
                    ladder,
                    primary_beam_search_trigger,
                    allow_visual_start_repair,
                ),
                ladder_peaks,
                &fit_ladder_peaks,
                sample_trace,
                ladder_trace,
            );
            match (baseline_preview, filtered_preview) {
                (Some(current), Some(candidate)) => {
                    if preview_prefers_candidate(&current, &candidate) {
                        Some(candidate)
                    } else {
                        Some(current)
                    }
                }
                (None, Some(candidate)) => Some(candidate),
                (Some(current), None) => Some(current),
                (None, None) => None,
            }
        } else {
            baseline_preview
        };

    let peak_feature_by_index = ladder_peaks
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let should_try_liz_broad_preview = best_preview
        .as_ref()
        .map(|preview| {
            preview_has_liz_blob_start(preview, &peak_feature_by_index)
                || preview_is_suspicious_for_exact_liz_retry(preview)
        })
        .unwrap_or(false);
    if should_try_liz_broad_preview {
        let corrected =
            baseline_correct_guarded_nonnegative(ladder_trace, 0.99, 100.0, 1000, 200, 0.10)
                .unwrap_or_else(|_| ladder_trace.to_vec());
        let quantile_corrected = baseline_correct_quantile_nonnegative(ladder_trace, 200, 0.10);
        let tail_extension_peaks = liz_tail_extension_candidates(
            &corrected,
            &quantile_corrected,
            ladder.expected_peak_count() * 2,
        );
        if !tail_extension_peaks.is_empty() {
            let tail_augmented = merge_candidate_sets(
                &[ladder_peaks.to_vec(), tail_extension_peaks],
                4,
                ladder.expected_peak_count() * 2 + 20,
            );
            if tail_augmented.len() >= target_len {
                let tail_augmented_preview = maybe_rerun_exact_liz_preview(
                    build_ladder_fit_preview_with_candidate_pool(
                        &tail_augmented,
                        &tail_augmented,
                        sample_trace,
                        ladder_trace,
                        ladder,
                        primary_beam_search_trigger,
                        allow_visual_start_repair,
                    ),
                    &tail_augmented,
                    &tail_augmented,
                    sample_trace,
                    ladder_trace,
                );
                best_preview = match (best_preview, tail_augmented_preview) {
                    (Some(current), Some(candidate)) => {
                        if exact_liz_preview_prefers_candidate(&current, &candidate) {
                            Some(candidate)
                        } else {
                            Some(current)
                        }
                    }
                    (None, Some(candidate)) => Some(candidate),
                    (some_current, None) => some_current,
                };
            }
        }
        let blob_lane_peaks = liz_blob_suspect_peak_candidates(
            &corrected,
            &quantile_corrected,
            &corrected,
            &quantile_corrected,
            ladder.expected_peak_count() * 2 + 15,
        );
        if blob_lane_peaks.len() >= target_len {
            let blob_preview = maybe_rerun_exact_liz_preview(
                build_ladder_fit_preview_with_candidate_pool(
                    &blob_lane_peaks,
                    &blob_lane_peaks,
                    sample_trace,
                    ladder_trace,
                    ladder,
                    primary_beam_search_trigger,
                    allow_visual_start_repair,
                ),
                &blob_lane_peaks,
                &blob_lane_peaks,
                sample_trace,
                ladder_trace,
            );
            best_preview = match (best_preview, blob_preview) {
                (Some(current), Some(candidate)) => {
                    if exact_liz_preview_prefers_candidate(&current, &candidate) {
                        Some(candidate)
                    } else {
                        Some(current)
                    }
                }
                (None, Some(candidate)) => Some(candidate),
                (some_current, None) => some_current,
            };
        }
        let broad_ladder_peaks = liz_broad_peak_candidates(
            ladder_trace,
            &corrected,
            &quantile_corrected,
            ladder.expected_peak_count() * 2 + 15,
        );
        if broad_ladder_peaks.len() >= target_len {
            let broad_preview = maybe_rerun_exact_liz_preview(
                build_ladder_fit_preview_with_candidate_pool(
                    &broad_ladder_peaks,
                    &broad_ladder_peaks,
                    sample_trace,
                    ladder_trace,
                    ladder,
                    primary_beam_search_trigger,
                    allow_visual_start_repair,
                ),
                &broad_ladder_peaks,
                &broad_ladder_peaks,
                sample_trace,
                ladder_trace,
            );
            best_preview = match (best_preview, broad_preview) {
                (Some(current), Some(candidate)) => {
                    if exact_liz_preview_prefers_candidate(&current, &candidate) {
                        Some(candidate)
                    } else {
                        Some(current)
                    }
                }
                (None, Some(candidate)) => Some(candidate),
                (some_current, None) => some_current,
            };
        }
    }

    let should_try_local_anchor_grid = best_preview
        .as_ref()
        .and_then(|preview| preview.sizing_model.as_ref())
        .is_some_and(|model| model.qc_metrics.linear_trend_max_abs_error_bp > 10.0);
    if should_try_local_anchor_grid {
        let corrected =
            baseline_correct_guarded_nonnegative(ladder_trace, 0.99, 100.0, 1000, 200, 0.10)
                .unwrap_or_else(|_| ladder_trace.to_vec());
        let quantile_corrected = baseline_correct_quantile_nonnegative(ladder_trace, 200, 0.10);
        let grid_augmented = preserve_liz_local_anchor_grid_candidates(
            ladder_peaks,
            &corrected,
            &quantile_corrected,
            ladder_trace,
            &quantile_corrected,
            target_len,
        );
        if grid_augmented.len() > ladder_peaks.len() && grid_augmented.len() >= target_len {
            let grid_preview = maybe_rerun_exact_liz_preview(
                build_ladder_fit_preview_with_candidate_pool(
                    &grid_augmented,
                    &grid_augmented,
                    sample_trace,
                    ladder_trace,
                    ladder,
                    primary_beam_search_trigger,
                    allow_visual_start_repair,
                ),
                &grid_augmented,
                &grid_augmented,
                sample_trace,
                ladder_trace,
            );
            best_preview = match (best_preview, grid_preview) {
                (Some(current), Some(candidate)) => {
                    if exact_liz_preview_prefers_candidate(&current, &candidate) {
                        Some(candidate)
                    } else {
                        Some(current)
                    }
                }
                (None, Some(candidate)) => Some(candidate),
                (some_current, None) => some_current,
            };
        }
    }

    let should_try_weak_anchor_grid = best_preview
        .as_ref()
        .is_some_and(|preview| liz_preview_has_weak_or_baseline_selection(preview, ladder_peaks));
    if should_try_weak_anchor_grid {
        let corrected =
            baseline_correct_guarded_nonnegative(ladder_trace, 0.99, 100.0, 1000, 200, 0.10)
                .unwrap_or_else(|_| ladder_trace.to_vec());
        let quantile_corrected = baseline_correct_quantile_nonnegative(ladder_trace, 200, 0.10);
        let grid_augmented = preserve_liz_local_anchor_grid_candidates(
            ladder_peaks,
            &corrected,
            &quantile_corrected,
            ladder_trace,
            &quantile_corrected,
            target_len,
        );
        if grid_augmented.len() > ladder_peaks.len() && grid_augmented.len() >= target_len {
            let grid_preview = maybe_rerun_exact_liz_preview(
                build_ladder_fit_preview_with_candidate_pool(
                    &grid_augmented,
                    &grid_augmented,
                    sample_trace,
                    ladder_trace,
                    ladder,
                    primary_beam_search_trigger,
                    allow_visual_start_repair,
                ),
                &grid_augmented,
                &grid_augmented,
                sample_trace,
                ladder_trace,
            );
            best_preview = match (best_preview, grid_preview) {
                (Some(current), Some(candidate)) => {
                    if liz_weak_anchor_grid_preview_prefers_candidate(
                        &current,
                        &candidate,
                        ladder_peaks,
                        &grid_augmented,
                    ) {
                        Some(candidate)
                    } else {
                        Some(current)
                    }
                }
                (None, Some(candidate)) => Some(candidate),
                (some_current, None) => some_current,
            };
        }
    }

    best_preview
}

fn liz_preview_linear_metrics(preview: &LadderFitPreview) -> Option<(f64, f64, f64)> {
    let metrics = &preview.sizing_model.as_ref()?.qc_metrics;
    Some((
        metrics.linear_trend_max_abs_error_bp,
        metrics.linear_trend_mean_abs_error_bp,
        metrics.linear_trend_r2,
    ))
}

fn liz_preview_weak_baseline_score(preview: &LadderFitPreview, peaks: &[Peak]) -> usize {
    let (baseline_count, cleaner_neighbor_count, strong_baseline_count) =
        selected_baseline_like_anchor_counts(
            LadderKind::Liz500250,
            &preview.best_scan_indices,
            peaks,
        );
    let (weak_count, very_weak_tail) =
        selected_weak_liz_anchor_counts(&preview.best_scan_indices, peaks);
    baseline_count
        + cleaner_neighbor_count.min(1)
        + strong_baseline_count
        + weak_count
        + usize::from(very_weak_tail)
}

fn liz_preview_has_weak_or_baseline_selection(preview: &LadderFitPreview, peaks: &[Peak]) -> bool {
    let weak_baseline_score = liz_preview_weak_baseline_score(preview, peaks);
    let Some((linear_max, linear_mean, _linear_r2)) = liz_preview_linear_metrics(preview) else {
        return false;
    };
    weak_baseline_score >= 3
        || (weak_baseline_score > 0 && (linear_max >= 4.5 || linear_mean >= 1.8))
}

fn liz_weak_anchor_grid_preview_prefers_candidate(
    current: &LadderFitPreview,
    candidate: &LadderFitPreview,
    current_peaks: &[Peak],
    candidate_peaks: &[Peak],
) -> bool {
    let Some((current_max, current_mean, current_r2)) = liz_preview_linear_metrics(current) else {
        return false;
    };
    let Some((candidate_max, candidate_mean, candidate_r2)) = liz_preview_linear_metrics(candidate)
    else {
        return false;
    };
    if candidate.best_scan_indices.len() != LadderKind::Liz500250.expected_peak_count()
        || candidate_max > 8.0
        || candidate_mean > 3.6
        || candidate_r2 < 0.9990
        || candidate_max > current_max + 0.60
        || candidate_mean > current_mean + 0.50
        || candidate_r2 + 0.00035 < current_r2
    {
        return false;
    }

    let current_bad = liz_preview_weak_baseline_score(current, current_peaks);
    let candidate_bad = liz_preview_weak_baseline_score(candidate, candidate_peaks);
    let material_linear_win =
        candidate_max + 0.35 < current_max || candidate_mean + 0.25 < current_mean;
    if candidate_bad + 2 <= current_bad && material_linear_win {
        return true;
    }
    candidate_bad < current_bad
        && (candidate_max + 0.40 < current_max || candidate_mean + 0.20 < current_mean)
}

fn maybe_rerun_exact_liz_preview(
    preview: Option<LadderFitPreview>,
    ladder_peaks: &[Peak],
    fit_ladder_peaks: &[Peak],
    sample_trace: &[f64],
    ladder_trace: &[f64],
) -> Option<LadderFitPreview> {
    let current = preview?;
    if liz_preview_is_high_confidence_bounded(&current, ladder_peaks) {
        return Some(current);
    }
    let estimate = current.estimated_combination_count;
    if estimate <= LIZ_BEAM_SEARCH_TRIGGER_COMBINATIONS
        || estimate > LIZ_EXACT_RERUN_MAX_COMBINATIONS
    {
        return Some(current);
    }

    let exact = build_ladder_fit_preview_with_candidate_pool(
        ladder_peaks,
        fit_ladder_peaks,
        sample_trace,
        ladder_trace,
        LadderKind::Liz500250,
        LIZ_EXACT_RERUN_MAX_COMBINATIONS,
        false,
    );
    match exact {
        Some(candidate) if exact_liz_preview_prefers_candidate(&current, &candidate) => {
            Some(candidate)
        }
        _ => Some(current),
    }
}

fn liz_exact_audit_enabled() -> bool {
    std::env::var(LIZ_EXACT_AUDIT_ENV).is_ok_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
}

fn liz_full_repair_audit_enabled() -> bool {
    std::env::var(LIZ_FULL_REPAIR_AUDIT_ENV).is_ok_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
}

fn capped_full_pool_beam_audit_enabled() -> bool {
    std::env::var(CAPPED_FULL_POOL_BEAM_AUDIT_ENV).is_ok_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
}

fn liz_preview_is_high_confidence_bounded(
    preview: &LadderFitPreview,
    ladder_peaks: &[Peak],
) -> bool {
    if preview.candidate_generation_capped
        || preview.best_scan_indices.len() != LadderKind::Liz500250.expected_peak_count()
        || liz_preview_has_weak_or_baseline_selection(preview, ladder_peaks)
    {
        return false;
    }
    let Some(model) = preview.sizing_model.as_ref() else {
        return false;
    };
    let metrics = &model.qc_metrics;
    metrics.monotonic_on_ladder
        && metrics.linear_trend_max_abs_error_bp <= 6.0
        && metrics.linear_trend_mean_abs_error_bp <= 2.5
        && metrics.linear_trend_r2 >= 0.9995
        && metrics.max_abs_error_bp <= 1.5
}

fn preview_is_suspicious_for_exact_liz_retry(preview: &LadderFitPreview) -> bool {
    let Some(model) = preview.sizing_model.as_ref() else {
        return false;
    };
    let metrics = &model.qc_metrics;
    metrics.linear_trend_max_abs_error_bp > LIZ_SUSPICIOUS_LINEAR_MAX_BP
        || metrics.linear_trend_mean_abs_error_bp > LIZ_SUSPICIOUS_LINEAR_MEAN_BP
        || metrics.linear_trend_r2 < LIZ_SUSPICIOUS_LINEAR_R2_MIN
}

fn apply_post_preview_rox_repair(
    best: Option<CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    repair_peak_feature_by_index: &BTreeMap<usize, Peak>,
    repair_peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder == LadderKind::Gs500Rox {
        let mut current = best;
        if let Some(candidate) = current.as_ref().and_then(|score| {
            repair_gs500rox_start_anchor_sequence(
                score,
                ladder_sizes,
                ladder,
                repair_peak_feature_by_index,
                repair_peak_features,
            )
        }) {
            current = Some(candidate);
        }
        return current;
    }

    if ladder != LadderKind::Rox400Hd {
        return best;
    }

    let mut current = best;
    if let Some(candidate) = current.as_ref().and_then(|score| {
        repair_rox_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if current
            .as_ref()
            .map(|score| {
                rox_start_pair_candidate_improves_current(score, &candidate)
                    || rox_start_pair_feature_candidate_can_override(score, &candidate)
            })
            .unwrap_or(true)
        {
            current = Some(candidate);
        }
    }
    for repair in [
        repair_rox_first_three_sequence,
        repair_rox_motif_start_block_sequence,
    ] {
        if let Some(candidate) = current.as_ref().and_then(|score| {
            repair(
                score,
                ladder_sizes,
                ladder,
                repair_peak_feature_by_index,
                repair_peak_features,
            )
        }) {
            if current
                .as_ref()
                .map(|score| repair_candidate_improves_current(score, &candidate))
                .unwrap_or(true)
            {
                current = Some(candidate);
            }
        }
    }
    if let Some(candidate) = current.as_ref().and_then(|score| {
        repair_rox_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if current
            .as_ref()
            .map(|score| {
                rox_start_pair_candidate_improves_current(score, &candidate)
                    || rox_start_pair_feature_candidate_can_override(score, &candidate)
            })
            .unwrap_or(true)
        {
            current = Some(candidate);
        }
    }
    if let Some(candidate) = current.as_ref().and_then(|score| {
        repair_rox_start_pair_feature_arbiter_sequence(
            score,
            ladder_sizes,
            ladder,
            repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        current = Some(candidate);
    }
    if let Some(candidate) = current.as_ref().and_then(|score| {
        repair_rox_nonlinear_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        current = Some(candidate);
    }

    current
}

fn liz_apex_local_gap_ok(scans: &[usize], step_index: usize) -> bool {
    if scans.len() != LIZ_APEX_GAP_MEDIAN.len() + 1 {
        return false;
    }

    let mut gap_indices = Vec::with_capacity(2);
    if step_index > 0 {
        gap_indices.push(step_index - 1);
    }
    if step_index + 1 < scans.len() {
        gap_indices.push(step_index);
    }
    gap_indices.sort_unstable();
    gap_indices.dedup();

    gap_indices.into_iter().all(|gap_index| {
        let gap = scans[gap_index + 1].saturating_sub(scans[gap_index]) as f64;
        let slack = (LIZ_APEX_GAP_MEDIAN[gap_index] * 0.12).max(8.0);
        let lower = LIZ_APEX_GAP_P10[gap_index] - slack;
        let upper = LIZ_APEX_GAP_P90[gap_index] + slack;
        gap >= lower && gap <= upper
    })
}

fn apex_candidate_has_peak_shape(candidate: &Peak) -> bool {
    if !candidate.height.is_finite()
        || !candidate.prominence.is_finite()
        || !candidate.width.is_finite()
        || candidate.height <= 0.0
        || candidate.prominence <= 0.0
    {
        return false;
    }

    let prominence_floor = 18.0_f64.max(candidate.height * 0.04);
    candidate.prominence >= prominence_floor && candidate.width >= 0.5 && candidate.width <= 80.0
}

fn apply_ladder_apex_recenter(
    best: Option<CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    let mut current_score = best?;
    if !matches!(ladder, LadderKind::Liz500250 | LadderKind::Rox400Hd)
        || current_score.indices.len() != ladder_sizes.len()
        || current_score.indices.len() < 3
    {
        return Some(current_score);
    }
    if ladder == LadderKind::Liz500250
        && current_score.indices.len() != LIZ_APEX_GAP_MEDIAN.len() + 1
    {
        return Some(current_score);
    }

    let selected_heights = current_score
        .indices
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if selected_heights.is_empty() {
        return Some(current_score);
    }
    let family_height_ref = median(&selected_heights).max(1.0);
    let radius = match ladder {
        LadderKind::Liz500250 => LIZ_APEX_RECENTER_RADIUS_SCANS,
        LadderKind::Rox400Hd => ROX_APEX_RECENTER_RADIUS_SCANS,
        _ => return Some(current_score),
    };

    let original_score = current_score.clone();
    let mut current_indices = current_score.indices.clone();
    for step_index in 0..current_indices.len() {
        let current_scan = current_indices[step_index];
        let current_peak_missing = !peak_feature_by_index.contains_key(&current_scan);
        let current_peak = match peak_feature_by_index.get(&current_scan).cloned() {
            Some(peak) => peak,
            None if ladder == LadderKind::Liz500250 => Peak {
                index: current_scan,
                height: 1.0,
                prominence: 1.0,
                width: 1.0,
                local_baseline: 1.0,
                score: 1.0,
            },
            None => continue,
        };
        let lower_bound = if step_index == 0 {
            0usize
        } else {
            current_indices[step_index - 1].saturating_add(1)
        };
        let upper_bound = if step_index + 1 >= current_indices.len() {
            usize::MAX
        } else {
            current_indices[step_index + 1].saturating_sub(1)
        };
        if lower_bound >= upper_bound {
            continue;
        }

        let mut best_step: Option<(CombinationScore, f64, f64, f64)> = None;
        for candidate in peak_features.iter().filter(|peak| {
            let weak_liz_tail_search = ladder == LadderKind::Liz500250
                && step_index >= 9
                && peak.index.abs_diff(current_scan) <= 90;
            peak.index != current_scan
                && peak.index > lower_bound
                && peak.index < upper_bound
                && (peak.index.abs_diff(current_scan) <= radius || weak_liz_tail_search)
                && !current_indices.contains(&peak.index)
        }) {
            if !apex_candidate_has_peak_shape(candidate) {
                continue;
            }

            let height_gain = candidate.height - current_peak.height;
            let height_gain_floor = match ladder {
                LadderKind::Liz500250 => 8.0_f64.max(current_peak.height.max(1.0) * 0.015),
                LadderKind::Rox400Hd => 25.0_f64.max(current_peak.height.max(1.0) * 0.10),
                _ => unreachable!(),
            };
            if height_gain < height_gain_floor {
                continue;
            }
            if ladder == LadderKind::Liz500250
                && step_index < 4
                && candidate.height > 5000.0_f64.max(family_height_ref * 4.0)
            {
                continue;
            }
            let current_height = current_peak.height.max(1.0);
            let candidate_height = candidate.height.max(1.0);
            let current_baseline_ratio =
                (current_peak.local_baseline.max(0.0) / current_height).clamp(0.0, 1.5);
            let candidate_baseline_ratio =
                (candidate.local_baseline.max(0.0) / candidate_height).clamp(0.0, 1.5);
            let current_purity = (current_peak.prominence / current_height).clamp(0.0, 1.0);
            let candidate_purity = (candidate.prominence / candidate_height).clamp(0.0, 1.0);
            let rox_current_height_ratio = if ladder == LadderKind::Rox400Hd {
                current_height / family_height_ref
            } else {
                1.0
            };
            let extreme_rox_family_foot = ladder == LadderKind::Rox400Hd
                && rox_current_height_ratio <= 0.25
                && candidate_height >= current_height * 8.0
                && candidate.prominence >= current_peak.prominence.max(1.0) * 8.0;
            if ladder == LadderKind::Rox400Hd {
                let strong_rox_baseline_foot =
                    current_baseline_ratio >= 0.30 && current_purity <= 0.55;
                if !strong_rox_baseline_foot
                    && !extreme_rox_family_foot
                    && current_score.linear_max_abs_error_bp < 5.0
                {
                    continue;
                }
                let rox_current_looks_like_foot = current_baseline_ratio >= 0.30
                    || current_purity <= 0.62
                    || extreme_rox_family_foot
                    || (rox_current_height_ratio <= 0.35
                        && candidate_height >= current_height * 1.8
                        && candidate.prominence >= current_peak.prominence.max(1.0) * 1.8);
                let rox_candidate_cleaner = candidate_baseline_ratio + 0.10
                    <= current_baseline_ratio
                    || candidate_purity >= current_purity + 0.16
                    || (extreme_rox_family_foot
                        && candidate_baseline_ratio <= 0.24
                        && candidate_purity >= 0.62);
                if !rox_current_looks_like_foot || !rox_candidate_cleaner {
                    continue;
                }
            }

            let mut trial = current_indices.clone();
            trial[step_index] = candidate.index;
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }
            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            let (linear_max_guard, linear_mean_guard) = match ladder {
                LadderKind::Liz500250 => (
                    LIZ_APEX_RECENTER_LINEAR_MAX_GUARD_BP,
                    LIZ_APEX_RECENTER_LINEAR_MEAN_GUARD_BP,
                ),
                LadderKind::Rox400Hd => (
                    APEX_RECENTER_LINEAR_MAX_GUARD_BP,
                    APEX_RECENTER_LINEAR_MEAN_GUARD_BP,
                ),
                _ => unreachable!(),
            };
            if trial_score.linear_max_abs_error_bp > linear_max_guard
                || trial_score.linear_mean_abs_error_bp > linear_mean_guard
            {
                continue;
            }
            if ladder == LadderKind::Rox400Hd
                && current_score.linear_max_abs_error_bp < 5.0
                && !extreme_rox_family_foot
                && (trial_score.linear_max_abs_error_bp
                    > current_score.linear_max_abs_error_bp + 0.10
                    || trial_score.linear_mean_abs_error_bp
                        > current_score.linear_mean_abs_error_bp + 0.10)
            {
                continue;
            }
            if ladder == LadderKind::Liz500250
                && current_score.linear_max_abs_error_bp < 5.6
                && (trial_score.linear_max_abs_error_bp
                    > current_score.linear_max_abs_error_bp + 0.25
                    || trial_score.linear_mean_abs_error_bp
                        > current_score.linear_mean_abs_error_bp + 0.20)
            {
                continue;
            }

            let prominence_gain = candidate.prominence - current_peak.prominence;
            let residual_cost = (trial_score.linear_max_abs_error_bp
                - current_score.linear_max_abs_error_bp)
                .max(0.0)
                * 40.0
                + (trial_score.linear_mean_abs_error_bp - current_score.linear_mean_abs_error_bp)
                    .max(0.0)
                    * 60.0;
            let peak_cost = (trial_score.peak_penalty - current_score.peak_penalty).max(0.0) * 80.0;
            let utility = height_gain + prominence_gain.max(0.0) * 0.15 - residual_cost - peak_cost;
            let weak_liz_family_foot = ladder == LadderKind::Liz500250
                && (current_peak_missing || current_score.linear_max_abs_error_bp > 6.0)
                && current_height <= family_height_ref * 0.14
                && candidate_height >= family_height_ref * 0.30
                && candidate_height >= current_height * 8.0
                && candidate.prominence >= current_peak.prominence.max(1.0) * 8.0;
            let liz_gap_ok_or_nonworse = if ladder == LadderKind::Liz500250 {
                let strong_liz_foot = current_baseline_ratio >= 0.30 || current_purity <= 0.55;
                if current_score.linear_max_abs_error_bp < 5.6
                    && current_score.linear_mean_abs_error_bp < 2.4
                    && !strong_liz_foot
                {
                    continue;
                }
                if liz_apex_local_gap_ok(&trial, step_index) {
                    true
                } else {
                    let current_gap_penalty =
                        ladder_gap_template_penalty(LadderKind::Liz500250, &current_indices);
                    let trial_gap_penalty =
                        ladder_gap_template_penalty(LadderKind::Liz500250, &trial);
                    trial_gap_penalty <= current_gap_penalty + 0.01
                }
            } else {
                true
            };
            let liz_linear_max_slack = if weak_liz_family_foot {
                if step_index < 4 { 1.05 } else { 1.25 }
            } else if step_index < 4 {
                0.35
            } else {
                1.10
            };
            let liz_linear_mean_slack = if weak_liz_family_foot { 0.75 } else { 0.55 };
            let liz_r2_slack = if weak_liz_family_foot {
                0.00075
            } else {
                0.00040
            };
            let liz_peak_penalty_slack = if weak_liz_family_foot { 2.00 } else { 1.00 };
            let weak_liz_fit_supported = !weak_liz_family_foot
                || if step_index >= 12 {
                    trial_score.linear_max_abs_error_bp
                        <= current_score.linear_max_abs_error_bp + 0.35
                        && trial_score.linear_mean_abs_error_bp
                            <= current_score.linear_mean_abs_error_bp + 0.10
                        && trial_score.linear_r2 + 0.00025 >= current_score.linear_r2
                } else {
                    trial_score.linear_mean_abs_error_bp + 0.05
                        < current_score.linear_mean_abs_error_bp
                        || trial_score.linear_max_abs_error_bp + 0.25
                            < current_score.linear_max_abs_error_bp
                };
            let compelling_liz_apex_snap = ladder == LadderKind::Liz500250
                && (weak_liz_family_foot
                    || (!current_peak_missing
                        && (current_baseline_ratio >= 0.30 || current_purity <= 0.55)))
                && weak_liz_fit_supported
                && candidate_height >= current_height * 1.65
                && candidate.prominence >= current_peak.prominence.max(1.0) * 1.80
                && candidate_baseline_ratio <= 0.24
                && candidate_purity >= 0.62
                && candidate_height <= family_height_ref * 2.25
                && trial_score.linear_max_abs_error_bp
                    <= current_score.linear_max_abs_error_bp + liz_linear_max_slack
                && trial_score.linear_mean_abs_error_bp
                    <= current_score.linear_mean_abs_error_bp + liz_linear_mean_slack
                && trial_score.linear_r2 + liz_r2_slack >= current_score.linear_r2
                && trial_score.peak_penalty <= current_score.peak_penalty + liz_peak_penalty_slack;
            if !liz_gap_ok_or_nonworse && !compelling_liz_apex_snap {
                continue;
            }
            if utility <= 0.0 && !compelling_liz_apex_snap {
                continue;
            }
            let effective_utility = if utility > 0.0 {
                utility
            } else {
                height_gain * 0.35 + prominence_gain.max(0.0) * 0.20 - peak_cost
            };

            let should_take = match best_step.as_ref() {
                Some((best_score, best_utility, best_height_gain, best_prominence_gain)) => {
                    effective_utility > *best_utility + 1e-6
                        || ((effective_utility - *best_utility).abs() <= 1e-6
                            && (height_gain > *best_height_gain + 1e-6
                                || ((height_gain - *best_height_gain).abs() <= 1e-6
                                    && (prominence_gain > *best_prominence_gain + 1e-6
                                        || ((prominence_gain - *best_prominence_gain).abs()
                                            <= 1e-6
                                            && compare_block_repair_candidates(
                                                &trial_score,
                                                best_score,
                                            ) == std::cmp::Ordering::Less)))))
                }
                None => true,
            };
            if should_take {
                best_step = Some((trial_score, effective_utility, height_gain, prominence_gain));
            }
        }

        if let Some((trial_score, _, _, _)) = best_step {
            current_indices = trial_score.indices.clone();
            current_score = trial_score;
        }
    }

    if ladder == LadderKind::Liz500250
        && current_score.indices != original_score.indices
        && current_score.linear_max_abs_error_bp > original_score.linear_max_abs_error_bp + 0.60
        && current_score.linear_mean_abs_error_bp > original_score.linear_mean_abs_error_bp + 0.05
        && current_score.linear_r2 + 0.00002 < original_score.linear_r2
    {
        return Some(original_score);
    }

    Some(current_score)
}

fn apex_recenter_refinement_preview(
    original_indices: &[usize],
    refined_indices: &[usize],
    ladder_sizes: &[f64],
) -> Option<RefinementPreview> {
    if original_indices.len() != refined_indices.len() || original_indices == refined_indices {
        return None;
    }

    let changed_step_indices = original_indices
        .iter()
        .zip(refined_indices.iter())
        .enumerate()
        .filter_map(|(index, (original, refined))| {
            if original != refined {
                Some(index)
            } else {
                None
            }
        })
        .collect::<Vec<_>>();
    if changed_step_indices.is_empty() {
        return None;
    }

    Some(RefinementPreview {
        changed_step_indices,
        original_scan_indices: original_indices.to_vec(),
        refined_scan_indices: refined_indices.to_vec(),
        refined_curvature_score: curvature_score(ladder_sizes, refined_indices),
        refined_quadratic_r2: quadratic_fit_r2(
            ladder_sizes,
            &refined_indices
                .iter()
                .map(|value| *value as f64)
                .collect::<Vec<_>>(),
        ),
    })
}

fn apply_ladder_apex_recenter_to_preview(
    best: &mut Option<CombinationScore>,
    sizing_model: &mut Option<SizingModelPreview>,
    refinement: &mut Option<RefinementPreview>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
    sample_trace: &[f64],
) {
    let Some(original_indices) = best.as_ref().map(|score| score.indices.clone()) else {
        return;
    };
    let Some(recentered_best) = apply_ladder_apex_recenter(
        best.clone(),
        ladder_sizes,
        ladder,
        peak_feature_by_index,
        peak_features,
    ) else {
        return;
    };
    if recentered_best.indices == original_indices {
        return;
    }

    let refined_indices = recentered_best.indices.clone();
    *best = Some(recentered_best);
    *sizing_model = fit_best_sizing_model(&refined_indices, ladder_sizes, sample_trace);
    *refinement =
        apex_recenter_refinement_preview(&original_indices, &refined_indices, ladder_sizes);
}

fn build_ladder_fit_preview_with_candidate_pool(
    ladder_peaks: &[Peak],
    fit_ladder_peaks: &[Peak],
    sample_trace: &[f64],
    ladder_trace: &[f64],
    ladder: LadderKind,
    beam_search_trigger: usize,
    allow_visual_start_repair: bool,
) -> Option<LadderFitPreview> {
    let target_len = ladder.expected_peak_count();
    if ladder_peaks.len() < 2 || target_len < 2 {
        return None;
    }
    let peak_indices = fit_ladder_peaks
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    let beam_width = if ladder == LadderKind::Liz500250 {
        LIZ_BEAM_SEARCH_WIDTH
    } else {
        BEAM_SEARCH_WIDTH
    };

    // For ROX ladders, filter out early blob peaks from the candidate pool.
    // OK ROX fits always start at ≥1520; peaks below that are blob artifacts.
    // We try the filtered pool first; if it doesn't have enough candidates we
    // fall back to the full pool.
    let min_first_anchor: usize = match ladder {
        LadderKind::Rox400Hd => 1520,
        // LIZ cases often have true 35/50 bp anchors around ~1475-1575.
        // Keeping the cutoff too high suppresses the correct start region and
        // forces the fitter into later blob/baseline candidates.
        LadderKind::Liz500250 => 1450,
        _ => 0,
    };
    let filtered_peak_indices: Vec<usize> = if min_first_anchor > 0 {
        peak_indices
            .iter()
            .copied()
            .filter(|idx| *idx >= min_first_anchor)
            .collect()
    } else {
        peak_indices.clone()
    };
    let filtered_ladder_peaks: Vec<Peak> = if min_first_anchor > 0 {
        fit_ladder_peaks
            .iter()
            .filter(|peak| peak.index >= min_first_anchor)
            .cloned()
            .collect()
    } else {
        fit_ladder_peaks.to_vec()
    };
    // Use the filtered pool only when it still leaves real choice.
    // If the cutoff collapses the pool to exactly the target length we can
    // accidentally hard-lock a shifted ladder sequence with no alternatives.
    let (active_peak_indices, active_ladder_peaks): (&[usize], &[Peak]) =
        if filtered_peak_indices.len() > target_len {
            (&filtered_peak_indices, &filtered_ladder_peaks)
        } else {
            (&peak_indices, fit_ladder_peaks)
        };

    let mut max_allowed_peak_gap = estimate_max_allowed_peak_gap(active_peak_indices, 5.0);
    let mut gap_expansions = 0usize;
    let mut estimated_combination_count = 0usize;
    let mut candidate_generation_capped = false;
    let mut combinations = Vec::new();
    let mut used_relaxed_fallback = false;
    let mut used_capped_full_pool_beam = false;

    for expansion in 0..=LADDER_MAX_GAP_EXPANSIONS {
        estimated_combination_count = estimate_combination_count_capped(
            active_peak_indices,
            target_len,
            max_allowed_peak_gap,
            MAX_CANDIDATE_COMBINATIONS + 1,
        );
        candidate_generation_capped = estimated_combination_count > MAX_CANDIDATE_COMBINATIONS;
        gap_expansions = expansion;
        if candidate_generation_capped {
            if capped_full_pool_beam_audit_enabled() {
                let peak_feature_by_index = active_ladder_peaks
                    .iter()
                    .map(|peak| (peak.index, peak.clone()))
                    .collect::<BTreeMap<_, _>>();
                combinations = generate_peak_combinations_beam(
                    active_peak_indices,
                    target_len,
                    max_allowed_peak_gap,
                    ladder.sizes(),
                    &peak_feature_by_index,
                    beam_width,
                    BEAM_SEARCH_FINAL_CAP,
                );
                if !combinations.is_empty() {
                    used_capped_full_pool_beam = true;
                    candidate_generation_capped = false;
                }
            }
            break;
        }

        combinations = if estimated_combination_count > beam_search_trigger {
            let peak_feature_by_index = active_ladder_peaks
                .iter()
                .map(|peak| (peak.index, peak.clone()))
                .collect::<BTreeMap<_, _>>();
            generate_peak_combinations_beam(
                active_peak_indices,
                target_len,
                max_allowed_peak_gap,
                ladder.sizes(),
                &peak_feature_by_index,
                beam_width,
                BEAM_SEARCH_FINAL_CAP,
            )
        } else {
            generate_peak_combinations(
                active_peak_indices,
                target_len,
                max_allowed_peak_gap,
                MAX_CANDIDATE_COMBINATIONS,
            )
        };
        if !combinations.is_empty() {
            break;
        }
        max_allowed_peak_gap = max_allowed_peak_gap.saturating_add(LADDER_GAP_EXPANSION_STEP);
    }

    if !candidate_generation_capped
        && combinations.is_empty()
        && active_peak_indices.len() >= target_len
    {
        let peak_feature_by_index = active_ladder_peaks
            .iter()
            .map(|peak| (peak.index, peak.clone()))
            .collect::<BTreeMap<_, _>>();
        combinations = generate_peak_combinations_beam(
            active_peak_indices,
            target_len,
            usize::MAX,
            ladder.sizes(),
            &peak_feature_by_index,
            beam_width,
            BEAM_SEARCH_FINAL_CAP,
        );
        used_relaxed_fallback = !combinations.is_empty();
    }

    if candidate_generation_capped {
        for keep_limit in [
            target_len + 8,
            target_len + 6,
            target_len + 4,
            target_len + 2,
        ] {
            for collapse_distance in [20usize, 28, 36, 48, 64, 80] {
                let reduced_ladder_peaks = thin_peak_pool_for_ladder(
                    &fit_ladder_peaks,
                    target_len,
                    collapse_distance,
                    keep_limit,
                );
                if reduced_ladder_peaks.len() < target_len
                    || reduced_ladder_peaks.len() >= fit_ladder_peaks.len()
                {
                    continue;
                }
                let reduced_indices = reduced_ladder_peaks
                    .iter()
                    .map(|peak| peak.index)
                    .collect::<Vec<_>>();
                let reduced_max_gap = estimate_max_allowed_peak_gap(&reduced_indices, 4.0);
                let reduced_estimate = estimate_combination_count_capped(
                    &reduced_indices,
                    target_len,
                    reduced_max_gap,
                    MAX_CANDIDATE_COMBINATIONS + 1,
                );
                let peak_feature_by_index = reduced_ladder_peaks
                    .iter()
                    .map(|peak| (peak.index, peak.clone()))
                    .collect::<BTreeMap<_, _>>();
                let reduced_combinations = if reduced_estimate > beam_search_trigger {
                    generate_peak_combinations_beam(
                        &reduced_indices,
                        target_len,
                        reduced_max_gap,
                        ladder.sizes(),
                        &peak_feature_by_index,
                        beam_width,
                        BEAM_SEARCH_FINAL_CAP,
                    )
                } else if reduced_estimate <= MAX_CANDIDATE_COMBINATIONS {
                    generate_peak_combinations(
                        &reduced_indices,
                        target_len,
                        reduced_max_gap,
                        MAX_CANDIDATE_COMBINATIONS,
                    )
                } else {
                    continue;
                };
                if reduced_combinations.is_empty() {
                    continue;
                }
                let ladder_sizes = ladder.sizes();
                let mut best = select_best_combination(
                    &reduced_combinations,
                    ladder_sizes,
                    ladder,
                    &reduced_ladder_peaks,
                    ladder_peaks,
                );
                let mut sizing_model = best.as_ref().and_then(|entry| {
                    fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                });
                let mut refinement = None;

                if let (Some(best_entry), Some(model)) = (best.as_ref(), sizing_model.as_ref()) {
                    if let Some(refined) = refine_best_combination(
                        &reduced_indices,
                        &best_entry.indices,
                        ladder_sizes,
                        model,
                    ) {
                        let refined_qr2 = quadratic_fit_r2(
                            ladder_sizes,
                            &refined
                                .refined_scan_indices
                                .iter()
                                .map(|value| *value as f64)
                                .collect::<Vec<_>>(),
                        );
                        let refined_curvature =
                            curvature_score(ladder_sizes, &refined.refined_scan_indices);
                        let _refined_domain_penalty = ladder_domain_penalty(
                            ladder,
                            &refined.refined_scan_indices,
                            &peak_feature_by_index,
                            &reduced_ladder_peaks,
                        );
                        let _refined_peak_penalty = ladder_peak_sequence_penalty(
                            &refined.refined_scan_indices,
                            ladder,
                            ladder_sizes,
                            &peak_feature_by_index,
                            &reduced_ladder_peaks,
                        );
                        let refined_score = score_combination(
                            &refined.refined_scan_indices,
                            ladder_sizes,
                            ladder,
                            &peak_feature_by_index,
                            &reduced_ladder_peaks,
                        );
                        if refinement_improves_current(best_entry, &refined_score) {
                            best = Some(refined_score);
                            sizing_model = fit_best_sizing_model(
                                &refined.refined_scan_indices,
                                ladder_sizes,
                                sample_trace,
                            );
                            refinement = Some(RefinementPreview {
                                changed_step_indices: refined.changed_step_indices,
                                original_scan_indices: refined.original_scan_indices,
                                refined_scan_indices: refined.refined_scan_indices,
                                refined_curvature_score: refined_curvature,
                                refined_quadratic_r2: refined_qr2,
                            });
                        }
                    }
                }

                let repair_peak_feature_by_index = ladder_peaks
                    .iter()
                    .map(|peak| (peak.index, peak.clone()))
                    .collect::<BTreeMap<_, _>>();
                let repaired_best = apply_post_preview_rox_repair(
                    best.clone(),
                    ladder_sizes,
                    ladder,
                    &repair_peak_feature_by_index,
                    ladder_peaks,
                );
                if repaired_best.as_ref().map(|score| &score.indices)
                    != best.as_ref().map(|score| &score.indices)
                {
                    best = repaired_best;
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }
                if allow_visual_start_repair {
                    let visual_start_best = repair_rox_visual_start_pair_from_trace(
                        best.clone(),
                        ladder_sizes,
                        ladder,
                        ladder_peaks,
                        ladder_trace,
                    );
                    if visual_start_best.as_ref().map(|score| &score.indices)
                        != best.as_ref().map(|score| &score.indices)
                    {
                        best = visual_start_best;
                        sizing_model = best.as_ref().and_then(|entry| {
                            fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                        });
                        refinement = None;
                    }
                }
                apply_ladder_apex_recenter_to_preview(
                    &mut best,
                    &mut sizing_model,
                    &mut refinement,
                    ladder_sizes,
                    ladder,
                    &repair_peak_feature_by_index,
                    ladder_peaks,
                    sample_trace,
                );
                if let Some(candidate) = repair_liz_strong_median_family_sequence(
                    best.as_ref(),
                    ladder_sizes,
                    ladder,
                    &repair_peak_feature_by_index,
                ) {
                    best = Some(candidate);
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }
                if let Some(candidate) = repair_liz_blob_start_family_sequence(
                    best.as_ref(),
                    ladder_sizes,
                    ladder,
                    &repair_peak_feature_by_index,
                ) {
                    best = Some(candidate);
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }
                if let Some(candidate) = repair_liz_clean_late_tail_family_sequence(
                    best.as_ref(),
                    ladder_sizes,
                    ladder,
                    &repair_peak_feature_by_index,
                ) {
                    best = Some(candidate);
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }
                if allow_visual_start_repair {
                    let visual_start_best = repair_rox_visual_start_pair_from_trace(
                        best.clone(),
                        ladder_sizes,
                        ladder,
                        ladder_peaks,
                        ladder_trace,
                    );
                    if visual_start_best.as_ref().map(|score| &score.indices)
                        != best.as_ref().map(|score| &score.indices)
                    {
                        best = visual_start_best;
                        sizing_model = best.as_ref().and_then(|entry| {
                            fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                        });
                        refinement = None;
                    }
                }
                let late_prepend_best = repair_rox_late_family_prepend_sequence(
                    best.clone(),
                    ladder_sizes,
                    ladder,
                    ladder_peaks,
                );
                if late_prepend_best.as_ref().map(|score| &score.indices)
                    != best.as_ref().map(|score| &score.indices)
                {
                    best = late_prepend_best;
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }
                let first_strong_family_best = repair_rox_late_to_first_strong_family_sequence(
                    best.clone(),
                    ladder_sizes,
                    ladder,
                    ladder_peaks,
                );
                if first_strong_family_best
                    .as_ref()
                    .map(|score| &score.indices)
                    != best.as_ref().map(|score| &score.indices)
                {
                    best = first_strong_family_best;
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }
                let strong_median_family_best = repair_rox_strong_median_family_sequence(
                    best.clone(),
                    ladder_sizes,
                    ladder,
                    ladder_peaks,
                );
                if strong_median_family_best
                    .as_ref()
                    .map(|score| &score.indices)
                    != best.as_ref().map(|score| &score.indices)
                {
                    best = strong_median_family_best;
                    sizing_model = best.as_ref().and_then(|entry| {
                        fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
                    });
                    refinement = None;
                }

                return Some(LadderFitPreview {
                    search_tier: "reduced_pool_fallback".to_owned(),
                    max_allowed_peak_gap: reduced_max_gap,
                    gap_expansions,
                    estimated_combination_count: reduced_estimate,
                    candidate_generation_capped: false,
                    evaluated_combination_count: reduced_combinations.len(),
                    best_scan_indices: best
                        .as_ref()
                        .map(|entry| entry.indices.clone())
                        .unwrap_or_default(),
                    best_curvature_score: best.as_ref().map(|entry| entry.curvature_score),
                    best_quadratic_r2: best.as_ref().map(|entry| entry.quadratic_r2),
                    sizing_model,
                    refinement,
                });
            }
        }
        return Some(LadderFitPreview {
            search_tier: "candidate_cap_failure".to_owned(),
            max_allowed_peak_gap,
            gap_expansions,
            estimated_combination_count,
            candidate_generation_capped: true,
            evaluated_combination_count: 0,
            best_scan_indices: Vec::new(),
            best_curvature_score: None,
            best_quadratic_r2: None,
            sizing_model: None,
            refinement: None,
        });
    }
    let ladder_sizes = ladder.sizes();
    let peak_feature_by_index = fit_ladder_peaks
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let mut best = select_best_combination(
        &combinations,
        ladder_sizes,
        ladder,
        &fit_ladder_peaks,
        ladder_peaks,
    );
    let mut sizing_model = best
        .as_ref()
        .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
    let mut refinement = None;

    if let (Some(best_entry), Some(model)) = (best.as_ref(), sizing_model.as_ref()) {
        if let Some(refined) =
            refine_best_combination(&peak_indices, &best_entry.indices, ladder_sizes, model)
        {
            let refined_qr2 = quadratic_fit_r2(
                ladder_sizes,
                &refined
                    .refined_scan_indices
                    .iter()
                    .map(|value| *value as f64)
                    .collect::<Vec<_>>(),
            );
            let refined_curvature = curvature_score(ladder_sizes, &refined.refined_scan_indices);
            let _refined_domain_penalty = ladder_domain_penalty(
                ladder,
                &refined.refined_scan_indices,
                &peak_feature_by_index,
                ladder_peaks,
            );
            let _refined_peak_penalty = ladder_peak_sequence_penalty(
                &refined.refined_scan_indices,
                ladder,
                ladder_sizes,
                &peak_feature_by_index,
                &fit_ladder_peaks,
            );
            let refined_score = score_combination(
                &refined.refined_scan_indices,
                ladder_sizes,
                ladder,
                &peak_feature_by_index,
                &fit_ladder_peaks,
            );
            if refinement_improves_current(best_entry, &refined_score) {
                best = Some(refined_score);
                sizing_model = fit_best_sizing_model(
                    &refined.refined_scan_indices,
                    ladder_sizes,
                    sample_trace,
                );
                refinement = Some(RefinementPreview {
                    changed_step_indices: refined.changed_step_indices,
                    original_scan_indices: refined.original_scan_indices,
                    refined_scan_indices: refined.refined_scan_indices,
                    refined_curvature_score: refined_curvature,
                    refined_quadratic_r2: refined_qr2,
                });
            }
        }
    }

    let repair_peak_feature_by_index = ladder_peaks
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let repaired_best = apply_post_preview_rox_repair(
        best.clone(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
        ladder_peaks,
    );
    if repaired_best.as_ref().map(|score| &score.indices)
        != best.as_ref().map(|score| &score.indices)
    {
        best = repaired_best;
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }
    if allow_visual_start_repair {
        let visual_start_best = repair_rox_visual_start_pair_from_trace(
            best.clone(),
            ladder_sizes,
            ladder,
            ladder_peaks,
            ladder_trace,
        );
        if visual_start_best.as_ref().map(|score| &score.indices)
            != best.as_ref().map(|score| &score.indices)
        {
            best = visual_start_best;
            sizing_model = best.as_ref().and_then(|entry| {
                fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
            });
            refinement = None;
        }
    }
    apply_ladder_apex_recenter_to_preview(
        &mut best,
        &mut sizing_model,
        &mut refinement,
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
        ladder_peaks,
        sample_trace,
    );
    if let Some(candidate) = repair_liz_strong_median_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        best = Some(candidate);
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }
    if let Some(candidate) = repair_liz_blob_start_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        best = Some(candidate);
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }
    if let Some(candidate) = repair_liz_clean_late_tail_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        best = Some(candidate);
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }
    if allow_visual_start_repair {
        let visual_start_best = repair_rox_visual_start_pair_from_trace(
            best.clone(),
            ladder_sizes,
            ladder,
            ladder_peaks,
            ladder_trace,
        );
        if visual_start_best.as_ref().map(|score| &score.indices)
            != best.as_ref().map(|score| &score.indices)
        {
            best = visual_start_best;
            sizing_model = best.as_ref().and_then(|entry| {
                fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace)
            });
            refinement = None;
        }
    }
    let late_prepend_best =
        repair_rox_late_family_prepend_sequence(best.clone(), ladder_sizes, ladder, ladder_peaks);
    if late_prepend_best.as_ref().map(|score| &score.indices)
        != best.as_ref().map(|score| &score.indices)
    {
        best = late_prepend_best;
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }
    let first_strong_family_best = repair_rox_late_to_first_strong_family_sequence(
        best.clone(),
        ladder_sizes,
        ladder,
        ladder_peaks,
    );
    if first_strong_family_best
        .as_ref()
        .map(|score| &score.indices)
        != best.as_ref().map(|score| &score.indices)
    {
        best = first_strong_family_best;
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }
    let strong_median_family_best =
        repair_rox_strong_median_family_sequence(best.clone(), ladder_sizes, ladder, ladder_peaks);
    if strong_median_family_best
        .as_ref()
        .map(|score| &score.indices)
        != best.as_ref().map(|score| &score.indices)
    {
        best = strong_median_family_best;
        sizing_model = best
            .as_ref()
            .and_then(|entry| fit_best_sizing_model(&entry.indices, ladder_sizes, sample_trace));
        refinement = None;
    }

    let search_tier = if used_relaxed_fallback {
        "robust_relaxed_beam"
    } else if used_capped_full_pool_beam {
        "audit_capped_full_pool_beam"
    } else if estimated_combination_count > beam_search_trigger {
        "primary_beam"
    } else {
        "primary_exact"
    };
    Some(LadderFitPreview {
        search_tier: search_tier.to_owned(),
        max_allowed_peak_gap,
        gap_expansions,
        estimated_combination_count,
        candidate_generation_capped: false,
        evaluated_combination_count: combinations.len(),
        best_scan_indices: best
            .as_ref()
            .map(|entry| entry.indices.clone())
            .unwrap_or_default(),
        best_curvature_score: best.as_ref().map(|entry| entry.curvature_score),
        best_quadratic_r2: best.as_ref().map(|entry| entry.quadratic_r2),
        sizing_model,
        refinement,
    })
}

fn preview_linear_metrics(preview: &LadderFitPreview) -> Option<(f64, f64, f64, f64)> {
    let metrics = preview.sizing_model.as_ref()?.qc_metrics.clone();
    Some((
        metrics.linear_trend_max_abs_error_bp,
        metrics.linear_trend_mean_abs_error_bp,
        metrics.linear_trend_r2,
        metrics.max_abs_error_bp,
    ))
}

fn preview_prefers_candidate(current: &LadderFitPreview, candidate: &LadderFitPreview) -> bool {
    match (
        preview_linear_metrics(current),
        preview_linear_metrics(candidate),
    ) {
        (Some(current_metrics), Some(candidate_metrics)) => {
            let (current_linear_max, current_linear_mean, current_linear_r2, current_max_abs) =
                current_metrics;
            let (
                candidate_linear_max,
                candidate_linear_mean,
                candidate_linear_r2,
                candidate_max_abs,
            ) = candidate_metrics;

            let improved_max = candidate_linear_max + 0.75 < current_linear_max;
            let improved_mean = candidate_linear_mean + 0.30 < current_linear_mean;
            let improved_r2 = candidate_linear_r2 > current_linear_r2 + 0.0015;
            let regressed_max = candidate_linear_max > current_linear_max + 1.00;
            let regressed_mean = candidate_linear_mean > current_linear_mean + 0.55;
            let regressed_r2 = candidate_linear_r2 + 0.0010 < current_linear_r2;
            let regressed_spline = candidate_max_abs > current_max_abs + 0.30;

            ((improved_max || improved_mean || improved_r2)
                && !(regressed_max || regressed_mean || regressed_r2 || regressed_spline))
                || (candidate_linear_max + 2.50 < current_linear_max
                    && candidate_linear_mean <= current_linear_mean + 0.80)
        }
        (None, Some(_)) => true,
        _ => false,
    }
}

fn preview_has_liz_blob_start(
    preview: &LadderFitPreview,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> bool {
    let scans = &preview.best_scan_indices;
    if scans.len() < 4 {
        return false;
    }
    let early = &scans[..scans.len().min(5)];
    let cluster_width = early[early.len() - 1].saturating_sub(early[0]);
    let tight_pairs = early
        .windows(2)
        .filter(|pair| pair[1].saturating_sub(pair[0]) <= 60)
        .count();
    let weak_or_dirty = early
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            baseline_ratio > 0.40 || purity < 0.45
        })
        .count();
    let poor_linear = preview
        .sizing_model
        .as_ref()
        .map(|model| {
            model.qc_metrics.linear_trend_max_abs_error_bp > 8.0
                || model.qc_metrics.linear_trend_mean_abs_error_bp > 3.0
                || model.qc_metrics.linear_trend_r2 < 0.9992
        })
        .unwrap_or(false);
    (cluster_width <= 420 && tight_pairs >= 1 && weak_or_dirty >= 2) || poor_linear
}

fn exact_liz_preview_prefers_candidate(
    current: &LadderFitPreview,
    candidate: &LadderFitPreview,
) -> bool {
    if preview_prefers_candidate(current, candidate) {
        return true;
    }

    match (
        preview_linear_metrics(current),
        preview_linear_metrics(candidate),
    ) {
        (Some(current_metrics), Some(candidate_metrics)) => {
            let (current_linear_max, current_linear_mean, current_linear_r2, _) = current_metrics;
            let (candidate_linear_max, candidate_linear_mean, candidate_linear_r2, _) =
                candidate_metrics;
            let material_linear_win = candidate_linear_max + 4.00 < current_linear_max
                && candidate_linear_mean <= current_linear_mean + 0.35
                && candidate_linear_r2 + 0.0002 >= current_linear_r2;
            let hard_regression = candidate_linear_max > current_linear_max + 1.00
                || candidate_linear_mean > current_linear_mean + 0.55
                || candidate_linear_r2 + 0.0010 < current_linear_r2;
            material_linear_win && !hard_regression
        }
        _ => false,
    }
}

fn thin_peak_pool_for_ladder(
    ladder_peaks: &[Peak],
    target_len: usize,
    collapse_distance: usize,
    keep_limit: usize,
) -> Vec<Peak> {
    if ladder_peaks.len() <= keep_limit {
        return ladder_peaks.to_vec();
    }

    let diverse = select_diverse_peak_subset_with_buckets(
        ladder_peaks.to_vec(),
        keep_limit,
        keep_limit.clamp(8, 24),
    );
    if diverse.len() < target_len {
        return ladder_peaks.to_vec();
    }

    let mut ranked = diverse;
    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .prominence
                    .partial_cmp(&left.prominence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let mut reduced: Vec<Peak> = Vec::new();
    'candidate: for peak in ranked {
        for kept in &reduced {
            if peak.index.abs_diff(kept.index) <= collapse_distance {
                continue 'candidate;
            }
        }
        reduced.push(peak);
        if reduced.len() >= keep_limit {
            break;
        }
    }

    if reduced.len() < target_len {
        return ladder_peaks.to_vec();
    }
    reduced.sort_by_key(|peak| peak.index);
    reduced
}

fn estimate_max_allowed_peak_gap(peak_indices: &[usize], multiplier: f64) -> usize {
    if peak_indices.len() < 2 {
        return 400;
    }
    let mean_gap = peak_indices
        .windows(2)
        .map(|window| window[1].saturating_sub(window[0]) as f64)
        .sum::<f64>()
        / (peak_indices.len() - 1) as f64;
    (mean_gap * multiplier).round().max(400.0) as usize
}

fn estimate_combination_count_capped(
    peak_indices: &[usize],
    target_len: usize,
    max_gap: usize,
    cap: usize,
) -> usize {
    fn dfs(
        peak_indices: &[usize],
        start: usize,
        chosen: usize,
        target_len: usize,
        max_gap: usize,
        last_selected: Option<usize>,
        cap: usize,
        memo: &mut BTreeMap<(usize, usize, Option<usize>), usize>,
    ) -> usize {
        if chosen == target_len {
            return 1;
        }
        if start >= peak_indices.len() {
            return 0;
        }
        let key = (start, chosen, last_selected);
        if let Some(value) = memo.get(&key) {
            return *value;
        }

        let mut total = 0usize;
        for candidate_index in start..peak_indices.len() {
            if let Some(last_index) = last_selected {
                let gap = peak_indices[candidate_index].abs_diff(peak_indices[last_index]);
                if gap > max_gap {
                    continue;
                }
            }
            total = total.saturating_add(dfs(
                peak_indices,
                candidate_index + 1,
                chosen + 1,
                target_len,
                max_gap,
                Some(candidate_index),
                cap,
                memo,
            ));
            if total >= cap {
                total = cap;
                break;
            }
        }

        memo.insert(key, total);
        total
    }

    if target_len == 0 || peak_indices.len() < target_len {
        return 0;
    }
    let mut memo = BTreeMap::new();
    dfs(
        peak_indices,
        0,
        0,
        target_len,
        max_gap,
        None,
        cap,
        &mut memo,
    )
}

fn generate_peak_combinations(
    peak_indices: &[usize],
    target_len: usize,
    max_gap: usize,
    max_combinations: usize,
) -> Vec<Vec<usize>> {
    fn dfs(
        peak_indices: &[usize],
        start: usize,
        target_len: usize,
        max_gap: usize,
        current: &mut Vec<usize>,
        results: &mut Vec<Vec<usize>>,
        max_combinations: usize,
    ) {
        if results.len() >= max_combinations {
            return;
        }
        if current.len() == target_len {
            results.push(current.clone());
            return;
        }
        if start >= peak_indices.len() {
            return;
        }

        for candidate_index in start..peak_indices.len() {
            if let Some(&last_scan) = current.last() {
                let gap = peak_indices[candidate_index].abs_diff(last_scan);
                if gap > max_gap {
                    continue;
                }
            }
            current.push(peak_indices[candidate_index]);
            dfs(
                peak_indices,
                candidate_index + 1,
                target_len,
                max_gap,
                current,
                results,
                max_combinations,
            );
            current.pop();
            if results.len() >= max_combinations {
                return;
            }
        }
    }

    if target_len == 0 || peak_indices.len() < target_len {
        return Vec::new();
    }

    let mut results = Vec::new();
    let mut current = Vec::with_capacity(target_len);
    dfs(
        peak_indices,
        0,
        target_len,
        max_gap,
        &mut current,
        &mut results,
        max_combinations,
    );
    results
}

fn generate_peak_combinations_beam(
    peak_indices: &[usize],
    target_len: usize,
    max_gap: usize,
    ladder_sizes: &[f64],
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    beam_width: usize,
    final_cap: usize,
) -> Vec<Vec<usize>> {
    #[derive(Clone)]
    struct BeamState {
        indices: Vec<usize>,
        next_start: usize,
        score: f64,
    }

    if target_len == 0 || peak_indices.len() < target_len || ladder_sizes.len() < target_len {
        return Vec::new();
    }

    let mut states = vec![BeamState {
        indices: Vec::with_capacity(target_len),
        next_start: 0,
        score: 0.0,
    }];

    for step in 0..target_len {
        let remaining_after_pick = target_len.saturating_sub(step + 1);
        let mut next_states = Vec::new();

        for state in &states {
            if peak_indices.len().saturating_sub(state.next_start) < remaining_after_pick + 1 {
                continue;
            }

            for candidate_index in state.next_start..peak_indices.len() {
                if peak_indices.len().saturating_sub(candidate_index + 1) < remaining_after_pick {
                    break;
                }
                if let Some(&last_scan) = state.indices.last() {
                    let gap = peak_indices[candidate_index].abs_diff(last_scan);
                    if gap > max_gap {
                        continue;
                    }
                }

                let mut indices = state.indices.clone();
                indices.push(peak_indices[candidate_index]);
                let score = partial_combination_beam_score(
                    &indices,
                    &ladder_sizes[..indices.len()],
                    peak_feature_by_index,
                    ladder_sizes.len(),
                );
                next_states.push(BeamState {
                    indices,
                    next_start: candidate_index + 1,
                    score,
                });
            }
        }

        if next_states.is_empty() {
            return Vec::new();
        }

        next_states.sort_by(|left, right| {
            left.score
                .partial_cmp(&right.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.indices.cmp(&right.indices))
        });
        if next_states.len() > beam_width {
            next_states.truncate(beam_width);
        }
        states = next_states;
    }

    let mut results = states
        .into_iter()
        .map(|state| (state.score, state.indices))
        .collect::<Vec<_>>();
    results.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.1.cmp(&right.1))
    });
    if results.len() > final_cap {
        results.truncate(final_cap);
    }
    results.into_iter().map(|(_, indices)| indices).collect()
}

fn partial_combination_beam_score(
    scans: &[usize],
    ladder_sizes: &[f64],
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    expected_total_len: usize,
) -> f64 {
    if scans.is_empty() || ladder_sizes.is_empty() || scans.len() != ladder_sizes.len() {
        return f64::INFINITY;
    }

    let prefix_curvature = if scans.len() >= 3 {
        curvature_score(ladder_sizes, scans)
    } else {
        0.0
    };

    let gap_ratios = scans
        .windows(2)
        .zip(ladder_sizes.windows(2))
        .filter_map(|(scan_window, bp_window)| {
            let bp_gap = bp_window[1] - bp_window[0];
            if bp_gap <= f64::EPSILON {
                None
            } else {
                Some((scan_window[1] as f64 - scan_window[0] as f64) / bp_gap)
            }
        })
        .collect::<Vec<_>>();
    let gap_penalty = coefficient_of_variation_penalty(&gap_ratios, 0.45) * 0.25;

    let score_reward = scans
        .iter()
        .filter_map(|scan| {
            peak_feature_by_index
                .get(scan)
                .map(|peak| peak.score.max(1.0).ln())
        })
        .sum::<f64>()
        / scans.len() as f64;

    let purity_penalty = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .map(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            baseline_ratio * (1.0 - 0.60 * purity)
        })
        .sum::<f64>()
        / scans.len() as f64;

    let early_dense_penalty = if gap_ratios.len() >= 2 {
        let early_len = gap_ratios.len().min(3);
        let median_gap_ratio = median(&gap_ratios).max(1.0);
        gap_ratios
            .iter()
            .take(early_len)
            .map(|ratio| ((median_gap_ratio * 0.68 - *ratio).max(0.0)) / median_gap_ratio)
            .sum::<f64>()
            / early_len as f64
    } else {
        0.0
    };

    let late_gap_outlier_penalty = if expected_total_len == 21 && gap_ratios.len() >= 3 {
        let late_len = gap_ratios.len().min(3);
        let median_gap_ratio = median(&gap_ratios).max(1.0);
        gap_ratios
            .iter()
            .rev()
            .take(late_len)
            .map(|ratio| ((ratio - median_gap_ratio * 1.35).max(0.0)) / median_gap_ratio)
            .sum::<f64>()
            / late_len as f64
            * 1.35
    } else {
        0.0
    };

    let rox_partial_skip_penalty = if expected_total_len == 21 && scans.len() >= 4 {
        let last_left = scans[scans.len() - 2];
        let last_right = scans[scans.len() - 1];
        let bp_gap = ladder_sizes[ladder_sizes.len() - 1] - ladder_sizes[ladder_sizes.len() - 2];
        if bp_gap <= f64::EPSILON {
            0.0
        } else {
            let median_gap_ratio = median(&gap_ratios).max(1.0);
            let expected_scan_gap = median_gap_ratio * bp_gap;
            let selected_gap = (last_right - last_left) as f64;
            if selected_gap <= expected_scan_gap * 1.15 {
                0.0
            } else {
                let recent_scores = scans
                    .iter()
                    .rev()
                    .skip(1)
                    .take(4)
                    .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.score))
                    .filter(|value| value.is_finite() && *value > 0.0)
                    .collect::<Vec<_>>();
                let score_ref = median(&recent_scores).max(1.0);
                let candidate = peak_feature_by_index
                    .values()
                    .filter(|peak| {
                        peak.index > last_left.saturating_add(12)
                            && peak.index + 12 < last_right
                            && peak.score >= (score_ref * 0.55).max(14.0)
                    })
                    .max_by(|left, right| {
                        left.score
                            .partial_cmp(&right.score)
                            .unwrap_or(std::cmp::Ordering::Equal)
                    });
                let Some(candidate) = candidate else {
                    return prefix_curvature
                        + gap_penalty
                        + purity_penalty * 0.60
                        + early_dense_penalty * 0.70
                        + late_gap_outlier_penalty
                        - score_reward * 0.04;
                };
                let candidate_gap = (candidate.index - last_left) as f64;
                let closeness = (1.10
                    - ((candidate_gap - expected_scan_gap).abs() / expected_scan_gap.max(1.0)))
                .clamp(0.15, 1.10);
                let candidate_strength = (candidate.score / score_ref).clamp(0.0, 1.8);
                (((selected_gap - expected_scan_gap) / expected_scan_gap.max(1.0)).max(0.0))
                    * closeness
                    * candidate_strength
                    * 2.90
            }
        }
    } else {
        0.0
    };
    let template_gap_penalty =
        partial_ladder_gap_template_penalty(scans, ladder_sizes, expected_total_len) * 0.45;

    prefix_curvature
        + gap_penalty
        + purity_penalty * 0.60
        + early_dense_penalty * 0.70
        + late_gap_outlier_penalty
        + rox_partial_skip_penalty
        + template_gap_penalty
        - score_reward * 0.04
}

#[derive(Debug, Clone, PartialEq)]
struct CombinationScore {
    indices: Vec<usize>,
    curvature_score: f64,
    quadratic_r2: f64,
    linear_mean_abs_error_bp: f64,
    linear_max_abs_error_bp: f64,
    linear_r2: f64,
    domain_penalty: f64,
    peak_penalty: f64,
    blended_score: f64,
}

fn polynomial_trend_metrics(x: &[f64], y: &[f64], degree: usize) -> (f64, f64, f64) {
    if x.len() != y.len() || x.is_empty() || x.len() <= degree {
        return (f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    }
    let Some(coefficients) = fit_polynomial_least_squares(x, y, degree) else {
        return (f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    };
    let predicted = x
        .iter()
        .map(|value| eval_polynomial(&coefficients, *value))
        .collect::<Vec<_>>();
    let mean_y = y.iter().sum::<f64>() / y.len() as f64;
    let abs_errors = y
        .iter()
        .zip(predicted.iter())
        .map(|(actual, fitted)| (actual - fitted).abs())
        .collect::<Vec<_>>();
    let ss_tot = y
        .iter()
        .map(|value| {
            let delta = *value - mean_y;
            delta * delta
        })
        .sum::<f64>();
    let ss_res = y
        .iter()
        .zip(predicted.iter())
        .map(|(actual, fitted)| {
            let delta = actual - fitted;
            delta * delta
        })
        .sum::<f64>();
    let r2 = if ss_tot <= f64::EPSILON {
        f64::NEG_INFINITY
    } else {
        1.0 - (ss_res / ss_tot)
    };
    let mean_abs = abs_errors.iter().sum::<f64>() / abs_errors.len() as f64;
    let max_abs = abs_errors.into_iter().fold(0.0_f64, f64::max);
    (mean_abs, max_abs, r2)
}

fn linear_trend_residual_metrics(ladder_sizes: &[f64], scans: &[usize]) -> (f64, f64, f64) {
    let x = scans.iter().map(|value| *value as f64).collect::<Vec<_>>();
    polynomial_trend_metrics(&x, ladder_sizes, 1)
}

fn peak_plausibility_penalty(
    scans: &[usize],
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> f64 {
    let heights = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if heights.is_empty() {
        return f64::INFINITY;
    }
    let height_ref = median(&heights).max(1.0);
    scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .map(|peak| {
            let weak = ((0.35 - (peak.height / height_ref)).max(0.0)) / 0.35;
            let blob = ((peak.height / height_ref - 3.5).max(0.0)) / 3.5;
            let baseline = (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 2.0);
            weak + blob + baseline * 0.35
        })
        .sum::<f64>()
        / scans.len() as f64
}

fn local_peak_quality_penalty(
    scans: &[usize],
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> f64 {
    let selected = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if selected.is_empty() {
        return f64::INFINITY;
    }

    let height_ref = median(
        &selected
            .iter()
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &selected
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let width_ref = median(
        &selected
            .iter()
            .map(|peak| peak.width.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    selected
        .iter()
        .map(|peak| {
            let height = peak.height.max(1.0);
            let purity = (peak.prominence / height).clamp(0.0, 1.4);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let height_ratio = peak.height / height_ref;
            let prominence_ratio = peak.prominence.max(1.0) / prominence_ref;
            let width_ratio = peak.width.max(1.0) / width_ref;

            let weak = ((0.32 - height_ratio).max(0.0)) / 0.32;
            let purity_penalty = ((0.58 - purity).max(0.0)) / 0.58;
            let baseline_penalty = ((baseline_ratio - 0.18).max(0.0)) / 0.22;
            let width_penalty = if width_ratio > 1.9 {
                (width_ratio - 1.9) / 1.1
            } else if width_ratio < 0.45 {
                (0.45 - width_ratio) / 0.25
            } else {
                0.0
            };
            let family_mismatch = ((0.22 - height_ratio.min(prominence_ratio)).max(0.0)) / 0.22;

            weak * 0.80
                + purity_penalty * 1.10
                + baseline_penalty * 0.95
                + width_penalty * 0.55
                + family_mismatch * 0.85
        })
        .sum::<f64>()
        / scans.len() as f64
}

fn score_combination(
    combo: &[usize],
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> CombinationScore {
    let curvature = curvature_score(ladder_sizes, combo);
    let qr2 = quadratic_fit_r2(
        ladder_sizes,
        &combo.iter().map(|value| *value as f64).collect::<Vec<_>>(),
    );
    let (linear_mean_abs_error_bp, linear_max_abs_error_bp, linear_r2) =
        linear_trend_residual_metrics(ladder_sizes, combo);
    let domain_penalty = ladder_domain_penalty(ladder, combo, peak_feature_by_index, peak_features);
    let peak_penalty = ladder_peak_sequence_penalty(
        combo,
        ladder,
        ladder_sizes,
        peak_feature_by_index,
        peak_features,
    ) + local_peak_quality_penalty(combo, peak_feature_by_index);
    let template_gap_penalty = ladder_gap_template_penalty(ladder, combo) * 0.90;
    let linear_mean_penalty = (linear_mean_abs_error_bp - LINEAR_TREND_MEAN_TARGET_BP).max(0.0)
        * LINEAR_TREND_MEAN_WEIGHT;
    let linear_max_penalty =
        (linear_max_abs_error_bp - LINEAR_TREND_MAX_TARGET_BP).max(0.0) * LINEAR_TREND_MAX_WEIGHT;
    let linear_r2_penalty = (LINEAR_TREND_R2_TARGET - linear_r2).max(0.0) * LINEAR_TREND_R2_WEIGHT;
    let rox_linear_hardcase_penalty = if ladder == LadderKind::Rox400Hd {
        (linear_mean_abs_error_bp - ROX_REVIEW_LINEAR_MEAN_BP).max(0.0)
            * ROX_LINEAR_HARDCASE_MEAN_WEIGHT
            + (linear_max_abs_error_bp - ROX_REVIEW_LINEAR_MAX_BP).max(0.0)
                * ROX_LINEAR_HARDCASE_MAX_WEIGHT
            + (ROX_REVIEW_LINEAR_R2_MIN - linear_r2).max(0.0) * ROX_LINEAR_HARDCASE_R2_WEIGHT
    } else {
        0.0
    };
    CombinationScore {
        indices: combo.to_vec(),
        curvature_score: curvature,
        quadratic_r2: qr2,
        linear_mean_abs_error_bp,
        linear_max_abs_error_bp,
        linear_r2,
        domain_penalty,
        peak_penalty,
        blended_score: curvature
            + domain_penalty
            + peak_penalty
            + template_gap_penalty
            + linear_mean_penalty
            + linear_max_penalty
            + linear_r2_penalty
            + rox_linear_hardcase_penalty,
    }
}

fn compare_combination_scores(
    left: &CombinationScore,
    right: &CombinationScore,
) -> std::cmp::Ordering {
    left.blended_score
        .partial_cmp(&right.blended_score)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| {
            left.linear_max_abs_error_bp
                .partial_cmp(&right.linear_max_abs_error_bp)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.linear_mean_abs_error_bp
                .partial_cmp(&right.linear_mean_abs_error_bp)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            right
                .linear_r2
                .partial_cmp(&left.linear_r2)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.peak_penalty
                .partial_cmp(&right.peak_penalty)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.curvature_score
                .partial_cmp(&right.curvature_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            right
                .quadratic_r2
                .partial_cmp(&left.quadratic_r2)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| left.indices.cmp(&right.indices))
}

fn block_repair_is_material(current: &CombinationScore, candidate: &CombinationScore) -> bool {
    let improved_max = candidate.linear_max_abs_error_bp + 1.00 < current.linear_max_abs_error_bp;
    let improved_mean =
        candidate.linear_mean_abs_error_bp + 0.35 < current.linear_mean_abs_error_bp;
    let improved_r2 = candidate.linear_r2 > current.linear_r2 + 0.0015;
    let regressed_mean =
        candidate.linear_mean_abs_error_bp > current.linear_mean_abs_error_bp + 0.50;
    let regressed_r2 = candidate.linear_r2 + 0.0010 < current.linear_r2;

    !regressed_mean
        && !regressed_r2
        && candidate.domain_penalty <= current.domain_penalty + 0.85
        && candidate.peak_penalty <= current.peak_penalty + 0.95
        && (improved_max || improved_mean || improved_r2)
}

fn compare_block_repair_candidates(
    left: &CombinationScore,
    right: &CombinationScore,
) -> std::cmp::Ordering {
    left.linear_max_abs_error_bp
        .partial_cmp(&right.linear_max_abs_error_bp)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| {
            left.linear_mean_abs_error_bp
                .partial_cmp(&right.linear_mean_abs_error_bp)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            right
                .linear_r2
                .partial_cmp(&left.linear_r2)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.peak_penalty
                .partial_cmp(&right.peak_penalty)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.domain_penalty
                .partial_cmp(&right.domain_penalty)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.blended_score
                .partial_cmp(&right.blended_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| left.indices.cmp(&right.indices))
}

fn refinement_improves_current(current: &CombinationScore, candidate: &CombinationScore) -> bool {
    compare_combination_scores(candidate, current) == std::cmp::Ordering::Less
        || block_repair_is_material(current, candidate)
}

fn repair_candidate_improves_current(
    current: &CombinationScore,
    candidate: &CombinationScore,
) -> bool {
    let hard_regression = candidate.linear_max_abs_error_bp
        > current.linear_max_abs_error_bp + 0.60
        || candidate.linear_mean_abs_error_bp > current.linear_mean_abs_error_bp + 0.30
        || candidate.linear_r2 + 0.0002 < current.linear_r2;
    if hard_regression {
        return false;
    }

    compare_block_repair_candidates(candidate, current) == std::cmp::Ordering::Less
        || block_repair_is_material(current, candidate)
}

fn rox_start_pair_candidate_improves_current(
    current: &CombinationScore,
    candidate: &CombinationScore,
) -> bool {
    if repair_candidate_improves_current(current, candidate) {
        return true;
    }

    candidate.linear_max_abs_error_bp + 1.10 < current.linear_max_abs_error_bp
        && candidate.linear_mean_abs_error_bp <= current.linear_mean_abs_error_bp + 0.55
        && candidate.linear_r2 + 0.00002 >= current.linear_r2
}

fn rox_start_pair_feature_candidate_can_override(
    current: &CombinationScore,
    candidate: &CombinationScore,
) -> bool {
    if current.indices.len() != candidate.indices.len()
        || candidate.indices.len() < 3
        || current.indices[2] != candidate.indices[2]
    {
        return false;
    }

    let current_first_gap = current.indices[1].saturating_sub(current.indices[0]) as f64;
    let first_gap = candidate.indices[1].saturating_sub(candidate.indices[0]) as f64;
    let second_gap = candidate.indices[2].saturating_sub(candidate.indices[1]) as f64;
    let current_start_is_suspicious = current.linear_max_abs_error_bp > 3.85
        || current.linear_mean_abs_error_bp > 1.25
        || current_first_gap < 38.0;

    current_start_is_suspicious
        && candidate.indices[1] > current.indices[1].saturating_add(8)
        && (45.0..=105.0).contains(&first_gap)
        && (135.0..=235.0).contains(&second_gap)
        && candidate.linear_max_abs_error_bp <= 7.35
        && candidate.linear_mean_abs_error_bp <= 3.20
        && candidate.linear_r2 >= 0.99880
        && candidate.linear_mean_abs_error_bp <= current.linear_mean_abs_error_bp + 0.98
        && candidate.linear_max_abs_error_bp <= current.linear_max_abs_error_bp + 1.70
        && candidate.linear_max_abs_error_bp + 0.50 >= current.linear_max_abs_error_bp
}

fn bp_trend_metrics_for_indices(
    indices: &[usize],
    ladder_sizes: &[f64],
    degree: usize,
) -> (f64, f64, f64) {
    let x = indices
        .iter()
        .map(|value| *value as f64)
        .collect::<Vec<_>>();
    polynomial_trend_metrics(&x, ladder_sizes, degree)
}

fn bp_trend_metrics_for_score(
    score: &CombinationScore,
    ladder_sizes: &[f64],
    degree: usize,
) -> (f64, f64, f64) {
    bp_trend_metrics_for_indices(&score.indices, ladder_sizes, degree)
}

fn rox_nonlinear_start_pair_candidate_can_override(
    current: &CombinationScore,
    candidate: &CombinationScore,
    ladder_sizes: &[f64],
) -> bool {
    if current.indices.len() != candidate.indices.len()
        || candidate.indices.len() < 3
        || current.indices[2] != candidate.indices[2]
    {
        return false;
    }
    let current_gap23 = current.indices[2].saturating_sub(current.indices[1]) as f64;
    let candidate_gap12 = candidate.indices[1].saturating_sub(candidate.indices[0]) as f64;
    let candidate_gap23 = candidate.indices[2].saturating_sub(candidate.indices[1]) as f64;
    if !(35.0..=115.0).contains(&candidate_gap12)
        || !(130.0..=240.0).contains(&candidate_gap23)
        || candidate_gap23 + 40.0 >= current_gap23
    {
        return false;
    }

    let (_current_d2_mean, current_d2_max, _current_d2_r2) =
        bp_trend_metrics_for_score(current, ladder_sizes, 2);
    let (current_d3_mean, current_d3_max, _current_d3_r2) =
        bp_trend_metrics_for_score(current, ladder_sizes, 3);
    let (_candidate_d2_mean, candidate_d2_max, _candidate_d2_r2) =
        bp_trend_metrics_for_score(candidate, ladder_sizes, 2);
    let (candidate_d3_mean, candidate_d3_max, _candidate_d3_r2) =
        bp_trend_metrics_for_score(candidate, ladder_sizes, 3);

    let current_suspicious =
        current_d3_max > 2.50 || current_d2_max > 4.00 || current_gap23 > 260.0;
    let nonlinear_win = candidate_d3_max + 1.20 < current_d3_max
        && candidate_d2_max + 1.50 < current_d2_max
        && candidate_d3_mean + 0.45 < current_d3_mean;
    let excellent_nonlinear =
        candidate_d3_max <= 0.80 && candidate_d3_mean <= 0.30 && candidate_d2_max <= 2.40;
    let linear_guard = candidate.linear_max_abs_error_bp <= 13.0
        && candidate.linear_mean_abs_error_bp <= 5.70
        && candidate.linear_r2 >= 0.9963
        && candidate.linear_max_abs_error_bp <= current.linear_max_abs_error_bp + 4.20;

    current_suspicious && nonlinear_win && excellent_nonlinear && linear_guard
}

fn rox_tail_family_candidate_improves_current(
    current: &CombinationScore,
    candidate: &CombinationScore,
) -> bool {
    if repair_candidate_improves_current(current, candidate) {
        return true;
    }

    candidate.linear_max_abs_error_bp + 0.60 < current.linear_max_abs_error_bp
        && candidate.linear_mean_abs_error_bp <= current.linear_mean_abs_error_bp + 0.35
        && candidate.linear_r2 + 0.00015 >= current.linear_r2
}

fn repair_gs500rox_start_anchor_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Gs500Rox
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() != 16
    {
        return None;
    }

    let first = best.indices[0];
    let second = best.indices[1];
    let last = *best.indices.last().unwrap_or(&0);
    let suspicious_late_start = first > GS500ROX_MAX_FIRST_ANCHOR as usize
        || best.linear_max_abs_error_bp > 3.25
        || best.linear_mean_abs_error_bp > 1.40;
    if !suspicious_late_start {
        return None;
    }

    let plausible_start_peak = |peak: &Peak| {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence / height).clamp(0.0, 1.5);
        let baseline_ok = baseline_ratio <= 0.55 || (baseline_ratio <= 0.68 && purity >= 0.36);
        peak.height >= 60.0 && peak.prominence >= 30.0 && baseline_ok && purity >= 0.22
    };
    let mut best_trial: Option<CombinationScore> = None;

    let third = best.indices[2];
    let fourth = best.indices[3];
    let gap_35_50 = second.saturating_sub(first);
    let gap_50_75 = third.saturating_sub(second);
    let start_alternative_before = peak_features.iter().any(|peak| {
        peak.index >= first.saturating_sub(120) && peak.index < first && plausible_start_peak(peak)
    });
    let start_alternative_between = peak_features
        .iter()
        .any(|peak| peak.index > first && peak.index < second && plausible_start_peak(peak));
    let suspect_both_start_family = first >= GS500ROX_ABSOLUTE_TIME_MIN as usize
        && first <= GS500ROX_MAX_FIRST_ANCHOR as usize
        && last >= 3900
        && gap_35_50 <= 85
        && gap_50_75 >= 180
        && (start_alternative_before || start_alternative_between);
    let suspect_35_start_family = first >= GS500ROX_ABSOLUTE_TIME_MIN as usize
        && first <= GS500ROX_MAX_FIRST_ANCHOR as usize
        && last >= 3900
        && gap_35_50 >= 115
        && gap_50_75 <= 165
        && start_alternative_between;

    if suspect_both_start_family || suspect_35_start_family {
        let tail_sizes = ladder_sizes[4..].to_vec();
        let tail_scans = best.indices[4..].to_vec();
        if let Some((tail_intercept, tail_slope)) = linear_scan_model(&tail_sizes, &tail_scans) {
            if tail_intercept.is_finite() && tail_slope.is_finite() && tail_slope > 0.0 {
                let mut projected: Vec<Vec<&Peak>> = Vec::new();
                for step_index in 0..4 {
                    let predicted = tail_intercept + tail_slope * ladder_sizes[step_index];
                    let radius = match step_index {
                        0 => 190.0,
                        1 => 190.0,
                        2 => 220.0,
                        _ => 240.0,
                    };
                    let mut candidates = peak_features
                        .iter()
                        .filter(|peak| {
                            peak.index >= GS500ROX_ABSOLUTE_TIME_MIN as usize
                                && peak.index + 18 < best.indices[4]
                                && ((peak.index as f64) - predicted).abs() <= radius
                                && plausible_start_peak(peak)
                        })
                        .collect::<Vec<_>>();
                    candidates.sort_by(|left, right| {
                        let left_distance = ((left.index as f64) - predicted).abs();
                        let right_distance = ((right.index as f64) - predicted).abs();
                        left_distance
                            .partial_cmp(&right_distance)
                            .unwrap_or(std::cmp::Ordering::Equal)
                            .then_with(|| {
                                right
                                    .score
                                    .partial_cmp(&left.score)
                                    .unwrap_or(std::cmp::Ordering::Equal)
                            })
                    });
                    candidates.truncate(9);
                    if candidates.is_empty() {
                        projected.clear();
                        break;
                    }
                    projected.push(candidates);
                }

                if projected.len() == 4 {
                    for p0 in &projected[0] {
                        for p1 in &projected[1] {
                            if p1.index <= p0.index || !(45..=210).contains(&(p1.index - p0.index))
                            {
                                continue;
                            }
                            for p2 in &projected[2] {
                                if p2.index <= p1.index
                                    || !(45..=260).contains(&(p2.index - p1.index))
                                {
                                    continue;
                                }
                                for p3 in &projected[3] {
                                    if p3.index <= p2.index
                                        || p3.index + 18 >= best.indices[4]
                                        || !(70..=330).contains(&(p3.index - p2.index))
                                    {
                                        continue;
                                    }

                                    let mut trial = best.indices.clone();
                                    trial[0] = p0.index;
                                    trial[1] = p1.index;
                                    trial[2] = p2.index;
                                    trial[3] = p3.index;
                                    if !trial.windows(2).all(|window| window[1] > window[0]) {
                                        continue;
                                    }
                                    if suspect_35_start_family
                                        && (trial[1] != second
                                            || trial[2] != third
                                            || trial[3] != fourth)
                                    {
                                        continue;
                                    }

                                    let trial_score = score_combination(
                                        &trial,
                                        ladder_sizes,
                                        ladder,
                                        peak_feature_by_index,
                                        peak_features,
                                    );
                                    let material_win = trial_score.linear_max_abs_error_bp + 3.5
                                        < best.linear_max_abs_error_bp
                                        || trial_score.linear_mean_abs_error_bp + 1.0
                                            < best.linear_mean_abs_error_bp;
                                    let no_hard_regression = trial_score.linear_max_abs_error_bp
                                        <= best.linear_max_abs_error_bp + 0.50
                                        && trial_score.linear_mean_abs_error_bp
                                            <= best.linear_mean_abs_error_bp + 0.60
                                        && trial_score.linear_r2 + 0.0015 >= best.linear_r2;
                                    let review_profile = trial_score.linear_max_abs_error_bp
                                        <= 35.0
                                        && trial_score.linear_mean_abs_error_bp <= 13.5
                                        && trial_score.linear_r2 >= 0.9890;
                                    if !(material_win && no_hard_regression && review_profile) {
                                        continue;
                                    }

                                    let should_take =
                                        if let Some(current_best) = best_trial.as_ref() {
                                            (
                                                trial_score.linear_mean_abs_error_bp,
                                                trial_score.linear_max_abs_error_bp,
                                                -trial_score.linear_r2,
                                                trial_score.blended_score,
                                            ) < (
                                                current_best.linear_mean_abs_error_bp,
                                                current_best.linear_max_abs_error_bp,
                                                -current_best.linear_r2,
                                                current_best.blended_score,
                                            )
                                        } else {
                                            true
                                        };
                                    if should_take {
                                        best_trial = Some(trial_score);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if best_trial.is_some() {
        return best_trial;
    }

    let start_candidates = peak_features
        .iter()
        .filter(|peak| {
            peak.index >= 1400
                && peak.index <= 1660
                && peak.index < best.indices[2]
                && plausible_start_peak(peak)
        })
        .collect::<Vec<_>>();
    for first_candidate in &start_candidates {
        for second_candidate in &start_candidates {
            if second_candidate.index <= first_candidate.index {
                continue;
            }
            let first_gap = second_candidate.index - first_candidate.index;
            if !(45..=185).contains(&first_gap) {
                continue;
            }
            if second_candidate.index + 35 >= best.indices[2] {
                continue;
            }

            let mut trial = best.indices.clone();
            trial[0] = first_candidate.index;
            trial[1] = second_candidate.index;
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }

            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            let material_win = trial_score.linear_max_abs_error_bp + 0.60
                < best.linear_max_abs_error_bp
                || trial_score.linear_mean_abs_error_bp + 0.40 < best.linear_mean_abs_error_bp;
            let no_hard_regression = trial_score.linear_max_abs_error_bp
                <= best.linear_max_abs_error_bp + 0.35
                && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.45
                && trial_score.linear_r2 + 0.0010 >= best.linear_r2;
            let usable_profile = trial_score.linear_max_abs_error_bp <= 32.0
                && trial_score.linear_mean_abs_error_bp <= 13.5
                && trial_score.linear_r2 >= 0.9890;
            if !(material_win && no_hard_regression && usable_profile) {
                continue;
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                (
                    trial_score.linear_mean_abs_error_bp,
                    trial_score.linear_max_abs_error_bp,
                    -trial_score.linear_r2,
                    trial_score.blended_score,
                ) < (
                    current_best.linear_mean_abs_error_bp,
                    current_best.linear_max_abs_error_bp,
                    -current_best.linear_r2,
                    current_best.blended_score,
                )
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    if best_trial.is_some() {
        return best_trial;
    }

    if best.linear_max_abs_error_bp > 8.0 || best.linear_mean_abs_error_bp > 3.5 {
        let block_candidates = peak_features
            .iter()
            .filter(|peak| {
                peak.index >= 1400
                    && peak.index <= best.indices[5].saturating_sub(18)
                    && plausible_start_peak(peak)
            })
            .collect::<Vec<_>>();
        let mut projected: Vec<Vec<&Peak>> = Vec::new();
        for step_index in 0..5 {
            let bp_offset = ladder_sizes[step_index] - ladder_sizes[0];
            let projected_scan = first as f64
                + (best.indices[5] as f64 - first as f64)
                    * (bp_offset / (ladder_sizes[5] - ladder_sizes[0]).max(1.0));
            let radius = match step_index {
                0 => 170.0,
                1 => 190.0,
                2 => 210.0,
                3 => 230.0,
                _ => 260.0,
            };
            let mut candidates = block_candidates
                .iter()
                .copied()
                .filter(|peak| ((peak.index as f64) - projected_scan).abs() <= radius)
                .collect::<Vec<_>>();
            candidates.sort_by(|left, right| {
                let left_distance = ((left.index as f64) - projected_scan).abs();
                let right_distance = ((right.index as f64) - projected_scan).abs();
                left_distance
                    .partial_cmp(&right_distance)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| {
                        right
                            .score
                            .partial_cmp(&left.score)
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
            });
            candidates.truncate(8);
            if candidates.is_empty() {
                projected.clear();
                break;
            }
            projected.push(candidates);
        }

        if projected.len() == 5 {
            for p0 in &projected[0] {
                for p1 in &projected[1] {
                    if p1.index <= p0.index || !(45..=190).contains(&(p1.index - p0.index)) {
                        continue;
                    }
                    for p2 in &projected[2] {
                        if p2.index <= p1.index || p2.index - p1.index < 45 {
                            continue;
                        }
                        for p3 in &projected[3] {
                            if p3.index <= p2.index || p3.index - p2.index < 45 {
                                continue;
                            }
                            for p4 in &projected[4] {
                                if p4.index <= p3.index
                                    || p4.index + 18 >= best.indices[5]
                                    || p4.index - p3.index < 90
                                {
                                    continue;
                                }
                                let mut trial = best.indices.clone();
                                trial[0] = p0.index;
                                trial[1] = p1.index;
                                trial[2] = p2.index;
                                trial[3] = p3.index;
                                trial[4] = p4.index;
                                if !trial.windows(2).all(|window| window[1] > window[0]) {
                                    continue;
                                }
                                let trial_score = score_combination(
                                    &trial,
                                    ladder_sizes,
                                    ladder,
                                    peak_feature_by_index,
                                    peak_features,
                                );
                                let strong_win = trial_score.linear_max_abs_error_bp + 2.0
                                    < best.linear_max_abs_error_bp
                                    || trial_score.linear_mean_abs_error_bp + 1.0
                                        < best.linear_mean_abs_error_bp;
                                let no_hard_regression = trial_score.linear_max_abs_error_bp
                                    <= best.linear_max_abs_error_bp + 0.50
                                    && trial_score.linear_mean_abs_error_bp
                                        <= best.linear_mean_abs_error_bp + 0.50
                                    && trial_score.linear_r2 + 0.0015 >= best.linear_r2;
                                let usable_profile = trial_score.linear_max_abs_error_bp <= 28.0
                                    && trial_score.linear_mean_abs_error_bp <= 12.0
                                    && trial_score.linear_r2 >= 0.9900;
                                if !(strong_win && no_hard_regression && usable_profile) {
                                    continue;
                                }
                                let should_take = if let Some(current_best) = best_trial.as_ref() {
                                    (
                                        trial_score.linear_mean_abs_error_bp,
                                        trial_score.linear_max_abs_error_bp,
                                        -trial_score.linear_r2,
                                        trial_score.blended_score,
                                    ) < (
                                        current_best.linear_mean_abs_error_bp,
                                        current_best.linear_max_abs_error_bp,
                                        -current_best.linear_r2,
                                        current_best.blended_score,
                                    )
                                } else {
                                    true
                                };
                                if should_take {
                                    best_trial = Some(trial_score);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if best_trial.is_some() {
        return best_trial;
    }

    if best.linear_max_abs_error_bp > 8.0 || best.linear_mean_abs_error_bp > 3.5 {
        let tail_sizes = ladder_sizes[7..].to_vec();
        let tail_scans = best.indices[7..].to_vec();
        if let Some((tail_intercept, tail_slope)) = linear_scan_model(&tail_sizes, &tail_scans) {
            if tail_intercept.is_finite() && tail_slope.is_finite() && tail_slope > 0.0 {
                let mut projected: Vec<Vec<&Peak>> = Vec::new();
                for step_index in 0..5 {
                    let predicted = tail_intercept + tail_slope * ladder_sizes[step_index];
                    let radius = match step_index {
                        0 => 260.0,
                        1 => 260.0,
                        2 => 285.0,
                        3 => 310.0,
                        _ => 360.0,
                    };
                    let mut candidates = peak_features
                        .iter()
                        .filter(|peak| {
                            peak.index >= 1400
                                && peak.index + 18 < best.indices[5]
                                && ((peak.index as f64) - predicted).abs() <= radius
                                && plausible_start_peak(peak)
                        })
                        .collect::<Vec<_>>();
                    candidates.sort_by(|left, right| {
                        let left_distance = ((left.index as f64) - predicted).abs();
                        let right_distance = ((right.index as f64) - predicted).abs();
                        left_distance
                            .partial_cmp(&right_distance)
                            .unwrap_or(std::cmp::Ordering::Equal)
                            .then_with(|| {
                                right
                                    .score
                                    .partial_cmp(&left.score)
                                    .unwrap_or(std::cmp::Ordering::Equal)
                            })
                    });
                    candidates.truncate(8);
                    if candidates.is_empty() {
                        projected.clear();
                        break;
                    }
                    projected.push(candidates);
                }

                if projected.len() == 5 {
                    for p0 in &projected[0] {
                        for p1 in &projected[1] {
                            if p1.index <= p0.index || !(45..=210).contains(&(p1.index - p0.index))
                            {
                                continue;
                            }
                            for p2 in &projected[2] {
                                if p2.index <= p1.index || p2.index - p1.index < 45 {
                                    continue;
                                }
                                for p3 in &projected[3] {
                                    if p3.index <= p2.index || p3.index - p2.index < 45 {
                                        continue;
                                    }
                                    for p4 in &projected[4] {
                                        if p4.index <= p3.index
                                            || p4.index + 18 >= best.indices[5]
                                            || p4.index - p3.index < 80
                                        {
                                            continue;
                                        }
                                        let mut trial = best.indices.clone();
                                        trial[0] = p0.index;
                                        trial[1] = p1.index;
                                        trial[2] = p2.index;
                                        trial[3] = p3.index;
                                        trial[4] = p4.index;
                                        if !trial.windows(2).all(|window| window[1] > window[0]) {
                                            continue;
                                        }
                                        let trial_score = score_combination(
                                            &trial,
                                            ladder_sizes,
                                            ladder,
                                            peak_feature_by_index,
                                            peak_features,
                                        );
                                        let strong_win = trial_score.linear_max_abs_error_bp + 2.5
                                            < best.linear_max_abs_error_bp
                                            || trial_score.linear_mean_abs_error_bp + 1.25
                                                < best.linear_mean_abs_error_bp;
                                        let no_hard_regression = trial_score
                                            .linear_max_abs_error_bp
                                            <= best.linear_max_abs_error_bp + 0.50
                                            && trial_score.linear_mean_abs_error_bp
                                                <= best.linear_mean_abs_error_bp + 0.55
                                            && trial_score.linear_r2 + 0.0015 >= best.linear_r2;
                                        let usable_profile = trial_score.linear_max_abs_error_bp
                                            <= 28.0
                                            && trial_score.linear_mean_abs_error_bp <= 12.0
                                            && trial_score.linear_r2 >= 0.9900;
                                        if !(strong_win && no_hard_regression && usable_profile) {
                                            continue;
                                        }
                                        let should_take =
                                            if let Some(current_best) = best_trial.as_ref() {
                                                (
                                                    trial_score.linear_mean_abs_error_bp,
                                                    trial_score.linear_max_abs_error_bp,
                                                    -trial_score.linear_r2,
                                                    trial_score.blended_score,
                                                ) < (
                                                    current_best.linear_mean_abs_error_bp,
                                                    current_best.linear_max_abs_error_bp,
                                                    -current_best.linear_r2,
                                                    current_best.blended_score,
                                                )
                                            } else {
                                                true
                                            };
                                        if should_take {
                                            best_trial = Some(trial_score);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if best_trial.is_some() {
        return best_trial;
    }

    if last >= 3900 {
        let selected_start_peaks = best
            .indices
            .iter()
            .take(5)
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .collect::<Vec<_>>();
        if selected_start_peaks.len() >= 5 {
            let mut reference_heights = selected_start_peaks
                .iter()
                .skip(1)
                .map(|peak| peak.height)
                .filter(|value| value.is_finite() && *value > 0.0)
                .collect::<Vec<_>>();
            reference_heights.sort_by(|left, right| {
                left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal)
            });
            let start_family_height = reference_heights[reference_heights.len() / 2].max(1.0);
            let current_first_peak = selected_start_peaks[0];
            let first_is_height_outlier = current_first_peak.height >= 12_000.0
                || current_first_peak.height >= start_family_height * 9.0;
            if first_is_height_outlier && first < 1510 {
                let clean_start_candidate = |peak: &Peak| {
                    let height_ratio = peak.height / start_family_height;
                    plausible_start_peak(peak)
                        && height_ratio >= 0.18
                        && height_ratio <= 3.2
                        && peak.height < current_first_peak.height * 0.35
                };
                let later_candidates = peak_features
                    .iter()
                    .filter(|peak| {
                        peak.index > first + 16
                            && peak.index + 20 < best.indices[2]
                            && peak.index <= 1625
                            && clean_start_candidate(peak)
                    })
                    .collect::<Vec<_>>();
                for p0 in &later_candidates {
                    for p1 in &later_candidates {
                        if p1.index <= p0.index {
                            continue;
                        }
                        let gap = p1.index - p0.index;
                        if !(45..=135).contains(&gap) {
                            continue;
                        }
                        let mut trial = best.indices.clone();
                        trial[0] = p0.index;
                        trial[1] = p1.index;
                        if !trial.windows(2).all(|window| window[1] > window[0]) {
                            continue;
                        }
                        let trial_score = score_combination(
                            &trial,
                            ladder_sizes,
                            ladder,
                            peak_feature_by_index,
                            peak_features,
                        );
                        let visually_safe_profile = trial_score.linear_max_abs_error_bp <= 6.25
                            && trial_score.linear_mean_abs_error_bp <= 2.35
                            && trial_score.linear_r2 >= 0.99955;
                        let qc_not_materially_worse = trial_score.linear_max_abs_error_bp
                            <= best.linear_max_abs_error_bp + 1.35
                            && trial_score.linear_mean_abs_error_bp
                                <= best.linear_mean_abs_error_bp + 0.55
                            && trial_score.linear_r2 + 0.00020 >= best.linear_r2;
                        let deblob_gain = p0.height <= current_first_peak.height * 0.35
                            && p1.height <= current_first_peak.height * 0.35;
                        if !(visually_safe_profile && qc_not_materially_worse && deblob_gain) {
                            continue;
                        }
                        let should_take = if let Some(current_best) = best_trial.as_ref() {
                            (
                                trial_score.linear_mean_abs_error_bp,
                                trial_score.linear_max_abs_error_bp,
                                -trial_score.linear_r2,
                                trial_score.blended_score,
                            ) < (
                                current_best.linear_mean_abs_error_bp,
                                current_best.linear_max_abs_error_bp,
                                -current_best.linear_r2,
                                current_best.blended_score,
                            )
                        } else {
                            true
                        };
                        if should_take {
                            best_trial = Some(trial_score);
                        }
                    }
                }
            }
        }
    }

    if best_trial.is_some() {
        return best_trial;
    }

    if best.linear_max_abs_error_bp > 12.0 || best.linear_mean_abs_error_bp > 5.0 {
        if let Some((intercept, slope)) = linear_scan_model(ladder_sizes, &best.indices) {
            if intercept.is_finite() && slope.is_finite() && slope > 0.0 {
                let mut candidate_sets: Vec<Vec<usize>> = Vec::with_capacity(ladder_sizes.len());
                for (step_index, bp) in ladder_sizes.iter().copied().enumerate() {
                    let predicted = intercept + slope * bp;
                    let radius = if step_index < 5 {
                        420.0
                    } else if step_index + 4 >= ladder_sizes.len() {
                        620.0
                    } else {
                        360.0
                    };
                    let mut candidates = peak_features
                        .iter()
                        .filter(|peak| {
                            let scan = peak.index as f64;
                            scan >= GS500ROX_ABSOLUTE_TIME_MIN
                                && scan <= GS500ROX_ABSOLUTE_TIME_MAX
                                && (scan - predicted).abs() <= radius
                                && plausible_start_peak(peak)
                        })
                        .collect::<Vec<_>>();
                    candidates.sort_by(|left, right| {
                        let left_distance = ((left.index as f64) - predicted).abs();
                        let right_distance = ((right.index as f64) - predicted).abs();
                        left_distance
                            .partial_cmp(&right_distance)
                            .unwrap_or(std::cmp::Ordering::Equal)
                            .then_with(|| {
                                right
                                    .score
                                    .partial_cmp(&left.score)
                                    .unwrap_or(std::cmp::Ordering::Equal)
                            })
                    });
                    candidates.truncate(
                        if step_index < 5 || step_index + 4 >= ladder_sizes.len() {
                            10
                        } else {
                            7
                        },
                    );
                    if candidates.is_empty() {
                        candidate_sets.clear();
                        break;
                    }
                    candidate_sets.push(candidates.into_iter().map(|peak| peak.index).collect());
                }

                if candidate_sets.len() == ladder_sizes.len() {
                    let mut beams: Vec<(Vec<usize>, f64)> = vec![(Vec::new(), 0.0)];
                    for (step_index, candidates) in candidate_sets.iter().enumerate() {
                        let predicted = intercept + slope * ladder_sizes[step_index];
                        let mut next_beams = Vec::new();
                        for (prefix, prefix_cost) in &beams {
                            for candidate in candidates {
                                if let Some(previous) = prefix.last() {
                                    if *candidate <= *previous {
                                        continue;
                                    }
                                    let gap = *candidate - *previous;
                                    if gap < 18 {
                                        continue;
                                    }
                                }
                                let Some(peak) = peak_feature_by_index.get(candidate) else {
                                    continue;
                                };
                                let distance_cost =
                                    ((*candidate as f64 - predicted).abs() / 220.0).min(4.0);
                                let strength_reward = (peak.score.max(1.0).ln() / 12.0).min(0.8);
                                let mut next_prefix = prefix.clone();
                                next_prefix.push(*candidate);
                                next_beams.push((
                                    next_prefix,
                                    prefix_cost + distance_cost - strength_reward,
                                ));
                            }
                        }
                        next_beams.sort_by(|left, right| {
                            left.1
                                .partial_cmp(&right.1)
                                .unwrap_or(std::cmp::Ordering::Equal)
                        });
                        next_beams.truncate(192);
                        beams = next_beams;
                        if beams.is_empty() {
                            break;
                        }
                    }

                    for (candidate_indices, _) in beams {
                        if candidate_indices.len() != ladder_sizes.len() {
                            continue;
                        }
                        let trial_score = score_combination(
                            &candidate_indices,
                            ladder_sizes,
                            ladder,
                            peak_feature_by_index,
                            peak_features,
                        );
                        let strong_win = trial_score.linear_max_abs_error_bp + 4.0
                            < best.linear_max_abs_error_bp
                            || trial_score.linear_mean_abs_error_bp + 2.0
                                < best.linear_mean_abs_error_bp;
                        let usable_profile = trial_score.linear_max_abs_error_bp <= 18.0
                            && trial_score.linear_mean_abs_error_bp <= 7.5
                            && trial_score.linear_r2 >= 0.9960;
                        let no_extreme_regression = trial_score.linear_max_abs_error_bp
                            <= best.linear_max_abs_error_bp + 0.50
                            && trial_score.linear_r2 + 0.0015 >= best.linear_r2;
                        if !(strong_win && usable_profile && no_extreme_regression) {
                            continue;
                        }
                        let should_take = if let Some(current_best) = best_trial.as_ref() {
                            (
                                trial_score.linear_mean_abs_error_bp,
                                trial_score.linear_max_abs_error_bp,
                                -trial_score.linear_r2,
                                trial_score.blended_score,
                            ) < (
                                current_best.linear_mean_abs_error_bp,
                                current_best.linear_max_abs_error_bp,
                                -current_best.linear_r2,
                                current_best.blended_score,
                            )
                        } else {
                            true
                        };
                        if should_take {
                            best_trial = Some(trial_score);
                        }
                    }
                }
            }
        }
    }

    if best_trial.is_some() {
        return best_trial;
    }

    if last < 3900 {
        return None;
    }

    let lower_bound = first
        .saturating_sub(140)
        .max((GS500ROX_PREFERRED_TIME_MIN - 40.0) as usize);
    let upper_bound = second.saturating_sub(60);
    if lower_bound >= upper_bound {
        return None;
    }

    let current_first_peak = peak_feature_by_index.get(&first);
    for candidate in peak_features.iter().filter(|peak| {
        if peak.index < lower_bound || peak.index > upper_bound || peak.index >= first {
            return false;
        }
        let first_gap = second.saturating_sub(peak.index) as f64;
        if !(55.0..=115.0).contains(&first_gap) {
            return false;
        }
        plausible_start_peak(peak)
    }) {
        let current_to_candidate_score_ratio = current_first_peak
            .map(|current| current.score / candidate.score.max(1.0))
            .unwrap_or(1.0);
        if current_to_candidate_score_ratio > 85.0 && candidate.prominence < 50.0 {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[0] = candidate.index;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let material_linear_win = trial_score.linear_max_abs_error_bp + 0.45
            < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.05
            && trial_score.linear_r2 + 0.00002 >= best.linear_r2;
        let safe_profile = trial_score.linear_max_abs_error_bp <= 4.75
            && trial_score.linear_mean_abs_error_bp <= 1.90
            && trial_score.linear_r2 >= 0.99975;
        if !(material_linear_win && safe_profile) {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_mean_abs_error_bp,
                trial_score.linear_max_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_mean_abs_error_bp,
                current_best.linear_max_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_tail_outlier_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 6
    {
        return None;
    }

    let tail_selected = best
        .indices
        .iter()
        .rev()
        .take(5)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if tail_selected.len() < 5 {
        return None;
    }

    let endpoint = tail_selected[0];
    let tail_ref_scores = tail_selected
        .iter()
        .skip(1)
        .map(|peak| peak.score)
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let tail_ref_heights = tail_selected
        .iter()
        .skip(1)
        .map(|peak| peak.height)
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if tail_ref_scores.is_empty() || tail_ref_heights.is_empty() {
        return None;
    }

    let score_ref = median(&tail_ref_scores).max(1.0);
    let height_ref = median(&tail_ref_heights).max(1.0);
    let endpoint_is_weak = endpoint.score < score_ref * 0.25 || endpoint.height < height_ref * 0.25;
    if !endpoint_is_weak {
        return None;
    }

    let left_bound = best.indices[best.indices.len() - 5];
    let right_bound = *best.indices.last().unwrap_or(&left_bound);
    let mut best_trial: Option<CombinationScore> = None;
    let (best_linear_mean, best_linear_max, _) =
        linear_trend_residual_metrics(ladder_sizes, &best.indices);
    let best_plausibility = peak_plausibility_penalty(&best.indices, peak_feature_by_index);

    // First try the simplest repair: replace the weak tail endpoint itself.
    for candidate in peak_features.iter().filter(|peak| {
        !best.indices.contains(&peak.index)
            && peak.index > left_bound.saturating_add(12)
            && peak.index + 12 < right_bound
            && peak.score >= score_ref * 0.55
    }) {
        let mut trial = best.indices.clone();
        if let Some(last) = trial.last_mut() {
            *last = candidate.index;
        }
        trial.sort_unstable();
        trial.dedup();
        if trial.len() != best.indices.len() {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let (trial_linear_mean, trial_linear_max, _) =
            linear_trend_residual_metrics(ladder_sizes, &trial);
        let trial_plausibility = peak_plausibility_penalty(&trial, peak_feature_by_index);

        let clearly_better = (trial_linear_max + 1.0 < best_linear_max
            && trial_score.curvature_score <= best.curvature_score + 0.10
            && trial_plausibility <= best_plausibility + 0.15)
            || (trial_linear_mean + 0.40 < best_linear_mean
                && trial_score.curvature_score + 0.05 < best.curvature_score
                && trial_plausibility <= best_plausibility + 0.15);

        if !clearly_better {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            let (current_linear_mean, current_linear_max, _) =
                linear_trend_residual_metrics(ladder_sizes, &current_best.indices);
            let current_plausibility =
                peak_plausibility_penalty(&current_best.indices, peak_feature_by_index);
            (
                trial_linear_max,
                trial_linear_mean,
                trial_score.curvature_score,
                trial_plausibility,
                trial_score.blended_score,
            ) < (
                current_linear_max,
                current_linear_mean,
                current_best.curvature_score,
                current_plausibility,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    for candidate in peak_features.iter().filter(|peak| {
        !best.indices.contains(&peak.index)
            && peak.index > left_bound.saturating_add(12)
            && peak.index + 12 < right_bound
            && peak.score >= score_ref * 0.55
    }) {
        for replace_idx in best.indices.len().saturating_sub(4)..best.indices.len() {
            let mut trial = best.indices.clone();
            trial[replace_idx] = candidate.index;
            trial.sort_unstable();
            trial.dedup();
            if trial.len() != best.indices.len() {
                continue;
            }

            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            let (trial_linear_mean, trial_linear_max, _) =
                linear_trend_residual_metrics(ladder_sizes, &trial);
            let trial_plausibility = peak_plausibility_penalty(&trial, peak_feature_by_index);

            let clearly_better = (trial_linear_max + 1.0 < best_linear_max
                && trial_score.curvature_score <= best.curvature_score + 0.10
                && trial_plausibility <= best_plausibility + 0.15)
                || (trial_linear_mean + 0.40 < best_linear_mean
                    && trial_score.curvature_score + 0.05 < best.curvature_score
                    && trial_plausibility <= best_plausibility + 0.15);

            if !clearly_better {
                continue;
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                let (current_linear_mean, current_linear_max, _) =
                    linear_trend_residual_metrics(ladder_sizes, &current_best.indices);
                let current_plausibility =
                    peak_plausibility_penalty(&current_best.indices, peak_feature_by_index);
                (
                    trial_linear_max,
                    trial_linear_mean,
                    trial_score.curvature_score,
                    trial_plausibility,
                    trial_score.blended_score,
                ) < (
                    current_linear_max,
                    current_linear_mean,
                    current_best.curvature_score,
                    current_plausibility,
                    current_best.blended_score,
                )
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }
    best_trial
}

fn repair_rox_tail_family_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 8
    {
        return None;
    }

    let tail_block = &best.indices[best.indices.len().saturating_sub(4)..];
    let cramped_tail = tail_block
        .windows(2)
        .any(|w| w[1].saturating_sub(w[0]) < 35);
    let tail_selected = best
        .indices
        .iter()
        .rev()
        .take(6)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if tail_selected.len() < 6 {
        return None;
    }
    let tail_ref_scores = tail_selected
        .iter()
        .skip(2)
        .map(|peak| peak.score)
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let tail_ref_heights = tail_selected
        .iter()
        .skip(2)
        .map(|peak| peak.height)
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if tail_ref_scores.is_empty() || tail_ref_heights.is_empty() {
        return None;
    }
    let score_ref = median(&tail_ref_scores).max(1.0);
    let height_ref = median(&tail_ref_heights).max(1.0);
    let weak_tail_members = tail_selected
        .iter()
        .take(4)
        .filter(|peak| peak.score < score_ref * 0.35 || peak.height < height_ref * 0.35)
        .count();
    if !cramped_tail && weak_tail_members < 2 {
        return None;
    }

    let left_bound = best.indices[best.indices.len() - 6];
    let right_bound = best.indices[best.indices.len() - 1].saturating_add(80);
    let late_tail_floor = best.indices[best.indices.len() - 1].saturating_sub(36);
    let mut tail_candidates = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 2.0);
            let is_late_tail = peak.index >= late_tail_floor;
            let score_floor = if is_late_tail {
                score_ref * 0.12
            } else {
                score_ref * 0.18
            };
            let height_floor = if is_late_tail {
                height_ref * 0.08
            } else {
                height_ref * 0.18
            };
            let prominence_floor = if is_late_tail { 70.0 } else { 90.0 };
            peak.index > left_bound.saturating_add(18)
                && peak.index <= right_bound
                && peak.score >= score_floor
                && peak.height >= height_floor
                && peak.prominence >= prominence_floor
                && baseline_ratio <= 1.1
        })
        .cloned()
        .collect::<Vec<_>>();
    if tail_candidates.len() < 4 {
        return None;
    }
    tail_candidates.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if tail_candidates.len() > 18 {
        tail_candidates.truncate(18);
    }
    tail_candidates.sort_by_key(|peak| peak.index);
    let candidate_indices = tail_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let mut best_trial: Option<CombinationScore> = None;
    for replacement in generate_peak_combinations(&candidate_indices, 4, usize::MAX, 768) {
        let mut trial = best.indices.clone();
        let start = trial.len().saturating_sub(4);
        trial[start..].copy_from_slice(&replacement);
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let tail_gaps = trial[start..]
            .windows(2)
            .map(|w| w[1].saturating_sub(w[0]) as f64)
            .collect::<Vec<_>>();
        if tail_gaps.iter().any(|gap| *gap < 42.0 || *gap > 180.0) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let compelling = trial_score.linear_max_abs_error_bp + 0.60 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp + 0.10 < best.linear_mean_abs_error_bp
            && trial_score.linear_r2 + 0.0002 >= best.linear_r2;
        if !compelling {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_block_repair_candidates(&trial_score, current_best) == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_third_and_tail_family_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 8
    {
        return None;
    }

    let third_gap = best.indices[2].saturating_sub(best.indices[1]) as f64;
    if third_gap < 185.0 || best.linear_max_abs_error_bp < 9.0 {
        return None;
    }

    let start_ref = best
        .indices
        .iter()
        .take(6)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if start_ref.len() < 6 {
        return None;
    }
    let score_ref = median(
        &start_ref
            .iter()
            .skip(2)
            .map(|peak| peak.score)
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let height_ref = median(
        &start_ref
            .iter()
            .skip(2)
            .map(|peak| peak.height)
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let mut third_candidates = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 2.0);
            peak.index > best.indices[1].saturating_add(90)
                && peak.index < best.indices[3].saturating_sub(20)
                && peak.index <= best.indices[2].saturating_add(30)
                && peak.score >= score_ref * 0.20
                && peak.height >= height_ref * 0.20
                && peak.prominence >= 80.0
                && baseline_ratio <= 1.15
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    third_candidates.push(best.indices[2]);
    third_candidates.sort_unstable();
    third_candidates.dedup();
    if third_candidates.len() > 8 {
        third_candidates = third_candidates[third_candidates.len().saturating_sub(8)..].to_vec();
    }

    let left_bound = best.indices[best.indices.len() - 6];
    let right_bound = best.indices[best.indices.len() - 1].saturating_add(80);
    let late_tail_floor = best.indices[best.indices.len() - 1].saturating_sub(36);
    let tail_ref = best
        .indices
        .iter()
        .rev()
        .take(6)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if tail_ref.len() < 6 {
        return None;
    }
    let tail_score_ref = median(
        &tail_ref
            .iter()
            .skip(2)
            .map(|peak| peak.score)
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let tail_height_ref = median(
        &tail_ref
            .iter()
            .skip(2)
            .map(|peak| peak.height)
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let mut tail_candidates = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 2.0);
            let is_late_tail = peak.index >= late_tail_floor;
            let score_floor = if is_late_tail {
                tail_score_ref * 0.10
            } else {
                tail_score_ref * 0.18
            };
            let height_floor = if is_late_tail {
                tail_height_ref * 0.06
            } else {
                tail_height_ref * 0.18
            };
            let prominence_floor = if is_late_tail { 65.0 } else { 90.0 };
            peak.index > left_bound.saturating_add(18)
                && peak.index <= right_bound
                && peak.score >= score_floor
                && peak.height >= height_floor
                && peak.prominence >= prominence_floor
                && baseline_ratio <= 1.1
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    tail_candidates.sort_unstable();
    tail_candidates.dedup();
    if tail_candidates.len() > 20 {
        tail_candidates = tail_candidates[tail_candidates.len().saturating_sub(20)..].to_vec();
    }
    if third_candidates.is_empty() || tail_candidates.len() < 4 {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for third in third_candidates {
        for replacement in generate_peak_combinations(&tail_candidates, 4, usize::MAX, 2048) {
            let mut trial = best.indices.clone();
            trial[2] = third;
            let start = trial.len().saturating_sub(4);
            trial[start..].copy_from_slice(&replacement);
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }
            let early_gaps = [
                trial[1].saturating_sub(trial[0]) as f64,
                trial[2].saturating_sub(trial[1]) as f64,
            ];
            if early_gaps[0] < 35.0
                || early_gaps[0] > 120.0
                || early_gaps[1] < 90.0
                || early_gaps[1] > 220.0
            {
                continue;
            }
            let tail_gaps = trial[start..]
                .windows(2)
                .enumerate()
                .map(|(i, w)| (i, w[1].saturating_sub(w[0]) as f64))
                .collect::<Vec<_>>();
            if tail_gaps.iter().any(|(i, gap)| {
                if *i == tail_gaps.len().saturating_sub(1) {
                    *gap < 42.0 || *gap > 260.0
                } else {
                    *gap < 42.0 || *gap > 180.0
                }
            }) {
                continue;
            }

            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            let compelling = trial_score.linear_max_abs_error_bp + 0.80
                < best.linear_max_abs_error_bp
                && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.35
                && trial_score.linear_r2 + 0.00015 >= best.linear_r2;
            if !compelling {
                continue;
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                compare_block_repair_candidates(&trial_score, current_best)
                    == std::cmp::Ordering::Less
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_trial
}

fn repair_rox_start_pair_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 6
    {
        return None;
    }

    let third_scan = best.indices[2];
    let later_reference = best
        .indices
        .iter()
        .skip(2)
        .take(4)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if later_reference.len() < 3 {
        return None;
    }
    let score_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.score)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let height_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.height)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.prominence)
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let first_peak = peak_feature_by_index.get(&best.indices[0])?;
    let second_peak = peak_feature_by_index.get(&best.indices[1])?;
    let current_first_gap = best.indices[1].saturating_sub(best.indices[0]) as f64;
    let current_second_gap = best.indices[2].saturating_sub(best.indices[1]) as f64;
    let second_baseline_ratio =
        (second_peak.local_baseline.max(0.0) / second_peak.height.max(1.0)).clamp(0.0, 1.5);
    let first_is_outlier = first_peak.score > score_ref * 1.55
        || first_peak.prominence > prominence_ref * 1.60
        || (first_peak.local_baseline.max(0.0) / first_peak.height.max(1.0)) > 0.22
        || current_first_gap < 34.0;
    let second_is_outlier = second_peak.score > score_ref * 1.45
        || second_peak.prominence > prominence_ref * 1.45
        || second_baseline_ratio > 0.20
        || current_first_gap < 38.0
        || current_second_gap > 175.0;
    if !(first_is_outlier || second_is_outlier) {
        return None;
    }

    let mut start_candidates = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            let strong_family_candidate = peak.score >= score_ref * 0.45
                && peak.prominence >= prominence_ref * 0.45
                && peak.height >= height_ref * 0.45;
            let clean_lower_amplitude_candidate = peak.score >= score_ref * 0.18
                && peak.prominence >= prominence_ref * 0.20
                && peak.height >= height_ref * 0.18
                && peak.prominence >= 420.0
                && peak.height >= 480.0
                && baseline_ratio <= 0.10;
            peak.index >= 1560
                && peak.index + 10 < third_scan
                && (strong_family_candidate || clean_lower_amplitude_candidate)
                && baseline_ratio <= 0.18
        })
        .cloned()
        .collect::<Vec<_>>();
    if start_candidates.len() < 2 {
        return None;
    }
    start_candidates.sort_by(|left, right| {
        let left_baseline_ratio =
            (left.local_baseline.max(0.0) / left.height.max(1.0)).clamp(0.0, 1.5);
        let right_baseline_ratio =
            (right.local_baseline.max(0.0) / right.height.max(1.0)).clamp(0.0, 1.5);
        let left_rank =
            left.score + left.prominence * 0.55 + left.height * 0.15 - left_baseline_ratio * 1800.0;
        let right_rank = right.score + right.prominence * 0.55 + right.height * 0.15
            - right_baseline_ratio * 1800.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    start_candidates.truncate(18);
    let supplemental_candidates = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.5);
            let late_second_window =
                peak.index > best.indices[1].saturating_add(18) && peak.index + 12 < third_scan;
            let first_window = peak.index + 12 < best.indices[1]
                && peak.index >= best.indices[0].saturating_sub(45);
            let current_second_as_first_window = first_is_outlier
                && peak.index >= best.indices[1].saturating_sub(6)
                && peak.index <= best.indices[1].saturating_add(6)
                && peak.index + 12 < third_scan;
            (late_second_window || first_window || current_second_as_first_window)
                && peak.index >= best.indices[0].saturating_sub(45)
                && peak.index <= third_scan.saturating_sub(10)
                && baseline_ratio <= 0.22
                && purity >= 0.38
                && peak.prominence >= 45.0
                && peak.height >= 85.0
        })
        .cloned()
        .collect::<Vec<_>>();
    start_candidates.extend(supplemental_candidates);
    start_candidates.sort_by_key(|peak| peak.index);
    start_candidates.dedup_by_key(|peak| peak.index);
    start_candidates.sort_by_key(|peak| peak.index);
    let start_indices = start_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let mut best_trial: Option<CombinationScore> = None;
    let mut best_feature_trial: Option<(CombinationScore, f64)> = None;
    let current_pair_feature_penalty =
        rox_start_pair_feature_penalty(first_peak, second_peak, height_ref, prominence_ref);
    for replacement in generate_peak_combinations(&start_indices, 2, usize::MAX, 256) {
        let first_gap = replacement[1].saturating_sub(replacement[0]) as f64;
        let second_gap = third_scan.saturating_sub(replacement[1]) as f64;
        if !(40.0..=110.0).contains(&first_gap) || !(110.0..=230.0).contains(&second_gap) {
            continue;
        }
        if !first_is_outlier {
            let first_shift = replacement[0].abs_diff(best.indices[0]) as f64;
            let allow_shifted_family_first = second_is_outlier
                && replacement[0] >= best.indices[1].saturating_sub(10)
                && replacement[0] <= best.indices[1].saturating_add(10)
                && replacement[1] > best.indices[1].saturating_add(24);
            if first_shift > 34.0 && !allow_shifted_family_first {
                continue;
            }
        }

        let mut trial = best.indices.clone();
        trial[..2].copy_from_slice(&replacement);
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let material_max_win =
            trial_score.linear_max_abs_error_bp + 0.60 < best.linear_max_abs_error_bp;
        let material_mean_win =
            trial_score.linear_mean_abs_error_bp + 0.20 < best.linear_mean_abs_error_bp;
        let acceptable_mean =
            trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.50;
        let acceptable_r2 = trial_score.linear_r2 + 0.0002 >= best.linear_r2;
        let preserves_current_first =
            !first_is_outlier && replacement[0].abs_diff(best.indices[0]) as f64 <= 22.0;
        let start_family_alignment = peak_feature_by_index
            .get(&replacement[0])
            .zip(peak_feature_by_index.get(&replacement[1]))
            .map(|(first, second)| {
                let first_baseline_ratio =
                    (first.local_baseline.max(0.0) / first.height.max(1.0)).clamp(0.0, 1.5);
                let second_baseline_ratio =
                    (second.local_baseline.max(0.0) / second.height.max(1.0)).clamp(0.0, 1.5);
                first_baseline_ratio <= 0.18
                    && second_baseline_ratio <= 0.16
                    && first.score <= score_ref * 1.65
                    && second.score <= score_ref * 1.65
                    && first.prominence <= prominence_ref * 1.70
                    && second.prominence <= prominence_ref * 1.65
            })
            .unwrap_or(false);
        let compelling_second_fix =
            second_is_outlier && preserves_current_first && material_mean_win && acceptable_r2;
        let compelling_late_clean_win = replacement[1] > best.indices[1].saturating_add(24)
            && trial_score.linear_max_abs_error_bp + 1.05 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.10
            && trial_score.linear_r2 + 0.00015 >= best.linear_r2;
        let compelling_clean_pair_win = second_is_outlier
            && replacement[1] > best.indices[1].saturating_add(8)
            && first_gap >= 45.0
            && first_gap <= 100.0
            && second_gap >= 140.0
            && second_gap <= 235.0
            && trial_score.linear_max_abs_error_bp + 0.90 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.15
            && trial_score.linear_r2 + 0.00015 >= best.linear_r2
            && peak_feature_by_index
                .get(&replacement[0])
                .zip(peak_feature_by_index.get(&replacement[1]))
                .map(|(first, second)| {
                    let first_baseline_ratio =
                        (first.local_baseline.max(0.0) / first.height.max(1.0)).clamp(0.0, 1.5);
                    let second_baseline_ratio =
                        (second.local_baseline.max(0.0) / second.height.max(1.0)).clamp(0.0, 1.5);
                    let first_purity = (first.prominence / first.height.max(1.0)).clamp(0.0, 1.5);
                    let second_purity =
                        (second.prominence / second.height.max(1.0)).clamp(0.0, 1.5);
                    first_baseline_ratio <= 0.08
                        && second_baseline_ratio <= 0.10
                        && first_purity >= 0.24
                        && second_purity >= 0.20
                        && second.prominence >= 42.0
                })
                .unwrap_or(false);
        let compelling_shifted_family_win = second_is_outlier
            && replacement[0] >= best.indices[1].saturating_sub(10)
            && replacement[0] <= best.indices[1].saturating_add(10)
            && replacement[1] > best.indices[1].saturating_add(24)
            && trial_score.linear_max_abs_error_bp + 1.10 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.55
            && trial_score.linear_r2 + 0.00002 >= best.linear_r2
            && peak_feature_by_index
                .get(&replacement[0])
                .zip(peak_feature_by_index.get(&replacement[1]))
                .zip(peak_feature_by_index.get(&best.indices[2]))
                .map(|((first, second), third)| {
                    let first_baseline_ratio =
                        (first.local_baseline.max(0.0) / first.height.max(1.0)).clamp(0.0, 1.5);
                    let second_baseline_ratio =
                        (second.local_baseline.max(0.0) / second.height.max(1.0)).clamp(0.0, 1.5);
                    first_baseline_ratio <= 0.10
                        && second_baseline_ratio <= 0.10
                        && first.height >= third.height * 0.75
                        && second.height >= third.height * 0.75
                        && first.prominence >= third.prominence * 0.75
                        && second.prominence >= third.prominence * 0.70
                })
                .unwrap_or(false);
        let candidate_pair_feature_penalty = peak_feature_by_index
            .get(&replacement[0])
            .zip(peak_feature_by_index.get(&replacement[1]))
            .map(|(first, second)| {
                rox_start_pair_feature_penalty(first, second, height_ref, prominence_ref)
            })
            .unwrap_or(f64::INFINITY);
        let current_start_needs_feature_arbiter = current_pair_feature_penalty >= 1.30
            && (best.linear_max_abs_error_bp > 3.85
                || best.linear_mean_abs_error_bp > 1.25
                || current_first_gap < 38.0
                || second_baseline_ratio > 0.26);
        let feature_pair_is_compelling = current_start_needs_feature_arbiter
            && candidate_pair_feature_penalty <= 0.55
            && candidate_pair_feature_penalty + 0.75 < current_pair_feature_penalty
            && replacement[1] > best.indices[1].saturating_add(8)
            && first_gap >= 45.0
            && first_gap <= 105.0
            && second_gap >= 135.0
            && second_gap <= 235.0
            && trial_score.linear_max_abs_error_bp <= 7.35
            && trial_score.linear_mean_abs_error_bp <= 3.20
            && trial_score.linear_r2 >= 0.99880
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.98
            && trial_score.linear_max_abs_error_bp <= best.linear_max_abs_error_bp + 1.70
            && (trial_score.linear_max_abs_error_bp <= best.linear_max_abs_error_bp + 0.90
                || current_pair_feature_penalty >= 1.75);
        if !((material_max_win && acceptable_mean && acceptable_r2 && start_family_alignment)
            || (compelling_second_fix && start_family_alignment)
            || (compelling_late_clean_win && start_family_alignment)
            || compelling_clean_pair_win
            || compelling_shifted_family_win
            || feature_pair_is_compelling)
        {
            continue;
        }

        if feature_pair_is_compelling {
            let should_take_feature = if let Some((current_best, current_feature_penalty)) =
                best_feature_trial.as_ref()
            {
                (
                    candidate_pair_feature_penalty,
                    trial_score.linear_max_abs_error_bp,
                    trial_score.linear_mean_abs_error_bp,
                    -trial_score.linear_r2,
                    trial_score.blended_score,
                ) < (
                    *current_feature_penalty,
                    current_best.linear_max_abs_error_bp,
                    current_best.linear_mean_abs_error_bp,
                    -current_best.linear_r2,
                    current_best.blended_score,
                )
            } else {
                true
            };
            if should_take_feature {
                best_feature_trial = Some((trial_score.clone(), candidate_pair_feature_penalty));
            }
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_feature_trial
        .map(|(score, _feature_penalty)| score)
        .or(best_trial)
}

fn rox_start_peak_feature_penalty(peak: &Peak, height_ref: f64, prominence_ref: f64) -> f64 {
    let height = peak.height.max(1.0);
    let prominence = peak.prominence.max(0.0);
    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
    let purity = (prominence / height).clamp(0.0, 1.5);
    let height_ratio = height / height_ref.max(1.0);
    let prominence_ratio = prominence / prominence_ref.max(1.0);
    let weak = ((0.40 - height_ratio.min(prominence_ratio)).max(0.0) / 0.40) * 1.20;
    let huge = ((height_ratio.max(prominence_ratio) - 7.0).max(0.0) / 7.0) * 0.80;
    let baseline_like = ((baseline_ratio - 0.12).max(0.0) / 0.18) * 1.10;
    let low_purity = ((0.55 - purity).max(0.0) / 0.55) * 0.80;
    weak + huge + baseline_like + low_purity
}

fn rox_start_pair_feature_penalty(
    first: &Peak,
    second: &Peak,
    height_ref: f64,
    prominence_ref: f64,
) -> f64 {
    rox_start_peak_feature_penalty(first, height_ref, prominence_ref)
        + rox_start_peak_feature_penalty(second, height_ref, prominence_ref)
}

fn repair_rox_start_pair_feature_arbiter_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 6
    {
        return None;
    }

    let later_reference = best
        .indices
        .iter()
        .skip(2)
        .take(4)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if later_reference.len() < 3 {
        return None;
    }
    let height_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.height)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.prominence)
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let Some(first_peak) = peak_feature_by_index.get(&best.indices[0]) else {
        return None;
    };
    let current_second_peak = peak_feature_by_index.get(&best.indices[1]);
    let current_pair_feature_penalty = current_second_peak
        .map(|second_peak| {
            rox_start_pair_feature_penalty(first_peak, second_peak, height_ref, prominence_ref)
        })
        .unwrap_or(2.50);
    let current_first_gap = best.indices[1].saturating_sub(best.indices[0]) as f64;
    let current_start_is_suspicious = current_pair_feature_penalty >= 1.30
        && (best.linear_max_abs_error_bp > 3.85
            || best.linear_mean_abs_error_bp > 1.25
            || current_first_gap < 38.0);
    if !current_start_is_suspicious {
        return None;
    }

    let third_scan = best.indices[2];
    let left_bound = best.indices[1].saturating_sub(35).max(1450);
    let right_bound = third_scan.saturating_sub(10);
    let candidates = peak_features
        .iter()
        .filter(|peak| peak.index >= left_bound && peak.index <= right_bound)
        .collect::<Vec<_>>();
    let mut best_trial: Option<(CombinationScore, f64)> = None;
    for first_pos in 0..candidates.len() {
        for second_pos in (first_pos + 1)..candidates.len() {
            let first = candidates[first_pos];
            let second = candidates[second_pos];
            let first_gap = second.index.saturating_sub(first.index) as f64;
            let second_gap = third_scan.saturating_sub(second.index) as f64;
            if !(45.0..=105.0).contains(&first_gap) || !(135.0..=235.0).contains(&second_gap) {
                continue;
            }
            if second.index <= best.indices[1].saturating_add(8) {
                continue;
            }
            let feature_penalty =
                rox_start_pair_feature_penalty(first, second, height_ref, prominence_ref);
            if feature_penalty > 0.08 || feature_penalty + 0.75 >= current_pair_feature_penalty {
                continue;
            }

            let mut trial = best.indices.clone();
            trial[0] = first.index;
            trial[1] = second.index;
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }
            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            if trial_score.linear_max_abs_error_bp > 7.35
                || trial_score.linear_mean_abs_error_bp > 3.20
                || trial_score.linear_r2 < 0.99875
                || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 1.05
                || trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 2.60
            {
                continue;
            }
            let should_take =
                if let Some((current_best, current_feature_penalty)) = best_trial.as_ref() {
                    (
                        feature_penalty,
                        trial_score.linear_max_abs_error_bp,
                        trial_score.linear_mean_abs_error_bp,
                        -trial_score.linear_r2,
                    ) < (
                        *current_feature_penalty,
                        current_best.linear_max_abs_error_bp,
                        current_best.linear_mean_abs_error_bp,
                        -current_best.linear_r2,
                    )
                } else {
                    true
                };
            if should_take {
                best_trial = Some((trial_score, feature_penalty));
            }
        }
    }

    best_trial.map(|(score, _)| score)
}

fn repair_rox_nonlinear_start_pair_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 6
    {
        return None;
    }

    let third_scan = best.indices[2];
    let current_gap23 = third_scan.saturating_sub(best.indices[1]) as f64;
    let (_current_d2_mean, current_d2_max, _current_d2_r2) =
        bp_trend_metrics_for_score(best, ladder_sizes, 2);
    let (_current_d3_mean, current_d3_max, _current_d3_r2) =
        bp_trend_metrics_for_score(best, ladder_sizes, 3);
    if current_gap23 <= 260.0 && current_d2_max <= 4.0 && current_d3_max <= 2.5 {
        return None;
    }

    let left_bound = best.indices[0].saturating_sub(320).max(1250);
    let right_bound = third_scan.saturating_sub(8);
    let mut start_candidates = peak_features
        .iter()
        .filter(|peak| peak.index >= left_bound && peak.index <= right_bound)
        .cloned()
        .collect::<Vec<_>>();
    if start_candidates.len() < 2 {
        return None;
    }
    start_candidates.sort_by_key(|peak| peak.index);
    start_candidates.dedup_by_key(|peak| peak.index);

    let mut best_trial: Option<(CombinationScore, f64, f64)> = None;
    for first_pos in 0..start_candidates.len() {
        for second_pos in (first_pos + 1)..start_candidates.len() {
            let first = &start_candidates[first_pos];
            let second = &start_candidates[second_pos];
            let first_gap = second.index.saturating_sub(first.index) as f64;
            let second_gap = third_scan.saturating_sub(second.index) as f64;
            if !(35.0..=115.0).contains(&first_gap) || !(130.0..=240.0).contains(&second_gap) {
                continue;
            }
            if second_gap + 40.0 >= current_gap23 {
                continue;
            }

            let mut trial = best.indices.clone();
            trial[0] = first.index;
            trial[1] = second.index;
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }
            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            if !rox_nonlinear_start_pair_candidate_can_override(best, &trial_score, ladder_sizes) {
                continue;
            }
            let (_d3_mean, d3_max, _d3_r2) =
                bp_trend_metrics_for_score(&trial_score, ladder_sizes, 3);
            let (_d2_mean, d2_max, _d2_r2) =
                bp_trend_metrics_for_score(&trial_score, ladder_sizes, 2);
            let should_take =
                if let Some((current_best, current_d3_max, current_d2_max)) = best_trial.as_ref() {
                    (
                        d3_max,
                        d2_max,
                        trial_score.linear_max_abs_error_bp,
                        trial_score.linear_mean_abs_error_bp,
                        trial_score.blended_score,
                    ) < (
                        *current_d3_max,
                        *current_d2_max,
                        current_best.linear_max_abs_error_bp,
                        current_best.linear_mean_abs_error_bp,
                        current_best.blended_score,
                    )
                } else {
                    true
                };
            if should_take {
                best_trial = Some((trial_score, d3_max, d2_max));
            }
        }
    }

    best_trial.map(|(score, _d3_max, _d2_max)| score)
}

fn repair_rox_first_three_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 8
    {
        return None;
    }

    let later_pairs = ladder_sizes
        .iter()
        .zip(best.indices.iter())
        .skip(3)
        .take(6)
        .map(|(bp, scan)| (*bp, *scan as f64))
        .collect::<Vec<_>>();
    if later_pairs.len() < 4 {
        return None;
    }

    let n = later_pairs.len() as f64;
    let sum_x = later_pairs.iter().map(|(x, _)| *x).sum::<f64>();
    let sum_y = later_pairs.iter().map(|(_, y)| *y).sum::<f64>();
    let mean_x = sum_x / n;
    let mean_y = sum_y / n;
    let sxx = later_pairs
        .iter()
        .map(|(x, _)| {
            let dx = *x - mean_x;
            dx * dx
        })
        .sum::<f64>();
    if sxx <= f64::EPSILON {
        return None;
    }
    let sxy = later_pairs
        .iter()
        .map(|(x, y)| (*x - mean_x) * (*y - mean_y))
        .sum::<f64>();
    let slope = sxy / sxx;
    if !slope.is_finite() || slope <= 0.0 {
        return None;
    }
    let intercept = mean_y - slope * mean_x;
    let current_gap_90_100 = best.indices[3].saturating_sub(best.indices[2]) as f64;
    let current_gap_100_120 = best.indices[4].saturating_sub(best.indices[3]) as f64;
    let current_has_collapsed_90_100 = current_gap_90_100 <= 42.0 && current_gap_100_120 >= 120.0;
    let predicted = ladder_sizes
        .iter()
        .take(3)
        .map(|bp| slope * *bp + intercept)
        .collect::<Vec<_>>();

    let later_reference = best
        .indices
        .iter()
        .skip(3)
        .take(5)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if later_reference.len() < 3 {
        return None;
    }
    let height_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.height)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.prominence)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let width_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.width)
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let mut candidate_sets: Vec<Vec<usize>> = Vec::new();
    let windows = [75.0, 75.0, 90.0];
    for (target, window) in predicted.iter().zip(windows.iter()) {
        let mut candidates = peak_features
            .iter()
            .filter(|peak| {
                let baseline_ratio =
                    (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                let height_ratio = peak.height / height_ref.max(1.0);
                let prominence_ratio = peak.prominence / prominence_ref.max(1.0);
                let width_ratio = peak.width / width_ref.max(1.0);
                (peak.index as f64 - *target).abs() <= *window
                    && peak.index + 10 < best.indices[3]
                    && baseline_ratio <= 0.30
                    && peak.prominence >= 28.0
                    && peak.height >= 32.0
                    && height_ratio >= 0.10
                    && prominence_ratio >= 0.10
                    && width_ratio >= 0.35
                    && width_ratio <= 2.4
            })
            .map(|peak| peak.index)
            .collect::<Vec<_>>();
        let current_scan = best.indices[candidate_sets.len()];
        if !candidates.contains(&current_scan) {
            candidates.push(current_scan);
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.is_empty() {
            return None;
        }
        candidate_sets.push(candidates);
    }

    let mut best_trial: Option<CombinationScore> = None;
    for first in &candidate_sets[0] {
        for second in &candidate_sets[1] {
            for third in &candidate_sets[2] {
                if !(*first < *second && *second < *third && *third < best.indices[3]) {
                    continue;
                }
                let gap1 = (*second as f64 - *first as f64).abs();
                let gap2 = (*third as f64 - *second as f64).abs();
                let gap3 = (best.indices[3] as f64 - *third as f64).abs();
                if !(35.0..=110.0).contains(&gap1)
                    || !(90.0..=220.0).contains(&gap2)
                    || !(35.0..=120.0).contains(&gap3)
                {
                    continue;
                }

                let mut trial = best.indices.clone();
                trial[0] = *first;
                trial[1] = *second;
                trial[2] = *third;
                if !trial.windows(2).all(|w| w[1] > w[0]) {
                    continue;
                }

                let trial_score = score_combination(
                    &trial,
                    ladder_sizes,
                    ladder,
                    peak_feature_by_index,
                    peak_features,
                );
                let strong_linear_win = trial_score.linear_max_abs_error_bp + 0.75
                    < best.linear_max_abs_error_bp
                    || (trial_score.linear_max_abs_error_bp + 0.35 < best.linear_max_abs_error_bp
                        && trial_score.linear_mean_abs_error_bp + 0.20
                            < best.linear_mean_abs_error_bp);
                let collapsed_gap_cleanup = current_has_collapsed_90_100
                    && trial_score.linear_max_abs_error_bp + 0.45 < best.linear_max_abs_error_bp
                    && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.05
                    && gap3 >= 48.0
                    && gap3 <= 72.0;
                let acceptable_r2 = trial_score.linear_r2 + 0.00015 >= best.linear_r2;
                if !((strong_linear_win || collapsed_gap_cleanup) && acceptable_r2) {
                    continue;
                }

                let should_take = if let Some(current_best) = best_trial.as_ref() {
                    (
                        trial_score.linear_max_abs_error_bp,
                        trial_score.linear_mean_abs_error_bp,
                        -trial_score.linear_r2,
                        trial_score.blended_score,
                    ) < (
                        current_best.linear_max_abs_error_bp,
                        current_best.linear_mean_abs_error_bp,
                        -current_best.linear_r2,
                        current_best.blended_score,
                    )
                } else {
                    true
                };
                if should_take {
                    best_trial = Some(trial_score);
                }
            }
        }
    }

    best_trial
}

fn repair_rox_collapsed_100_anchor_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 8
    {
        return None;
    }

    let current_gap_90_100 = best.indices[3].saturating_sub(best.indices[2]) as f64;
    let current_gap_100_120 = best.indices[4].saturating_sub(best.indices[3]) as f64;
    if current_gap_90_100 > 42.0 || current_gap_100_120 < 120.0 {
        return None;
    }

    let family_reference = best
        .indices
        .iter()
        .skip(4)
        .take(6)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if family_reference.len() < 4 {
        return None;
    }
    let height_ref = median(
        &family_reference
            .iter()
            .map(|peak| peak.height)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &family_reference
            .iter()
            .map(|peak| peak.prominence)
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let mut best_trial: Option<CombinationScore> = None;
    for peak in peak_features {
        if peak.index <= best.indices[2].saturating_add(46)
            || peak.index >= best.indices[4].saturating_sub(34)
            || peak.index == best.indices[3]
        {
            continue;
        }
        let gap_90_100 = peak.index.saturating_sub(best.indices[2]) as f64;
        let gap_100_120 = best.indices[4].saturating_sub(peak.index) as f64;
        if !(48.0..=72.0).contains(&gap_90_100) || !(92.0..=128.0).contains(&gap_100_120) {
            continue;
        }

        let baseline_ratio = (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
        if baseline_ratio > 0.34
            || purity < 0.48
            || peak.height < 40.0
            || peak.prominence < 32.0
            || peak.height < height_ref * 0.08
            || peak.prominence < prominence_ref * 0.08
        {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[3] = peak.index;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let useful_minor_gain = trial_score.linear_max_abs_error_bp + 0.45
            < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.08
            && trial_score.linear_r2 + 0.00015 >= best.linear_r2;
        if !useful_minor_gain {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_collapsed_150_anchor_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 9
    {
        return None;
    }

    let current_gap_120_150 = best.indices[5].saturating_sub(best.indices[4]) as f64;
    let current_gap_150_160 = best.indices[6].saturating_sub(best.indices[5]) as f64;
    if current_gap_120_150 > 156.0 || current_gap_150_160 < 70.0 {
        return None;
    }

    let family_reference = best
        .indices
        .iter()
        .skip(6)
        .take(7)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if family_reference.len() < 4 {
        return None;
    }
    let height_ref = median(
        &family_reference
            .iter()
            .map(|peak| peak.height)
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &family_reference
            .iter()
            .map(|peak| peak.prominence)
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let mut best_trial: Option<CombinationScore> = None;
    for peak in peak_features {
        if peak.index <= best.indices[4].saturating_add(150)
            || peak.index >= best.indices[6].saturating_sub(42)
            || peak.index == best.indices[5]
            || peak.index <= best.indices[5]
        {
            continue;
        }
        let gap_120_150 = peak.index.saturating_sub(best.indices[4]) as f64;
        let gap_150_160 = best.indices[6].saturating_sub(peak.index) as f64;
        if !(158.0..=186.0).contains(&gap_120_150) || !(48.0..=68.0).contains(&gap_150_160) {
            continue;
        }

        let baseline_ratio = (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
        if baseline_ratio > 0.34
            || purity < 0.48
            || peak.height < 40.0
            || peak.prominence < 32.0
            || peak.height < height_ref * 0.08
            || peak.prominence < prominence_ref * 0.08
        {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[5] = peak.index;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let useful_minor_gain = trial_score.linear_max_abs_error_bp + 0.42
            < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.08
            && trial_score.linear_r2 + 0.00015 >= best.linear_r2;
        if !useful_minor_gain {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_large_50_60_gap_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 4
    {
        return None;
    }

    let first = best.indices[0];
    let second = best.indices[1];
    let third = best.indices[2];
    let gap_50_60 = second.saturating_sub(first);
    if !(82..=125).contains(&gap_50_60) || third <= second {
        return None;
    }
    if best.linear_max_abs_error_bp <= 2.5 && best.linear_mean_abs_error_bp <= 1.0 {
        return None;
    }

    let first_peak = peak_feature_by_index.get(&first)?;
    let first_height = first_peak.height.max(1.0);
    let mut best_trial: Option<CombinationScore> = None;
    for peak in peak_features {
        if peak.index <= first.saturating_add(34)
            || peak.index >= second.saturating_sub(8)
            || peak.index >= third.saturating_sub(70)
        {
            continue;
        }
        let new_gap = peak.index.saturating_sub(first);
        if !(43..=76).contains(&new_gap) {
            continue;
        }

        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        let height_ratio = (height / first_height).clamp(0.0, 10.0);
        if height < 80.0
            || peak.prominence < 55.0
            || baseline_ratio > 0.45
            || purity < 0.50
            || height_ratio < 0.35
        {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[1] = peak.index;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp + 0.35 >= best.linear_max_abs_error_bp
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.15
            || trial_score.linear_r2 + 0.00008 < best.linear_r2
        {
            continue;
        }
        if trial_score.linear_max_abs_error_bp > 3.6
            && trial_score.linear_max_abs_error_bp + 1.0 >= best.linear_max_abs_error_bp
        {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_large_100_120_gap_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 7
    {
        return None;
    }

    let gap_100_120 = best.indices[4].saturating_sub(best.indices[3]);
    let gap_120_150 = best.indices[5].saturating_sub(best.indices[4]);
    if gap_100_120 < 130 || gap_120_150 > 145 {
        return None;
    }

    let current_peak = peak_feature_by_index.get(&best.indices[4])?;
    let mut best_trial: Option<CombinationScore> = None;
    for peak in peak_features {
        if peak.index < best.indices[3].saturating_add(75)
            || peak.index > best.indices[4].saturating_sub(12)
            || peak.index >= best.indices[5].saturating_sub(100)
        {
            continue;
        }
        let new_gap_100_120 = peak.index.saturating_sub(best.indices[3]);
        let new_gap_120_150 = best.indices[5].saturating_sub(peak.index);
        if !(95..=118).contains(&new_gap_100_120) || !(150..=180).contains(&new_gap_120_150) {
            continue;
        }

        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        if height < 80.0
            || peak.prominence < 55.0
            || baseline_ratio > 0.45
            || purity < 0.50
            || height < current_peak.height.max(1.0) * 1.25
        {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[4] = peak.index;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp + 0.25 >= best.linear_max_abs_error_bp
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.10
            || trial_score.linear_r2 + 0.00008 < best.linear_r2
        {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_start_prefix_pair_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 4
    {
        return None;
    }

    let gap_50_60 = best.indices[1].saturating_sub(best.indices[0]);
    let gap_60_90 = best.indices[2].saturating_sub(best.indices[1]);
    if gap_60_90 < 185 && (45..=82).contains(&gap_50_60) {
        return None;
    }
    let current_first = peak_feature_by_index.get(&best.indices[0])?;
    let current_second = peak_feature_by_index.get(&best.indices[1])?;
    let peak_quality = |peak: &Peak| {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        let bad = baseline_ratio >= 0.30 || purity <= 0.65 || height < 250.0;
        (height, baseline_ratio, purity, bad)
    };
    let (current_first_height, current_first_baseline, _current_first_purity, current_first_bad) =
        peak_quality(current_first);
    let (
        current_second_height,
        current_second_baseline,
        _current_second_purity,
        current_second_bad,
    ) = peak_quality(current_second);
    let current_bad = usize::from(current_first_bad) + usize::from(current_second_bad);
    let current_strength = current_first_height + current_second_height;
    let current_baseline = current_first_baseline + current_second_baseline;
    let current_curvature = curvature_score(ladder_sizes, &best.indices);

    let mut prefix = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
            peak.index >= best.indices[0].saturating_sub(80)
                && peak.index <= best.indices[2].saturating_sub(45)
                && height >= 80.0
                && peak.prominence >= 55.0
                && baseline_ratio <= 0.50
                && purity >= 0.50
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    prefix.sort_unstable();
    prefix.dedup();
    if prefix.len() < 2 || prefix.len() > 14 {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for pair in generate_peak_combinations(&prefix, 2, usize::MAX, 128) {
        let first = pair[0];
        let second = pair[1];
        if !(35..=75).contains(&second.saturating_sub(first))
            || second >= best.indices[2].saturating_sub(90)
        {
            continue;
        }
        if first == best.indices[0] && second == best.indices[1] {
            continue;
        }
        let Some(first_peak) = peak_feature_by_index.get(&first) else {
            continue;
        };
        let Some(second_peak) = peak_feature_by_index.get(&second) else {
            continue;
        };
        let (first_height, first_baseline, _first_purity, first_bad) = peak_quality(first_peak);
        let (second_height, second_baseline, _second_purity, second_bad) =
            peak_quality(second_peak);
        let candidate_bad = usize::from(first_bad) + usize::from(second_bad);
        if candidate_bad > current_bad {
            continue;
        }
        let candidate_strength = first_height + second_height;
        let candidate_baseline = first_baseline + second_baseline;
        let better_peaks = candidate_bad < current_bad
            || candidate_strength > current_strength * 2.20
            || candidate_baseline + 0.30 < current_baseline;
        if !better_peaks {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[0] = first;
        trial[1] = second;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp >= 8.0
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.55
            || trial_score.linear_r2 + 0.00035 < best.linear_r2
        {
            continue;
        }
        if trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 0.02
            && trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.05
        {
            continue;
        }
        if current_bad == 0
            && trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.05
        {
            continue;
        }
        let trial_curvature = curvature_score(ladder_sizes, &trial_score.indices);
        if trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 0.10 {
            if trial_curvature + 0.0005 >= current_curvature {
                continue;
            }
        } else if trial_curvature > current_curvature + 0.0020 {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                curvature_score(ladder_sizes, &trial_score.indices),
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                curvature_score(ladder_sizes, &current_best.indices),
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_minor_start_triple_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 5
    {
        return None;
    }

    let gap_50_60 = best.indices[1].saturating_sub(best.indices[0]);
    let gap_60_90 = best.indices[2].saturating_sub(best.indices[1]);
    let gap_90_100 = best.indices[3].saturating_sub(best.indices[2]);
    if gap_60_90 < 190 && gap_50_60 < 80 {
        return None;
    }
    if best.linear_max_abs_error_bp >= 8.0 || best.linear_mean_abs_error_bp >= 3.0 {
        return None;
    }

    let clean_peak = |peak: &Peak| {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        height >= 60.0 && peak.prominence >= 45.0 && baseline_ratio <= 0.55 && purity >= 0.45
    };

    let mut prefix = peak_features
        .iter()
        .filter(|peak| {
            peak.index >= best.indices[0].saturating_sub(180)
                && peak.index <= best.indices[3].saturating_sub(40)
                && clean_peak(peak)
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    prefix.sort_unstable();
    prefix.dedup();
    if prefix.len() < 3 || prefix.len() > 80 {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for (first_pos, first) in prefix.iter().copied().enumerate() {
        for (second_pos, second) in prefix.iter().copied().enumerate().skip(first_pos + 1) {
            let candidate_gap_50_60 = second.saturating_sub(first);
            if !(45..=65).contains(&candidate_gap_50_60) {
                continue;
            }
            for third in prefix.iter().copied().skip(second_pos + 1) {
                let candidate_gap_60_90 = third.saturating_sub(second);
                let candidate_gap_90_100 = best.indices[3].saturating_sub(third);
                let allow_wide_60_90_with_clean_90_100 = gap_60_90 > 190
                    && (179..=205).contains(&candidate_gap_60_90)
                    && (45..=75).contains(&candidate_gap_90_100);
                if !(45..=65).contains(&candidate_gap_50_60)
                    || (!(150..=178).contains(&candidate_gap_60_90)
                        && !allow_wide_60_90_with_clean_90_100)
                    || !(45..=75).contains(&candidate_gap_90_100)
                {
                    continue;
                }
                if first == best.indices[0] && second == best.indices[1] && third == best.indices[2]
                {
                    continue;
                }

                let normalizes_start = (gap_60_90 > 188 && candidate_gap_60_90 + 18 < gap_60_90)
                    || (gap_50_60 > 78 && candidate_gap_50_60 + 18 < gap_50_60)
                    || (gap_90_100 > 78 && candidate_gap_90_100 + 10 < gap_90_100);
                if !normalizes_start {
                    continue;
                }

                let mut trial = best.indices.clone();
                trial[0] = first;
                trial[1] = second;
                trial[2] = third;
                if !trial.windows(2).all(|window| window[1] > window[0]) {
                    continue;
                }
                let trial_score = score_combination(
                    &trial,
                    ladder_sizes,
                    ladder,
                    peak_feature_by_index,
                    peak_features,
                );
                if trial_score.linear_max_abs_error_bp >= 8.0
                    || trial_score.linear_mean_abs_error_bp > 2.25
                {
                    continue;
                }

                let should_take = if let Some(current_best) = best_trial.as_ref() {
                    (
                        trial_score.linear_max_abs_error_bp,
                        trial_score.linear_mean_abs_error_bp,
                        -trial_score.linear_r2,
                        trial_score.peak_penalty,
                        trial_score.blended_score,
                    ) < (
                        current_best.linear_max_abs_error_bp,
                        current_best.linear_mean_abs_error_bp,
                        -current_best.linear_r2,
                        current_best.peak_penalty,
                        current_best.blended_score,
                    )
                } else {
                    true
                };
                if should_take {
                    best_trial = Some(trial_score);
                }
            }
        }
    }

    best_trial
}

fn repair_rox_visual_start_pair_from_trace(
    best: Option<CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_features: &[Peak],
    sample_trace: &[f64],
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Rox400Hd
        || current.indices.len() != ladder_sizes.len()
        || current.indices.len() < 5
        || sample_trace.is_empty()
    {
        return Some(current);
    }

    let first = current.indices[0];
    let second = current.indices[1];
    let third = current.indices[2];
    let fourth = current.indices[3];
    if fourth >= sample_trace.len() {
        return Some(current);
    }

    let gap_50_60 = second.saturating_sub(first);
    let gap_60_90 = third.saturating_sub(second);
    let gap_90_100 = fourth.saturating_sub(third);

    let trace_height =
        |scan: usize| -> f64 { sample_trace.get(scan).copied().unwrap_or(0.0).max(1.0) };
    let current_heights = [
        trace_height(first),
        trace_height(second),
        trace_height(third),
        trace_height(fourth),
    ];
    let current_tail_median = median(&current_heights[1..]).max(1.0);
    let current_first_ratio = current_heights[0] / current_tail_median;
    let current_tail_spread = current_heights[1..]
        .iter()
        .map(|height| (height.max(1.0) / current_tail_median).ln().abs())
        .fold(0.0_f64, f64::max);
    let current_start_low = current_heights[0].min(current_heights[1]) < 120.0;
    let direct_shift_start = (current_heights[0] < 160.0 && current_heights[1] >= 180.0)
        || (current_first_ratio > 2.80 && current_heights[1] >= 180.0)
        || (gap_60_90 > 188 && current_heights[1] >= 180.0);
    let suspicious_start = current_first_ratio < 0.55
        || current_first_ratio > 2.80
        || current_start_low
        || gap_50_60 > 78
        || gap_50_60 < 45
        || gap_90_100 > 78;
    if !suspicious_start {
        return Some(current);
    }

    let search_start = first.saturating_sub(120).min(sample_trace.len());
    let search_end = third.saturating_add(1).min(sample_trace.len());
    if search_end <= search_start + 3 {
        return Some(current);
    }

    let mut augmented = peak_features.to_vec();
    let mut trace_candidate_indices = Vec::new();
    for mut peak in find_peaks(&sample_trace[search_start..search_end], 20.0, 3) {
        peak.index += search_start;
        if peak.prominence < 20.0 {
            continue;
        }
        trace_candidate_indices.push(peak.index);
        if !augmented
            .iter()
            .any(|existing| existing.index == peak.index)
        {
            augmented.push(peak);
        }
    }
    for scan in [first, second, third] {
        if scan < sample_trace.len() && !augmented.iter().any(|peak| peak.index == scan) {
            augmented.push(Peak {
                index: scan,
                height: sample_trace[scan],
                prominence: sample_trace[scan].abs().max(1.0),
                width: 1.0,
                local_baseline: 0.0,
                score: sample_trace[scan].abs().max(1.0),
            });
        }
    }
    augmented.sort_by_key(|peak| peak.index);
    let augmented_by_index = augmented
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    trace_candidate_indices.sort_unstable();
    trace_candidate_indices.dedup();

    if direct_shift_start && second < sample_trace.len() {
        trace_candidate_indices.push(second);
        trace_candidate_indices.sort_unstable();
        trace_candidate_indices.dedup();
    }

    let mut best_direct_trial: Option<CombinationScore> = None;
    let mut best_trial: Option<CombinationScore> = None;
    for candidate_first in trace_candidate_indices.iter().copied() {
        for candidate_second in trace_candidate_indices.iter().copied() {
            if candidate_first >= candidate_second || candidate_second >= third {
                continue;
            }
            if !(1450..=1850).contains(&candidate_first) || third > 2050 {
                continue;
            }
            let candidate_gap_50_60 = candidate_second.saturating_sub(candidate_first);
            let candidate_gap_60_90 = third.saturating_sub(candidate_second);
            if !(45..=65).contains(&candidate_gap_50_60)
                || !(150..=180).contains(&candidate_gap_60_90)
                || !(45..=78).contains(&gap_90_100)
            {
                continue;
            }

            let candidate_heights = [
                trace_height(candidate_first),
                trace_height(candidate_second),
                trace_height(third),
                trace_height(fourth),
            ];
            let candidate_tail_median = median(&candidate_heights[1..]).max(1.0);
            let candidate_first_ratio = candidate_heights[0] / candidate_tail_median;
            let direct_shift = direct_shift_start && candidate_first == second;
            let candidate_tail_spread = candidate_heights[1..]
                .iter()
                .map(|height| (height.max(1.0) / candidate_tail_median).ln().abs())
                .fold(0.0_f64, f64::max);
            let max_first_ratio = if direct_shift { 30.0 } else { 5.50 };
            if candidate_tail_spread > 0.75
                || candidate_first_ratio < 0.25
                || candidate_first_ratio > max_first_ratio
            {
                continue;
            }

            let visual_win = candidate_tail_spread + 0.10 < current_tail_spread
                || candidate_heights[0].min(candidate_heights[1])
                    > 80.0_f64.max(current_heights[0].min(current_heights[1]) * 1.80)
                || (candidate_first_ratio > 0.35 && current_first_ratio < 0.35)
                || gap_60_90 > 205;
            if !visual_win {
                continue;
            }

            let mut trial = current.indices.clone();
            trial[0] = candidate_first;
            trial[1] = candidate_second;
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }
            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                &augmented_by_index,
                &augmented,
            );
            if trial_score.linear_max_abs_error_bp >= 8.0
                || trial_score.linear_mean_abs_error_bp > 2.40
                || trial_score.linear_r2 < 0.9988
            {
                continue;
            }

            if direct_shift && trial_score.linear_max_abs_error_bp <= 6.0 {
                let should_take_direct = if let Some(current_best) = best_direct_trial.as_ref() {
                    (
                        trial_score.linear_max_abs_error_bp,
                        trial_score.linear_mean_abs_error_bp,
                        -trial_score.linear_r2,
                        trial_score.peak_penalty,
                        trial_score.blended_score,
                    ) < (
                        current_best.linear_max_abs_error_bp,
                        current_best.linear_mean_abs_error_bp,
                        -current_best.linear_r2,
                        current_best.peak_penalty,
                        current_best.blended_score,
                    )
                } else {
                    true
                };
                if should_take_direct {
                    best_direct_trial = Some(trial_score);
                }
                continue;
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                (
                    trial_score.linear_max_abs_error_bp,
                    trial_score.linear_mean_abs_error_bp,
                    -trial_score.linear_r2,
                    trial_score.peak_penalty,
                    trial_score.blended_score,
                ) < (
                    current_best.linear_max_abs_error_bp,
                    current_best.linear_mean_abs_error_bp,
                    -current_best.linear_r2,
                    current_best.peak_penalty,
                    current_best.blended_score,
                )
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_direct_trial.or(best_trial).or(Some(current))
}

fn repair_rox_late_family_prepend_sequence(
    best: Option<CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Rox400Hd
        || current.indices.len() != ladder_sizes.len()
        || current.indices.len() < 8
    {
        return Some(current);
    }

    let first = current.indices[0];
    if first <= 1850 || current.linear_max_abs_error_bp > 6.2 {
        return Some(current);
    }

    let peak_feature_by_index = peak_features
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let prefix_candidates = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            peak.index >= 1500
                && peak.index < first
                && peak.height >= 45.0
                && peak.prominence >= 22.0
                && baseline_ratio <= 0.60
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    if prefix_candidates.len() < 4 {
        return Some(current);
    }

    let mut best_trial: Option<CombinationScore> = None;
    for prepend_len in 3..=6 {
        if prepend_len >= current.indices.len() {
            continue;
        }
        let mut candidates = prefix_candidates.clone();
        candidates.retain(|scan| *scan < first.saturating_sub(20));
        candidates.sort_unstable();
        candidates.dedup();
        let combos = generate_peak_combinations(&candidates, prepend_len, 260, 250_000);
        for prefix in combos {
            if prefix.len() != prepend_len || !prefix.windows(2).all(|window| window[1] > window[0])
            {
                continue;
            }
            let gap_to_late = first.saturating_sub(*prefix.last().unwrap_or(&first));
            if !(45..=190).contains(&gap_to_late) {
                continue;
            }
            let mut trial = prefix;
            trial.extend_from_slice(&current.indices[..current.indices.len() - prepend_len]);
            if trial.len() != current.indices.len() || !trial.windows(2).all(|w| w[1] > w[0]) {
                continue;
            }

            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                &peak_feature_by_index,
                peak_features,
            );
            if trial_score.linear_max_abs_error_bp > 6.0
                || trial_score.linear_mean_abs_error_bp > 2.8
                || trial_score.linear_r2 < 0.9988
            {
                continue;
            }
            let should_take = if let Some(current_best) = best_trial.as_ref() {
                (
                    trial_score.linear_max_abs_error_bp,
                    trial_score.linear_mean_abs_error_bp,
                    -trial_score.linear_r2,
                    trial_score.peak_penalty,
                    trial_score.blended_score,
                ) < (
                    current_best.linear_max_abs_error_bp,
                    current_best.linear_mean_abs_error_bp,
                    -current_best.linear_r2,
                    current_best.peak_penalty,
                    current_best.blended_score,
                )
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_trial.or(Some(current))
}

fn repair_rox_late_to_first_strong_family_sequence(
    best: Option<CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Rox400Hd
        || current.indices.len() != ladder_sizes.len()
        || current.indices.first().copied().unwrap_or(0) <= 1850
    {
        return Some(current);
    }

    let mut family_peaks = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            peak.index >= 1500
                && peak.index <= 4000
                && peak.height >= 250.0
                && peak.prominence >= 45.0
                && baseline_ratio <= 0.90
        })
        .cloned()
        .collect::<Vec<_>>();
    family_peaks.sort_by_key(|peak| peak.index);
    family_peaks.dedup_by_key(|peak| peak.index);
    if family_peaks.len() < ladder_sizes.len() {
        return Some(current);
    }

    let mut states: Vec<(f64, Vec<usize>)> = family_peaks
        .iter()
        .enumerate()
        .filter(|(_, peak)| peak.index >= 1520 && peak.index <= 1850)
        .map(|(idx, _)| (0.0, vec![idx]))
        .collect();
    if states.is_empty() {
        return Some(current);
    }

    for expected_gap in ROX_BROAD_GAP_MEDIAN.iter().copied() {
        let mut next_states: Vec<(f64, Vec<usize>)> = Vec::new();
        for (score, path) in states.iter() {
            let prev_idx = match path.last().copied() {
                Some(value) => value,
                None => continue,
            };
            let prev_scan = family_peaks[prev_idx].index;
            for (candidate_idx, peak) in family_peaks.iter().enumerate().skip(prev_idx + 1) {
                let gap = peak.index.saturating_sub(prev_scan) as f64;
                let min_gap = (expected_gap * 0.45).max(20.0);
                let max_gap = expected_gap * 1.75 + 30.0;
                if gap < min_gap || gap > max_gap {
                    continue;
                }
                let tolerance = (expected_gap * 0.16).max(10.0);
                let gap_penalty = ((gap - expected_gap).abs() - tolerance).max(0.0) / tolerance;
                let baseline_ratio =
                    (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                let quality_penalty =
                    if peak.height >= 350.0 && peak.prominence >= 70.0 && baseline_ratio <= 0.75 {
                        0.0
                    } else {
                        ((350.0 - peak.height).max(0.0) / 350.0)
                            + ((70.0 - peak.prominence).max(0.0) / 70.0)
                            + (baseline_ratio - 0.75).max(0.0)
                    };
                let mut next_path = path.clone();
                next_path.push(candidate_idx);
                next_states.push((score + gap_penalty + quality_penalty * 0.20, next_path));
            }
        }
        if next_states.is_empty() {
            return Some(current);
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if next_states.len() > 200 {
            next_states.truncate(200);
        }
        states = next_states;
    }

    let peak_feature_by_index = peak_features
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();

    let mut best_candidate: Option<(f64, CombinationScore)> = None;
    for (dp_score, path) in states.into_iter().take(80) {
        if path.len() != ladder_sizes.len() {
            continue;
        }
        let trial = path
            .into_iter()
            .map(|idx| family_peaks[idx].index)
            .collect::<Vec<_>>();
        if !trial.windows(2).all(|window| window[1] > window[0])
            || trial.first().copied().unwrap_or(usize::MAX)
                > current
                    .indices
                    .first()
                    .copied()
                    .unwrap_or(0)
                    .saturating_sub(220)
        {
            continue;
        }
        let candidate = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &peak_feature_by_index,
            peak_features,
        );
        if candidate.linear_max_abs_error_bp > 6.0
            || candidate.linear_mean_abs_error_bp > 2.8
            || candidate.linear_r2 < 0.9988
        {
            continue;
        }
        let should_take = if let Some((current_dp_score, current_best)) = best_candidate.as_ref() {
            (
                (dp_score * 1000.0).round() as i64,
                candidate.linear_max_abs_error_bp,
                candidate.linear_mean_abs_error_bp,
                -candidate.linear_r2,
                candidate.peak_penalty,
                candidate.blended_score,
            ) < (
                (current_dp_score * 1000.0).round() as i64,
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.peak_penalty,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_candidate = Some((dp_score, candidate));
        }
    }
    best_candidate
        .map(|(_, candidate)| candidate)
        .or(Some(current))
}

fn repair_rox_strong_median_family_sequence(
    best: Option<CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Rox400Hd || current.indices.len() != ladder_sizes.len() {
        return Some(current);
    }

    let peak_feature_by_index = peak_features
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let selected_baseline_like = current
        .indices
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            height < 80.0 || baseline_ratio >= 0.45 || purity <= 0.55
        })
        .count();
    let impossible_early_start = current.indices.first().copied().unwrap_or(usize::MAX) < 1300;
    let should_try = impossible_early_start
        || current.linear_max_abs_error_bp > 10.0
        || current.linear_mean_abs_error_bp > 4.5
        || (selected_baseline_like >= 3 && current.linear_max_abs_error_bp > 7.5);
    if !should_try {
        return Some(current);
    }

    let reference_heights = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            (1350..=4300).contains(&peak.index)
                && peak.height >= 80.0
                && peak.prominence >= 35.0
                && baseline_ratio <= 0.90
        })
        .map(|peak| peak.height.max(1.0))
        .collect::<Vec<_>>();
    if reference_heights.len() < ladder_sizes.len() {
        return Some(current);
    }
    let height_ref = median(&reference_heights).max(1.0);
    let mut family_peaks = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1350..=4300).contains(&peak.index)
                && peak.height >= (height_ref * 0.18).max(80.0)
                && peak.prominence >= (height_ref * 0.14).max(35.0)
                && (baseline_ratio <= 0.35 || purity >= 0.65)
        })
        .cloned()
        .collect::<Vec<_>>();
    family_peaks.sort_by_key(|peak| peak.index);
    family_peaks.dedup_by_key(|peak| peak.index);
    if family_peaks.len() < ladder_sizes.len() {
        return Some(current);
    }

    let mut states = family_peaks
        .iter()
        .enumerate()
        .filter(|(_, peak)| (1350..=1900).contains(&peak.index))
        .map(|(idx, peak)| {
            let height_log_delta = (peak.height.max(1.0) / height_ref).ln().abs();
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            (height_log_delta * 0.04 + baseline_ratio * 0.15, vec![idx])
        })
        .collect::<Vec<_>>();
    if states.is_empty() {
        return Some(current);
    }

    for expected_gap in ROX_BROAD_GAP_MEDIAN.iter().copied() {
        let mut next_states: Vec<(f64, Vec<usize>)> = Vec::new();
        for (score, path) in states.iter() {
            let prev_idx = match path.last().copied() {
                Some(value) => value,
                None => continue,
            };
            let prev_scan = family_peaks[prev_idx].index;
            for (candidate_idx, peak) in family_peaks.iter().enumerate().skip(prev_idx + 1) {
                let gap = peak.index.saturating_sub(prev_scan) as f64;
                let min_gap = (expected_gap * 0.35).max(18.0);
                let max_gap = expected_gap * 2.20 + 80.0;
                if gap < min_gap || gap > max_gap {
                    continue;
                }
                let tolerance = (expected_gap * 0.18).max(12.0);
                let gap_penalty = ((gap - expected_gap).abs() - tolerance).max(0.0) / tolerance;
                let height_log_delta = (peak.height.max(1.0) / height_ref).ln().abs().min(2.0);
                let baseline_ratio =
                    (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.5);
                let quality_penalty = height_log_delta * 0.08
                    + baseline_ratio * 0.20
                    + (1.0 - purity).max(0.0) * 0.05;
                let mut next_path = path.clone();
                next_path.push(candidate_idx);
                next_states.push((score + gap_penalty + quality_penalty, next_path));
            }
        }
        if next_states.is_empty() {
            return Some(current);
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if next_states.len() > ROX_STRONG_MEDIAN_FAMILY_BEAM {
            next_states.truncate(ROX_STRONG_MEDIAN_FAMILY_BEAM);
        }
        states = next_states;
    }

    let mut best_candidate: Option<(f64, CombinationScore)> = None;
    for (dp_score, path) in states.into_iter().take(ROX_STRONG_MEDIAN_FAMILY_FINALISTS) {
        if path.len() != ladder_sizes.len() {
            continue;
        }
        let trial = path
            .into_iter()
            .map(|idx| family_peaks[idx].index)
            .collect::<Vec<_>>();
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let candidate = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &peak_feature_by_index,
            peak_features,
        );
        if candidate.linear_max_abs_error_bp > 6.0
            || candidate.linear_mean_abs_error_bp > 2.8
            || candidate.linear_r2 < 0.9988
        {
            continue;
        }
        if candidate.linear_max_abs_error_bp + 1.0 >= current.linear_max_abs_error_bp
            && !impossible_early_start
        {
            continue;
        }
        let should_take = if let Some((current_dp_score, current_best)) = best_candidate.as_ref() {
            (
                (dp_score * 1000.0).round() as i64,
                candidate.linear_max_abs_error_bp,
                candidate.linear_mean_abs_error_bp,
                -candidate.linear_r2,
                candidate.peak_penalty,
                candidate.blended_score,
            ) < (
                (current_dp_score * 1000.0).round() as i64,
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.peak_penalty,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_candidate = Some((dp_score, candidate));
        }
    }

    best_candidate
        .map(|(_, candidate)| candidate)
        .or(Some(current))
}

fn repair_liz_first_anchor_family_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 6
    {
        return None;
    }
    let current_first = peak_feature_by_index.get(&best.indices[0])?;
    let current_second = peak_feature_by_index.get(&best.indices[1])?;
    let current_third = peak_feature_by_index.get(&best.indices[2])?;
    let current_is_blob_dominant = current_first.height > current_second.height * 1.35
        || current_first.prominence > current_second.prominence * 1.30
        || current_first.score > current_second.score * 1.20;
    let current_is_suspiciously_early = current_first.index < 1450
        && current_second.index >= 1530
        && best.linear_max_abs_error_bp > 5.0;
    let should_check_blob_first_despite_stable_fit =
        current_is_blob_dominant && best.linear_max_abs_error_bp > 5.0;
    if liz_fit_is_high_confidence_stable(best) && !should_check_blob_first_despite_stable_fit {
        return None;
    }
    if best.linear_max_abs_error_bp <= 5.0 && best.linear_mean_abs_error_bp <= 2.0 {
        return None;
    }
    if !(current_is_blob_dominant || current_is_suspiciously_early) {
        return None;
    }

    let reference_heights = best
        .indices
        .iter()
        .skip(1)
        .take(5)
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let reference_scores = best
        .indices
        .iter()
        .skip(1)
        .take(5)
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.score))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if reference_heights.is_empty() || reference_scores.is_empty() {
        return None;
    }
    let height_ref = median(&reference_heights).max(1.0);
    let score_ref = median(&reference_scores).max(1.0);

    let mut best_trial: Option<CombinationScore> = None;
    for candidate in peak_features.iter().filter(|peak| {
        peak.index >= current_first.index.saturating_sub(80)
            && peak.index + 12 < best.indices[1]
            && peak.index + 8 < current_first.index
            && liz_linear_first_peak_is_plausible(peak, height_ref, score_ref)
    }) {
        let candidate_baseline_ratio =
            (candidate.local_baseline.max(0.0) / candidate.height.max(1.0)).clamp(0.0, 1.5);
        let family_like = candidate_baseline_ratio <= 0.26
            && candidate.height >= current_second.height * 0.70
            && candidate.height <= current_second.height * 1.35
            && candidate.prominence >= current_second.prominence * 0.70
            && candidate.prominence <= current_third.prominence * 1.45;
        if !family_like {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[0] = candidate.index;
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let compelling_linear_win = trial_score.linear_max_abs_error_bp + 1.20
            < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.10
            && trial_score.linear_r2 + 0.00005 >= best.linear_r2;
        let compelling_family_tradeoff = candidate.index >= current_first.index.saturating_add(55)
            && candidate.index >= 1495
            && trial_score.linear_max_abs_error_bp <= best.linear_max_abs_error_bp + 0.65
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.20
            && trial_score.linear_r2 + 0.00020 >= best.linear_r2
            && trial_score.peak_penalty + 0.60 < best.peak_penalty;
        let compelling = compelling_linear_win || compelling_family_tradeoff;
        if !compelling {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

const LIZ_BLOB_EARLY_BLOCK_ANCHOR_STEP: usize = 10;
const LIZ_BLOB_EARLY_BLOCK_MAX_EARLY_PEAKS: usize = 18;
const LIZ_BLOB_EARLY_BLOCK_MAX_COMBINATIONS: usize = 100_000;

fn repair_liz_blob_early_block_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 12
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }
    if best.linear_max_abs_error_bp <= 20.0 && best.linear_mean_abs_error_bp <= 8.0 {
        return None;
    }

    let early = &best.indices[..best.indices.len().min(6)];
    let tight_pairs = early
        .windows(2)
        .filter(|pair| pair[1].saturating_sub(pair[0]) <= 60)
        .count();
    let weak_or_dirty = early
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            baseline_ratio > 0.45 || purity < 0.42
        })
        .count();
    if tight_pairs < 2 && weak_or_dirty < 2 {
        return None;
    }

    let anchor_step = LIZ_BLOB_EARLY_BLOCK_ANCHOR_STEP.min(best.indices.len().saturating_sub(5));
    let anchor_scan = best.indices[anchor_step];
    let reference_heights = best
        .indices
        .iter()
        .skip(anchor_step)
        .take(4)
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let reference_scores = best
        .indices
        .iter()
        .skip(anchor_step)
        .take(4)
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.score))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if reference_heights.is_empty() || reference_scores.is_empty() {
        return None;
    }
    let height_ref = median(&reference_heights).max(1.0);
    let score_ref = median(&reference_scores).max(1.0);

    let mut early_candidates = peak_features
        .iter()
        .filter(|peak| peak.index >= 1425 && peak.index + 8 < anchor_scan)
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            let giant_blob = peak.index < 1450
                && peak.height > height_ref * 3.5
                && (baseline_ratio > 0.10 || purity < 0.55);
            let dirty = baseline_ratio > 0.72 && purity < 0.35;
            !giant_blob
                && !dirty
                && peak.height >= 28.0
                && peak.prominence >= 20.0
                && liz_linear_first_peak_is_plausible(peak, height_ref, score_ref)
        })
        .cloned()
        .collect::<Vec<_>>();
    if early_candidates.len() < anchor_step {
        return None;
    }

    early_candidates.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.50 - left_baseline_ratio * 180.0 + left_purity * 80.0;
        let right_rank = right.score + right.prominence * 0.50 - right_baseline_ratio * 180.0
            + right_purity * 80.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if early_candidates.len() > LIZ_BLOB_EARLY_BLOCK_MAX_EARLY_PEAKS {
        early_candidates.truncate(LIZ_BLOB_EARLY_BLOCK_MAX_EARLY_PEAKS);
    }
    early_candidates.sort_by_key(|peak| peak.index);

    let early_indices = early_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    let replacements = generate_peak_combinations(
        &early_indices,
        anchor_step,
        usize::MAX,
        LIZ_BLOB_EARLY_BLOCK_MAX_COMBINATIONS,
    );
    if replacements.is_empty() {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for replacement in replacements {
        if replacement[anchor_step - 1] >= anchor_scan.saturating_sub(8) {
            continue;
        }
        let mut trial = best.indices.clone();
        trial[..anchor_step].copy_from_slice(&replacement);
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let strong_linear_win = trial_score.linear_max_abs_error_bp + 8.0
            < best.linear_max_abs_error_bp
            || (trial_score.linear_max_abs_error_bp + 4.0 < best.linear_max_abs_error_bp
                && trial_score.linear_mean_abs_error_bp + 1.0 < best.linear_mean_abs_error_bp);
        let acceptable_r2 = trial_score.linear_r2 + 0.00010 >= best.linear_r2;
        let acceptable_penalties = trial_score.peak_penalty <= best.peak_penalty + 2.0
            && trial_score.domain_penalty <= best.domain_penalty + 1.4;
        if !(strong_linear_win && acceptable_r2 && acceptable_penalties) {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_motif_start_block_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 8
    {
        return None;
    }
    if best.linear_max_abs_error_bp <= 8.0
        && best.linear_mean_abs_error_bp <= 3.0
        && best.linear_r2 >= 0.9988
    {
        return None;
    }

    let anchor_scan = best.indices[4];
    let later_reference = best
        .indices
        .iter()
        .skip(4)
        .take(6)
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if later_reference.len() < 4 {
        return None;
    }

    let height_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let prominence_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let width_ref = median(
        &later_reference
            .iter()
            .map(|peak| peak.width.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);

    let middle_gap_ratios = best.indices[4..best.indices.len().min(12)]
        .windows(2)
        .zip(ladder_sizes[4..ladder_sizes.len().min(12)].windows(2))
        .filter_map(|(scan_window, bp_window)| {
            let bp_gap = bp_window[1] - bp_window[0];
            if bp_gap <= f64::EPSILON {
                None
            } else {
                Some((scan_window[1] as f64 - scan_window[0] as f64) / bp_gap)
            }
        })
        .collect::<Vec<_>>();
    let scan_per_bp = median(&middle_gap_ratios).max(4.0);
    let expected_gaps = [
        scan_per_bp * (ladder_sizes[1] - ladder_sizes[0]),
        scan_per_bp * (ladder_sizes[2] - ladder_sizes[1]),
        scan_per_bp * (ladder_sizes[3] - ladder_sizes[2]),
        scan_per_bp * (ladder_sizes[4] - ladder_sizes[3]),
    ];

    let mut early_candidates = peak_features
        .iter()
        .filter(|peak| peak.index >= 1450 && peak.index + 8 < anchor_scan)
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            let width_ratio = peak.width.max(1.0) / width_ref.max(1.0);
            let height_ratio = peak.height / height_ref.max(1.0);
            let prominence_ratio = peak.prominence / prominence_ref.max(1.0);
            peak.prominence >= 25.0
                && peak.height >= 28.0
                && baseline_ratio <= 0.32
                && purity >= 0.50
                && width_ratio >= 0.35
                && width_ratio <= 2.7
                && height_ratio >= 0.08
                && prominence_ratio >= 0.08
        })
        .cloned()
        .collect::<Vec<_>>();
    if early_candidates.len() < 4 {
        return None;
    }

    early_candidates.sort_by(|left, right| {
        let left_baseline_ratio =
            (left.local_baseline.max(0.0) / left.height.max(1.0)).clamp(0.0, 1.5);
        let right_baseline_ratio =
            (right.local_baseline.max(0.0) / right.height.max(1.0)).clamp(0.0, 1.5);
        let left_rank =
            left.score + left.prominence * 0.45 + left.height.min(height_ref * 1.4) * 0.10
                - left_baseline_ratio * 1200.0;
        let right_rank =
            right.score + right.prominence * 0.45 + right.height.min(height_ref * 1.4) * 0.10
                - right_baseline_ratio * 1200.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if early_candidates.len() > 14 {
        early_candidates.truncate(14);
    }
    early_candidates.sort_by_key(|peak| peak.index);
    let early_indices = early_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let mut best_trial: Option<CombinationScore> = None;
    for replacement in generate_peak_combinations(&early_indices, 4, usize::MAX, 768) {
        if replacement[3] >= anchor_scan.saturating_sub(8) {
            continue;
        }

        let gaps = [
            replacement[1].saturating_sub(replacement[0]) as f64,
            replacement[2].saturating_sub(replacement[1]) as f64,
            replacement[3].saturating_sub(replacement[2]) as f64,
            anchor_scan.saturating_sub(replacement[3]) as f64,
        ];
        let motif_penalty = gaps
            .iter()
            .zip(expected_gaps.iter())
            .map(|(gap, expected)| {
                let tolerance = (expected * 0.45).max(28.0);
                ((*gap - *expected).abs() / tolerance).max(0.0)
            })
            .sum::<f64>();
        let major_gap_violation = gaps
            .iter()
            .zip(expected_gaps.iter())
            .any(|(gap, expected)| {
                let tolerance = (expected * 0.70).max(55.0);
                (*gap - *expected).abs() > tolerance
            });
        if motif_penalty > 5.5 || major_gap_violation {
            continue;
        }

        let mut trial = best.indices.clone();
        trial[..4].copy_from_slice(&replacement);
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let strong_linear_win = trial_score.linear_max_abs_error_bp + 0.75
            < best.linear_max_abs_error_bp
            || (trial_score.linear_max_abs_error_bp + 0.35 < best.linear_max_abs_error_bp
                && trial_score.linear_mean_abs_error_bp + 0.25 < best.linear_mean_abs_error_bp);
        let acceptable_r2 = trial_score.linear_r2 + 0.00015 >= best.linear_r2;
        let acceptable_penalties = trial_score.peak_penalty <= best.peak_penalty + 1.20
            && trial_score.domain_penalty <= best.domain_penalty + 0.90;
        if !(strong_linear_win && acceptable_r2 && acceptable_penalties) {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.peak_penalty,
                trial_score.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.peak_penalty,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_rox_baseline_family_rebuild(
    current: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd || ladder_sizes.len() != 21 {
        return None;
    }

    if let Some(existing) = current {
        if existing.indices.len() == ladder_sizes.len()
            && existing.linear_max_abs_error_bp < 6.0
            && existing.linear_mean_abs_error_bp < 2.5
            && existing.linear_r2 >= 0.9990
        {
            return None;
        }
    }

    let mut ranked = peak_features
        .iter()
        .filter(|peak| peak.score.is_finite() && peak.height.is_finite())
        .cloned()
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                right
                    .height
                    .partial_cmp(&left.height)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.index.cmp(&right.index))
    });

    let start_pool = ranked
        .iter()
        .filter(|peak| (1900..=2350).contains(&peak.index))
        .take(8)
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    let tail_pool = ranked
        .iter()
        .filter(|peak| (3900..=4400).contains(&peak.index))
        .take(8)
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    if start_pool.len() < 2 || tail_pool.len() < 2 {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for start_seed in start_pool {
        for tail_seed in tail_pool.iter().copied() {
            if tail_seed <= start_seed.saturating_add(1200) {
                continue;
            }

            let span_bp = (ladder_sizes.last().copied().unwrap_or(400.0)
                - ladder_sizes.first().copied().unwrap_or(50.0))
            .max(1.0);
            let slope = (tail_seed.saturating_sub(start_seed) as f64) / span_bp;
            if !slope.is_finite() || slope <= 0.0 {
                continue;
            }

            let mut chosen = Vec::with_capacity(ladder_sizes.len());
            let mut used = std::collections::BTreeSet::new();
            let mut last_index = 0usize;
            let mut failed = false;

            for ladder_bp in ladder_sizes.iter().copied() {
                let target = start_seed as f64
                    + slope * (ladder_bp - ladder_sizes.first().copied().unwrap_or(50.0));
                let tolerance = (slope * 16.0).max(100.0);
                let mut best_local: Option<(f64, f64, usize)> = None;

                for peak in peak_features {
                    if used.contains(&peak.index) || peak.index <= last_index.saturating_add(4) {
                        continue;
                    }
                    let delta = (peak.index as f64 - target).abs();
                    if delta > tolerance {
                        continue;
                    }
                    let weak_penalty = (40.0 - peak.height).max(0.0);
                    let baseline_penalty =
                        ((peak.local_baseline.max(0.0) / peak.height.max(1.0)) - 0.35).max(0.0);
                    let local = (
                        delta + weak_penalty * 0.4 + baseline_penalty * 12.0,
                        -peak.height,
                        peak.index,
                    );
                    if let Some(existing) = best_local {
                        if local < existing {
                            best_local = Some(local);
                        }
                    } else {
                        best_local = Some(local);
                    }
                }

                let Some((_score, _neg_height, picked)) = best_local else {
                    failed = true;
                    break;
                };
                chosen.push(picked);
                used.insert(picked);
                last_index = picked;
            }

            if failed
                || chosen.len() != ladder_sizes.len()
                || !chosen.windows(2).all(|w| w[1] > w[0])
            {
                continue;
            }

            let trial_score = score_combination(
                &chosen,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            let should_take = if let Some(current_best) = best_trial.as_ref() {
                (
                    trial_score.linear_max_abs_error_bp,
                    trial_score.linear_mean_abs_error_bp,
                    -trial_score.linear_r2,
                    trial_score.blended_score,
                ) < (
                    current_best.linear_max_abs_error_bp,
                    current_best.linear_mean_abs_error_bp,
                    -current_best.linear_r2,
                    current_best.blended_score,
                )
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    let best_trial = best_trial?;
    if let Some(existing) = current {
        let compelling = best_trial.linear_max_abs_error_bp + 5.0
            < existing.linear_max_abs_error_bp
            && best_trial.linear_mean_abs_error_bp + 2.0 < existing.linear_mean_abs_error_bp
            && best_trial.linear_r2 + 0.0005 >= existing.linear_r2;
        if !block_repair_is_material(existing, &best_trial) && !compelling {
            return None;
        }
    }

    Some(best_trial)
}

fn repair_rox_full_span_family_rebuild(
    current: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd || ladder_sizes.len() != 21 {
        return None;
    }

    if let Some(existing) = current {
        if existing.indices.len() != ladder_sizes.len() {
            return None;
        }
        let first_anchor = existing.indices.first().copied().unwrap_or(0);
        let last_anchor = existing.indices.last().copied().unwrap_or(0);
        let span = last_anchor.saturating_sub(first_anchor);
        let suspicious_compressed_rox_family = existing.linear_max_abs_error_bp >= 5.0
            && existing.linear_mean_abs_error_bp >= 1.45
            && (first_anchor > 1850 || last_anchor > 3900 || span > 2250);
        if existing.linear_max_abs_error_bp <= 10.0
            && existing.linear_mean_abs_error_bp <= 4.5
            && !suspicious_compressed_rox_family
        {
            return None;
        }
    }

    let mut start_pool = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            peak.index >= 1450
                && peak.index <= 2100
                && peak.height >= 30.0
                && peak.prominence >= 24.0
                && baseline_ratio <= 0.38
        })
        .cloned()
        .collect::<Vec<_>>();
    let mut tail_pool = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            peak.index >= 3300
                && peak.index <= 4300
                && peak.height >= 28.0
                && peak.prominence >= 22.0
                && baseline_ratio <= 0.42
        })
        .cloned()
        .collect::<Vec<_>>();
    if start_pool.len() < 2 || tail_pool.len() < 2 {
        return None;
    }

    let rank_peak = |peak: &Peak| {
        let baseline_ratio = (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
        peak.score + peak.prominence * 0.45 + peak.height.min(900.0) * 0.08 - baseline_ratio * 850.0
    };
    start_pool.sort_by(|left, right| {
        rank_peak(right)
            .partial_cmp(&rank_peak(left))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    tail_pool.sort_by(|left, right| {
        rank_peak(right)
            .partial_cmp(&rank_peak(left))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    start_pool.truncate(10);
    tail_pool.truncate(10);

    let first_bp = ladder_sizes.first().copied().unwrap_or(50.0);
    let last_bp = ladder_sizes.last().copied().unwrap_or(400.0);
    let span_bp = (last_bp - first_bp).max(1.0);
    let mut best_trial: Option<CombinationScore> = None;

    for start_peak in &start_pool {
        for tail_peak in &tail_pool {
            if tail_peak.index <= start_peak.index.saturating_add(1400) {
                continue;
            }
            let slope = (tail_peak.index.saturating_sub(start_peak.index) as f64) / span_bp;
            if !(4.2..=11.8).contains(&slope) {
                continue;
            }

            let mut chosen = Vec::with_capacity(ladder_sizes.len());
            let mut used = std::collections::BTreeSet::new();
            let mut failed = false;
            for (step_idx, ladder_bp) in ladder_sizes.iter().copied().enumerate() {
                let picked = if step_idx == 0 {
                    start_peak.index
                } else if step_idx + 1 == ladder_sizes.len() {
                    tail_peak.index
                } else {
                    let target = start_peak.index as f64 + slope * (ladder_bp - first_bp);
                    let tolerance = (slope * 12.0).max(70.0);
                    let mut local_best: Option<(f64, usize)> = None;
                    for peak in peak_features {
                        if used.contains(&peak.index) {
                            continue;
                        }
                        if let Some(previous) = chosen.last() {
                            if peak.index <= (*previous as usize).saturating_add(4) {
                                continue;
                            }
                        }
                        if peak.index >= tail_peak.index.saturating_sub(4) {
                            continue;
                        }
                        let delta = (peak.index as f64 - target).abs();
                        if delta > tolerance {
                            continue;
                        }
                        let baseline_ratio =
                            (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                        if baseline_ratio > 0.70 || peak.prominence < 18.0 || peak.height < 22.0 {
                            continue;
                        }
                        let weak_penalty = (55.0 - peak.height).max(0.0) * 0.18;
                        let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.5);
                        let local_score = delta
                            + baseline_ratio * 36.0
                            + weak_penalty
                            + (0.32 - purity).max(0.0) * 30.0;
                        let candidate = (local_score, peak.index);
                        if local_best.map_or(true, |existing| candidate < existing) {
                            local_best = Some(candidate);
                        }
                    }
                    let Some((_score, index)) = local_best else {
                        failed = true;
                        break;
                    };
                    index
                };
                if used.contains(&picked) {
                    failed = true;
                    break;
                }
                if let Some(previous) = chosen.last() {
                    if picked <= *previous {
                        failed = true;
                        break;
                    }
                }
                chosen.push(picked);
                used.insert(picked);
            }

            if failed
                || chosen.len() != ladder_sizes.len()
                || !chosen.windows(2).all(|window| window[1] > window[0])
            {
                continue;
            }

            let trial_score = score_combination(
                &chosen,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            if trial_score.linear_max_abs_error_bp > 6.2
                || trial_score.linear_mean_abs_error_bp > 2.8
                || trial_score.linear_r2 < 0.9990
            {
                continue;
            }
            if let Some(existing) = current {
                let existing_first = existing.indices.first().copied().unwrap_or(0);
                let candidate_first = trial_score.indices.first().copied().unwrap_or(0);
                if existing_first < 1850
                    && candidate_first > existing_first.saturating_add(220)
                    && existing.linear_max_abs_error_bp <= 6.0
                    && existing.linear_mean_abs_error_bp <= 2.8
                {
                    continue;
                }
                if existing.linear_max_abs_error_bp <= 6.0
                    && existing.linear_mean_abs_error_bp <= 2.8
                    && trial_score.linear_max_abs_error_bp + 0.50
                        >= existing.linear_max_abs_error_bp
                    && trial_score.linear_mean_abs_error_bp + 0.25
                        >= existing.linear_mean_abs_error_bp
                    && trial_score.linear_r2 < existing.linear_r2 + 0.00020
                {
                    continue;
                }
                let compelling = trial_score.linear_max_abs_error_bp + 4.0
                    < existing.linear_max_abs_error_bp
                    && trial_score.linear_mean_abs_error_bp + 1.0
                        < existing.linear_mean_abs_error_bp
                    && trial_score.linear_r2 + 0.0002 >= existing.linear_r2;
                if !repair_candidate_improves_current(existing, &trial_score) && !compelling {
                    continue;
                }
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                compare_block_repair_candidates(&trial_score, current_best)
                    == std::cmp::Ordering::Less
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_trial
}

fn repair_rox_strong_family_window_sequence(
    current: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd || ladder_sizes.len() != 21 {
        return None;
    }

    if let Some(existing) = current {
        if existing.linear_max_abs_error_bp <= 5.0
            && existing.linear_mean_abs_error_bp <= 2.0
            && existing.linear_r2 >= 0.9995
        {
            return None;
        }
    }

    let mut family = peak_feature_by_index
        .values()
        .filter(|peak| (1500..=4000).contains(&peak.index) && peak.height > 250.0)
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    if family.len() != ladder_sizes.len() {
        return None;
    }
    family.sort_unstable();
    if !family.windows(2).all(|window| window[1] > window[0]) {
        return None;
    }

    let peak_pool = peak_feature_by_index.values().cloned().collect::<Vec<_>>();
    let candidate = score_combination(
        &family,
        ladder_sizes,
        ladder,
        peak_feature_by_index,
        &peak_pool,
    );
    if candidate.linear_max_abs_error_bp > 5.0
        || candidate.linear_mean_abs_error_bp > 2.5
        || candidate.linear_r2 < 0.9995
    {
        return None;
    }

    if let Some(existing) = current {
        if !repair_candidate_improves_current(existing, &candidate)
            && !(candidate.linear_max_abs_error_bp + 4.0 < existing.linear_max_abs_error_bp
                && candidate.linear_mean_abs_error_bp + 1.5 < existing.linear_mean_abs_error_bp
                && candidate.linear_r2 + 0.0005 >= existing.linear_r2)
        {
            return None;
        }
    }

    Some(candidate)
}

fn repair_rox_clean_early_family_sequence(
    current: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd || ladder_sizes.len() != 21 {
        return None;
    }

    let existing = current?;
    if existing.indices.len() != ladder_sizes.len()
        || existing.linear_max_abs_error_bp <= 8.0
        || existing.linear_mean_abs_error_bp <= 3.0
        || existing.indices.last().copied().unwrap_or(0) < 4300
    {
        return None;
    }

    let selected_late_foot = existing
        .indices
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            peak.index >= 3900 && (height < 120.0 || baseline_ratio >= 0.75 || purity <= 0.25)
        })
        .count();
    if selected_late_foot < 4 {
        return None;
    }

    let clean = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1450..=3700).contains(&peak.index)
                && height >= 300.0
                && peak.prominence >= 250.0
                && baseline_ratio <= 0.25
                && purity >= 0.70
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    if clean.len() < ladder_sizes.len() || clean.len() > ladder_sizes.len() + 4 {
        return None;
    }

    let mut clean = clean;
    clean.sort_unstable();
    clean.dedup();
    if clean.len() < ladder_sizes.len() || clean.len() > ladder_sizes.len() + 4 {
        return None;
    }

    let peak_pool = peak_feature_by_index.values().cloned().collect::<Vec<_>>();
    let mut best_trial: Option<CombinationScore> = None;
    for family in generate_peak_combinations(&clean, ladder_sizes.len(), usize::MAX, 12_000) {
        let candidate = score_combination(
            &family,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            &peak_pool,
        );
        if candidate.linear_max_abs_error_bp > 5.0
            || candidate.linear_mean_abs_error_bp > 2.4
            || candidate.linear_r2 < 0.9994
        {
            continue;
        }
        if candidate.linear_max_abs_error_bp + 3.0 >= existing.linear_max_abs_error_bp
            || candidate.linear_mean_abs_error_bp + 1.2 >= existing.linear_mean_abs_error_bp
            || candidate.linear_r2 + 0.0005 < existing.linear_r2
        {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                candidate.linear_max_abs_error_bp,
                candidate.linear_mean_abs_error_bp,
                -candidate.linear_r2,
                candidate.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(candidate);
        }
    }

    best_trial
}

#[allow(dead_code)]
fn repair_rox_consistent_height_family_sequence(
    current: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    if ladder != LadderKind::Rox400Hd || ladder_sizes.len() != 21 {
        return None;
    }

    let clean = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1500..=3850).contains(&peak.index)
                && height >= 450.0
                && height >= 80.0
                && peak.prominence >= 400.0
                && baseline_ratio <= 0.25
                && purity >= 0.75
        })
        .cloned()
        .collect::<Vec<_>>();
    if clean.len() < ladder_sizes.len() {
        return None;
    }

    let height_ref = median(&clean.iter().map(|peak| peak.height).collect::<Vec<_>>()).max(1.0);
    let mut ranked_family = clean
        .iter()
        .filter_map(|peak| {
            let height = peak.height.max(1.0);
            let height_log_delta = (height / height_ref).ln().abs();
            if height_log_delta > 0.38 {
                return None;
            }
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            let shape_penalty = baseline_ratio * 0.25 + (1.0 - purity).max(0.0) * 0.20;
            Some((height_log_delta + shape_penalty, peak.index))
        })
        .collect::<Vec<_>>();
    if ranked_family.len() < ladder_sizes.len() {
        return None;
    }
    ranked_family.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.1.cmp(&right.1))
    });
    ranked_family.truncate(ladder_sizes.len());

    let selected_heights = ranked_family
        .iter()
        .filter_map(|(_, index)| peak_feature_by_index.get(index))
        .map(|peak| (peak.height.max(1.0) / height_ref).ln().abs())
        .collect::<Vec<_>>();
    if selected_heights.len() != ladder_sizes.len() || median(&selected_heights) > 0.18 {
        return None;
    }

    let mut family = ranked_family
        .iter()
        .map(|(_, index)| *index)
        .collect::<Vec<_>>();
    family.sort_unstable();
    family.dedup();
    if family.len() != ladder_sizes.len() || !family.windows(2).all(|window| window[1] > window[0])
    {
        return None;
    }

    let peak_pool = peak_feature_by_index.values().cloned().collect::<Vec<_>>();
    let candidate = score_combination(
        &family,
        ladder_sizes,
        ladder,
        peak_feature_by_index,
        &peak_pool,
    );
    if candidate.linear_max_abs_error_bp > 5.0
        || candidate.linear_mean_abs_error_bp > 2.25
        || candidate.linear_r2 < 0.99945
    {
        return None;
    }

    if let Some(existing) = current {
        if existing.linear_max_abs_error_bp < 5.0
            || existing.indices.last().copied().unwrap_or(0) < 3900
        {
            return None;
        }
        let selected_baseline_like = existing
            .indices
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.5);
                baseline_ratio >= 0.45 || purity <= 0.55
            })
            .count();
        let selected_sub80 = existing
            .indices
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .filter(|peak| peak.height.max(1.0) < 80.0)
            .count();
        if selected_sub80 == 0 {
            return None;
        }
        if selected_baseline_like == 0
            && existing.linear_max_abs_error_bp <= 3.80
            && existing.linear_mean_abs_error_bp <= 1.60
            && existing.linear_r2 >= 0.99970
        {
            return None;
        }
        let material_family_win = candidate.linear_max_abs_error_bp + 1.0
            < existing.linear_max_abs_error_bp
            && candidate.linear_mean_abs_error_bp <= existing.linear_mean_abs_error_bp + 0.10
            && candidate.linear_r2 + 0.00020 >= existing.linear_r2;
        let clear_baseline_repair = selected_baseline_like >= 2
            && candidate.linear_max_abs_error_bp + 0.35 < existing.linear_max_abs_error_bp
            && candidate.linear_mean_abs_error_bp <= existing.linear_mean_abs_error_bp + 0.40
            && candidate.linear_r2 + 0.00010 >= existing.linear_r2;
        if !material_family_win && !clear_baseline_repair {
            return None;
        }
    }

    Some(candidate)
}

fn repair_liz_consistent_height_family_sequence(
    current: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250 || ladder_sizes.len() != 16 {
        return None;
    }

    let clean = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1250..=4700).contains(&peak.index)
                && height >= 80.0
                && peak.prominence >= 55.0
                && baseline_ratio <= 0.40
                && purity >= 0.55
        })
        .cloned()
        .collect::<Vec<_>>();
    if clean.len() < ladder_sizes.len() {
        return None;
    }

    let height_ref = median(&clean.iter().map(|peak| peak.height).collect::<Vec<_>>()).max(1.0);
    let mut ranked_family = clean
        .iter()
        .filter_map(|peak| {
            let height = peak.height.max(1.0);
            let height_log_delta = (height / height_ref).ln().abs();
            if height_log_delta > 0.95 {
                return None;
            }
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            let shape_penalty = baseline_ratio * 0.22 + (0.85 - purity).max(0.0) * 0.18;
            Some((height_log_delta + shape_penalty, peak.index))
        })
        .collect::<Vec<_>>();
    if ranked_family.len() < ladder_sizes.len() {
        return None;
    }
    ranked_family.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.1.cmp(&right.1))
    });
    ranked_family.truncate(ladder_sizes.len());

    let selected_heights = ranked_family
        .iter()
        .filter_map(|(_, index)| peak_feature_by_index.get(index))
        .map(|peak| (peak.height.max(1.0) / height_ref).ln().abs())
        .collect::<Vec<_>>();
    if selected_heights.len() != ladder_sizes.len() || median(&selected_heights) > 0.42 {
        return None;
    }

    let mut family = ranked_family
        .iter()
        .map(|(_, index)| *index)
        .collect::<Vec<_>>();
    family.sort_unstable();
    family.dedup();
    if family.len() != ladder_sizes.len() || !family.windows(2).all(|window| window[1] > window[0])
    {
        return None;
    }

    let peak_pool = peak_feature_by_index.values().cloned().collect::<Vec<_>>();
    let candidate = score_combination(
        &family,
        ladder_sizes,
        ladder,
        peak_feature_by_index,
        &peak_pool,
    );
    if candidate.linear_max_abs_error_bp > 6.0
        || candidate.linear_mean_abs_error_bp > 2.85
        || candidate.linear_r2 < 0.99920
    {
        return None;
    }

    if let Some(existing) = current {
        let selected_suspect = existing
            .indices
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.5);
                height < 80.0 || baseline_ratio >= 0.42 || purity <= 0.50
            })
            .count();
        let material_family_win = candidate.linear_max_abs_error_bp + 1.0
            < existing.linear_max_abs_error_bp
            && candidate.linear_mean_abs_error_bp <= existing.linear_mean_abs_error_bp + 0.15
            && candidate.linear_r2 + 0.00015 >= existing.linear_r2;
        let clear_baseline_repair = selected_suspect >= 2
            && candidate.linear_max_abs_error_bp + 0.25 < existing.linear_max_abs_error_bp
            && candidate.linear_mean_abs_error_bp <= existing.linear_mean_abs_error_bp + 0.35
            && candidate.linear_r2 + 0.00005 >= existing.linear_r2;
        if !material_family_win && !clear_baseline_repair {
            return None;
        }
    }

    Some(candidate)
}

fn repair_liz_strong_median_family_sequence(
    best: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Liz500250 || current.indices.len() != ladder_sizes.len() {
        return None;
    }

    let selected_peaks = current
        .indices
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if selected_peaks.len() < ladder_sizes.len() / 2 {
        return None;
    }
    let selected_height_ref = median(
        &selected_peaks
            .iter()
            .skip(1)
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let first_blob = selected_peaks
        .first()
        .is_some_and(|peak| peak.height.max(1.0) > selected_height_ref * 5.0);
    let weak_selected = selected_peaks
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            height < 80.0 || baseline_ratio >= 0.42 || purity <= 0.50
        })
        .count();
    let selected_prominence_ref = median(
        &selected_peaks
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let selected_strong_prominences = selected_peaks
        .iter()
        .map(|peak| peak.prominence.max(1.0))
        .filter(|prominence| *prominence >= selected_prominence_ref)
        .collect::<Vec<_>>();
    let family_prominence_ref = median(&selected_strong_prominences).max(selected_prominence_ref);
    let relative_weak_selected = if family_prominence_ref >= 250.0 {
        let weak_floor = (family_prominence_ref * 0.15).max(45.0);
        selected_peaks
            .iter()
            .filter(|peak| peak.prominence.max(0.0) < weak_floor)
            .count()
    } else {
        0
    };
    if current.linear_max_abs_error_bp <= 10.0 && weak_selected < 6 && relative_weak_selected < 6 {
        return None;
    }
    if !first_blob && weak_selected < 4 && relative_weak_selected < 6 {
        return None;
    }

    let reference_heights = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            (1250..=5450).contains(&peak.index)
                && peak.height >= 80.0
                && peak.prominence >= 45.0
                && (baseline_ratio <= 0.55 || peak.prominence / height >= 0.50)
        })
        .map(|peak| peak.height.max(1.0))
        .collect::<Vec<_>>();
    if reference_heights.len() < ladder_sizes.len() {
        return None;
    }
    let height_ref = median(&reference_heights).max(1.0);
    let mut family_peaks = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1250..=5450).contains(&peak.index)
                && peak.height >= (height_ref * 0.06).max(80.0)
                && peak.prominence >= (height_ref * 0.05).max(45.0)
                && (baseline_ratio <= 0.55 || purity >= 0.50)
                && peak.height <= height_ref * 14.0
        })
        .cloned()
        .collect::<Vec<_>>();
    family_peaks.sort_by_key(|peak| peak.index);
    family_peaks.dedup_by_key(|peak| peak.index);
    if family_peaks.len() < ladder_sizes.len() {
        return None;
    }

    let mut states = family_peaks
        .iter()
        .enumerate()
        .filter(|(_, peak)| (1250..=1850).contains(&peak.index))
        .map(|(idx, peak)| {
            let height_log_delta = (peak.height.max(1.0) / height_ref).ln().abs().min(2.5);
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            (height_log_delta * 0.04 + baseline_ratio * 0.15, vec![idx])
        })
        .collect::<Vec<_>>();
    if states.is_empty() {
        return None;
    }

    for expected_gap in LIZ_BROAD_GAP_MEDIAN.iter().copied() {
        let mut next_states: Vec<(f64, Vec<usize>)> = Vec::new();
        for (score, path) in states.iter() {
            let prev_idx = match path.last().copied() {
                Some(value) => value,
                None => continue,
            };
            let prev_scan = family_peaks[prev_idx].index;
            for (candidate_idx, peak) in family_peaks.iter().enumerate().skip(prev_idx + 1) {
                let gap = peak.index.saturating_sub(prev_scan) as f64;
                let min_gap = (expected_gap * 0.35).max(18.0);
                let max_gap = expected_gap * 2.20 + 90.0;
                if gap < min_gap || gap > max_gap {
                    continue;
                }
                let tolerance = (expected_gap * 0.18).max(12.0);
                let gap_penalty = ((gap - expected_gap).abs() - tolerance).max(0.0) / tolerance;
                let height_log_delta = (peak.height.max(1.0) / height_ref).ln().abs().min(2.5);
                let baseline_ratio =
                    (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.5);
                let quality_penalty = height_log_delta * 0.08
                    + baseline_ratio * 0.20
                    + (1.0 - purity).max(0.0) * 0.05;
                let mut next_path = path.clone();
                next_path.push(candidate_idx);
                next_states.push((score + gap_penalty + quality_penalty, next_path));
            }
        }
        if next_states.is_empty() {
            return None;
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if next_states.len() > LIZ_STRONG_MEDIAN_FAMILY_BEAM {
            next_states.truncate(LIZ_STRONG_MEDIAN_FAMILY_BEAM);
        }
        states = next_states;
    }

    let peak_pool = peak_feature_by_index.values().cloned().collect::<Vec<_>>();
    let mut best_candidate: Option<(f64, CombinationScore)> = None;
    for (dp_score, path) in states.into_iter().take(LIZ_STRONG_MEDIAN_FAMILY_FINALISTS) {
        if path.len() != ladder_sizes.len() {
            continue;
        }
        let trial = path
            .into_iter()
            .map(|idx| family_peaks[idx].index)
            .collect::<Vec<_>>();
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let candidate = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            &peak_pool,
        );
        if candidate.linear_max_abs_error_bp > 6.0
            || candidate.linear_mean_abs_error_bp > 2.8
            || candidate.linear_r2 < 0.9992
            || candidate.linear_max_abs_error_bp + 1.0 >= current.linear_max_abs_error_bp
        {
            continue;
        }
        let should_take = if let Some((current_dp_score, current_best)) = best_candidate.as_ref() {
            (
                (dp_score * 1000.0).round() as i64,
                candidate.linear_max_abs_error_bp,
                candidate.linear_mean_abs_error_bp,
                -candidate.linear_r2,
                candidate.peak_penalty,
                candidate.blended_score,
            ) < (
                (current_dp_score * 1000.0).round() as i64,
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.peak_penalty,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_candidate = Some((dp_score, candidate));
        }
    }

    best_candidate.map(|(_, candidate)| candidate)
}

fn repair_liz_blob_start_family_sequence(
    best: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || current.indices.len() != ladder_sizes.len()
        || current.linear_max_abs_error_bp <= 10.0
    {
        return None;
    }

    let selected_peaks = current
        .indices
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if selected_peaks.len() < ladder_sizes.len() / 2 {
        return None;
    }
    let selected_height_ref = median(
        &selected_peaks
            .iter()
            .skip(1)
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let first_blob = selected_peaks
        .first()
        .is_some_and(|peak| peak.height.max(1.0) > selected_height_ref * 5.0);
    let weak_selected = selected_peaks
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            height < 120.0 || baseline_ratio >= 0.42 || purity <= 0.50
        })
        .count();
    if !first_blob && weak_selected < 3 {
        return None;
    }

    let mut family_peaks = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1350..=5450).contains(&peak.index)
                && height >= 60.0
                && peak.prominence >= 40.0
                && (baseline_ratio <= 0.75 || purity >= 0.45)
        })
        .cloned()
        .collect::<Vec<_>>();
    family_peaks.sort_by_key(|peak| peak.index);
    family_peaks.dedup_by_key(|peak| peak.index);
    if family_peaks.len() < ladder_sizes.len() {
        return None;
    }

    let mut states = family_peaks
        .iter()
        .enumerate()
        .filter(|(_, peak)| (1400..=1800).contains(&peak.index))
        .map(|(idx, peak)| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let huge_non_blob_penalty = if height > 5000.0 { 20.0 } else { 0.0 };
            let weak_penalty = if height < 80.0 { 1.0 } else { 0.0 };
            (
                baseline_ratio * 4.0 + huge_non_blob_penalty + weak_penalty,
                vec![idx],
            )
        })
        .collect::<Vec<_>>();
    if states.is_empty() {
        return None;
    }

    for (step, expected_gap) in LIZ_BROAD_GAP_MEDIAN.iter().copied().enumerate() {
        let mut next_states: Vec<(f64, Vec<usize>)> = Vec::new();
        for (score, path) in states.iter() {
            let prev_idx = match path.last().copied() {
                Some(value) => value,
                None => continue,
            };
            let prev_scan = family_peaks[prev_idx].index;
            for (candidate_idx, peak) in family_peaks.iter().enumerate().skip(prev_idx + 1) {
                let gap = peak.index.saturating_sub(prev_scan);
                if gap < 12 {
                    continue;
                }
                if gap > 900 {
                    break;
                }
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.5);
                let huge_non_blob_penalty = if height > 5000.0 && ladder_sizes[step + 1] != 100.0 {
                    25.0
                } else {
                    0.0
                };
                let weak_penalty = if height < 100.0 { 2.0 } else { 0.0 };
                let tolerance = (expected_gap * 0.55).max(35.0);
                let gap_penalty =
                    ((gap as f64 - expected_gap).abs() - tolerance).max(0.0) / tolerance;

                let mut next_path = path.clone();
                next_path.push(candidate_idx);
                let mut partial_linear_penalty = 0.0;
                if next_path.len() >= 6 {
                    let trial = next_path
                        .iter()
                        .map(|idx| family_peaks[*idx].index)
                        .collect::<Vec<_>>();
                    let partial = score_combination(
                        &trial,
                        &ladder_sizes[..trial.len()],
                        ladder,
                        peak_feature_by_index,
                        &family_peaks,
                    );
                    partial_linear_penalty += partial.linear_mean_abs_error_bp * 0.50;
                    partial_linear_penalty +=
                        (partial.linear_max_abs_error_bp - 8.0).max(0.0) * 0.80;
                    partial_linear_penalty += (0.9970 - partial.linear_r2).max(0.0) * 500.0;
                }

                next_states.push((
                    score
                        + gap_penalty
                        + baseline_ratio * 4.0
                        + (0.60 - purity).max(0.0) * 3.0
                        + huge_non_blob_penalty
                        + weak_penalty
                        + partial_linear_penalty,
                    next_path,
                ));
            }
        }
        if next_states.is_empty() {
            return None;
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if next_states.len() > LIZ_BLOB_START_FAMILY_BEAM {
            next_states.truncate(LIZ_BLOB_START_FAMILY_BEAM);
        }
        states = next_states;
    }

    let mut best_candidate: Option<(f64, CombinationScore)> = None;
    for (dp_score, path) in states.into_iter().take(LIZ_BLOB_START_FAMILY_FINALISTS) {
        if path.len() != ladder_sizes.len() {
            continue;
        }
        let trial = path
            .iter()
            .map(|idx| family_peaks[*idx].index)
            .collect::<Vec<_>>();
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let candidate = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            &family_peaks,
        );
        if candidate.linear_max_abs_error_bp > 9.8
            || candidate.linear_mean_abs_error_bp > 4.05
            || candidate.linear_r2 < 0.99870
            || candidate.linear_max_abs_error_bp + 1.0 >= current.linear_max_abs_error_bp
        {
            continue;
        }
        let non_100_saturated = path.iter().enumerate().any(|(step, idx)| {
            ladder_sizes[step] != 100.0 && family_peaks[*idx].height.max(1.0) > 5000.0
        });
        if non_100_saturated {
            continue;
        }
        let candidate_weak = path
            .iter()
            .filter(|idx| family_peaks[**idx].height.max(1.0) < 100.0)
            .count();
        let candidate_prominences = path
            .iter()
            .map(|idx| family_peaks[*idx].prominence.max(1.0))
            .collect::<Vec<_>>();
        let candidate_prominence_ref = median(&candidate_prominences).max(1.0);
        let weak_family_outliers = path
            .iter()
            .filter(|idx| family_peaks[**idx].prominence.max(0.0) < candidate_prominence_ref * 0.18)
            .count();
        if candidate_weak > weak_selected.saturating_sub(2).max(1) || weak_family_outliers > 2 {
            continue;
        }
        let late_count = trial
            .iter()
            .filter(|scan| **scan > LIZ_SELECTED_LATE_REVIEW_SCAN)
            .count();
        if late_count > 2 {
            continue;
        }
        let should_take = if let Some((current_dp_score, current_best)) = best_candidate.as_ref() {
            (
                candidate.linear_max_abs_error_bp,
                candidate.linear_mean_abs_error_bp,
                -candidate.linear_r2,
                candidate_weak,
                (dp_score * 1000.0).round() as i64,
                candidate.peak_penalty,
                candidate.blended_score,
            ) < (
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                usize::MAX,
                (current_dp_score * 1000.0).round() as i64,
                current_best.peak_penalty,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            best_candidate = Some((dp_score, candidate));
        }
    }

    best_candidate.map(|(_, candidate)| candidate)
}

fn repair_liz_clean_late_tail_family_sequence(
    best: Option<&CombinationScore>,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> Option<CombinationScore> {
    let current = best?;
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || current.indices.len() != ladder_sizes.len()
        || current.linear_max_abs_error_bp <= 10.0
    {
        return None;
    }

    let selected_peaks = current
        .indices
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    let selected_height_ref = median(
        &selected_peaks
            .iter()
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let weak_selected = selected_peaks
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            height < selected_height_ref * 0.16 || baseline_ratio >= 0.42 || purity <= 0.50
        })
        .count();
    if weak_selected < 3 && current.linear_mean_abs_error_bp <= 4.5 {
        return None;
    }

    let mut family_peaks = peak_feature_by_index
        .values()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            (1350..=6100).contains(&peak.index)
                && height >= 30.0
                && peak.prominence >= 20.0
                && (baseline_ratio <= 0.75 || purity >= 0.45)
        })
        .cloned()
        .collect::<Vec<_>>();
    family_peaks.sort_by_key(|peak| peak.index);
    family_peaks.dedup_by_key(|peak| peak.index);
    if family_peaks.len() < ladder_sizes.len() {
        return None;
    }

    let anchor_bps = [400.0, 450.0, 490.0, 500.0];
    let mut best_candidate: Option<(f64, CombinationScore)> = None;
    for (first_idx, first_peak) in family_peaks.iter().enumerate() {
        if !(1400..=1800).contains(&first_peak.index) {
            continue;
        }
        let first_quality = liz_clean_late_tail_peak_quality(first_peak, ladder_sizes[0]);
        if first_quality >= 16.0 {
            continue;
        }
        for tail_peak in family_peaks.iter().skip(first_idx + 1) {
            if tail_peak.index < 3800 {
                continue;
            }
            for anchor_bp in anchor_bps {
                let denom = anchor_bp - ladder_sizes[0];
                if denom <= 0.0 {
                    continue;
                }
                let scan_per_bp = (tail_peak.index as f64 - first_peak.index as f64) / denom;
                if !(5.0..=16.0).contains(&scan_per_bp) {
                    continue;
                }
                let intercept = first_peak.index as f64 - scan_per_bp * ladder_sizes[0];
                let mut trial = Vec::with_capacity(ladder_sizes.len());
                let mut previous_scan = 0usize;
                let mut path_quality = 0.0;
                for bp in ladder_sizes {
                    let expected_scan = scan_per_bp * *bp + intercept;
                    let window = if *bp < 120.0 {
                        220.0
                    } else if *bp < 360.0 {
                        330.0
                    } else {
                        520.0
                    };
                    let best_peak = family_peaks
                        .iter()
                        .filter(|peak| peak.index > previous_scan)
                        .filter_map(|peak| {
                            let distance = (peak.index as f64 - expected_scan).abs();
                            if distance > window {
                                return None;
                            }
                            let quality =
                                distance / window + liz_clean_late_tail_peak_quality(peak, *bp);
                            Some((quality, peak.index))
                        })
                        .min_by(|left, right| {
                            left.0
                                .partial_cmp(&right.0)
                                .unwrap_or(std::cmp::Ordering::Equal)
                                .then_with(|| left.1.cmp(&right.1))
                        });
                    let Some((quality, scan)) = best_peak else {
                        trial.clear();
                        break;
                    };
                    trial.push(scan);
                    previous_scan = scan;
                    path_quality += quality;
                }
                if trial.len() != ladder_sizes.len()
                    || !trial.windows(2).all(|window| window[1] > window[0])
                {
                    continue;
                }
                let candidate = score_combination(
                    &trial,
                    ladder_sizes,
                    ladder,
                    peak_feature_by_index,
                    &family_peaks,
                );
                if candidate.linear_max_abs_error_bp > 9.8
                    || candidate.linear_mean_abs_error_bp > 4.05
                    || candidate.linear_r2 < 0.99870
                    || candidate.linear_max_abs_error_bp + 1.0 >= current.linear_max_abs_error_bp
                {
                    continue;
                }
                let late_count = trial
                    .iter()
                    .filter(|scan| **scan > LIZ_SELECTED_LATE_REVIEW_SCAN)
                    .count();
                if late_count > 2 || !liz_late_tail_is_clean(&trial, &family_peaks) {
                    continue;
                }
                let weak_count = trial
                    .iter()
                    .filter_map(|scan| peak_feature_by_index.get(scan))
                    .filter(|peak| peak.height.max(1.0) < 90.0)
                    .count();
                let trial_prominences = trial
                    .iter()
                    .filter_map(|scan| peak_feature_by_index.get(scan))
                    .map(|peak| peak.prominence.max(1.0))
                    .collect::<Vec<_>>();
                let trial_prominence_ref = median(&trial_prominences).max(1.0);
                let weak_family_outliers = trial
                    .iter()
                    .filter_map(|scan| peak_feature_by_index.get(scan))
                    .filter(|peak| peak.prominence.max(0.0) < trial_prominence_ref * 0.18)
                    .count();
                let saturated_non_100 = trial.iter().enumerate().any(|(idx, scan)| {
                    peak_feature_by_index.get(scan).is_some_and(|peak| {
                        ladder_sizes[idx] != 100.0 && peak.height.max(1.0) > 5000.0
                    })
                });
                if weak_count > 1 || weak_family_outliers > 2 || saturated_non_100 {
                    continue;
                }
                let rank = path_quality
                    + candidate.linear_max_abs_error_bp * 1.6
                    + candidate.linear_mean_abs_error_bp * 1.2
                    - candidate.linear_r2 * 2.0;
                let should_take =
                    if let Some((current_rank, current_best)) = best_candidate.as_ref() {
                        (
                            candidate.linear_max_abs_error_bp,
                            candidate.linear_mean_abs_error_bp,
                            rank,
                            candidate.peak_penalty,
                            candidate.blended_score,
                        ) < (
                            current_best.linear_max_abs_error_bp,
                            current_best.linear_mean_abs_error_bp,
                            *current_rank,
                            current_best.peak_penalty,
                            current_best.blended_score,
                        )
                    } else {
                        true
                    };
                if should_take {
                    best_candidate = Some((rank, candidate));
                }
            }
        }
    }

    best_candidate.map(|(_, candidate)| candidate)
}

fn liz_clean_late_tail_peak_quality(peak: &Peak, bp: f64) -> f64 {
    let height = peak.height.max(1.0);
    let prominence = peak.prominence.max(0.0);
    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
    let purity = (prominence / height).clamp(0.0, 1.5);
    baseline_ratio * 3.0
        + (0.55 - purity).max(0.0) * 2.0
        + if height < 90.0 { 0.5 } else { 0.0 }
        + if height > 5000.0 && bp != 100.0 {
            12.0
        } else {
            0.0
        }
}

fn repair_anchor_block_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if best.indices.len() != ladder_sizes.len() || best.indices.len() < 5 {
        return None;
    }
    if best.linear_mean_abs_error_bp <= BLOCK_REPAIR_LINEAR_MEAN_TRIGGER_BP
        && best.linear_max_abs_error_bp <= BLOCK_REPAIR_LINEAR_MAX_TRIGGER_BP
    {
        return None;
    }

    let block_ranges = candidate_block_ranges(ladder, best.indices.len());
    if block_ranges.is_empty() {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for (start, end) in block_ranges {
        let candidate_scans = block_candidate_scans(
            &best.indices,
            ladder_sizes,
            ladder,
            start,
            end,
            peak_feature_by_index,
            peak_features,
        );
        let block_len = end.saturating_sub(start) + 1;
        if candidate_scans.len() <= block_len {
            continue;
        }

        for replacement in generate_peak_combinations(
            &candidate_scans,
            block_len,
            usize::MAX,
            BLOCK_REPAIR_MAX_COMBINATIONS,
        ) {
            if replacement == best.indices[start..=end] {
                continue;
            }
            let mut trial = best.indices.clone();
            trial[start..=end].copy_from_slice(&replacement);
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }

            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            if !block_repair_is_material(best, &trial_score) {
                continue;
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                compare_block_repair_candidates(&trial_score, current_best)
                    == std::cmp::Ordering::Less
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_trial
}

fn repair_liz_linear_first_start_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 8
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }
    let suspicious_start = best.indices.len() >= 4
        && (best.indices[1].saturating_sub(best.indices[0]) < 95
            || best.indices[2].saturating_sub(best.indices[1]) > 190
            || best.indices[3].saturating_sub(best.indices[2]) > 185);
    let suspicious_tail = best.indices.len() >= 2
        && peak_feature_by_index
            .get(&best.indices[best.indices.len() - 1])
            .map(|last| {
                let score_ref = peak_feature_by_index
                    .get(&best.indices[best.indices.len() - 2])
                    .map(|peak| peak.score.max(1.0))
                    .unwrap_or(1.0);
                let stronger_nearby = peak_features.iter().any(|peak| {
                    peak.index + 8 < last.index
                        && last.index.saturating_sub(peak.index) <= 180
                        && peak.score >= score_ref * 0.75
                        && peak.score >= last.score * 2.0
                });
                stronger_nearby && last.score < score_ref * 0.35
            })
            .unwrap_or(false);
    let should_try = best.linear_max_abs_error_bp > 10.0
        || best.linear_mean_abs_error_bp > 5.0
        || best.linear_r2 < 0.9986
        || ((best.linear_max_abs_error_bp > 5.0 || best.linear_mean_abs_error_bp > 2.5)
            && (suspicious_start || suspicious_tail));
    if !should_try {
        return None;
    }

    let anchor_scan = best.indices[4];
    let tail_reference_heights = best
        .indices
        .iter()
        .skip(4)
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let tail_reference_scores = best
        .indices
        .iter()
        .skip(4)
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.score))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if tail_reference_heights.is_empty() || tail_reference_scores.is_empty() {
        return None;
    }
    let height_ref = median(&tail_reference_heights).max(1.0);
    let score_ref = median(&tail_reference_scores).max(1.0);

    let mut early_candidates = peak_features
        .iter()
        .filter(|peak| peak.index >= 1400 && peak.index + 8 < anchor_scan)
        .filter(|peak| peak.index <= anchor_scan.saturating_sub(10))
        .filter(|peak| liz_linear_first_peak_is_plausible(peak, height_ref, score_ref))
        .cloned()
        .collect::<Vec<_>>();
    if early_candidates.len() < 4 {
        return None;
    }

    early_candidates.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if early_candidates.len() > LIZ_LINEAR_FIRST_START_REPAIR_MAX_EARLY_PEAKS {
        early_candidates.truncate(LIZ_LINEAR_FIRST_START_REPAIR_MAX_EARLY_PEAKS);
    }
    early_candidates.sort_by_key(|peak| peak.index);

    let early_indices = early_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    let replacements = generate_peak_combinations(
        &early_indices,
        4,
        usize::MAX,
        LIZ_LINEAR_FIRST_START_REPAIR_MAX_COMBINATIONS,
    );
    if replacements.is_empty() {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for replacement in replacements {
        if replacement[3] >= anchor_scan.saturating_sub(6) {
            continue;
        }
        let mut trial = best.indices.clone();
        trial[..4].copy_from_slice(&replacement);
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }

        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if !liz_linear_first_candidate_is_acceptable(best, &trial_score, peak_feature_by_index) {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_liz_linear_first_candidates(&trial_score, current_best)
                == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_linear_start_and_tail_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || best.indices.len() != ladder_sizes.len()
        || best.indices.len() < 10
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }

    let suspicious_start = best.indices[1].saturating_sub(best.indices[0]) < 95
        || best.indices[2].saturating_sub(best.indices[1]) > 190
        || best.indices[3].saturating_sub(best.indices[2]) > 185;
    let suspicious_tail = peak_feature_by_index
        .get(best.indices.last().unwrap_or(&0))
        .map(|last| {
            let prev_score = peak_feature_by_index
                .get(&best.indices[best.indices.len() - 2])
                .map(|peak| peak.score.max(1.0))
                .unwrap_or(1.0);
            peak_features.iter().any(|peak| {
                peak.index + 8 < last.index
                    && last.index.saturating_sub(peak.index) <= 180
                    && peak.score >= prev_score * 0.75
                    && peak.score >= last.score * 2.0
            })
        })
        .unwrap_or(false);
    if !((best.linear_max_abs_error_bp > 5.0 || best.linear_mean_abs_error_bp > 2.5)
        && suspicious_start
        && suspicious_tail)
    {
        return None;
    }

    let anchor_scan = best.indices[4];
    let tail_block_len = if *best.indices.last().unwrap_or(&0) < 4400 {
        4
    } else {
        2
    };
    let tail_anchor_idx = best.indices.len().saturating_sub(tail_block_len + 1);
    let tail_left_bound = best.indices[tail_anchor_idx];
    let tail_reference_heights = best
        .indices
        .iter()
        .skip(4)
        .take(best.indices.len().saturating_sub(6))
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let tail_reference_scores = best
        .indices
        .iter()
        .skip(4)
        .take(best.indices.len().saturating_sub(6))
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.score))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    if tail_reference_heights.is_empty() || tail_reference_scores.is_empty() {
        return None;
    }
    let height_ref = median(&tail_reference_heights).max(1.0);
    let score_ref = median(&tail_reference_scores).max(1.0);

    let mut early_candidates = peak_features
        .iter()
        .filter(|peak| peak.index >= 1400 && peak.index + 8 < anchor_scan)
        .filter(|peak| liz_linear_first_peak_is_plausible(peak, height_ref, score_ref))
        .cloned()
        .collect::<Vec<_>>();
    early_candidates.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    if early_candidates.len() > LIZ_LINEAR_FIRST_START_REPAIR_MAX_EARLY_PEAKS {
        early_candidates.truncate(LIZ_LINEAR_FIRST_START_REPAIR_MAX_EARLY_PEAKS);
    }
    early_candidates.sort_by_key(|peak| peak.index);
    let early_indices = early_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    let early_replacements = generate_peak_combinations(
        &early_indices,
        4,
        usize::MAX,
        LIZ_LINEAR_FIRST_START_REPAIR_MAX_COMBINATIONS,
    );
    if early_replacements.is_empty() {
        return None;
    }

    let mut tail_candidates = peak_features
        .iter()
        .filter(|peak| peak.index > tail_left_bound.saturating_add(20))
        .filter(|peak| peak.index <= best.indices[best.indices.len() - 1].saturating_add(420))
        .filter(|peak| {
            peak.score >= score_ref * 0.20
                && peak.prominence >= 40.0
                && peak.height >= height_ref * 0.18
        })
        .cloned()
        .collect::<Vec<_>>();
    tail_candidates.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    tail_candidates.truncate(12);
    tail_candidates.sort_by_key(|peak| peak.index);
    let tail_indices = tail_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    let tail_replacements = generate_peak_combinations(
        &tail_indices,
        tail_block_len,
        usize::MAX,
        if tail_block_len >= 4 { 512 } else { 64 },
    );
    if tail_replacements.is_empty() {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for early in &early_replacements {
        if early[3] >= anchor_scan.saturating_sub(6) {
            continue;
        }
        for tail in &tail_replacements {
            if tail[0] <= tail_left_bound.saturating_add(10) {
                continue;
            }
            let mut trial = best.indices.clone();
            trial[..4].copy_from_slice(early);
            let len = trial.len();
            let tail_start = len.saturating_sub(tail_block_len);
            trial[tail_start..].copy_from_slice(tail);
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }

            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            if !liz_linear_first_candidate_is_acceptable(best, &trial_score, peak_feature_by_index)
            {
                continue;
            }

            let should_take = if let Some(current_best) = best_trial.as_ref() {
                compare_liz_linear_first_candidates(&trial_score, current_best)
                    == std::cmp::Ordering::Less
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_trial
}

fn repair_liz_mid_triplet_outlier_only_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }

    const TRIPLET_START: usize = 4; // LIZ 139/150/160 bp
    let current_triplet = &best.indices[TRIPLET_START..=TRIPLET_START + 2];
    let current_peaks = current_triplet
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if current_peaks.len() != 3 {
        return None;
    }
    let current_heights = current_peaks
        .iter()
        .map(|peak| peak.height.max(1.0))
        .collect::<Vec<_>>();
    let current_height_ref = median(&current_heights).max(1.0);
    let current_max_height = current_heights.iter().copied().fold(0.0, f64::max);
    let current_gap_150_160 = current_triplet[2].saturating_sub(current_triplet[1]);
    let triplet_has_blob_outlier = current_max_height >= 1200.0
        && current_max_height >= current_height_ref * 4.0
        && current_gap_150_160 > 110;
    if !triplet_has_blob_outlier {
        return None;
    }

    let mut triplet_pool = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.index >= current_triplet[0].saturating_sub(80)
                && peak.index <= current_triplet[2].saturating_add(35)
                && peak.height >= 28.0
                && peak.prominence >= 20.0
                && peak.score >= 28.0
                && (baseline_ratio <= 0.58 || purity >= 0.42)
        })
        .cloned()
        .collect::<Vec<_>>();
    if triplet_pool.len() < 3 {
        return None;
    }
    triplet_pool.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.35 + left_purity * 40.0 - left_baseline_ratio * 220.0;
        let right_rank = right.score + right.prominence * 0.35 + right_purity * 40.0
            - right_baseline_ratio * 220.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    triplet_pool.truncate(16);
    triplet_pool.sort_by_key(|peak| peak.index);
    let triplet_indices = triplet_pool
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let mut best_trial: Option<CombinationScore> = None;
    for triplet in generate_peak_combinations(&triplet_indices, 3, usize::MAX, 512) {
        if triplet == current_triplet {
            continue;
        }
        let gap_139_150 = triplet[1].saturating_sub(triplet[0]) as f64;
        let gap_150_160 = triplet[2].saturating_sub(triplet[1]) as f64;
        let span = triplet[2].saturating_sub(triplet[0]) as f64;
        if !(24.0..=92.0).contains(&gap_139_150)
            || !(24.0..=96.0).contains(&gap_150_160)
            || span > 150.0
        {
            continue;
        }
        let ratio = gap_139_150 / gap_150_160.max(1.0);
        if !(0.35..=2.25).contains(&ratio) {
            continue;
        }
        let trial_peaks = triplet
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .collect::<Vec<_>>();
        if trial_peaks.len() != 3 {
            continue;
        }
        let trial_heights = trial_peaks
            .iter()
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>();
        let trial_height_ref = median(&trial_heights).max(1.0);
        let trial_max_height = trial_heights.iter().copied().fold(0.0, f64::max);
        if trial_height_ref < current_height_ref * 0.20
            || trial_max_height > current_max_height * 0.35
        {
            continue;
        }

        let mut indices = best.indices.clone();
        indices[TRIPLET_START] = triplet[0];
        indices[TRIPLET_START + 1] = triplet[1];
        indices[TRIPLET_START + 2] = triplet[2];
        if !indices.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &indices,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let compelling_blob_triplet_repair = trial_score.linear_max_abs_error_bp + 2.0
            < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 1.25
            && trial_score.linear_mean_abs_error_bp <= 3.8
            && trial_score.linear_max_abs_error_bp <= 10.2
            && trial_score.linear_r2 + 0.00025 >= best.linear_r2
            && trial_score.peak_penalty <= best.peak_penalty + 4.0
            && trial_score.domain_penalty <= best.domain_penalty + 6.0;
        if !compelling_blob_triplet_repair {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_liz_linear_first_candidates(&trial_score, current_best)
                == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_tail_pair_split_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    let current_gap = best.indices[15].saturating_sub(best.indices[14]);
    let expected_gap = LIZ_BROAD_GAP_MEDIAN[14];
    if current_gap >= 30 {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.is_empty() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);
    let lower_bound = best.indices[13].saturating_add(12);
    let upper_bound = best.indices[15].saturating_add(90).min(4620);

    let mut tail_candidates = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.index > lower_bound
                && peak.index <= upper_bound
                && peak.height >= 18.0
                && peak.prominence >= 16.0
                && peak.score >= 28.0
                && peak.height <= family_height_ref * 3.0
                && (baseline_ratio <= 0.55 || purity >= 0.42)
        })
        .cloned()
        .collect::<Vec<_>>();
    if tail_candidates.len() < 2 {
        return None;
    }
    tail_candidates.sort_by(|left, right| {
        let left_height = left.height.max(1.0);
        let right_height = right.height.max(1.0);
        let left_baseline_ratio = (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
        let right_baseline_ratio = (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
        let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
        let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
        let left_rank =
            left.score + left.prominence * 0.35 + left_purity * 35.0 - left_baseline_ratio * 180.0;
        let right_rank = right.score + right.prominence * 0.35 + right_purity * 35.0
            - right_baseline_ratio * 180.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    tail_candidates.truncate(12);
    tail_candidates.sort_by_key(|peak| peak.index);
    let candidate_indices = tail_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let current_gap_error = (current_gap as f64 - expected_gap).abs();
    let mut best_trial: Option<CombinationScore> = None;
    for pair in generate_peak_combinations(&candidate_indices, 2, usize::MAX, 256) {
        let trial_gap = pair[1].saturating_sub(pair[0]) as f64;
        if !(34.0..=72.0).contains(&trial_gap) {
            continue;
        }
        let trial_gap_error = (trial_gap - expected_gap).abs();
        if trial_gap_error + 18.0 >= current_gap_error {
            continue;
        }
        let mut indices = best.indices.clone();
        indices[14] = pair[0];
        indices[15] = pair[1];
        if !indices.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &indices,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        let keeps_review_safe_profile = trial_score.linear_max_abs_error_bp <= 10.0
            && trial_score.linear_mean_abs_error_bp <= 4.5
            && trial_score.linear_r2 >= 0.9985;
        let acceptable_tradeoff = trial_score.linear_max_abs_error_bp
            <= best.linear_max_abs_error_bp + 0.85
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.70
            && trial_score.linear_r2 + 0.00030 >= best.linear_r2;
        let improves_curved_tail = trial_score.quadratic_r2 > best.quadratic_r2 + 0.00004;
        if !(keeps_review_safe_profile && acceptable_tradeoff && improves_curved_tail) {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_liz_linear_first_candidates(&trial_score, current_best)
                == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_weak_tail_doublet_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.len() != best.indices.len() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);
    let tail_peak = peak_feature_by_index.get(&best.indices[15])?;
    if tail_peak.height > 120.0 && tail_peak.height > family_height_ref * 0.18 {
        return None;
    }

    let lower_bound = best.indices[13].saturating_add(120);
    let upper_bound = best.indices[15].saturating_add(20).min(5000);
    let mut candidate_indices = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.index >= lower_bound
                && peak.index <= upper_bound
                && peak.height >= family_height_ref * 0.25
                && peak.prominence >= family_height_ref * 0.18
                && peak.height <= family_height_ref * 2.25
                && baseline_ratio <= 0.24
                && purity >= 0.62
        })
        .map(|peak| peak.index)
        .collect::<Vec<_>>();
    candidate_indices.sort_unstable();
    candidate_indices.dedup();
    if candidate_indices.len() < 2 {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for pair in generate_peak_combinations(&candidate_indices, 2, usize::MAX, 128) {
        let gap = pair[1].saturating_sub(pair[0]);
        if !(34..=72).contains(&gap) {
            continue;
        }
        let mut trial = best.indices.clone();
        trial[14] = pair[0];
        trial[15] = pair[1];
        if !trial.windows(2).all(|window| window[1] > window[0]) {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 7.2
            || trial_score.linear_mean_abs_error_bp > 2.6
            || trial_score.linear_r2 < 0.99955
            || trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 1.25
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.20
            || trial_score.linear_r2 + 0.00005 < best.linear_r2
            || trial_score.peak_penalty > best.peak_penalty + 2.5
        {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.linear_max_abs_error_bp,
                trial_score.peak_penalty,
            ) < (
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.linear_max_abs_error_bp,
                current_best.peak_penalty,
            )
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_start_triplet_shift_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if best.linear_mean_abs_error_bp < 3.4 || best.linear_max_abs_error_bp > 9.2 {
        return None;
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.is_empty() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);

    let pick_best_between = |lo: usize, hi: usize| -> Option<usize> {
        peak_features
            .iter()
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                peak.index > lo
                    && peak.index < hi
                    && peak.height >= family_height_ref * 0.18
                    && peak.prominence >= family_height_ref * 0.16
                    && peak.score >= 80.0
                    && peak.height <= family_height_ref * 3.5
                    && (baseline_ratio <= 0.45 || purity >= 0.48)
            })
            .max_by(|left, right| {
                let left_height = left.height.max(1.0);
                let right_height = right.height.max(1.0);
                let left_baseline_ratio =
                    (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
                let right_baseline_ratio =
                    (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
                let left_rank = left.score + left.prominence * 0.35 - left_baseline_ratio * 240.0;
                let right_rank =
                    right.score + right.prominence * 0.35 - right_baseline_ratio * 240.0;
                left_rank
                    .partial_cmp(&right_rank)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|peak| peak.index)
    };

    let new_100 = pick_best_between(
        best.indices[3].saturating_add(45),
        best.indices[4].saturating_sub(30),
    )?;
    let new_160 = pick_best_between(
        best.indices[6].saturating_add(35),
        best.indices[7].saturating_sub(35),
    )?;

    let mut trial = best.indices.clone();
    trial[0] = best.indices[1];
    trial[1] = best.indices[2];
    trial[2] = best.indices[3];
    trial[3] = new_100;
    trial[4] = best.indices[5];
    trial[5] = best.indices[6];
    trial[6] = new_160;

    if !trial.windows(2).all(|window| window[1] > window[0]) {
        return None;
    }
    let trial_score = score_combination(
        &trial,
        ladder_sizes,
        ladder,
        peak_feature_by_index,
        peak_features,
    );
    let strong_profile = trial_score.linear_max_abs_error_bp <= 6.5
        && trial_score.linear_mean_abs_error_bp <= 2.6
        && trial_score.linear_r2 >= 0.99945;
    let material_win = trial_score.linear_max_abs_error_bp + 1.4 < best.linear_max_abs_error_bp
        && trial_score.linear_mean_abs_error_bp + 1.0 < best.linear_mean_abs_error_bp;
    if strong_profile && material_win {
        Some(trial_score)
    } else {
        None
    }
}

fn repair_liz_shifted_start_mid_family_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }
    if best.linear_max_abs_error_bp <= 6.5
        && best.linear_mean_abs_error_bp <= 2.4
        && best.linear_r2 >= 0.99935
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_peaks = best
        .indices
        .iter()
        .filter_map(|scan| augmented_peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if selected_peaks.len() != best.indices.len() {
        return None;
    }
    let family_height_ref = median(
        &selected_peaks
            .iter()
            .map(|peak| peak.height.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    let family_prominence_ref = median(
        &selected_peaks
            .iter()
            .map(|peak| peak.prominence.max(1.0))
            .collect::<Vec<_>>(),
    )
    .max(1.0);
    if family_height_ref < 180.0 || family_prominence_ref < 80.0 {
        return None;
    }

    let suspicious_selected = selected_peaks
        .iter()
        .take(7)
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
            height > family_height_ref * 3.5
                || height < family_height_ref * 0.20
                || baseline_ratio > 0.42
                || purity < 0.45
        })
        .count();
    let start_cluster = peak_features
        .iter()
        .filter(|peak| {
            peak.index >= best.indices[0].saturating_sub(20)
                && peak.index <= best.indices[1].saturating_add(45)
                && peak.height >= 20.0
                && peak.prominence >= 18.0
        })
        .count();
    let mid_gap_suspicious = best.indices[6].saturating_sub(best.indices[4]) < 170
        || best.indices[7].saturating_sub(best.indices[6]) > 260;
    if suspicious_selected == 0
        && start_cluster < 4
        && !mid_gap_suspicious
        && best.linear_max_abs_error_bp <= 8.0
    {
        return None;
    }

    let good_peak = |peak: &Peak, bp: f64| {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        height >= family_height_ref * 0.18
            && height >= 80.0
            && peak.prominence >= family_prominence_ref * 0.14
            && peak.prominence >= 45.0
            && baseline_ratio <= 0.48
            && purity >= 0.44
            && (bp >= 139.0 || height <= family_height_ref * 3.8)
            && height <= family_height_ref * (if bp >= 139.0 { 9.0 } else { 3.8 })
    };

    let candidate_scans_between = |lo: usize, hi: usize, bp: f64| -> Vec<usize> {
        if hi <= lo {
            return Vec::new();
        }
        let mut candidates = peak_features
            .iter()
            .filter(|peak| peak.index > lo && peak.index < hi && good_peak(peak, bp))
            .map(|peak| peak.index)
            .collect::<Vec<_>>();
        candidates.sort_unstable();
        candidates.dedup();
        candidates
    };

    let current_plausibility =
        peak_plausibility_penalty(&best.indices, &augmented_peak_feature_by_index);
    let mut best_trial: Option<CombinationScore> = None;
    let consider = |trial: Vec<usize>, best_trial: &mut Option<CombinationScore>| {
        if trial.len() != ladder_sizes.len()
            || trial == best.indices
            || !trial.windows(2).all(|window| window[1] > window[0])
        {
            return;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &augmented_peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 10.0
            || trial_score.linear_mean_abs_error_bp > 4.35
            || trial_score.linear_r2 < 0.99845
        {
            return;
        }
        let trial_plausibility =
            peak_plausibility_penalty(&trial_score.indices, &augmented_peak_feature_by_index);
        let linear_win = trial_score.linear_max_abs_error_bp + 0.35 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.55
            && trial_score.linear_r2 + 0.00020 >= best.linear_r2;
        let plausibility_win = trial_plausibility + 0.14 < current_plausibility
            && trial_score.linear_max_abs_error_bp <= best.linear_max_abs_error_bp + 0.65
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.75
            && trial_score.linear_r2 + 0.00035 >= best.linear_r2;
        let strong_rescue = trial_score.linear_max_abs_error_bp <= 7.2
            && trial_score.linear_mean_abs_error_bp <= 3.0
            && trial_score.linear_r2 >= 0.99925
            && trial_plausibility <= current_plausibility + 0.05;
        if !(linear_win || plausibility_win || strong_rescue) {
            return;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            (
                trial_plausibility,
                trial_score.linear_max_abs_error_bp,
                trial_score.linear_mean_abs_error_bp,
                -trial_score.linear_r2,
                trial_score.peak_penalty,
                trial_score.blended_score,
            ) < (
                peak_plausibility_penalty(&current_best.indices, &augmented_peak_feature_by_index),
                current_best.linear_max_abs_error_bp,
                current_best.linear_mean_abs_error_bp,
                -current_best.linear_r2,
                current_best.peak_penalty,
                current_best.blended_score,
            )
        } else {
            true
        };
        if should_take {
            *best_trial = Some(trial_score);
        }
    };

    if best.indices[0] < 1580 || selected_peaks[0].height.max(1.0) > family_height_ref * 2.8 {
        let lo = best.indices[6].saturating_add(18);
        let hi = best.indices[7].saturating_sub(18);
        for new_160 in candidate_scans_between(lo, hi, 160.0).into_iter().take(12) {
            let mut trial = best.indices.clone();
            for step in 0..=5 {
                trial[step] = best.indices[step + 1];
            }
            trial[6] = new_160;
            consider(trial, &mut best_trial);
        }
    }

    if best.indices[4] < best.indices[5] && best.indices[6] < best.indices[7] {
        let lo = best.indices[6].saturating_add(18);
        let hi = best.indices[7].saturating_sub(18);
        for new_160 in candidate_scans_between(lo, hi, 160.0).into_iter().take(12) {
            let mut trial = best.indices.clone();
            trial[4] = best.indices[5];
            trial[5] = best.indices[6];
            trial[6] = new_160;
            consider(trial, &mut best_trial);
        }
    }

    if selected_peaks[0].height.max(1.0) > family_height_ref * 2.4
        || (start_cluster >= 4 && best.indices[0] < 1540)
    {
        let lo = best.indices[0].saturating_add(10);
        let hi = best.indices[1].saturating_sub(8);
        for new_35 in candidate_scans_between(lo, hi, 35.0).into_iter().take(8) {
            let mut trial = best.indices.clone();
            trial[0] = new_35;
            consider(trial, &mut best_trial);
        }
    }

    best_trial
}

fn repair_liz_weak_tail_apex_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.is_empty() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);

    let mut candidate_sets: Vec<Vec<usize>> = Vec::new();
    for step in 12..16 {
        let current = best.indices[step];
        let mut candidates = vec![current];
        let lo = if step == 12 {
            best.indices[11].saturating_add(25)
        } else {
            best.indices[step - 1].saturating_sub(5)
        };
        let hi = if step == 15 {
            current.saturating_add(90).min(4620)
        } else {
            best.indices[step + 1].saturating_add(90).min(4620)
        };
        let current_height = peak_feature_by_index
            .get(&current)
            .map(|peak| peak.height.max(1.0))
            .unwrap_or(1.0);
        let previous_tail_weak = step == 15
            && peak_feature_by_index
                .get(&best.indices[14])
                .map(|peak| peak.height.max(1.0) <= family_height_ref * 0.10)
                .unwrap_or(true);
        let required_height_vs_current = if previous_tail_weak { 0.70 } else { 5.0 };
        for peak in peak_feature_by_index.values() {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            if peak.index <= lo
                || peak.index > hi
                || peak.index.abs_diff(current) > 110
                || height < family_height_ref * 0.22
                || height < current_height * required_height_vs_current
                || peak.prominence < family_height_ref * 0.18
                || baseline_ratio > 0.35
                || purity < 0.58
            {
                continue;
            }
            candidates.push(peak.index);
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.len() > 5 {
            candidates.sort_by(|left, right| {
                let left_peak = peak_feature_by_index.get(left);
                let right_peak = peak_feature_by_index.get(right);
                let left_rank = left_peak
                    .map(|peak| peak.score + peak.prominence * 0.35)
                    .unwrap_or(0.0);
                let right_rank = right_peak
                    .map(|peak| peak.score + peak.prominence * 0.35)
                    .unwrap_or(0.0);
                right_rank
                    .partial_cmp(&left_rank)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            candidates.truncate(5);
            candidates.sort_unstable();
        }
        candidate_sets.push(candidates);
    }

    let mut best_trial: Option<(CombinationScore, usize)> = None;
    for s12 in &candidate_sets[0] {
        for s13 in &candidate_sets[1] {
            for s14 in &candidate_sets[2] {
                for s15 in &candidate_sets[3] {
                    let tail = [*s12, *s13, *s14, *s15];
                    if !tail.windows(2).all(|window| window[1] > window[0]) {
                        continue;
                    }
                    if tail == best.indices[12..16] {
                        continue;
                    }
                    let mut improved_weak_steps = 0usize;
                    for (offset, candidate_scan) in tail.iter().enumerate() {
                        let step = 12 + offset;
                        let current_scan = best.indices[step];
                        let current_height = peak_feature_by_index
                            .get(&current_scan)
                            .map(|peak| peak.height.max(1.0))
                            .unwrap_or(1.0);
                        let candidate_height = peak_feature_by_index
                            .get(candidate_scan)
                            .map(|peak| peak.height.max(1.0))
                            .unwrap_or(1.0);
                        if current_height <= family_height_ref * 0.10
                            && candidate_height >= family_height_ref * 0.28
                            && candidate_height >= current_height * 8.0
                        {
                            improved_weak_steps += 1;
                        }
                    }
                    if improved_weak_steps == 0 {
                        continue;
                    }
                    let mut trial = best.indices.clone();
                    trial[12..16].copy_from_slice(&tail);
                    let trial_score = score_combination(
                        &trial,
                        ladder_sizes,
                        ladder,
                        peak_feature_by_index,
                        peak_features,
                    );
                    let keeps_review_safe_profile = trial_score.linear_max_abs_error_bp <= 10.0
                        && trial_score.linear_mean_abs_error_bp <= 4.5
                        && trial_score.linear_r2 >= 0.9985;
                    let acceptable_tradeoff = trial_score.linear_max_abs_error_bp
                        <= best.linear_max_abs_error_bp + 2.20
                        && trial_score.linear_mean_abs_error_bp
                            <= best.linear_mean_abs_error_bp + 1.00
                        && trial_score.linear_r2 + 0.00045 >= best.linear_r2;
                    if !(keeps_review_safe_profile && acceptable_tradeoff) {
                        continue;
                    }
                    let should_take = if let Some((current_best, current_improved)) =
                        best_trial.as_ref()
                    {
                        improved_weak_steps > *current_improved
                            || (improved_weak_steps == *current_improved
                                && compare_liz_linear_first_candidates(&trial_score, current_best)
                                    == std::cmp::Ordering::Less)
                    } else {
                        true
                    };
                    if should_take {
                        best_trial = Some((trial_score, improved_weak_steps));
                    }
                }
            }
        }
    }

    best_trial.map(|(score, _)| score)
}

fn repair_liz_weak_anchor_block_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.len() != best.indices.len() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);
    if family_height_ref < 250.0 {
        return None;
    }

    let weak_anchor = |scan: usize| {
        augmented_peak_feature_by_index
            .get(&scan)
            .map(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
                height <= family_height_ref * 0.18
                    || height < 120.0
                    || (height <= family_height_ref * 0.28
                        && (baseline_ratio >= 0.30 || purity <= 0.65))
            })
            .unwrap_or(true)
    };
    let current_weak_count = best
        .indices
        .iter()
        .filter(|scan| weak_anchor(**scan))
        .count();
    if current_weak_count == 0 || current_weak_count > 6 {
        return None;
    }

    let mut ranges = Vec::new();
    for step in 0..best.indices.len() {
        if !weak_anchor(best.indices[step]) {
            continue;
        }
        ranges.push((step, step));
        if step > 0 {
            ranges.push((step - 1, step));
        }
        if step + 1 < best.indices.len() {
            ranges.push((step, step + 1));
        }
    }
    ranges.sort_unstable();
    ranges.dedup();

    let mut best_trial: Option<(CombinationScore, usize)> = None;
    for (start, end) in ranges {
        let block_len = end - start + 1;
        let lo = if start == 0 {
            best.indices[start].saturating_sub(140)
        } else {
            best.indices[start - 1].saturating_add(18)
        };
        let hi = if end + 1 >= best.indices.len() {
            best.indices[end].saturating_add(170).min(5000)
        } else {
            best.indices[end + 1].saturating_sub(18)
        };
        if hi <= lo {
            continue;
        }

        let mut candidates = best.indices[start..=end].to_vec();
        for peak in augmented_peak_feature_by_index.values() {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
            let near_block =
                (start..=end).any(|step| peak.index.abs_diff(best.indices[step]) <= 115);
            if peak.index <= lo
                || peak.index >= hi
                || !near_block
                || height < family_height_ref * 0.25
                || peak.prominence < family_height_ref * 0.18
                || baseline_ratio > 0.35
                || purity < 0.58
            {
                continue;
            }
            candidates.push(peak.index);
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.len() <= block_len {
            continue;
        }

        for replacement in generate_peak_combinations(&candidates, block_len, usize::MAX, 96) {
            if replacement == best.indices[start..=end] {
                continue;
            }
            let mut trial = best.indices.clone();
            trial[start..=end].copy_from_slice(&replacement);
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }

            let trial_weak_count = trial.iter().filter(|scan| weak_anchor(**scan)).count();
            if trial_weak_count >= current_weak_count {
                continue;
            }
            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                &augmented_peak_feature_by_index,
                peak_features,
            );
            if trial_score.linear_max_abs_error_bp > 10.0
                || trial_score.linear_mean_abs_error_bp > 4.5
                || trial_score.linear_r2 < 0.9985
                || trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 2.20
                || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 1.00
                || trial_score.linear_r2 + 0.00045 < best.linear_r2
            {
                continue;
            }

            let should_take = if let Some((current_best, current_weak)) = best_trial.as_ref() {
                trial_weak_count < *current_weak
                    || (trial_weak_count == *current_weak
                        && compare_liz_linear_first_candidates(&trial_score, current_best)
                            == std::cmp::Ordering::Less)
            } else {
                true
            };
            if should_take {
                best_trial = Some((trial_score, trial_weak_count));
            }
        }
    }

    best_trial.map(|(score, _)| score)
}

fn repair_liz_weak_suffix_apex_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .filter(|height| (80.0..=5000.0).contains(height))
        .collect::<Vec<_>>();
    let family_height_ref = median(&selected_heights).max(1.0);
    if family_height_ref < 180.0 {
        return None;
    }

    let weak_anchor = |scan: usize| {
        augmented_peak_feature_by_index
            .get(&scan)
            .map(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
                height < 120.0
                    || height <= family_height_ref * 0.16
                    || (height <= family_height_ref * 0.30
                        && (baseline_ratio >= 0.30 || purity <= 0.65))
            })
            .unwrap_or(true)
    };
    let weak_steps = best
        .indices
        .iter()
        .enumerate()
        .filter_map(|(step, scan)| weak_anchor(*scan).then_some(step))
        .collect::<Vec<_>>();
    let suffix_weak_steps = weak_steps
        .iter()
        .copied()
        .filter(|step| *step >= 8)
        .collect::<Vec<_>>();
    if suffix_weak_steps.len() < 2 {
        return None;
    }
    let suffix_start = *suffix_weak_steps.iter().min().unwrap_or(&8);

    let clean_peak = |peak: &Peak| {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        height >= 80.0
            && height <= 12000.0
            && peak.prominence >= 50.0
            && baseline_ratio <= 0.55
            && purity >= 0.25
            && (height >= family_height_ref * 0.10 || height >= 600.0)
    };

    let mut candidate_lists: Vec<(usize, Vec<usize>)> = Vec::new();
    for step in suffix_start..best.indices.len() {
        let current = best.indices[step];
        let mut candidates = vec![current];
        for peak in augmented_peak_feature_by_index.values() {
            if !clean_peak(peak) {
                continue;
            }
            let local_radius = if step >= 13 { 180 } else { 145 };
            if peak.index.abs_diff(current) <= local_radius {
                candidates.push(peak.index);
            }
            if step + 1 < best.indices.len() && peak.index == best.indices[step + 1] {
                candidates.push(peak.index);
            }
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.len() > 8 {
            candidates.sort_by(|left, right| {
                let rank = |idx: &usize| {
                    augmented_peak_feature_by_index
                        .get(idx)
                        .map(|peak| {
                            let height = peak.height.max(1.0);
                            let baseline_ratio =
                                (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                            let selected_bonus = if *idx == current { -1.5 } else { 0.0 };
                            (*idx).abs_diff(current) as f64 / 60.0
                                - height.min(3000.0) / 1500.0
                                - peak.prominence.max(0.0).min(2500.0) / 1800.0
                                + baseline_ratio * 2.0
                                + selected_bonus
                        })
                        .unwrap_or(20.0)
                };
                rank(left)
                    .partial_cmp(&rank(right))
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| left.cmp(right))
            });
            candidates.truncate(8);
            candidates.sort_unstable();
        }
        candidate_lists.push((step, candidates));
    }

    let mut states: Vec<(f64, Vec<usize>)> = vec![(0.0, best.indices[..suffix_start].to_vec())];
    for (step, candidates) in candidate_lists {
        let expected_gap = LIZ_BROAD_GAP_MEDIAN[step - 1];
        let min_gap = (expected_gap - 130.0).max(20.0);
        let max_gap = expected_gap + 170.0;
        let mut next_states: Vec<(f64, Vec<usize>)> = Vec::new();
        for (state_score, state) in states.iter() {
            let previous = state.last().copied().unwrap_or(0);
            for candidate in candidates.iter().copied() {
                if candidate <= previous.saturating_add(5) {
                    continue;
                }
                let gap = candidate.saturating_sub(previous) as f64;
                if gap < min_gap || gap > max_gap {
                    continue;
                }
                let peak = augmented_peak_feature_by_index.get(&candidate);
                let (height, prominence, baseline_ratio, purity) = peak
                    .map(|peak| {
                        let height = peak.height.max(1.0);
                        (
                            height,
                            peak.prominence.max(0.0),
                            (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5),
                            (peak.prominence.max(0.0) / height).clamp(0.0, 1.5),
                        )
                    })
                    .unwrap_or((1.0, 0.0, 1.5, 0.0));
                let current_weak_penalty =
                    if weak_anchor(best.indices[step]) && candidate == best.indices[step] {
                        2.0
                    } else {
                        0.0
                    };
                let score = *state_score
                    + (gap - expected_gap).abs() / 60.0
                    + baseline_ratio * 2.0
                    + (0.50 - purity).max(0.0) * 2.0
                    - height.min(3000.0) / 2500.0
                    - prominence.min(2500.0) / 3500.0
                    + current_weak_penalty;
                let mut trial = state.clone();
                trial.push(candidate);
                next_states.push((score, trial));
            }
        }
        if next_states.is_empty() {
            return None;
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.1.cmp(&right.1))
        });
        next_states.truncate(160);
        states = next_states;
    }

    let current_weak_count = weak_steps.len();
    let mut best_trial: Option<(CombinationScore, usize)> = None;
    for (_state_score, trial) in states {
        if trial == best.indices
            || trial.len() != best.indices.len()
            || !trial.windows(2).all(|window| window[1] > window[0])
        {
            continue;
        }
        let trial_weak_count = trial.iter().filter(|scan| weak_anchor(**scan)).count();
        if current_weak_count.saturating_sub(trial_weak_count) < 2 {
            continue;
        }
        if trial_weak_count > 1 {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &augmented_peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 8.0
            || trial_score.linear_mean_abs_error_bp > 3.4
            || trial_score.linear_r2 < 0.9990
            || trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 2.2
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 1.55
        {
            continue;
        }
        let should_take = if let Some((current_best, current_weak_count)) = best_trial.as_ref() {
            trial_weak_count < *current_weak_count
                || (trial_weak_count == *current_weak_count
                    && compare_liz_linear_first_candidates(&trial_score, current_best)
                        == std::cmp::Ordering::Less)
        } else {
            true
        };
        if should_take {
            best_trial = Some((trial_score, trial_weak_count));
        }
    }

    best_trial.map(|(score, _)| score)
}

fn repair_liz_capped_foot_to_apex_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
        || best.linear_max_abs_error_bp > 10.5
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected = best
        .indices
        .iter()
        .filter_map(|scan| augmented_peak_feature_by_index.get(scan))
        .collect::<Vec<_>>();
    if selected.len() != best.indices.len() {
        return None;
    }

    let strong_selected_heights = selected
        .iter()
        .map(|peak| peak.height.max(1.0))
        .filter(|height| (300.0..=6500.0).contains(height))
        .collect::<Vec<_>>();
    if strong_selected_heights.len() < 4 {
        return None;
    }
    let family_height_ref = median(&strong_selected_heights).max(1.0);
    let selected_prominences = selected
        .iter()
        .map(|peak| peak.prominence.max(1.0))
        .filter(|prominence| *prominence >= 35.0)
        .collect::<Vec<_>>();
    let family_prominence_ref = median(&selected_prominences).max(1.0);

    let peak_quality = |scan: usize| {
        augmented_peak_feature_by_index.get(&scan).map(|peak| {
            let height = peak.height.max(1.0);
            let prominence = peak.prominence.max(0.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (prominence / height).clamp(0.0, 1.5);
            let weak_or_foot = height < 120.0
                || prominence < family_prominence_ref * 0.14
                || height < family_height_ref * 0.16
                || (height < family_height_ref * 0.32
                    && (baseline_ratio >= 0.30 || purity <= 0.58));
            (height, prominence, baseline_ratio, purity, weak_or_foot)
        })
    };

    let weak_steps = best
        .indices
        .iter()
        .enumerate()
        .filter_map(|(step, scan)| {
            peak_quality(*scan).and_then(|(_, _, _, _, weak)| weak.then_some(step))
        })
        .collect::<Vec<_>>();
    if weak_steps.len() < 2 || weak_steps.len() > 9 {
        return None;
    }

    let clean_candidate = |peak: &Peak, current_scan: usize| {
        let height = peak.height.max(1.0);
        let prominence = peak.prominence.max(0.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (prominence / height).clamp(0.0, 1.5);
        let Some((current_height, current_prominence, _, _, _)) = peak_quality(current_scan) else {
            return false;
        };
        height >= 80.0
            && height <= 12000.0
            && prominence >= 45.0
            && baseline_ratio <= 0.55
            && purity >= 0.25
            && (height >= family_height_ref * 0.12 || height >= 600.0)
            && (height >= current_height * 1.55 || prominence >= current_prominence.max(1.0) * 1.7)
    };

    let mut step_candidates = Vec::new();
    for step in weak_steps.iter().copied() {
        let current = best.indices[step];
        let radius = if step >= 12 {
            190
        } else if step >= 8 {
            165
        } else if step >= 4 {
            125
        } else {
            90
        };
        let mut candidates = vec![current];
        for peak in augmented_peak_feature_by_index.values() {
            if peak.index == current
                || peak.index.abs_diff(current) > radius
                || !clean_candidate(peak, current)
            {
                continue;
            }
            let lower_bound = if step == 0 {
                0
            } else {
                best.indices[step - 1].saturating_add(8)
            };
            let upper_bound = if step + 1 >= best.indices.len() {
                usize::MAX
            } else {
                best.indices[step + 1].saturating_sub(8)
            };
            if peak.index <= lower_bound || peak.index >= upper_bound {
                continue;
            }
            candidates.push(peak.index);
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.len() <= 1 {
            continue;
        }
        candidates.sort_by(|left, right| {
            let rank = |idx: &usize| {
                augmented_peak_feature_by_index
                    .get(idx)
                    .map(|peak| {
                        if *idx == current {
                            return -0.25;
                        }
                        let height = peak.height.max(1.0);
                        let prominence = peak.prominence.max(0.0);
                        let baseline_ratio =
                            (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                        (*idx).abs_diff(current) as f64 / radius.max(1) as f64
                            + baseline_ratio * 1.5
                            - height.min(5000.0) / 3500.0
                            - prominence.min(4000.0) / 5000.0
                    })
                    .unwrap_or(100.0)
            };
            rank(left)
                .partial_cmp(&rank(right))
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.cmp(right))
        });
        candidates.truncate(4);
        candidates.sort_unstable();
        step_candidates.push((step, candidates));
    }
    if step_candidates.is_empty() {
        return None;
    }
    step_candidates.sort_by_key(|(step, _)| *step);

    let current_weak_count = weak_steps.len();
    let mut states: Vec<(f64, Vec<usize>)> = vec![(0.0, best.indices.clone())];
    for (step, candidates) in step_candidates {
        let mut next_states = Vec::new();
        for (state_score, state) in states.iter() {
            for candidate in candidates.iter().copied() {
                if candidate == state[step] {
                    next_states.push((*state_score, state.clone()));
                    continue;
                }
                let mut trial = state.clone();
                trial[step] = candidate;
                if !trial.windows(2).all(|window| window[1] > window[0]) {
                    continue;
                }
                let gap_penalty = ladder_gap_template_penalty(LadderKind::Liz500250, &trial);
                let peak = augmented_peak_feature_by_index.get(&candidate);
                let peak_reward = peak
                    .map(|peak| {
                        let height = peak.height.max(1.0);
                        let prominence = peak.prominence.max(0.0);
                        height.min(5000.0) / 2500.0 + prominence.min(4000.0) / 3500.0
                    })
                    .unwrap_or(0.0);
                next_states.push((*state_score + gap_penalty / 18.0 - peak_reward, trial));
            }
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.1.cmp(&right.1))
        });
        next_states.dedup_by(|left, right| left.1 == right.1);
        next_states.truncate(96);
        states = next_states;
        if states.is_empty() {
            return None;
        }
    }

    let mut best_trial: Option<(CombinationScore, usize)> = None;
    for (_, trial) in states {
        if trial == best.indices {
            continue;
        }
        let trial_weak_count = trial
            .iter()
            .filter(|scan| {
                peak_quality(**scan)
                    .map(|(_, _, _, _, weak)| weak)
                    .unwrap_or(true)
            })
            .count();
        if current_weak_count.saturating_sub(trial_weak_count) < 2 {
            continue;
        }
        if trial_weak_count > 2 {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &augmented_peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 8.0
            || trial_score.linear_mean_abs_error_bp > 3.6
            || trial_score.linear_r2 < 0.9990
            || trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 1.00
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.85
            || trial_score.linear_r2 + 0.00035 < best.linear_r2
        {
            continue;
        }
        let should_take = if let Some((current_best, current_weak_count)) = best_trial.as_ref() {
            trial_weak_count < *current_weak_count
                || (trial_weak_count == *current_weak_count
                    && compare_liz_linear_first_candidates(&trial_score, current_best)
                        == std::cmp::Ordering::Less)
        } else {
            true
        };
        if should_take {
            best_trial = Some((trial_score, trial_weak_count));
        }
    }

    best_trial.map(|(score, _)| score)
}

fn repair_liz_weak_multi_anchor_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }
    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.len() != best.indices.len() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);
    if family_height_ref < 250.0 {
        return None;
    }

    let weak_anchor = |scan: usize| {
        augmented_peak_feature_by_index
            .get(&scan)
            .map(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
                height < 120.0
                    || height <= family_height_ref * 0.16
                    || (height <= family_height_ref * 0.28
                        && (baseline_ratio >= 0.30 || purity <= 0.65))
            })
            .unwrap_or(true)
    };
    let weak_steps = best
        .indices
        .iter()
        .enumerate()
        .filter_map(|(step, scan)| weak_anchor(*scan).then_some(step))
        .collect::<Vec<_>>();
    let current_weak_count = weak_steps.len();
    if !(2..=5).contains(&current_weak_count) {
        return None;
    }

    let mut candidate_lists: Vec<(usize, Vec<usize>)> = Vec::new();
    for step in weak_steps {
        let current_scan = best.indices[step];
        let lo = if step == 0 {
            current_scan.saturating_sub(120)
        } else {
            best.indices[step - 1].saturating_add(18)
        };
        let hi = if step + 1 >= best.indices.len() {
            current_scan.saturating_add(130).min(5000)
        } else {
            best.indices[step + 1].saturating_sub(18)
        };
        if hi <= lo {
            continue;
        }
        let mut candidates = vec![current_scan];
        for peak in augmented_peak_feature_by_index.values() {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
            if peak.index <= lo
                || peak.index >= hi
                || peak.index.abs_diff(current_scan) > 90
                || height < family_height_ref * 0.24
                || peak.prominence < family_height_ref * 0.18
                || baseline_ratio > 0.36
                || purity < 0.56
            {
                continue;
            }
            candidates.push(peak.index);
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.len() > 5 {
            candidates.sort_by(|left, right| {
                let left_peak = augmented_peak_feature_by_index.get(left);
                let right_peak = augmented_peak_feature_by_index.get(right);
                let rank = |peak: Option<&Peak>| {
                    peak.map(|peak| {
                        let height = peak.height.max(1.0);
                        let baseline_ratio =
                            (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
                        peak.height + peak.prominence * 0.30 + purity * 80.0
                            - baseline_ratio * 160.0
                    })
                    .unwrap_or(0.0)
                };
                rank(right_peak)
                    .partial_cmp(&rank(left_peak))
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            candidates.truncate(5);
            candidates.sort_unstable();
        }
        if candidates.len() > 1 {
            candidate_lists.push((step, candidates));
        }
    }
    if candidate_lists.is_empty() {
        return None;
    }

    let mut states = vec![best.indices.clone()];
    for (step, candidates) in candidate_lists {
        let mut next_states = Vec::new();
        for state in states.iter() {
            for candidate in candidates.iter().copied() {
                let mut trial = state.clone();
                trial[step] = candidate;
                if trial.windows(2).all(|window| window[1] > window[0]) {
                    next_states.push(trial);
                }
            }
        }
        next_states.sort();
        next_states.dedup();
        if next_states.len() > 512 {
            next_states.truncate(512);
        }
        states = next_states;
    }

    let mut best_trial: Option<(CombinationScore, usize)> = None;
    for trial in states {
        if trial == best.indices {
            continue;
        }
        let trial_weak_count = trial.iter().filter(|scan| weak_anchor(**scan)).count();
        if trial_weak_count > 1 || current_weak_count.saturating_sub(trial_weak_count) < 2 {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &augmented_peak_feature_by_index,
            peak_features,
        );
        let complete_weak_cleanup = trial_weak_count == 0
            && current_weak_count <= 3
            && trial_score.linear_max_abs_error_bp <= 9.8
            && trial_score.linear_mean_abs_error_bp <= 3.20
            && trial_score.linear_r2 >= 0.99930
            && trial_score.linear_max_abs_error_bp <= best.linear_max_abs_error_bp + 1.20
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.55;
        if !complete_weak_cleanup
            && (trial_score.linear_max_abs_error_bp > 6.8
                || trial_score.linear_mean_abs_error_bp > 2.35
                || trial_score.linear_r2 < 0.99960
                || trial_score.linear_max_abs_error_bp > best.linear_max_abs_error_bp + 1.00
                || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.20
                || trial_score.linear_r2 + 0.00005 < best.linear_r2)
        {
            continue;
        }
        let should_take = if let Some((current_best, current_weak)) = best_trial.as_ref() {
            trial_weak_count < *current_weak
                || (trial_weak_count == *current_weak
                    && compare_liz_linear_first_candidates(&trial_score, current_best)
                        == std::cmp::Ordering::Less)
        } else {
            true
        };
        if should_take {
            best_trial = Some((trial_score, trial_weak_count));
        }
    }

    best_trial.map(|(score, _)| score)
}

fn repair_liz_poor_linear_local_anchor_grid_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if best.linear_max_abs_error_bp <= 10.0 {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .filter(|height| (80.0..=5000.0).contains(height))
        .collect::<Vec<_>>();
    let family_height_ref = median(&selected_heights).max(1.0);
    if family_height_ref < 180.0 {
        return None;
    }

    let clean_local_anchor = |peak: &Peak| {
        let height = peak.height.max(1.0);
        let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
        let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
        height >= 80.0
            && height >= family_height_ref * 0.18
            && height <= family_height_ref * 6.5
            && peak.prominence >= family_height_ref * 0.08
            && baseline_ratio <= 0.58
            && purity >= 0.24
    };

    let candidate_steps = [1_usize, 6_usize, 9_usize]; // 50, 160, 300 bp
    let mut candidate_lists: Vec<(usize, Vec<usize>)> = Vec::new();
    for step in candidate_steps {
        let current_scan = best.indices[step];
        let (lo, hi, radius) = match step {
            1 => (
                best.indices[0].saturating_add(35),
                best.indices[2].saturating_sub(30),
                115_usize,
            ),
            6 => (
                best.indices[5].saturating_add(24),
                best.indices[7].saturating_sub(36),
                145_usize,
            ),
            9 => (
                best.indices[8].saturating_add(65),
                best.indices[10].saturating_sub(60),
                150_usize,
            ),
            _ => continue,
        };
        if hi <= lo {
            continue;
        }

        let mut candidates = vec![current_scan];
        for peak in augmented_peak_feature_by_index.values() {
            if peak.index <= lo
                || peak.index >= hi
                || peak.index.abs_diff(current_scan) > radius
                || !clean_local_anchor(peak)
            {
                continue;
            }
            candidates.push(peak.index);
        }
        candidates.sort_unstable();
        candidates.dedup();
        if candidates.len() > 6 {
            candidates.sort_by(|left, right| {
                let rank = |scan: &usize| {
                    augmented_peak_feature_by_index
                        .get(scan)
                        .map(|peak| {
                            let height = peak.height.max(1.0);
                            let baseline_ratio =
                                (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                            let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
                            peak.prominence + peak.height * 0.18 + purity * 90.0
                                - baseline_ratio * 160.0
                        })
                        .unwrap_or(0.0)
                };
                rank(right)
                    .partial_cmp(&rank(left))
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| left.cmp(right))
            });
            if !candidates.contains(&current_scan) {
                candidates.push(current_scan);
            }
            candidates.truncate(6);
            candidates.sort_unstable();
        }
        if candidates.len() > 1 {
            candidate_lists.push((step, candidates));
        }
    }
    if candidate_lists.is_empty() {
        return None;
    }

    let mut states = vec![best.indices.clone()];
    for (step, candidates) in candidate_lists {
        let mut next_states = Vec::new();
        for state in states.iter() {
            for candidate in candidates.iter().copied() {
                let mut trial = state.clone();
                trial[step] = candidate;
                if trial.windows(2).all(|window| window[1] > window[0]) {
                    next_states.push(trial);
                }
            }
        }
        next_states.sort();
        next_states.dedup();
        if next_states.len() > 512 {
            next_states.truncate(512);
        }
        states = next_states;
    }

    let current_plausibility =
        peak_plausibility_penalty(&best.indices, &augmented_peak_feature_by_index);
    let mut best_trial: Option<CombinationScore> = None;
    for trial in states {
        if trial == best.indices {
            continue;
        }
        let changed_steps = trial
            .iter()
            .zip(best.indices.iter())
            .filter(|(left, right)| left != right)
            .count();
        if changed_steps == 0 || changed_steps > 3 {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &augmented_peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 8.0
            || trial_score.linear_mean_abs_error_bp > 3.6
            || trial_score.linear_r2 < 0.9990
            || trial_score.linear_max_abs_error_bp + 2.0 >= best.linear_max_abs_error_bp
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.55
            || trial_score.peak_penalty > best.peak_penalty + 5.0
            || trial_score.domain_penalty > best.domain_penalty + 6.0
        {
            continue;
        }
        let trial_plausibility =
            peak_plausibility_penalty(&trial, &augmented_peak_feature_by_index);
        if trial_plausibility > current_plausibility + 0.35 {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_liz_linear_first_candidates(&trial_score, current_best)
                == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_tail_neighbor_shift_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }

    let current_490 = best.indices[14];
    let current_500 = best.indices[15];
    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .collect::<Vec<_>>();
    if selected_heights.is_empty() {
        return None;
    }
    let family_height_ref = median(&selected_heights).max(1.0);
    let current_490_weak = peak_feature_by_index
        .get(&current_490)
        .map(|peak| peak.height.max(1.0) <= family_height_ref * 0.14)
        .unwrap_or(true);
    if !current_490_weak {
        return None;
    }

    let mut new_490_candidates = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.0);
            peak.index > best.indices[13]
                && peak.index.abs_diff(current_500) <= 10
                && height >= family_height_ref * 0.28
                && peak.prominence >= family_height_ref * 0.20
                && baseline_ratio <= 0.35
                && purity >= 0.58
        })
        .collect::<Vec<_>>();
    if let Some(current_500_peak) = peak_feature_by_index.get(&current_500) {
        if !new_490_candidates
            .iter()
            .any(|peak| peak.index == current_500)
        {
            new_490_candidates.push(current_500_peak);
        }
    }
    if new_490_candidates.is_empty() {
        return None;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for new_490_peak in new_490_candidates {
        for next_peak in peak_features {
            let next_height = next_peak.height.max(1.0);
            let next_baseline_ratio =
                (next_peak.local_baseline.max(0.0) / next_height).clamp(0.0, 1.5);
            let next_purity = (next_peak.prominence / next_height).clamp(0.0, 1.0);
            let gap = next_peak.index.saturating_sub(new_490_peak.index) as f64;
            if next_peak.index <= new_490_peak.index
                || !(34.0..=82.0).contains(&gap)
                || next_peak.index > new_490_peak.index.saturating_add(95)
                || next_height < family_height_ref * 0.28
                || next_peak.prominence < family_height_ref * 0.20
                || next_baseline_ratio > 0.35
                || next_purity < 0.58
            {
                continue;
            }

            let mut trial = best.indices.clone();
            trial[14] = new_490_peak.index;
            trial[15] = next_peak.index;
            if !trial.windows(2).all(|window| window[1] > window[0]) {
                continue;
            }
            let trial_score = score_combination(
                &trial,
                ladder_sizes,
                ladder,
                peak_feature_by_index,
                peak_features,
            );
            let keeps_review_safe_profile = trial_score.linear_max_abs_error_bp <= 10.0
                && trial_score.linear_mean_abs_error_bp <= 4.5
                && trial_score.linear_r2 >= 0.9985;
            let acceptable_tradeoff = trial_score.linear_max_abs_error_bp
                <= best.linear_max_abs_error_bp + 2.40
                && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 1.00
                && trial_score.linear_r2 + 0.00055 >= best.linear_r2;
            let preserves_or_improves_shape = trial_score.quadratic_r2 + 0.00015
                >= best.quadratic_r2
                || trial_score.linear_mean_abs_error_bp + 0.20 < best.linear_mean_abs_error_bp
                || trial_score.linear_r2 > best.linear_r2 + 0.00003;
            if !(keeps_review_safe_profile && acceptable_tradeoff && preserves_or_improves_shape) {
                continue;
            }
            let should_take = if let Some(current_best) = best_trial.as_ref() {
                compare_liz_linear_first_candidates(&trial_score, current_best)
                    == std::cmp::Ordering::Less
            } else {
                true
            };
            if should_take {
                best_trial = Some(trial_score);
            }
        }
    }

    best_trial
}

fn repair_liz_mid_triplet_left_shift_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if best.linear_max_abs_error_bp <= 8.0
        && best.linear_mean_abs_error_bp <= 3.2
        && best.linear_r2 >= 0.9990
    {
        return None;
    }

    let mut augmented_peak_feature_by_index = peak_feature_by_index.clone();
    for peak in peak_features {
        augmented_peak_feature_by_index
            .entry(peak.index)
            .or_insert_with(|| peak.clone());
    }

    let selected_heights = best
        .indices
        .iter()
        .filter_map(|scan| {
            augmented_peak_feature_by_index
                .get(scan)
                .map(|peak| peak.height.max(1.0))
        })
        .filter(|height| (80.0..=5000.0).contains(height))
        .collect::<Vec<_>>();
    let family_height_ref = median(&selected_heights).max(1.0);
    if family_height_ref < 120.0 {
        return None;
    }

    let clean_family_peak = |scan: usize| {
        augmented_peak_feature_by_index
            .get(&scan)
            .map(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.5);
                height >= 80.0
                    && height <= 12000.0
                    && height >= family_height_ref * 0.16
                    && peak.prominence >= family_height_ref * 0.12
                    && baseline_ratio <= 0.45
                    && purity >= 0.42
            })
            .unwrap_or(false)
    };

    let mut trials: Vec<Vec<usize>> = Vec::new();

    // Pattern seen in the annotated 2024 LIZ cases: the true 139 bp peak is just
    // before the current 139 call, while current 139/150 are actually 150/160.
    if clean_family_peak(best.indices[4]) && clean_family_peak(best.indices[5]) {
        let target_139 = best.indices[3] as f64 + LIZ_BROAD_GAP_MEDIAN[3];
        let lo = best.indices[3].saturating_add(45);
        let hi = best.indices[4].saturating_sub(18);
        for peak in augmented_peak_feature_by_index.values() {
            if peak.index <= lo || peak.index >= hi {
                continue;
            }
            let gap_139_150 = best.indices[4].saturating_sub(peak.index) as f64;
            let gap_150_160 = best.indices[5].saturating_sub(best.indices[4]) as f64;
            if !(40.0..=86.0).contains(&gap_139_150)
                || !(38.0..=86.0).contains(&gap_150_160)
                || (peak.index as f64 - target_139).abs() > 95.0
                || !clean_family_peak(peak.index)
            {
                continue;
            }
            let mut trial = best.indices.clone();
            trial[4] = peak.index;
            trial[5] = best.indices[4];
            trial[6] = best.indices[5];
            if trial.windows(2).all(|window| window[1] > window[0]) {
                trials.push(trial);
            }
        }
    }

    // Sister pattern: current 150/160 are clean, and the missing 160 is the next
    // clean peak before 200 bp.
    if clean_family_peak(best.indices[5]) && clean_family_peak(best.indices[6]) {
        let lo = best.indices[6].saturating_add(28);
        let hi = best.indices[7].saturating_sub(32);
        for peak in augmented_peak_feature_by_index.values() {
            let gap_150_160 = best.indices[6].saturating_sub(best.indices[5]) as f64;
            let gap_160_200 = peak.index.saturating_sub(best.indices[6]) as f64;
            if peak.index <= lo
                || peak.index >= hi
                || !(38.0..=88.0).contains(&gap_150_160)
                || !(120.0..=260.0).contains(&gap_160_200)
                || !clean_family_peak(peak.index)
            {
                continue;
            }
            let mut trial = best.indices.clone();
            trial[4] = best.indices[5];
            trial[5] = best.indices[6];
            trial[6] = peak.index;
            if trial.windows(2).all(|window| window[1] > window[0]) {
                trials.push(trial);
            }
        }
    }

    let mut best_trial: Option<CombinationScore> = None;
    for trial in trials {
        if trial == best.indices {
            continue;
        }
        let trial_score = score_combination(
            &trial,
            ladder_sizes,
            ladder,
            &augmented_peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 8.0
            || trial_score.linear_mean_abs_error_bp > 3.35
            || trial_score.linear_r2 < 0.9990
            || trial_score.linear_max_abs_error_bp + 1.8 >= best.linear_max_abs_error_bp
            || trial_score.linear_mean_abs_error_bp > best.linear_mean_abs_error_bp + 0.35
        {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_liz_linear_first_candidates(&trial_score, current_best)
                == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_mid_triplet_anchor_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }
    if best.linear_max_abs_error_bp <= 8.0
        && best.linear_mean_abs_error_bp <= 3.2
        && best.linear_r2 >= 0.9988
    {
        return None;
    }

    const TRIPLET_START: usize = 4; // LIZ 139/150/160 bp
    let triplet_bps = [
        ladder_sizes[TRIPLET_START],
        ladder_sizes[TRIPLET_START + 1],
        ladder_sizes[TRIPLET_START + 2],
    ];
    let mut triplet_pool = peak_features
        .iter()
        .filter(|peak| {
            let baseline_ratio =
                (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
            let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.5);
            peak.index >= 1900
                && peak.index <= 2550
                && peak.height >= 35.0
                && peak.prominence >= 25.0
                && baseline_ratio <= 0.45
                && purity >= 0.30
        })
        .cloned()
        .collect::<Vec<_>>();
    if triplet_pool.len() < 3 {
        return None;
    }
    triplet_pool.sort_by(|left, right| {
        let left_baseline_ratio =
            (left.local_baseline.max(0.0) / left.height.max(1.0)).clamp(0.0, 1.5);
        let right_baseline_ratio =
            (right.local_baseline.max(0.0) / right.height.max(1.0)).clamp(0.0, 1.5);
        let left_rank = left.score + left.prominence * 0.45 - left_baseline_ratio * 260.0;
        let right_rank = right.score + right.prominence * 0.45 - right_baseline_ratio * 260.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    triplet_pool.truncate(18);
    triplet_pool.sort_by_key(|peak| peak.index);
    let triplet_indices = triplet_pool
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let mut best_trial: Option<CombinationScore> = None;
    for triplet in generate_peak_combinations(&triplet_indices, 3, usize::MAX, 512) {
        let gap_139_150 = triplet[1].saturating_sub(triplet[0]) as f64;
        let gap_150_160 = triplet[2].saturating_sub(triplet[1]) as f64;
        if !(38.0..=90.0).contains(&gap_139_150) || !(35.0..=88.0).contains(&gap_150_160) {
            continue;
        }
        let ratio = gap_139_150 / gap_150_160.max(1.0);
        if !(0.72..=1.55).contains(&ratio) {
            continue;
        }

        let slope_a = gap_139_150 / (triplet_bps[1] - triplet_bps[0]).max(1.0);
        let slope_b = gap_150_160 / (triplet_bps[2] - triplet_bps[1]).max(1.0);
        let scan_per_bp = (slope_a + slope_b) * 0.5;
        if !(3.6..=8.8).contains(&scan_per_bp) {
            continue;
        }
        let intercept = (triplet[0] as f64 - scan_per_bp * triplet_bps[0] + triplet[1] as f64
            - scan_per_bp * triplet_bps[1]
            + triplet[2] as f64
            - scan_per_bp * triplet_bps[2])
            / 3.0;

        let reference_peaks = triplet
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .collect::<Vec<_>>();
        if reference_peaks.len() < 3 {
            continue;
        }
        let height_ref = median(
            &reference_peaks
                .iter()
                .map(|peak| peak.height)
                .collect::<Vec<_>>(),
        )
        .max(1.0);
        let score_ref = median(
            &reference_peaks
                .iter()
                .map(|peak| peak.score)
                .collect::<Vec<_>>(),
        )
        .max(1.0);

        let mut chosen = Vec::with_capacity(ladder_sizes.len());
        let mut used = std::collections::BTreeSet::new();
        let mut failed = false;
        for (step_idx, ladder_bp) in ladder_sizes.iter().copied().enumerate() {
            let picked = if (TRIPLET_START..=TRIPLET_START + 2).contains(&step_idx) {
                triplet[step_idx - TRIPLET_START]
            } else {
                let target = intercept + scan_per_bp * ladder_bp;
                let tolerance = if step_idx < TRIPLET_START {
                    (scan_per_bp * 12.0).max(62.0)
                } else {
                    (scan_per_bp * 16.0).max(78.0)
                };
                let mut local_best: Option<(f64, usize)> = None;
                for peak in peak_features {
                    if used.contains(&peak.index) {
                        continue;
                    }
                    if let Some(previous) = chosen.last() {
                        if peak.index <= (*previous as usize).saturating_add(4) {
                            continue;
                        }
                    }
                    let delta = (peak.index as f64 - target).abs();
                    if delta > tolerance {
                        continue;
                    }
                    let height = peak.height.max(1.0);
                    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                    let purity = (peak.prominence / height).clamp(0.0, 1.5);
                    if baseline_ratio > 0.70 || peak.prominence < 16.0 || peak.height < 18.0 {
                        continue;
                    }
                    let family_height_penalty =
                        ((0.20 - (peak.height / height_ref)).max(0.0)) * 50.0;
                    let family_score_penalty = ((0.16 - (peak.score / score_ref)).max(0.0)) * 45.0;
                    let local_score = delta
                        + baseline_ratio * 28.0
                        + (0.34 - purity).max(0.0) * 28.0
                        + family_height_penalty
                        + family_score_penalty;
                    let candidate = (local_score, peak.index);
                    if local_best.map_or(true, |existing| candidate < existing) {
                        local_best = Some(candidate);
                    }
                }
                let Some((_score, index)) = local_best else {
                    failed = true;
                    break;
                };
                index
            };

            if used.contains(&picked) {
                failed = true;
                break;
            }
            if let Some(previous) = chosen.last() {
                if picked <= *previous {
                    failed = true;
                    break;
                }
            }
            chosen.push(picked);
            used.insert(picked);
        }

        if failed
            || chosen.len() != ladder_sizes.len()
            || !chosen.windows(2).all(|window| window[1] > window[0])
        {
            continue;
        }

        let trial_score = score_combination(
            &chosen,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if trial_score.linear_max_abs_error_bp > 6.2
            || trial_score.linear_mean_abs_error_bp > 2.8
            || trial_score.linear_r2 < 0.9990
        {
            continue;
        }
        let compelling = trial_score.linear_max_abs_error_bp + 2.0 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.30
            && trial_score.linear_r2 + 0.00010 >= best.linear_r2;
        if !repair_candidate_improves_current(best, &trial_score) && !compelling {
            continue;
        }

        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_block_repair_candidates(&trial_score, current_best) == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn repair_liz_tail_to_front_reverse_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    if ladder != LadderKind::Liz500250
        || ladder_sizes.len() != 16
        || best.indices.len() != ladder_sizes.len()
    {
        return None;
    }
    if liz_fit_is_high_confidence_stable(best) {
        return None;
    }
    if best.linear_max_abs_error_bp <= 8.0
        && best.linear_mean_abs_error_bp <= 3.2
        && best.linear_r2 >= 0.9988
    {
        return None;
    }
    let severe_linear_liz_mismatch = best.linear_max_abs_error_bp > 10.0
        && best.linear_mean_abs_error_bp > 3.5
        && best.linear_r2 < 0.9992;
    let suspicious_start_or_tail = severe_linear_liz_mismatch
        || best.indices.first().copied().unwrap_or(0) > 1650
        || best.indices.last().copied().unwrap_or(0) > 4620
        || best
            .indices
            .windows(2)
            .skip(11)
            .any(|pair| pair[1].saturating_sub(pair[0]) > 330);
    if !suspicious_start_or_tail {
        return None;
    }

    const TAIL_START: usize = 12; // LIZ 400/450/490/500 bp
    const REVERSE_BEAM_WIDTH: usize = 96;
    let tail_upper_bound =
        if best.indices.last().copied().unwrap_or(0) > 4620 || severe_linear_liz_mismatch {
            5100
        } else {
            4620
        };

    let mut tail_candidates = peak_features
        .iter()
        .filter(|peak| {
            let height = peak.height.max(1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            let purity = (peak.prominence / height).clamp(0.0, 1.5);
            peak.index >= 3500
                && peak.index <= tail_upper_bound
                && peak.height >= 22.0
                && peak.prominence >= 16.0
                && baseline_ratio <= 0.65
                && purity >= 0.24
        })
        .cloned()
        .collect::<Vec<_>>();
    if tail_candidates.len() < 4 {
        return None;
    }
    tail_candidates.sort_by(|left, right| {
        let left_baseline_ratio =
            (left.local_baseline.max(0.0) / left.height.max(1.0)).clamp(0.0, 1.5);
        let right_baseline_ratio =
            (right.local_baseline.max(0.0) / right.height.max(1.0)).clamp(0.0, 1.5);
        let left_rank =
            left.score + left.prominence * 0.45 + left.height * 0.06 - left_baseline_ratio * 240.0;
        let right_rank = right.score + right.prominence * 0.45 + right.height * 0.06
            - right_baseline_ratio * 240.0;
        right_rank
            .partial_cmp(&left_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.index.cmp(&right.index))
    });
    tail_candidates.truncate(18);
    tail_candidates.sort_by_key(|peak| peak.index);
    let tail_indices = tail_candidates
        .iter()
        .map(|peak| peak.index)
        .collect::<Vec<_>>();

    let mut states: Vec<(f64, Vec<usize>)> = Vec::new();
    for tail in generate_peak_combinations(&tail_indices, 4, usize::MAX, 512) {
        let mut gap_penalty = 0.0;
        let mut valid = true;
        for (offset, pair) in tail.windows(2).enumerate() {
            let gap_idx = TAIL_START + offset;
            let gap = pair[1].saturating_sub(pair[0]) as f64;
            let lo = LIZ_BROAD_GAP_P10[gap_idx] - 18.0;
            let hi = LIZ_BROAD_GAP_P90[gap_idx] + 28.0;
            if gap < lo || gap > hi {
                valid = false;
                break;
            }
            gap_penalty += ((gap - LIZ_BROAD_GAP_MEDIAN[gap_idx]).abs()
                / (LIZ_BROAD_GAP_MEDIAN[gap_idx] * 0.35).max(18.0))
            .min(3.0);
        }
        if !valid {
            continue;
        }
        let quality_penalty = tail
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .map(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.5);
                baseline_ratio * 1.2 + (0.42 - purity).max(0.0) * 1.8
            })
            .sum::<f64>();
        states.push((gap_penalty + quality_penalty, tail));
    }
    if states.is_empty() {
        return None;
    }
    states.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.1.cmp(&right.1))
    });
    states.truncate(REVERSE_BEAM_WIDTH);

    for step_idx in (0..TAIL_START).rev() {
        let expected_gap = LIZ_BROAD_GAP_MEDIAN[step_idx];
        let low_gap = (LIZ_BROAD_GAP_P10[step_idx] - 30.0).max(22.0);
        let high_gap = LIZ_BROAD_GAP_P90[step_idx] + 44.0;
        let mut next_states: Vec<(f64, Vec<usize>)> = Vec::new();

        for (state_score, suffix) in &states {
            let next_scan = suffix[0];
            let target = next_scan as f64 - expected_gap;
            let mut local_candidates = peak_features
                .iter()
                .filter(|peak| {
                    if suffix.contains(&peak.index) || peak.index + 4 >= next_scan {
                        return false;
                    }
                    let gap = next_scan.saturating_sub(peak.index) as f64;
                    if gap < low_gap || gap > high_gap {
                        return false;
                    }
                    let height = peak.height.max(1.0);
                    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                    let purity = (peak.prominence / height).clamp(0.0, 1.5);
                    let early_blob = step_idx <= 3
                        && peak.index < 1500
                        && peak.height > 800.0
                        && (baseline_ratio > 0.10 || purity < 0.55);
                    !early_blob
                        && peak.height >= 18.0
                        && peak.prominence >= 14.0
                        && baseline_ratio <= 0.75
                        && purity >= 0.22
                })
                .cloned()
                .collect::<Vec<_>>();
            if local_candidates.is_empty() {
                continue;
            }
            local_candidates.sort_by(|left, right| {
                let left_delta = (left.index as f64 - target).abs();
                let right_delta = (right.index as f64 - target).abs();
                let left_height = left.height.max(1.0);
                let right_height = right.height.max(1.0);
                let left_baseline_ratio =
                    (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
                let right_baseline_ratio =
                    (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
                let left_purity = (left.prominence / left_height).clamp(0.0, 1.5);
                let right_purity = (right.prominence / right_height).clamp(0.0, 1.5);
                let left_rank =
                    left_delta + left_baseline_ratio * 22.0 + (0.40 - left_purity).max(0.0) * 28.0
                        - left.score.min(350.0) * 0.015;
                let right_rank = right_delta
                    + right_baseline_ratio * 22.0
                    + (0.40 - right_purity).max(0.0) * 28.0
                    - right.score.min(350.0) * 0.015;
                left_rank
                    .partial_cmp(&right_rank)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| left.index.cmp(&right.index))
            });
            local_candidates.truncate(10);

            for peak in local_candidates {
                let gap = next_scan.saturating_sub(peak.index) as f64;
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.5);
                let gap_score = (gap - expected_gap).abs() / (expected_gap * 0.28).max(18.0);
                let quality_score = baseline_ratio * 1.4
                    + (0.42 - purity).max(0.0) * 1.8
                    + (30.0 - peak.prominence).max(0.0) / 30.0;
                let mut candidate_suffix = Vec::with_capacity(suffix.len() + 1);
                candidate_suffix.push(peak.index);
                candidate_suffix.extend_from_slice(suffix);
                next_states.push((*state_score + gap_score + quality_score, candidate_suffix));
            }
        }

        if next_states.is_empty() {
            return None;
        }
        next_states.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.1.cmp(&right.1))
        });
        next_states.truncate(REVERSE_BEAM_WIDTH);
        states = next_states;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for (_state_score, indices) in states {
        if indices.len() != ladder_sizes.len()
            || !indices.windows(2).all(|window| window[1] > window[0])
        {
            continue;
        }
        let trial_score = score_combination(
            &indices,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if !liz_reverse_changed_early_anchors_have_family_signal(
            best,
            &trial_score,
            peak_feature_by_index,
        ) {
            continue;
        }
        if trial_score.linear_max_abs_error_bp > 6.2
            || trial_score.linear_mean_abs_error_bp > 2.8
            || trial_score.linear_r2 < 0.9990
        {
            continue;
        }
        let compelling = trial_score.linear_max_abs_error_bp + 2.0 < best.linear_max_abs_error_bp
            && trial_score.linear_mean_abs_error_bp <= best.linear_mean_abs_error_bp + 0.45
            && trial_score.linear_r2 + 0.00005 >= best.linear_r2;
        if !repair_candidate_improves_current(best, &trial_score) && !compelling {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_block_repair_candidates(&trial_score, current_best) == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial_score);
        }
    }

    best_trial
}

fn liz_reverse_changed_early_anchors_have_family_signal(
    current: &CombinationScore,
    candidate: &CombinationScore,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> bool {
    let mut reference_heights = Vec::new();
    let mut reference_prominences = Vec::new();
    for scan in &current.indices {
        if let Some(peak) = peak_feature_by_index.get(scan) {
            reference_heights.push(peak.height.max(1.0));
            reference_prominences.push(peak.prominence.max(1.0));
        }
    }
    if reference_heights.len() < 6 || reference_prominences.len() < 6 {
        return true;
    }
    let height_ref = median(&reference_heights).max(1.0);
    let prominence_ref = median(&reference_prominences).max(1.0);

    for step_idx in 0..4 {
        let current_scan = match current.indices.get(step_idx) {
            Some(scan) => *scan,
            None => continue,
        };
        let candidate_scan = match candidate.indices.get(step_idx) {
            Some(scan) => *scan,
            None => continue,
        };
        if current_scan.abs_diff(candidate_scan) <= 2 {
            continue;
        }
        let Some(peak) = peak_feature_by_index.get(&candidate_scan) else {
            return false;
        };
        let height_ratio = peak.height.max(1.0) / height_ref;
        let prominence_ratio = peak.prominence.max(1.0) / prominence_ref;
        if height_ratio < 0.18
            || prominence_ratio < 0.16
            || height_ratio > 4.5
            || prominence_ratio > 4.5
        {
            return false;
        }
    }
    true
}

fn liz_linear_first_peak_is_plausible(peak: &Peak, height_ref: f64, score_ref: f64) -> bool {
    let height = peak.height.max(1.0);
    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
    let purity = (peak.prominence / height).clamp(0.0, 1.0);
    let height_ratio = peak.height / height_ref.max(1.0);
    let score_ratio = peak.score / score_ref.max(1.0);

    peak.prominence >= 20.0
        && peak.score >= 14.0
        && height_ratio <= 5.2
        && !(height_ratio < 0.08 && (baseline_ratio > 0.16 || purity < 0.62))
        && !(baseline_ratio > 0.48 && purity < 0.52)
        && !(score_ratio < 0.04 && purity < 0.58)
}

fn liz_linear_first_candidate_is_acceptable(
    current: &CombinationScore,
    candidate: &CombinationScore,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> bool {
    if liz_linear_first_candidate_has_compelling_linear_win(
        current,
        candidate,
        peak_feature_by_index,
    ) {
        return true;
    }

    let hard_regression = candidate.linear_r2 + 0.0006 < current.linear_r2
        || candidate.linear_mean_abs_error_bp > current.linear_mean_abs_error_bp + 0.75
        || candidate.linear_max_abs_error_bp > current.linear_max_abs_error_bp + 0.60
        || candidate.domain_penalty > current.domain_penalty + 1.40
        || candidate.peak_penalty > current.peak_penalty + 1.60;
    if hard_regression {
        return false;
    }

    candidate.linear_max_abs_error_bp + 1.00 < current.linear_max_abs_error_bp
        || (candidate.linear_max_abs_error_bp + 0.40 < current.linear_max_abs_error_bp
            && candidate.linear_mean_abs_error_bp + 0.20 < current.linear_mean_abs_error_bp)
}

fn liz_linear_first_candidate_has_compelling_linear_win(
    current: &CombinationScore,
    candidate: &CombinationScore,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
) -> bool {
    let huge_linear_win = candidate.linear_max_abs_error_bp + 2.25
        < current.linear_max_abs_error_bp
        && candidate.linear_mean_abs_error_bp + 1.10 < current.linear_mean_abs_error_bp
        && candidate.linear_r2 + 0.0003 >= current.linear_r2;
    let strong_linear_profile = candidate.linear_max_abs_error_bp <= 10.0
        && candidate.linear_mean_abs_error_bp <= 3.8
        && candidate.linear_r2 >= 0.99920;
    if !(huge_linear_win && strong_linear_profile) {
        return false;
    }

    let current_plausibility = peak_plausibility_penalty(&current.indices, peak_feature_by_index);
    let candidate_plausibility =
        peak_plausibility_penalty(&candidate.indices, peak_feature_by_index);
    let penalties_not_exploding = candidate.domain_penalty <= current.domain_penalty + 8.0
        && candidate.peak_penalty <= current.peak_penalty + 8.0
        && candidate_plausibility <= current_plausibility + 0.65;

    penalties_not_exploding
}

fn compare_liz_linear_first_candidates(
    left: &CombinationScore,
    right: &CombinationScore,
) -> std::cmp::Ordering {
    left.linear_max_abs_error_bp
        .partial_cmp(&right.linear_max_abs_error_bp)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| {
            left.linear_mean_abs_error_bp
                .partial_cmp(&right.linear_mean_abs_error_bp)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            right
                .linear_r2
                .partial_cmp(&left.linear_r2)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.peak_penalty
                .partial_cmp(&right.peak_penalty)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| {
            left.domain_penalty
                .partial_cmp(&right.domain_penalty)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .then_with(|| left.indices.cmp(&right.indices))
}

fn repair_liz_bounded_suspicious_sequence(
    best: &CombinationScore,
    ladder_sizes: &[f64],
    ladder: LadderKind,
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Option<CombinationScore> {
    const MAX_CANDIDATES_PER_STEP: usize = 6;
    const BEAM_WIDTH: usize = 96;

    if ladder != LadderKind::Liz500250 || best.indices.len() != ladder_sizes.len() {
        return None;
    }
    if peak_features.len() > 44 && best.indices.last().copied().unwrap_or(0) < 4400 {
        return None;
    }
    if best.linear_max_abs_error_bp <= 6.0
        && best.linear_mean_abs_error_bp <= 2.5
        && best.linear_r2 >= 0.9992
    {
        return None;
    }

    let (intercept, slope) = linear_scan_model(ladder_sizes, &best.indices)?;
    if !intercept.is_finite() || !slope.is_finite() || slope <= 0.0 {
        return None;
    }

    let suspicious_start = best.indices.len() >= 4
        && (best.indices[0] < 1500
            || best.indices[0] > 1565
            || best.indices[1].saturating_sub(best.indices[0]) < 55
            || best.indices[2].saturating_sub(best.indices[1]) > 175);
    let suspicious_tail = best.indices.last().copied().unwrap_or(0) < 4300
        && (best.linear_max_abs_error_bp > 8.0 || best.linear_mean_abs_error_bp > 4.0);

    let mut candidate_sets: Vec<Vec<usize>> = Vec::with_capacity(ladder_sizes.len());
    for (step_index, bp) in ladder_sizes.iter().copied().enumerate() {
        let predicted = intercept + slope * bp;
        let radius = if step_index < 4 && suspicious_start {
            180.0
        } else if step_index + 2 >= ladder_sizes.len() && suspicious_tail {
            520.0
        } else if step_index < 8 {
            120.0
        } else {
            150.0
        };
        let mut candidates = peak_features
            .iter()
            .filter(|peak| {
                let delta = (peak.index as f64 - predicted).abs();
                if delta <= radius {
                    return true;
                }
                suspicious_start && step_index < 4 && (1450..=1900).contains(&peak.index)
                    || suspicious_tail
                        && step_index + 2 >= ladder_sizes.len()
                        && (4200..=4600).contains(&peak.index)
            })
            .filter(|peak| liz_bounded_candidate_peak_is_plausible(peak, step_index))
            .cloned()
            .collect::<Vec<_>>();
        if let Some(current_peak) = peak_feature_by_index.get(&best.indices[step_index]) {
            candidates.push(current_peak.clone());
        }
        candidates.sort_by(|left, right| {
            let left_rank = liz_bounded_candidate_rank(left, predicted, step_index);
            let right_rank = liz_bounded_candidate_rank(right, predicted, step_index);
            left_rank
                .partial_cmp(&right_rank)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.index.cmp(&right.index))
        });
        candidates.dedup_by_key(|peak| peak.index);
        if candidates.len() > MAX_CANDIDATES_PER_STEP {
            candidates.truncate(MAX_CANDIDATES_PER_STEP);
        }
        let mut indices = candidates.iter().map(|peak| peak.index).collect::<Vec<_>>();
        indices.sort_unstable();
        indices.dedup();
        if indices.is_empty() {
            return None;
        }
        candidate_sets.push(indices);
    }

    let mut beam: Vec<Vec<usize>> = vec![Vec::new()];
    for (step_index, candidates) in candidate_sets.iter().enumerate() {
        let mut next = Vec::new();
        for prefix in &beam {
            let last = prefix.last().copied().unwrap_or(0);
            for candidate in candidates {
                if !prefix.is_empty() && *candidate <= last.saturating_add(3) {
                    continue;
                }
                let mut trial = prefix.clone();
                trial.push(*candidate);
                next.push(trial);
            }
        }
        if next.is_empty() {
            return None;
        }
        next.sort_by(|left, right| {
            let left_score = liz_bounded_partial_rank(left, &ladder_sizes[..=step_index]);
            let right_score = liz_bounded_partial_rank(right, &ladder_sizes[..=step_index]);
            left_score
                .partial_cmp(&right_score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.cmp(right))
        });
        if next.len() > BEAM_WIDTH {
            next.truncate(BEAM_WIDTH);
        }
        beam = next;
    }

    let mut best_trial: Option<CombinationScore> = None;
    for indices in beam {
        if indices.len() != ladder_sizes.len() {
            continue;
        }
        let trial = score_combination(
            &indices,
            ladder_sizes,
            ladder,
            peak_feature_by_index,
            peak_features,
        );
        if !liz_bounded_candidate_improves_current(best, &trial) {
            continue;
        }
        let should_take = if let Some(current_best) = best_trial.as_ref() {
            compare_liz_linear_first_candidates(&trial, current_best) == std::cmp::Ordering::Less
        } else {
            true
        };
        if should_take {
            best_trial = Some(trial);
        }
    }

    best_trial
}

fn linear_scan_model(ladder_sizes: &[f64], scans: &[usize]) -> Option<(f64, f64)> {
    if ladder_sizes.len() != scans.len() || scans.len() < 2 {
        return None;
    }
    let n = ladder_sizes.len() as f64;
    let mean_x = ladder_sizes.iter().sum::<f64>() / n;
    let mean_y = scans.iter().map(|scan| *scan as f64).sum::<f64>() / n;
    let mut numerator = 0.0;
    let mut denominator = 0.0;
    for (x, y) in ladder_sizes.iter().zip(scans.iter()) {
        let dx = *x - mean_x;
        numerator += dx * (*y as f64 - mean_y);
        denominator += dx * dx;
    }
    if denominator <= f64::EPSILON {
        return None;
    }
    let slope = numerator / denominator;
    let intercept = mean_y - slope * mean_x;
    Some((intercept, slope))
}

fn liz_bounded_candidate_peak_is_plausible(peak: &Peak, step_index: usize) -> bool {
    let height = peak.height.max(1.0);
    let purity = (peak.prominence / height).clamp(0.0, 1.0);
    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
    let min_height = if step_index + 2 >= LadderKind::Liz500250.expected_peak_count() {
        18.0
    } else if step_index < 4 {
        18.0
    } else {
        20.0
    };
    peak.height >= min_height
        && peak.prominence >= 14.0
        && peak.score >= 12.0
        && (baseline_ratio <= 0.60 || purity >= 0.42)
}

fn liz_bounded_candidate_rank(peak: &Peak, predicted: f64, step_index: usize) -> f64 {
    let delta = (peak.index as f64 - predicted).abs();
    let height = peak.height.max(1.0);
    let purity = (peak.prominence / height).clamp(0.0, 1.0);
    let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
    let height_bonus = peak.height.sqrt().min(120.0) * 0.10;
    let early_blob_cost = if step_index < 4 && peak.index < 1500 && peak.height > 800.0 {
        120.0
    } else {
        0.0
    };
    delta - height_bonus + baseline_ratio * 45.0 + (0.70 - purity).max(0.0) * 55.0 + early_blob_cost
}

fn liz_bounded_partial_rank(scans: &[usize], ladder_sizes: &[f64]) -> f64 {
    let linear_penalty = if scans.len() >= 3 {
        let (_, max_abs, r2) = linear_trend_residual_metrics(ladder_sizes, scans);
        max_abs * 0.25 + (0.999 - r2).max(0.0) * 80.0
    } else {
        0.0
    };
    linear_penalty + partial_ladder_gap_template_penalty(scans, ladder_sizes, 16) * 4.0
}

fn liz_bounded_candidate_improves_current(
    current: &CombinationScore,
    candidate: &CombinationScore,
) -> bool {
    let strong_profile = candidate.linear_max_abs_error_bp <= 8.0
        && candidate.linear_mean_abs_error_bp <= 3.6
        && candidate.linear_r2 >= 0.9990;
    let material_win = candidate.linear_max_abs_error_bp + 1.50 < current.linear_max_abs_error_bp
        || candidate.linear_mean_abs_error_bp + 0.85 < current.linear_mean_abs_error_bp;
    let hard_regression = candidate.linear_max_abs_error_bp
        > current.linear_max_abs_error_bp + 0.50
        || candidate.linear_mean_abs_error_bp > current.linear_mean_abs_error_bp + 0.35
        || candidate.linear_r2 + 0.00025 < current.linear_r2;
    if hard_regression {
        return false;
    }
    material_win
        && (strong_profile
            || (candidate.domain_penalty <= current.domain_penalty + 2.5
                && candidate.peak_penalty <= current.peak_penalty + 2.5))
}

fn candidate_block_ranges(ladder: LadderKind, len: usize) -> Vec<(usize, usize)> {
    if len < 5 {
        return Vec::new();
    }

    let mut ranges = Vec::new();
    match ladder {
        LadderKind::Liz500250 => {
            ranges.push((0, 3.min(len - 1)));
            ranges.push((0, 2.min(len - 1)));
            if len >= 4 {
                ranges.push((len - 4, len - 1));
            }
            if len >= 3 {
                ranges.push((len - 3, len - 1));
            }
        }
        LadderKind::Rox400Hd => {
            ranges.push((0, 3.min(len - 1)));
            if len >= 4 {
                ranges.push((len - 4, len - 1));
            }
            if len >= 5 {
                ranges.push((len - 5, len - 2));
            }
        }
        LadderKind::Gs500Rox => {
            ranges.push((0, 3.min(len - 1)));
            if len >= 4 {
                ranges.push((len - 4, len - 1));
            }
        }
    }
    ranges.sort_unstable();
    ranges.dedup();
    ranges
}

fn block_candidate_scans(
    scans: &[usize],
    ladder_sizes: &[f64],
    ladder: LadderKind,
    start: usize,
    end: usize,
    _peak_feature_by_index: &BTreeMap<usize, Peak>,
    peak_features: &[Peak],
) -> Vec<usize> {
    if scans.is_empty() || start > end || end >= scans.len() {
        return Vec::new();
    }

    let projected_targets = projected_scan_targets_for_block(scans, ladder_sizes, start, end);
    let block_first = scans[start] as f64;
    let block_last = scans[end] as f64;
    let block_radius = block_candidate_radius(ladder, start, end, scans.len());
    let lower_bound = if start == 0 {
        0usize
    } else {
        scans[start - 1].saturating_add(6)
    };
    let upper_bound = if end + 1 >= scans.len() {
        usize::MAX
    } else {
        scans[end + 1].saturating_sub(6)
    };

    let current_block = scans[start..=end].to_vec();
    let mut ranked = peak_features
        .iter()
        .filter(|peak| peak.index >= lower_bound && peak.index <= upper_bound)
        .filter_map(|peak| {
            let scan = peak.index as f64;
            let near_projected = projected_targets
                .iter()
                .any(|target| (scan - *target).abs() <= block_radius);
            let near_current = scan >= block_first - block_radius * 0.75
                && scan <= block_last + block_radius * 0.75;
            if !near_projected && !near_current && !current_block.contains(&peak.index) {
                return None;
            }
            let min_target_delta = projected_targets
                .iter()
                .map(|target| (scan - *target).abs())
                .fold(f64::INFINITY, f64::min);
            let baseline_ratio = peak.local_baseline.max(0.0) / peak.height.max(1.0);
            Some((
                (
                    min_target_delta,
                    baseline_ratio,
                    -peak.score,
                    -peak.prominence,
                    peak.index,
                ),
                peak.index,
            ))
        })
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut selected = current_block.clone();
    for (_, scan) in ranked {
        if selected.contains(&scan) {
            continue;
        }
        selected.push(scan);
        if selected.len() >= BLOCK_REPAIR_MAX_CANDIDATES {
            break;
        }
    }
    selected.sort_unstable();
    selected.dedup();
    selected
}

fn projected_scan_targets_for_block(
    scans: &[usize],
    ladder_sizes: &[f64],
    start: usize,
    end: usize,
) -> Vec<f64> {
    let gap_ratios = scans
        .windows(2)
        .zip(ladder_sizes.windows(2))
        .enumerate()
        .filter_map(|(pair_index, (scan_window, bp_window))| {
            if pair_index >= start.saturating_sub(1) && pair_index <= end {
                return None;
            }
            let bp_gap = bp_window[1] - bp_window[0];
            if bp_gap <= f64::EPSILON {
                return None;
            }
            Some((scan_window[1] as f64 - scan_window[0] as f64) / bp_gap)
        })
        .collect::<Vec<_>>();
    let fallback_gap_ratios = scans
        .windows(2)
        .zip(ladder_sizes.windows(2))
        .filter_map(|(scan_window, bp_window)| {
            let bp_gap = bp_window[1] - bp_window[0];
            if bp_gap <= f64::EPSILON {
                None
            } else {
                Some((scan_window[1] as f64 - scan_window[0] as f64) / bp_gap)
            }
        })
        .collect::<Vec<_>>();
    let gap_ratio = median(if gap_ratios.is_empty() {
        &fallback_gap_ratios
    } else {
        &gap_ratios
    })
    .max(1.0);

    (start..=end)
        .map(|step_index| {
            let left_projection = if start > 0 {
                let mut projected = scans[start - 1] as f64;
                for gap_index in start..=step_index {
                    let bp_gap = ladder_sizes[gap_index] - ladder_sizes[gap_index - 1];
                    projected += gap_ratio * bp_gap;
                }
                Some(projected)
            } else {
                None
            };
            let right_projection = if end + 1 < scans.len() {
                let mut projected = scans[end + 1] as f64;
                for gap_index in ((step_index + 1)..=end + 1).rev() {
                    let bp_gap = ladder_sizes[gap_index] - ladder_sizes[gap_index - 1];
                    projected -= gap_ratio * bp_gap;
                }
                Some(projected)
            } else {
                None
            };

            match (left_projection, right_projection) {
                (Some(left), Some(right)) => 0.5 * (left + right),
                (Some(left), None) => left,
                (None, Some(right)) => right,
                (None, None) => scans[step_index] as f64,
            }
        })
        .collect()
}

fn block_candidate_radius(ladder: LadderKind, start: usize, end: usize, len: usize) -> f64 {
    match ladder {
        LadderKind::Liz500250 if start == 0 => BLOCK_REPAIR_EARLY_LIZ_RADIUS_SCANS,
        LadderKind::Liz500250 if end + 1 == len => BLOCK_REPAIR_TAIL_LIZ_RADIUS_SCANS,
        _ => BLOCK_REPAIR_DEFAULT_RADIUS_SCANS,
    }
}

fn select_best_combination(
    combinations: &[Vec<usize>],
    ladder_sizes: &[f64],
    ladder: LadderKind,
    scoring_peak_features: &[Peak],
    repair_peak_features: &[Peak],
) -> Option<CombinationScore> {
    let peak_feature_by_index = scoring_peak_features
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();
    let repair_peak_feature_by_index = repair_peak_features
        .iter()
        .map(|peak| (peak.index, peak.clone()))
        .collect::<BTreeMap<_, _>>();

    // For ROX ladders, prefer combinations whose first anchor is in the
    // legitimate region.  Empirically every good ROX fit starts at ≥1520
    // while blob-dominated fits start at 1130–1500.  Try the clean region
    // first; only fall back to unrestricted if nothing viable is found.
    let rox_min_first_anchor: Option<usize> = match ladder {
        LadderKind::Rox400Hd => Some(1520),
        _ => None,
    };

    let pick_best = |iter: Box<dyn Iterator<Item = &Vec<usize>> + '_>| -> Option<CombinationScore> {
        iter.filter(|combo| combo.len() == ladder_sizes.len())
            .map(|combo| {
                score_combination(
                    combo,
                    ladder_sizes,
                    ladder,
                    &peak_feature_by_index,
                    scoring_peak_features,
                )
            })
            .min_by(compare_combination_scores)
    };

    let mut best = if let Some(min_first) = rox_min_first_anchor {
        let normal_start = pick_best(Box::new(combinations.iter().filter(|combo| {
            combo
                .first()
                .map_or(false, |first| *first >= min_first && *first <= 1850)
        })));
        if normal_start.as_ref().is_some_and(|score| {
            score.linear_max_abs_error_bp <= 6.0
                && score.linear_mean_abs_error_bp <= 2.8
                && score.linear_r2 >= 0.9988
        }) {
            normal_start
        } else {
            let preferred =
                pick_best(Box::new(combinations.iter().filter(|combo| {
                    combo.first().map_or(false, |first| *first >= min_first)
                })));
            preferred.or_else(|| pick_best(Box::new(combinations.iter())))
        }
    } else {
        pick_best(Box::new(combinations.iter()))
    };
    let initial_best_for_regression_guard = best.clone();
    let initial_best_for_rox_minor_start = best.clone();

    if ladder == LadderKind::Liz500250
        && !liz_full_repair_audit_enabled()
        && best
            .as_ref()
            .is_some_and(|score| liz_initial_fit_can_skip_repairs(score, repair_peak_features))
    {
        return best;
    }

    if let Some(candidate) = repair_rox_strong_family_window_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_rox_clean_early_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        if best
            .as_ref()
            .map(|current| {
                repair_candidate_improves_current(current, &candidate)
                    || (candidate.linear_max_abs_error_bp + 2.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp + 0.8
                            < current.linear_mean_abs_error_bp
                        && candidate.linear_r2 + 0.0004 >= current.linear_r2)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_liz_consistent_height_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        if best
            .as_ref()
            .map(|current| {
                repair_candidate_improves_current(current, &candidate)
                    || (candidate.linear_max_abs_error_bp + 0.75 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp
                            <= current.linear_mean_abs_error_bp + 0.35
                        && candidate.linear_r2 + 0.00008 >= current.linear_r2)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_liz_strong_median_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        if best
            .as_ref()
            .map(|current| {
                repair_candidate_improves_current(current, &candidate)
                    || (candidate.linear_max_abs_error_bp + 1.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp + 0.6
                            < current.linear_mean_abs_error_bp
                        && candidate.linear_r2 + 0.00015 >= current.linear_r2)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_liz_blob_start_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        if best
            .as_ref()
            .map(|current| {
                repair_candidate_improves_current(current, &candidate)
                    || (candidate.linear_max_abs_error_bp + 4.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp + 1.0
                            < current.linear_mean_abs_error_bp
                        && candidate.linear_r2 + 0.00015 >= current.linear_r2)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_liz_clean_late_tail_family_sequence(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
    ) {
        if best
            .as_ref()
            .map(|current| {
                repair_candidate_improves_current(current, &candidate)
                    || (candidate.linear_max_abs_error_bp + 1.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp + 1.0
                            < current.linear_mean_abs_error_bp
                        && candidate.linear_r2 + 0.00015 >= current.linear_r2)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_rox_baseline_family_rebuild(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
        repair_peak_features,
    ) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = repair_rox_full_span_family_rebuild(
        best.as_ref(),
        ladder_sizes,
        ladder,
        &repair_peak_feature_by_index,
        repair_peak_features,
    ) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
            || best
                .as_ref()
                .map(|current| {
                    candidate.linear_max_abs_error_bp + 4.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp + 1.0
                            < current.linear_mean_abs_error_bp
                        && candidate.linear_r2 + 0.0002 >= current.linear_r2
                })
                .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_gs500rox_start_anchor_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_tail_outlier_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_tail_family_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| rox_tail_family_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_third_and_tail_family_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| rox_tail_family_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| {
                rox_start_pair_candidate_improves_current(current, &candidate)
                    || rox_start_pair_feature_candidate_can_override(current, &candidate)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_first_three_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_collapsed_100_anchor_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_collapsed_150_anchor_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_large_50_60_gap_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_large_100_120_gap_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_start_prefix_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_motif_start_block_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| {
                rox_start_pair_candidate_improves_current(current, &candidate)
                    || rox_start_pair_feature_candidate_can_override(current, &candidate)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_anchor_block_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| {
                rox_start_pair_candidate_improves_current(current, &candidate)
                    || rox_start_pair_feature_candidate_can_override(current, &candidate)
            })
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_start_pair_feature_arbiter_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_rox_nonlinear_start_pair_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_first_anchor_family_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_blob_early_block_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_linear_first_start_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_linear_start_and_tail_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_mid_triplet_outlier_only_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_tail_pair_split_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_tail_doublet_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_start_triplet_shift_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_shifted_start_mid_family_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_tail_apex_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_anchor_block_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_multi_anchor_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_tail_neighbor_shift_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_mid_triplet_left_shift_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_mid_triplet_anchor_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
            || best
                .as_ref()
                .map(|current| {
                    candidate.linear_max_abs_error_bp + 2.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp
                            <= current.linear_mean_abs_error_bp + 0.30
                        && candidate.linear_r2 + 0.00010 >= current.linear_r2
                })
                .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_tail_to_front_reverse_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| repair_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
            || best
                .as_ref()
                .map(|current| {
                    candidate.linear_max_abs_error_bp + 2.0 < current.linear_max_abs_error_bp
                        && candidate.linear_mean_abs_error_bp
                            <= current.linear_mean_abs_error_bp + 0.45
                        && candidate.linear_r2 + 0.00005 >= current.linear_r2
                })
                .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_bounded_suspicious_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        if best
            .as_ref()
            .map(|current| liz_bounded_candidate_improves_current(current, &candidate))
            .unwrap_or(true)
        {
            best = Some(candidate);
        }
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_tail_neighbor_shift_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_tail_doublet_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_anchor_block_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_multi_anchor_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_weak_suffix_apex_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_capped_foot_to_apex_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }
    if let Some(candidate) = best.as_ref().and_then(|score| {
        repair_liz_poor_linear_local_anchor_grid_sequence(
            score,
            ladder_sizes,
            ladder,
            &repair_peak_feature_by_index,
            repair_peak_features,
        )
    }) {
        best = Some(candidate);
    }

    let rox_minor_start_candidate = best
        .as_ref()
        .and_then(|score| {
            repair_rox_minor_start_triple_sequence(
                score,
                ladder_sizes,
                ladder,
                &repair_peak_feature_by_index,
                repair_peak_features,
            )
        })
        .or_else(|| {
            initial_best_for_rox_minor_start.as_ref().and_then(|score| {
                repair_rox_minor_start_triple_sequence(
                    score,
                    ladder_sizes,
                    ladder,
                    &repair_peak_feature_by_index,
                    repair_peak_features,
                )
            })
        });
    if let Some(candidate) = rox_minor_start_candidate {
        best = Some(candidate);
    }

    let restore_initial_best = if let (Some(initial), Some(final_score)) =
        (&initial_best_for_regression_guard, &best)
    {
        let initial_was_strong = initial.indices.len() == ladder_sizes.len()
            && initial.linear_max_abs_error_bp <= 5.0
            && initial.linear_mean_abs_error_bp <= 2.2
            && initial.linear_r2 >= 0.9990;
        let final_is_bad_review_like =
            final_score.linear_max_abs_error_bp > 8.0 || final_score.linear_mean_abs_error_bp > 3.4;
        let shifted_late_family_regression = if ladder == LadderKind::Rox400Hd
            && initial.indices.len() == ladder_sizes.len()
            && final_score.indices.len() == ladder_sizes.len()
        {
            let initial_first = initial.indices.first().copied().unwrap_or(0);
            let final_first = final_score.indices.first().copied().unwrap_or(0);
            let initial_good_normal_start = (1520..=1850).contains(&initial_first)
                && initial.linear_max_abs_error_bp <= 6.0
                && initial.linear_mean_abs_error_bp <= 2.8
                && initial.linear_r2 >= 0.9988;
            let shifted_to_late_family =
                final_first > initial_first.saturating_add(220) && final_first > 1850;
            let initial_gap_penalty =
                partial_ladder_gap_template_penalty(&initial.indices, ladder_sizes, 21);
            let final_gap_penalty =
                partial_ladder_gap_template_penalty(&final_score.indices, ladder_sizes, 21);
            let final_has_large_qc_win = final_score.linear_max_abs_error_bp + 2.0
                < initial.linear_max_abs_error_bp
                && final_score.linear_mean_abs_error_bp + 0.50 < initial.linear_mean_abs_error_bp
                && final_score.linear_r2 + 0.00020 >= initial.linear_r2;
            let final_breaks_gap_template =
                final_gap_penalty > initial_gap_penalty + 2.5 && final_gap_penalty > 3.0;
            initial_good_normal_start
                && shifted_to_late_family
                && (!final_has_large_qc_win || final_breaks_gap_template)
        } else {
            false
        };
        initial_was_strong && final_is_bad_review_like || shifted_late_family_regression
    } else {
        false
    };
    if restore_initial_best {
        best = initial_best_for_regression_guard;
    }

    best
}

fn ladder_domain_penalty(
    ladder: LadderKind,
    scans: &[usize],
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    all_peak_features: &[Peak],
) -> f64 {
    if scans.is_empty() {
        return f64::INFINITY;
    }

    let (hard_min, hard_max, preferred_min, preferred_max, max_first_anchor) = match ladder {
        LadderKind::Rox400Hd => (
            ROX_HARD_TIME_MIN,
            ROX_HARD_TIME_MAX,
            ROX_PREFERRED_TIME_MIN,
            ROX_PREFERRED_TIME_MAX,
            ROX_MAX_FIRST_ANCHOR,
        ),
        LadderKind::Gs500Rox => (
            GS500ROX_HARD_TIME_MIN,
            GS500ROX_HARD_TIME_MAX,
            GS500ROX_PREFERRED_TIME_MIN,
            GS500ROX_PREFERRED_TIME_MAX,
            GS500ROX_MAX_FIRST_ANCHOR,
        ),
        LadderKind::Liz500250 => (
            LIZ_HARD_TIME_MIN,
            LIZ_HARD_TIME_MAX,
            LIZ_PREFERRED_TIME_MIN,
            LIZ_PREFERRED_TIME_MAX,
            LIZ_MAX_FIRST_ANCHOR,
        ),
    };

    let scans_f = scans.iter().map(|value| *value as f64).collect::<Vec<_>>();
    let hard_out_fraction = scans_f
        .iter()
        .filter(|value| **value < hard_min || **value > hard_max)
        .count() as f64
        / scans_f.len() as f64;

    let median_scan = scans_f[scans_f.len() / 2];
    let median_window_penalty = if median_scan < preferred_min {
        (preferred_min - median_scan) / preferred_min.max(1.0)
    } else if median_scan > preferred_max {
        (median_scan - preferred_max) / preferred_max.max(1.0)
    } else {
        0.0
    };

    let first_anchor_late_penalty = if scans_f[0] > max_first_anchor {
        let diff = scans_f[0] - max_first_anchor;
        (diff * diff) / 10000.0 // Quad penalty for starting late
    } else {
        0.0
    };
    let first_anchor_early_penalty = if scans_f[0] < preferred_min {
        (preferred_min - scans_f[0]) / preferred_min.max(1.0)
    } else {
        0.0
    };
    let last_anchor_early_penalty = if let Some(last_scan) = scans_f.last() {
        if *last_scan < preferred_max - 260.0 {
            ((preferred_max - 260.0) - *last_scan) / preferred_max.max(1.0)
        } else {
            0.0
        }
    } else {
        0.0
    };
    let last_anchor_late_penalty = if let Some(last_scan) = scans_f.last() {
        if *last_scan > preferred_max + 80.0 {
            (*last_scan - (preferred_max + 80.0)) / preferred_max.max(1.0)
        } else {
            0.0
        }
    } else {
        0.0
    };

    // Heavy penalty for ROX fits that start far below the expected region.
    // First anchors below ~1400 are always blob contamination, never real ladder.
    let deep_early_penalty = match ladder {
        LadderKind::Rox400Hd => {
            if scans_f[0] < 1400.0 {
                ((1400.0 - scans_f[0]) / 120.0).clamp(0.0, 2.5)
            } else {
                0.0
            }
        }
        _ => 0.0,
    };

    let gap_cv_penalty = if scans_f.len() >= 3 {
        let gaps = scans_f
            .windows(2)
            .map(|window| window[1] - window[0])
            .collect::<Vec<_>>();
        let mean_gap = gaps.iter().sum::<f64>() / gaps.len() as f64;
        if mean_gap <= f64::EPSILON {
            1.0
        } else {
            let variance = gaps
                .iter()
                .map(|gap| {
                    let d = *gap - mean_gap;
                    d * d
                })
                .sum::<f64>()
                / gaps.len() as f64;
            let cv = variance.sqrt() / mean_gap;
            (cv - 0.55).max(0.0)
        }
    } else {
        0.0
    };

    let intensities = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let intensity_cv_penalty = if intensities.len() >= 4 {
        let mean_intensity = intensities.iter().sum::<f64>() / intensities.len() as f64;
        if mean_intensity <= f64::EPSILON {
            1.0
        } else {
            let variance = intensities
                .iter()
                .map(|value| {
                    let d = *value - mean_intensity;
                    d * d
                })
                .sum::<f64>()
                / intensities.len() as f64;
            let cv = variance.sqrt() / mean_intensity;
            (cv - 0.60).max(0.0)
        }
    } else {
        0.0
    };

    let prominences = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.prominence))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let widths = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.width))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();

    let weak_prominence_penalty = if !prominences.is_empty() {
        let median_prominence = median(&prominences).max(1.0);
        let target_prominence = (median_prominence * 0.45).max(25.0);
        prominences
            .iter()
            .map(|value| ((target_prominence - *value).max(0.0)) / target_prominence)
            .sum::<f64>()
            / prominences.len() as f64
    } else {
        0.0
    };

    let width_cv_penalty = coefficient_of_variation_penalty(&widths, 0.85);

    let early_skip_penalty = if !all_peak_features.is_empty() {
        let early_peaks = all_peak_features
            .iter()
            .filter(|peak| {
                let scan = peak.index as f64;
                scan >= preferred_min - 50.0
                    && scan <= (max_first_anchor + 140.0)
                    && peak.prominence >= 30.0
            })
            .collect::<Vec<_>>();
        if early_peaks.is_empty() {
            0.0
        } else {
            let early_scores = early_peaks
                .iter()
                .map(|peak| peak.score)
                .collect::<Vec<_>>();
            let score_floor = median(&early_scores) * 0.65;
            let earliest_strong = early_peaks
                .iter()
                .filter(|peak| peak.score >= score_floor.max(20.0))
                .map(|peak| peak.index as f64)
                .min_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
            if let Some(earliest) = earliest_strong {
                ((scans_f[0] - earliest - 25.0).max(0.0)) / 150.0
            } else {
                0.0
            }
        }
    } else {
        0.0
    };

    let early_cluster_penalty = if scans_f.len() >= 3 {
        let early_scan_count = scans_f
            .iter()
            .take_while(|scan| **scan < preferred_min + 250.0)
            .count();
        if early_scan_count >= 2 {
            let early_gaps = scans_f[..early_scan_count]
                .windows(2)
                .map(|window| window[1] - window[0])
                .collect::<Vec<_>>();
            let all_gaps = scans_f
                .windows(2)
                .map(|window| window[1] - window[0])
                .collect::<Vec<_>>();
            if early_gaps.is_empty() || all_gaps.is_empty() {
                0.0
            } else {
                let early_gap_median = median(&early_gaps);
                let global_gap_median = median(&all_gaps).max(1.0);
                ((global_gap_median * 0.60 - early_gap_median).max(0.0)) / global_gap_median
            }
        } else {
            0.0
        }
    } else {
        0.0
    };

    let liz_early_blob_start_penalty = if ladder == LadderKind::Liz500250 && scans_f.len() >= 3 {
        let first = scans_f[0];
        if first >= 1500.0 {
            0.0
        } else {
            let local_blob_count = all_peak_features
                .iter()
                .filter(|peak| {
                    let scan = peak.index as f64;
                    scan >= first - 10.0
                        && scan <= first + 90.0
                        && peak.prominence >= 25.0
                        && peak.height >= 20.0
                })
                .count();
            if local_blob_count < 3 {
                0.0
            } else {
                (((1500.0 - first) / 75.0).clamp(0.0, 2.6))
                    * (((local_blob_count as f64 - 2.0) / 3.0).clamp(0.4, 1.5))
                    * 1.8
            }
        }
    } else {
        0.0
    };

    let pre_window_penalty = scans_f.iter().filter(|scan| **scan < preferred_min).count() as f64
        / scans_f.len().max(1) as f64;

    hard_out_fraction * LADDER_DOMAIN_TIME_WEIGHT
        + median_window_penalty * LADDER_DOMAIN_TIME_WEIGHT
        + first_anchor_late_penalty * LADDER_DOMAIN_FIRST_ANCHOR_WEIGHT
        + first_anchor_early_penalty * (LADDER_DOMAIN_FIRST_ANCHOR_WEIGHT + 2.00)
        + last_anchor_early_penalty * (LADDER_DOMAIN_TIME_WEIGHT + 1.20)
        + last_anchor_late_penalty * (LADDER_DOMAIN_TIME_WEIGHT + 2.20)
        + deep_early_penalty * 2.80
        + gap_cv_penalty * LADDER_DOMAIN_GAP_WEIGHT
        + intensity_cv_penalty * LADDER_DOMAIN_INTENSITY_WEIGHT
        + weak_prominence_penalty * 0.35
        + width_cv_penalty * 0.20
        + early_skip_penalty * LADDER_DOMAIN_FIRST_ANCHOR_WEIGHT
        + early_cluster_penalty * 0.90
        + liz_early_blob_start_penalty
        + pre_window_penalty * 6.50
}

fn ladder_peak_sequence_penalty(
    scans: &[usize],
    ladder: LadderKind,
    ladder_sizes: &[f64],
    peak_feature_by_index: &BTreeMap<usize, Peak>,
    all_peak_features: &[Peak],
) -> f64 {
    if scans.len() < 2 || scans.len() != ladder_sizes.len() {
        return 0.0;
    }

    let gap_ratios = scans
        .windows(2)
        .zip(ladder_sizes.windows(2))
        .filter_map(|(scan_window, bp_window)| {
            let bp_gap = bp_window[1] - bp_window[0];
            if bp_gap <= f64::EPSILON {
                return None;
            }
            Some((scan_window[1] as f64 - scan_window[0] as f64) / bp_gap)
        })
        .collect::<Vec<_>>();
    let gap_ratio_penalty = coefficient_of_variation_penalty(&gap_ratios, 0.35) * 0.35;
    let median_gap_ratio = median(&gap_ratios).max(1.0);

    let rox_tail_gap_consistency_penalty = if ladder_sizes.len() == 21 && gap_ratios.len() >= 4 {
        let tail_len = gap_ratios.len().min(4);
        gap_ratios
            .iter()
            .rev()
            .take(tail_len)
            .map(|ratio| {
                ((ratio - median_gap_ratio).abs() - median_gap_ratio * 0.22).max(0.0)
                    / median_gap_ratio
            })
            .sum::<f64>()
            / tail_len as f64
            * 3.10
    } else {
        0.0
    };

    let gs500_start_penalty = if ladder == LadderKind::Gs500Rox {
        let first_scan = scans[0] as f64;
        let first_anchor_early_penalty = ((1400.0 - first_scan).max(0.0)) / 80.0;
        let first_anchor_late_penalty = ((first_scan - 1600.0).max(0.0)) / 140.0;
        let first_gap_penalty = scans
            .windows(2)
            .next()
            .map(|window| {
                let gap = window[1] as f64 - window[0] as f64;
                let low_penalty = ((45.0 - gap).max(0.0)) / 25.0;
                let high_penalty = ((gap - 170.0).max(0.0)) / 55.0;
                low_penalty + high_penalty
            })
            .unwrap_or(0.0);
        let fourth_gap_penalty = if scans.len() >= 5 {
            let gap_100_to_139 = scans[4] as f64 - scans[3] as f64;
            let low_penalty = ((90.0 - gap_100_to_139).max(0.0)) / 70.0;
            let high_penalty = ((gap_100_to_139 - 430.0).max(0.0)) / 150.0;
            low_penalty + high_penalty
        } else {
            0.0
        };
        first_anchor_early_penalty * 1.45
            + first_anchor_late_penalty * 0.35
            + first_gap_penalty * 0.18
            + fourth_gap_penalty * 0.12
    } else if ladder_sizes.len() == 16 {
        let first_scan = scans[0] as f64;
        let first_anchor_penalty =
            ((GS500ROX_PREFERRED_TIME_MIN + 30.0 - first_scan).max(0.0)) / 95.0;
        let first_gap_penalty = scans
            .windows(2)
            .next()
            .map(|window| {
                let gap = window[1] as f64 - window[0] as f64;
                let low_penalty = ((66.0 - gap).max(0.0)) / 28.0;
                let high_penalty = ((gap - 80.0).max(0.0)) / 26.0;
                low_penalty + high_penalty
            })
            .unwrap_or(0.0);
        first_anchor_penalty * 1.35 + first_gap_penalty * 0.45
    } else {
        0.0
    };

    let rox_start_penalty = if ladder_sizes.len() == 21 {
        let first_scan = scans[0] as f64;
        let first_anchor_penalty = ((1620.0 - first_scan).max(0.0)) / 95.0;
        let first_gap_penalty = scans
            .windows(2)
            .next()
            .map(|window| {
                let gap = window[1] as f64 - window[0] as f64;
                ((gap - 85.0).max(0.0)) / 36.0
            })
            .unwrap_or(0.0);
        first_anchor_penalty * 1.60 + first_gap_penalty * 1.15
    } else {
        0.0
    };

    let liz_start_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 3 {
        let first_scan = scans[0] as f64;
        let first_gap = scans[1] as f64 - scans[0] as f64;
        let second_gap = scans[2] as f64 - scans[1] as f64;
        let third_gap = if scans.len() >= 4 {
            scans[3] as f64 - scans[2] as f64
        } else {
            0.0
        };
        let first_anchor_late_penalty = ((first_scan - 1490.0).max(0.0)) / 75.0;
        let first_anchor_early_penalty = ((1490.0 - first_scan).max(0.0)) / 60.0;
        let first_gap_low = ((46.0 - first_gap).max(0.0)) / 20.0;
        let first_gap_high = ((first_gap - 90.0).max(0.0)) / 42.0;
        let second_gap_low = ((40.0 - second_gap).max(0.0)) / 18.0;
        let second_gap_high = if scans.len() >= 3 {
            ((second_gap - 170.0).max(0.0)) / 44.0
        } else {
            0.0
        };
        let third_gap_high = if scans.len() >= 4 {
            ((third_gap - 185.0).max(0.0)) / 56.0
        } else {
            0.0
        };
        let early_span_high = if scans.len() >= 4 {
            let early_span = scans[3] as f64 - scans[0] as f64;
            ((early_span - 470.0).max(0.0)) / 120.0
        } else {
            0.0
        };
        first_anchor_late_penalty * 1.85
            + first_anchor_early_penalty * 2.10
            + first_gap_low * 1.25
            + first_gap_high * 0.85
            + second_gap_low * 0.75
            + second_gap_high * 1.05
            + third_gap_high * 1.30
            + early_span_high * 0.95
    } else {
        0.0
    };

    let bridge_skip_penalty = if ladder_sizes.len() == 16 && scans.len() >= 2 {
        let first = scans[0];
        let second = scans[1];
        let candidate = all_peak_features
            .iter()
            .filter(|peak| {
                peak.index > first.saturating_add(10)
                    && peak.index + 10 < second
                    && peak.prominence >= 120.0
                    && peak.score >= 850.0
            })
            .max_by(|left, right| {
                left.score
                    .partial_cmp(&right.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        if let Some(peak) = candidate {
            let score_ref = peak_feature_by_index
                .get(&scans[1])
                .map(|selected| selected.score.max(1.0))
                .unwrap_or(1.0);
            ((peak.score / score_ref).clamp(0.0, 1.25)) * 0.85
        } else {
            0.0
        }
    } else {
        0.0
    };

    let rox_bridge_skip_penalty = if ladder_sizes.len() == 21 && scans.len() >= 2 {
        let first = scans[0];
        let second = scans[1];
        let candidate = all_peak_features
            .iter()
            .filter(|peak| {
                peak.index > first.saturating_add(8)
                    && peak.index + 8 < second
                    && peak.prominence >= 80.0
                    && peak.score >= 220.0
            })
            .max_by(|left, right| {
                left.score
                    .partial_cmp(&right.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        if let Some(peak) = candidate {
            let score_ref = peak_feature_by_index
                .get(&scans[1])
                .map(|selected| selected.score.max(1.0))
                .unwrap_or(1.0);
            ((peak.score / score_ref).clamp(0.0, 1.35)) * 0.95
        } else {
            0.0
        }
    } else {
        0.0
    };

    let liz_bridge_skip_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 2 {
        let first = scans[0];
        let second = scans[1];
        let candidate = all_peak_features
            .iter()
            .filter(|peak| {
                peak.index > first.saturating_add(8)
                    && peak.index + 8 < second
                    && peak.prominence >= 55.0
                    && peak.score >= 120.0
                    && (peak.prominence / peak.height.max(1.0)) >= 0.45
            })
            .max_by(|left, right| {
                left.score
                    .partial_cmp(&right.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        if let Some(peak) = candidate {
            let score_ref = peak_feature_by_index
                .get(&scans[1])
                .map(|selected| selected.score.max(1.0))
                .unwrap_or(1.0);
            ((peak.score / score_ref).clamp(0.0, 1.6)) * 1.35
        } else {
            0.0
        }
    } else {
        0.0
    };

    let rox_blob_cluster_penalty = if ladder_sizes.len() == 21 && scans.len() >= 3 {
        let first = scans[0] as f64;
        let first_gap = scans[1] as f64 - scans[0] as f64;
        let second_gap = scans[2] as f64 - scans[1] as f64;
        // Primary pattern: dense cluster at start with gap to next real peak
        let dense_selected_start = first < 1605.0 && first_gap < 52.0 && second_gap > 80.0;
        // Fallback: any start below 1480 with nearby blob peaks is suspicious
        let deep_early_blob = first < 1480.0 && {
            let local_blob_count = all_peak_features
                .iter()
                .filter(|peak| {
                    let scan = peak.index as f64;
                    scan >= first - 15.0
                        && scan <= first + 60.0
                        && peak.prominence >= 40.0
                        && peak.height >= 70.0
                })
                .count();
            local_blob_count >= 3
        };
        if dense_selected_start {
            let local_cluster = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index >= scans[0].saturating_sub(10)
                        && peak.index <= scans[1].saturating_add(25)
                        && peak.prominence >= 45.0
                })
                .count();
            let cluster_factor = ((local_cluster as f64 - 2.0).max(0.0) / 4.0).clamp(0.0, 1.0);
            let early_factor = ((1605.0 - first).max(0.0) / 120.0).clamp(0.0, 1.0);
            let gap_factor = ((52.0 - first_gap).max(0.0) / 36.0).clamp(0.0, 1.0);
            (0.55 + cluster_factor + early_factor + gap_factor) * 1.25
        } else if deep_early_blob {
            ((1480.0 - first).max(0.0) / 100.0).clamp(0.3, 1.8) * 1.40
        } else {
            0.0
        }
    } else {
        0.0
    };

    let gs500_blob_cluster_penalty = if ladder_sizes.len() == 16 && scans.len() >= 4 {
        let cluster_candidates = all_peak_features
            .iter()
            .filter(|peak| {
                peak.index >= scans[0].saturating_sub(20)
                    && peak.index <= scans[2].saturating_add(20)
                    && peak.prominence >= 500.0
            })
            .collect::<Vec<_>>();
        let dense_cluster = cluster_candidates.len() >= 4;
        let early_start = scans[0] < 1650;
        if dense_cluster && early_start {
            ((1650.0 - scans[0] as f64).max(0.0) / 140.0) * 1.10
        } else {
            0.0
        }
    } else {
        0.0
    };

    let gs500_tail_twin_penalty = if ladder_sizes.len() == 16 && scans.len() >= 3 {
        let selected_tail = &scans[scans.len() - 3..];
        let strong_tail_candidates = all_peak_features
            .iter()
            .filter(|peak| {
                peak.index >= selected_tail[0].saturating_sub(10) && peak.prominence >= 300.0
            })
            .map(|peak| peak.index)
            .collect::<Vec<_>>();
        let has_late_twin = strong_tail_candidates
            .iter()
            .any(|index| *index >= scans[scans.len() - 1] + 35);
        let second_last_too_early = scans[scans.len() - 2] + 55 < scans[scans.len() - 1];
        if has_late_twin && second_last_too_early {
            0.95
        } else {
            0.0
        }
    } else {
        0.0
    };

    let early_gap_penalty = if gap_ratios.len() >= 3 {
        let early_len = gap_ratios.len().min(4);
        gap_ratios
            .iter()
            .take(early_len)
            .map(|ratio| ((median_gap_ratio * 0.72 - *ratio).max(0.0)) / median_gap_ratio)
            .sum::<f64>()
            / early_len as f64
            * 0.95
    } else {
        0.0
    };

    let selected_scores = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.score))
        .collect::<Vec<_>>();
    let weak_score_penalty = if !selected_scores.is_empty() {
        let median_score = median(&selected_scores).max(1.0);
        let target_score = (median_score * 0.45).max(20.0);
        selected_scores
            .iter()
            .map(|value| ((target_score - *value).max(0.0)) / target_score)
            .sum::<f64>()
            / selected_scores.len() as f64
            * 0.55
    } else {
        0.0
    };

    let liz_mid_triplet_skip_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 8 {
        let mut penalties = Vec::new();
        for pair_index in 3..scans.len().saturating_sub(1).min(14) {
            let left_scan = scans[pair_index];
            let right_scan = scans[pair_index + 1];
            let left_peak = if let Some(value) = peak_feature_by_index.get(&left_scan) {
                value
            } else {
                continue;
            };
            let right_peak = if let Some(value) = peak_feature_by_index.get(&right_scan) {
                value
            } else {
                continue;
            };
            let selected_gap = right_scan.saturating_sub(left_scan) as f64;
            let expected_gap_bp = ladder_sizes[pair_index + 1] - ladder_sizes[pair_index];
            if expected_gap_bp <= f64::EPSILON {
                continue;
            }
            let expected_scan_gap = median_gap_ratio * expected_gap_bp;
            if selected_gap <= expected_scan_gap * 1.45 {
                continue;
            }

            let candidate = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index > left_scan.saturating_add(10)
                        && peak.index + 10 < right_scan
                        && peak.prominence >= 55.0
                        && peak.score >= 90.0
                        && (peak.prominence / peak.height.max(1.0)) >= 0.42
                })
                .max_by(|left, right| {
                    left.score
                        .partial_cmp(&right.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
            let Some(candidate) = candidate else {
                continue;
            };
            let candidate_vs_neighbors =
                (candidate.score / left_peak.score.max(right_peak.score).max(1.0)).clamp(0.0, 2.0);
            let gap_improvement =
                ((selected_gap - expected_scan_gap) / expected_scan_gap.max(1.0)).clamp(0.0, 2.0);
            if candidate_vs_neighbors < 0.35 {
                continue;
            }
            penalties.push(gap_improvement * candidate_vs_neighbors);
        }
        penalties.into_iter().fold(0.0_f64, f64::max) * 1.85
    } else {
        0.0
    };

    let selected_heights = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();
    let selected_prominences = scans
        .iter()
        .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.prominence))
        .filter(|value| value.is_finite() && *value > 0.0)
        .collect::<Vec<_>>();

    let intensity_outlier_penalty = if selected_heights.len() >= 4 {
        let median_height = median(&selected_heights).max(1.0);
        let absolute_soft_ceiling = match ladder {
            LadderKind::Rox400Hd => 1800.0,
            LadderKind::Gs500Rox => 2500.0,
            LadderKind::Liz500250 => 5000.0,
        };
        let relative_soft_ceiling = match ladder {
            LadderKind::Rox400Hd => (median_height * 2.8).max(absolute_soft_ceiling),
            _ => (median_height * 3.6).max(absolute_soft_ceiling),
        };
        selected_heights
            .iter()
            .map(|height| ((height - relative_soft_ceiling).max(0.0)) / relative_soft_ceiling)
            .sum::<f64>()
            / selected_heights.len() as f64
            * match ladder {
                LadderKind::Rox400Hd => 1.45,
                _ => 0.55,
            }
    } else {
        0.0
    };

    let low_intensity_outlier_penalty = if selected_heights.len() >= 4 {
        let median_height = median(&selected_heights).max(1.0);
        let soft_floor = match ladder {
            LadderKind::Liz500250 => (median_height * 0.32).clamp(85.0, 170.0),
            LadderKind::Rox400Hd => (median_height * 0.24).clamp(28.0, 90.0),
            LadderKind::Gs500Rox => (median_height * 0.28).clamp(55.0, 140.0),
        };
        scans
            .iter()
            .filter_map(|scan| {
                let peak = peak_feature_by_index.get(scan)?;
                let height = peak.height.max(1.0);
                let weakness = ((soft_floor - height).max(0.0)) / soft_floor;
                if weakness <= 0.0 {
                    return Some(0.0);
                }
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                let suspicious = baseline_ratio > 0.22 || purity < 0.58 || weakness > 0.25;
                if !suspicious {
                    return Some(0.0);
                }
                Some(weakness * (0.55 + baseline_ratio * 0.95 + (0.62 - purity).max(0.0)))
            })
            .sum::<f64>()
            / selected_heights.len() as f64
            * match ladder {
                LadderKind::Liz500250 => 1.10,
                LadderKind::Rox400Hd => 1.35,
                LadderKind::Gs500Rox => 0.60,
            }
    } else {
        0.0
    };

    let rox_family_signal_penalty = if ladder == LadderKind::Rox400Hd
        && selected_heights.len() >= 6
        && selected_prominences.len() >= 6
    {
        let median_height = median(&selected_heights).max(1.0);
        let median_prominence = median(&selected_prominences).max(1.0);
        scans
            .iter()
            .enumerate()
            .filter_map(|(index, scan)| {
                let peak = peak_feature_by_index.get(scan)?;
                let height_ratio = peak.height / median_height;
                let prominence_ratio = peak.prominence / median_prominence;
                let baseline_ratio =
                    (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.0);

                let very_low = height_ratio < 0.20 && prominence_ratio < 0.20;
                let low_tail = scan >= &3600usize && height_ratio < 0.24 && prominence_ratio < 0.22;
                let huge_blob = index == 0 && height_ratio > 3.2 && baseline_ratio > 0.10;
                let mixed_blob = height_ratio > 4.4 && purity < 0.42;

                if !(very_low || low_tail || huge_blob || mixed_blob) {
                    return Some(0.0);
                }

                let low_penalty =
                    ((0.24 - height_ratio).max(0.0) + (0.24 - prominence_ratio).max(0.0)) * 1.8;
                let blob_penalty = ((height_ratio - 3.2).max(0.0) * 0.35)
                    + ((baseline_ratio - 0.10).max(0.0) * 4.5)
                    + ((0.46 - purity).max(0.0) * 3.0);
                Some(low_penalty + blob_penalty)
            })
            .sum::<f64>()
            / selected_heights.len() as f64
            * 1.85
    } else {
        0.0
    };

    let liz_isolated_low_peak_penalty = if ladder == LadderKind::Liz500250
        && selected_heights.len() >= 6
        && selected_prominences.len() >= 6
    {
        let median_height = median(&selected_heights).max(1.0);
        let median_prominence = median(&selected_prominences).max(1.0);
        if median_height < 220.0 && median_prominence < 180.0 {
            0.0
        } else {
            scans
                .iter()
                .enumerate()
                .filter_map(|(index, scan)| {
                    let peak = peak_feature_by_index.get(scan)?;
                    let height_ratio = peak.height / median_height;
                    let prominence_ratio = peak.prominence / median_prominence;
                    if height_ratio >= 0.40 && prominence_ratio >= 0.38 {
                        return Some(0.0);
                    }

                    let mut neighbor_heights = Vec::with_capacity(2);
                    let mut neighbor_prominences = Vec::with_capacity(2);
                    if index > 0 {
                        if let Some(left) = peak_feature_by_index.get(&scans[index - 1]) {
                            neighbor_heights.push(left.height);
                            neighbor_prominences.push(left.prominence);
                        }
                    }
                    if index + 1 < scans.len() {
                        if let Some(right) = peak_feature_by_index.get(&scans[index + 1]) {
                            neighbor_heights.push(right.height);
                            neighbor_prominences.push(right.prominence);
                        }
                    }
                    if neighbor_heights.is_empty() || neighbor_prominences.is_empty() {
                        return Some(0.0);
                    }

                    let neighbor_height_ref = median(&neighbor_heights).max(1.0);
                    let neighbor_prominence_ref = median(&neighbor_prominences).max(1.0);
                    let local_height_ratio = peak.height / neighbor_height_ref;
                    let local_prominence_ratio = peak.prominence / neighbor_prominence_ref;
                    if local_height_ratio >= 0.52 && local_prominence_ratio >= 0.48 {
                        return Some(0.0);
                    }

                    let absolute_height_floor = (median_height * 0.18).clamp(80.0, 165.0);
                    let absolute_prominence_floor = (median_prominence * 0.18).clamp(55.0, 150.0);
                    let weak_height = ((0.40 - height_ratio).max(0.0)) / 0.40;
                    let weak_prominence = ((0.38 - prominence_ratio).max(0.0)) / 0.38;
                    let local_height_valley = ((0.52 - local_height_ratio).max(0.0)) / 0.52;
                    let local_prominence_valley = ((0.48 - local_prominence_ratio).max(0.0)) / 0.48;
                    let absolute_height_weakness =
                        ((absolute_height_floor - peak.height).max(0.0)) / absolute_height_floor;
                    let absolute_prominence_weakness =
                        ((absolute_prominence_floor - peak.prominence).max(0.0))
                            / absolute_prominence_floor;
                    let position_weight = if index == 0 || index + 1 == scans.len() {
                        0.75
                    } else if index <= 2 {
                        1.00
                    } else {
                        1.18
                    };
                    Some(
                        (weak_height * 0.30
                            + weak_prominence * 0.55
                            + local_height_valley * 0.65
                            + local_prominence_valley * 1.00
                            + absolute_height_weakness * 0.25
                            + absolute_prominence_weakness * 0.35)
                            * position_weight,
                    )
                })
                .sum::<f64>()
                / scans.len() as f64
                * 1.40
        }
    } else {
        0.0
    };

    let prominence_uniformity_penalty = if selected_prominences.len() >= 4 {
        coefficient_of_variation_penalty(&selected_prominences, 0.70) * 0.35
    } else {
        0.0
    };

    let neighbor_intensity_penalty = scans
        .windows(2)
        .filter_map(|window| {
            let left = peak_feature_by_index.get(&window[0])?;
            let right = peak_feature_by_index.get(&window[1])?;
            let high = left.prominence.max(right.prominence).max(1.0);
            let low = left.prominence.min(right.prominence).max(1.0);
            Some((high / low).ln().max(0.0))
        })
        .sum::<f64>()
        / (scans.len() - 1) as f64
        * 0.20;

    let late_weak_penalty = if !selected_scores.is_empty() {
        let median_score = median(&selected_scores).max(1.0);
        let selected_heights = scans
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
            .collect::<Vec<_>>();
        let median_height = median(&selected_heights).max(1.0);
        let late_score_floor = (median_score * 0.30).max(16.0);
        let late_height_floor = (median_height * 0.35).max(55.0);
        scans
            .iter()
            .enumerate()
            .filter_map(|(index, scan)| {
                let peak = peak_feature_by_index.get(scan)?;
                let position = index as f64 / (scans.len().saturating_sub(1).max(1) as f64);
                if position < 0.55 {
                    return None;
                }
                let score_penalty = ((late_score_floor - peak.score).max(0.0)) / late_score_floor;
                let height_penalty =
                    ((late_height_floor - peak.height).max(0.0)) / late_height_floor;
                Some((score_penalty + height_penalty) * position)
            })
            .sum::<f64>()
            / scans.len() as f64
            * 0.70
    } else {
        0.0
    };

    let rox_tail_endpoint_penalty = if ladder_sizes.len() == 21 && scans.len() >= 6 {
        let tail_selected = scans
            .iter()
            .rev()
            .take(5)
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .collect::<Vec<_>>();
        if tail_selected.len() >= 4 {
            let endpoint = tail_selected[0];
            let tail_reference_heights = tail_selected
                .iter()
                .skip(1)
                .map(|peak| peak.height)
                .filter(|value| value.is_finite() && *value > 0.0)
                .collect::<Vec<_>>();
            let tail_reference_scores = tail_selected
                .iter()
                .skip(1)
                .map(|peak| peak.score)
                .filter(|value| value.is_finite() && *value > 0.0)
                .collect::<Vec<_>>();
            if tail_reference_heights.is_empty() || tail_reference_scores.is_empty() {
                0.0
            } else {
                let height_ref = median(&tail_reference_heights).max(1.0);
                let score_ref = median(&tail_reference_scores).max(1.0);
                let height_ratio = endpoint.height / height_ref;
                let score_ratio = endpoint.score / score_ref;
                let weak_height = ((0.55 - height_ratio).max(0.0)) / 0.55;
                let weak_score = ((0.55 - score_ratio).max(0.0)) / 0.55;
                let absolute_weak_height = ((28.0 - endpoint.height).max(0.0)) / 28.0;
                let absolute_weak_score = ((18.0 - endpoint.score).max(0.0)) / 18.0;
                (weak_height * 1.10
                    + weak_score * 1.15
                    + absolute_weak_height * 1.10
                    + absolute_weak_score * 0.95)
                    * 2.10
            }
        } else {
            0.0
        }
    } else {
        0.0
    };

    let rox_tail_skip_penalty = if ladder_sizes.len() == 21 && scans.len() >= 6 {
        let mut penalties = Vec::new();
        let tail_start = scans.len().saturating_sub(5);
        for pair_index in tail_start..scans.len().saturating_sub(1) {
            let left_scan = scans[pair_index];
            let right_scan = scans[pair_index + 1];
            let left_peak = if let Some(value) = peak_feature_by_index.get(&left_scan) {
                value
            } else {
                continue;
            };
            let right_peak = if let Some(value) = peak_feature_by_index.get(&right_scan) {
                value
            } else {
                continue;
            };
            let selected_gap = right_scan.saturating_sub(left_scan) as f64;
            let expected_gap_bp = ladder_sizes[pair_index + 1] - ladder_sizes[pair_index];
            if expected_gap_bp <= f64::EPSILON {
                continue;
            }
            let expected_scan_gap = median_gap_ratio * expected_gap_bp;
            if selected_gap <= expected_scan_gap * 1.20 {
                continue;
            }

            let candidate = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index > left_scan.saturating_add(12)
                        && peak.index + 12 < right_scan
                        && peak.prominence >= 14.0
                        && peak.score >= 14.0
                })
                .max_by(|left, right| {
                    left.score
                        .partial_cmp(&right.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
            let Some(candidate) = candidate else {
                continue;
            };

            let gap_improvement =
                ((selected_gap - expected_scan_gap) / expected_scan_gap.max(1.0)).max(0.0);
            let candidate_left_gap = candidate.index.saturating_sub(left_scan) as f64;
            let candidate_right_gap = right_scan.saturating_sub(candidate.index) as f64;
            let candidate_gap_error = ((candidate_left_gap - expected_scan_gap)
                .abs()
                .min((candidate_right_gap - expected_scan_gap).abs()))
                / expected_scan_gap.max(1.0);
            let gap_closeness = (1.15 - candidate_gap_error).clamp(0.15, 1.15);
            let candidate_vs_right = (candidate.score / right_peak.score.max(1.0)).clamp(0.0, 2.0);
            let candidate_vs_left = (candidate.score / left_peak.score.max(1.0)).clamp(0.0, 2.0);
            let candidate_height_vs_right =
                (candidate.height / right_peak.height.max(1.0)).clamp(0.0, 3.0);
            let candidate_strength = candidate_vs_right
                .max(candidate_vs_left)
                .max(candidate_height_vs_right)
                .min(2.2);
            let weak_right_penalty =
                ((0.55 - (right_peak.height / candidate.height.max(1.0))).max(0.0)) / 0.55;
            let severe_skip_bonus = if gap_closeness >= 0.85 && candidate_strength >= 0.75 {
                2.25
            } else {
                0.0
            };
            penalties.push(
                gap_improvement.min(1.8)
                    * gap_closeness
                    * (candidate_strength + weak_right_penalty * 0.75)
                    + severe_skip_bonus,
            );
        }
        if penalties.is_empty() {
            0.0
        } else {
            penalties.iter().copied().fold(0.0_f64, f64::max) * 3.75
        }
    } else {
        0.0
    };

    let early_baseline_penalty = if scans.len() >= 4 {
        let early_len = scans.len().min(5);
        scans
            .iter()
            .take(early_len)
            .filter_map(|scan| {
                let peak = peak_feature_by_index.get(scan)?;
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                Some((baseline_ratio * (1.0 - 0.65 * purity)).max(0.0))
            })
            .sum::<f64>()
            / early_len as f64
            * 0.85
    } else {
        0.0
    };

    let liz_early_baseline_blob_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 4 {
        let early_len = scans.len().min(5);
        scans
            .iter()
            .take(early_len)
            .enumerate()
            .filter_map(|(index, scan)| {
                let peak = peak_feature_by_index.get(scan)?;
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                let weak_height = ((70.0 - peak.height).max(0.0)) / 70.0;
                let weak_prominence = ((55.0 - peak.prominence).max(0.0)) / 55.0;
                let position_weight = 1.2 - 0.15 * index as f64;
                Some(
                    ((baseline_ratio - 0.18).max(0.0) / 0.82
                        + (0.55 - purity).max(0.0) / 0.55
                        + weak_height
                        + weak_prominence)
                        * position_weight.max(0.6),
                )
            })
            .sum::<f64>()
            / early_len as f64
            * 1.45
    } else {
        0.0
    };

    let liz_blob_cluster_start_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 5 {
        let early = &scans[..scans.len().min(5)];
        let selected_heights = early
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>();
        let median_height = if selected_heights.is_empty() {
            1.0
        } else {
            median(&selected_heights).max(1.0)
        };
        let cluster_width = early[early.len() - 1].saturating_sub(early[0]) as f64;
        let tight_pairs = early
            .windows(2)
            .filter(|pair| pair[1].saturating_sub(pair[0]) <= 55)
            .count();
        let weak_or_dirty = early
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                baseline_ratio > 0.45 || purity < 0.42
            })
            .count();
        let giant_blob = early
            .iter()
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .filter(|peak| {
                let height = peak.height.max(1.0);
                let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
                let purity = (peak.prominence / height).clamp(0.0, 1.0);
                peak.index < 1500
                    && peak.height > median_height * 3.5
                    && (baseline_ratio > 0.10 || purity < 0.55)
            })
            .count();
        if cluster_width <= 220.0 && tight_pairs >= 2 && (weak_or_dirty >= 2 || giant_blob >= 1) {
            let density_penalty = ((220.0 - cluster_width).max(0.0)) / 220.0;
            let tight_penalty = (tight_pairs as f64 - 1.0).max(0.0) / 3.0;
            let dirty_penalty = weak_or_dirty as f64 / early.len() as f64;
            let blob_penalty = giant_blob as f64;
            (density_penalty + tight_penalty + dirty_penalty + blob_penalty) * 4.2
        } else {
            0.0
        }
    } else {
        0.0
    };

    let liz_post_blob_start_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 3 {
        let first = scans[0];
        let second = scans[1];
        let selected_first = peak_feature_by_index.get(&first);
        let selected_second = peak_feature_by_index.get(&second);
        if let (Some(first_peak), Some(second_peak)) = (selected_first, selected_second) {
            let first_height = first_peak.height.max(1.0);
            let first_purity = (first_peak.prominence / first_height).clamp(0.0, 1.0);
            let first_baseline_ratio =
                (first_peak.local_baseline.max(0.0) / first_height).clamp(0.0, 1.5);
            let cluster_count = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index >= first.saturating_sub(10)
                        && peak.index <= first.saturating_add(95)
                        && peak.prominence >= 20.0
                        && peak.height >= 18.0
                })
                .count();
            let later_clean_candidate = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index > first.saturating_add(35)
                        && peak.index < first.saturating_add(170)
                        && peak.index + 8 < second
                        && peak.prominence >= first_peak.prominence * 0.55
                        && peak.height >= first_peak.height * 0.45
                })
                .max_by(|left, right| {
                    let left_height = left.height.max(1.0);
                    let right_height = right.height.max(1.0);
                    let left_purity = (left.prominence / left_height).clamp(0.0, 1.0);
                    let right_purity = (right.prominence / right_height).clamp(0.0, 1.0);
                    let left_baseline_ratio =
                        (left.local_baseline.max(0.0) / left_height).clamp(0.0, 1.5);
                    let right_baseline_ratio =
                        (right.local_baseline.max(0.0) / right_height).clamp(0.0, 1.5);
                    let left_rank = left.score + left_purity * 120.0 - left_baseline_ratio * 180.0;
                    let right_rank =
                        right.score + right_purity * 120.0 - right_baseline_ratio * 180.0;
                    left_rank
                        .partial_cmp(&right_rank)
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
            if let Some(candidate) = later_clean_candidate {
                let candidate_height = candidate.height.max(1.0);
                let candidate_purity = (candidate.prominence / candidate_height).clamp(0.0, 1.0);
                let candidate_baseline_ratio =
                    (candidate.local_baseline.max(0.0) / candidate_height).clamp(0.0, 1.5);
                let candidate_is_cleaner = candidate_purity >= first_purity + 0.08
                    || candidate_baseline_ratio + 0.10 < first_baseline_ratio;
                let candidate_is_family_like = candidate.height >= second_peak.height * 0.45
                    && candidate.height <= second_peak.height * 1.55
                    && candidate.prominence >= second_peak.prominence * 0.45;
                if cluster_count >= 4
                    && first < 1525
                    && candidate_is_cleaner
                    && candidate_is_family_like
                {
                    (((cluster_count as f64 - 3.0) / 3.0).clamp(0.4, 1.6))
                        * ((candidate.index.saturating_sub(first) as f64 / 110.0).clamp(0.4, 1.4))
                        * 1.55
                } else {
                    0.0
                }
            } else {
                0.0
            }
        } else {
            0.0
        }
    } else {
        0.0
    };

    let liz_first_family_anchor_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 4 {
        let first = scans[0];
        let second = scans[1];
        let family = scans
            .iter()
            .take(4)
            .filter_map(|scan| peak_feature_by_index.get(scan))
            .collect::<Vec<_>>();
        if family.len() < 4 {
            0.0
        } else {
            let ref_heights = family
                .iter()
                .skip(1)
                .map(|peak| peak.height)
                .collect::<Vec<_>>();
            let ref_prominences = family
                .iter()
                .skip(1)
                .map(|peak| peak.prominence)
                .collect::<Vec<_>>();
            let height_ref = median(&ref_heights).max(1.0);
            let prominence_ref = median(&ref_prominences).max(1.0);
            let first_peak = family[0];
            let first_height_ratio = first_peak.height / height_ref;
            let first_prominence_ratio = first_peak.prominence / prominence_ref;
            let first_purity = (first_peak.prominence / first_peak.height.max(1.0)).clamp(0.0, 1.0);
            let first_baseline_ratio =
                (first_peak.local_baseline.max(0.0) / first_peak.height.max(1.0)).clamp(0.0, 1.5);

            let local_cluster_count = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index >= first.saturating_sub(10)
                        && peak.index <= second.saturating_add(20)
                        && peak.prominence >= 18.0
                        && peak.height >= 18.0
                })
                .count();

            let better_later_anchor = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index > first.saturating_add(16)
                        && peak.index + 8 < second
                        && peak.height >= height_ref * 0.45
                        && peak.height <= height_ref * 1.70
                        && peak.prominence >= prominence_ref * 0.42
                })
                .max_by(|left, right| {
                    let left_height_ratio = (left.height / height_ref).clamp(0.0, 3.0);
                    let right_height_ratio = (right.height / height_ref).clamp(0.0, 3.0);
                    let left_prominence_ratio = (left.prominence / prominence_ref).clamp(0.0, 3.0);
                    let right_prominence_ratio =
                        (right.prominence / prominence_ref).clamp(0.0, 3.0);
                    let left_purity = (left.prominence / left.height.max(1.0)).clamp(0.0, 1.0);
                    let right_purity = (right.prominence / right.height.max(1.0)).clamp(0.0, 1.0);
                    let left_baseline_ratio =
                        (left.local_baseline.max(0.0) / left.height.max(1.0)).clamp(0.0, 1.5);
                    let right_baseline_ratio =
                        (right.local_baseline.max(0.0) / right.height.max(1.0)).clamp(0.0, 1.5);
                    let left_family_match = 1.0
                        - ((1.0 - left_height_ratio).abs() * 0.85
                            + (1.0 - left_prominence_ratio).abs() * 1.05)
                            .clamp(0.0, 1.8);
                    let right_family_match = 1.0
                        - ((1.0 - right_height_ratio).abs() * 0.85
                            + (1.0 - right_prominence_ratio).abs() * 1.05)
                            .clamp(0.0, 1.8);
                    let left_rank =
                        left_family_match * 220.0 + left_purity * 70.0 + left.score * 0.05
                            - left_baseline_ratio * 120.0;
                    let right_rank =
                        right_family_match * 220.0 + right_purity * 70.0 + right.score * 0.05
                            - right_baseline_ratio * 120.0;
                    left_rank
                        .partial_cmp(&right_rank)
                        .unwrap_or(std::cmp::Ordering::Equal)
                });

            if let Some(candidate) = better_later_anchor {
                let candidate_height_ratio = (candidate.height / height_ref).clamp(0.0, 3.0);
                let candidate_prominence_ratio =
                    (candidate.prominence / prominence_ref).clamp(0.0, 3.0);
                let candidate_purity =
                    (candidate.prominence / candidate.height.max(1.0)).clamp(0.0, 1.0);
                let candidate_baseline_ratio =
                    (candidate.local_baseline.max(0.0) / candidate.height.max(1.0)).clamp(0.0, 1.5);
                let first_family_match = 1.0
                    - ((1.0 - first_height_ratio).abs() * 0.85
                        + (1.0 - first_prominence_ratio).abs() * 1.05)
                        .clamp(0.0, 1.8);
                let candidate_family_match = 1.0
                    - ((1.0 - candidate_height_ratio).abs() * 0.85
                        + (1.0 - candidate_prominence_ratio).abs() * 1.05)
                        .clamp(0.0, 1.8);
                let candidate_is_cleaner = candidate_purity >= first_purity + 0.04
                    || candidate_baseline_ratio + 0.06 < first_baseline_ratio;
                let candidate_is_better_family = candidate_family_match
                    >= first_family_match + 0.22
                    || (candidate_family_match >= 0.72
                        && first_family_match <= 0.45
                        && candidate_is_cleaner);
                let very_early_first = first < 1510;
                let cluster_weight =
                    ((local_cluster_count as f64 - 2.0).max(0.0) / 3.0).clamp(0.25, 1.5);
                let gap_weight = ((candidate.index.saturating_sub(first) as f64 - 14.0).max(0.0)
                    / 90.0)
                    .clamp(0.25, 1.3);
                if candidate_is_better_family && (very_early_first || local_cluster_count >= 4) {
                    (0.65
                        + (first_family_match.max(0.0) - candidate_family_match.max(0.0)).abs()
                        + ((0.60 - first_purity).max(0.0) / 0.60)
                        + ((first_baseline_ratio - candidate_baseline_ratio).max(0.0) / 0.40))
                        * cluster_weight
                        * gap_weight
                        * 1.55
                } else {
                    0.0
                }
            } else {
                0.0
            }
        }
    } else {
        0.0
    };

    let liz_tail_skip_penalty = if ladder == LadderKind::Liz500250 && scans.len() >= 5 {
        let mut penalties = Vec::new();
        let tail_start = scans.len().saturating_sub(4);
        for pair_index in tail_start..scans.len().saturating_sub(1) {
            let left_scan = scans[pair_index];
            let right_scan = scans[pair_index + 1];
            let left_peak = if let Some(value) = peak_feature_by_index.get(&left_scan) {
                value
            } else {
                continue;
            };
            let right_peak = if let Some(value) = peak_feature_by_index.get(&right_scan) {
                value
            } else {
                continue;
            };
            let selected_gap = right_scan.saturating_sub(left_scan) as f64;
            let expected_gap_bp = ladder_sizes[pair_index + 1] - ladder_sizes[pair_index];
            if expected_gap_bp <= f64::EPSILON {
                continue;
            }
            let expected_scan_gap = median_gap_ratio * expected_gap_bp;
            if selected_gap <= expected_scan_gap * 1.15 {
                continue;
            }

            let candidate = all_peak_features
                .iter()
                .filter(|peak| {
                    peak.index > left_scan.saturating_add(10)
                        && peak.index + 10 < right_scan
                        && peak.prominence >= 20.0
                        && peak.score >= 18.0
                        && (peak.prominence / peak.height.max(1.0)) >= 0.28
                })
                .max_by(|left, right| {
                    left.score
                        .partial_cmp(&right.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
            let Some(candidate) = candidate else {
                continue;
            };

            let gap_improvement =
                ((selected_gap - expected_scan_gap) / expected_scan_gap.max(1.0)).max(0.0);
            let candidate_left_gap = candidate.index.saturating_sub(left_scan) as f64;
            let candidate_right_gap = right_scan.saturating_sub(candidate.index) as f64;
            let candidate_gap_error = ((candidate_left_gap - expected_scan_gap)
                .abs()
                .min((candidate_right_gap - expected_scan_gap).abs()))
                / expected_scan_gap.max(1.0);
            let gap_closeness = (1.10 - candidate_gap_error).clamp(0.10, 1.10);
            let candidate_strength = (candidate.score / right_peak.score.max(1.0))
                .max(candidate.score / left_peak.score.max(1.0))
                .max(candidate.height / right_peak.height.max(1.0))
                .clamp(0.0, 2.0);
            let weak_right_penalty =
                ((0.62 - (right_peak.height / candidate.height.max(1.0))).max(0.0)) / 0.62;
            penalties.push(
                gap_improvement.min(1.6)
                    * gap_closeness
                    * (candidate_strength + weak_right_penalty * 0.65),
            );
        }
        if penalties.is_empty() {
            0.0
        } else {
            penalties.into_iter().fold(0.0_f64, f64::max) * 2.65
        }
    } else {
        0.0
    };

    let early_blob_height_penalty = if scans.len() >= 4 {
        let median_height = median(&selected_heights).max(1.0);
        let early_len = scans.len().min(4);
        scans
            .iter()
            .take(early_len)
            .enumerate()
            .filter_map(|(index, scan)| {
                let peak = peak_feature_by_index.get(scan)?;
                let height_ratio = peak.height / median_height;
                let purity = (peak.prominence / peak.height.max(1.0)).clamp(0.0, 1.0);
                let baseline_ratio =
                    (peak.local_baseline.max(0.0) / peak.height.max(1.0)).clamp(0.0, 1.5);
                let excess_height = ((height_ratio - 2.4).max(0.0)) / 2.4;
                let impurity = (0.75 - purity).max(0.0) / 0.75;
                let baseline_load = (baseline_ratio - 0.20).max(0.0) / 0.80;
                let position_weight = 1.15 - 0.18 * index as f64;
                Some(excess_height * (0.55 + impurity + baseline_load) * position_weight.max(0.6))
            })
            .sum::<f64>()
            / early_len as f64
            * 0.95
    } else {
        0.0
    };

    let rox_early_balance_penalty = if ladder_sizes.len() == 21 && scans.len() >= 6 {
        let ref_heights = scans
            .iter()
            .skip(2)
            .take(4)
            .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.height))
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>();
        let ref_prominences = scans
            .iter()
            .skip(2)
            .take(4)
            .filter_map(|scan| peak_feature_by_index.get(scan).map(|peak| peak.prominence))
            .filter(|value| value.is_finite() && *value > 0.0)
            .collect::<Vec<_>>();
        if ref_heights.is_empty() || ref_prominences.is_empty() {
            0.0
        } else {
            let height_ref = median(&ref_heights).max(1.0);
            let prominence_ref = median(&ref_prominences).max(1.0);
            scans
                .iter()
                .take(2)
                .enumerate()
                .filter_map(|(index, scan)| {
                    let peak = peak_feature_by_index.get(scan)?;
                    let height_ratio = peak.height / height_ref;
                    let prominence_ratio = peak.prominence / prominence_ref;
                    let weak_penalty = ((0.58 - prominence_ratio).max(0.0)) / 0.58;
                    let strong_penalty = ((height_ratio - 2.35).max(0.0)) / 2.35;
                    let early_penalty = if peak.index < 1605 {
                        ((1605.0 - peak.index as f64).max(0.0)) / 120.0
                    } else {
                        0.0
                    };
                    let position_weight = if index == 0 { 1.15 } else { 0.95 };
                    Some(
                        (weak_penalty * 1.05 + strong_penalty * 0.95 + early_penalty * 0.50)
                            * position_weight,
                    )
                })
                .sum::<f64>()
                / 2.0
                * 1.05
        }
    } else {
        0.0
    };

    gap_ratio_penalty
        + rox_tail_gap_consistency_penalty
        + gs500_start_penalty
        + rox_start_penalty
        + liz_start_penalty
        + bridge_skip_penalty
        + rox_bridge_skip_penalty
        + liz_bridge_skip_penalty
        + rox_blob_cluster_penalty
        + gs500_blob_cluster_penalty
        + gs500_tail_twin_penalty
        + early_gap_penalty
        + weak_score_penalty
        + liz_mid_triplet_skip_penalty
        + intensity_outlier_penalty
        + low_intensity_outlier_penalty
        + rox_family_signal_penalty
        + liz_isolated_low_peak_penalty
        + prominence_uniformity_penalty
        + neighbor_intensity_penalty
        + late_weak_penalty
        + rox_tail_endpoint_penalty
        + rox_tail_skip_penalty
        + early_baseline_penalty
        + liz_early_baseline_blob_penalty
        + liz_blob_cluster_start_penalty
        + liz_post_blob_start_penalty
        + liz_first_family_anchor_penalty
        + liz_tail_skip_penalty
        + early_blob_height_penalty
        + rox_early_balance_penalty
}

fn coefficient_of_variation_penalty(values: &[f64], tolerance: f64) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }
    let mean = values.iter().sum::<f64>() / values.len() as f64;
    if mean <= f64::EPSILON {
        return 1.0;
    }
    let variance = values
        .iter()
        .map(|value| {
            let delta = *value - mean;
            delta * delta
        })
        .sum::<f64>()
        / values.len() as f64;
    let cv = variance.sqrt() / mean;
    (cv - tolerance).max(0.0)
}

fn ladder_gap_template_penalty(ladder: LadderKind, scans: &[usize]) -> f64 {
    let (median, p10, p90) = match ladder {
        LadderKind::Liz500250 if scans.len() == LIZ_BROAD_GAP_MEDIAN.len() + 1 => (
            &LIZ_BROAD_GAP_MEDIAN[..],
            &LIZ_BROAD_GAP_P10[..],
            &LIZ_BROAD_GAP_P90[..],
        ),
        // ROX broad gap priors are useful diagnostically, but a broad
        // scorer pass regressed tail-shift hardcases. Keep ROX selection on
        // the existing residual/family logic until ROX template use is gated.
        LadderKind::Rox400Hd => return 0.0,
        _ => return 0.0,
    };
    gap_template_penalty_for_arrays(scans, median, p10, p90, 0)
}

fn partial_ladder_gap_template_penalty(
    scans: &[usize],
    ladder_sizes: &[f64],
    expected_total_len: usize,
) -> f64 {
    if scans.len() < 2 || scans.len() != ladder_sizes.len() {
        return 0.0;
    }
    if expected_total_len == ROX_BROAD_GAP_MEDIAN.len() + 1 {
        return 0.0;
    }
    if expected_total_len == LIZ_BROAD_GAP_MEDIAN.len() + 1
        && ladder_sizes
            .first()
            .is_some_and(|value| (*value - 35.0).abs() < 0.1)
    {
        return gap_template_penalty_for_arrays(
            scans,
            &LIZ_BROAD_GAP_MEDIAN,
            &LIZ_BROAD_GAP_P10,
            &LIZ_BROAD_GAP_P90,
            0,
        );
    }
    0.0
}

fn gap_template_penalty_for_arrays(
    scans: &[usize],
    median: &[f64],
    p10: &[f64],
    p90: &[f64],
    offset: usize,
) -> f64 {
    if scans.len() < 2 || offset + scans.len() - 1 > median.len() {
        return 0.0;
    }

    let mut penalties = Vec::with_capacity(scans.len() - 1);
    for (gap_index, window) in scans.windows(2).enumerate() {
        let template_index = offset + gap_index;
        let observed_gap = window[1].saturating_sub(window[0]) as f64;
        let expected = median[template_index].max(1.0);
        let slack = (expected * 0.10).max(8.0);
        let lower = (p10[template_index] - slack).max(1.0);
        let upper = p90[template_index] + slack;
        let deviation = if observed_gap < lower {
            lower - observed_gap
        } else if observed_gap > upper {
            observed_gap - upper
        } else {
            0.0
        };
        if deviation > 0.0 {
            let normalized = (deviation / expected).min(3.0);
            let close_gap_multiplier = if expected <= 65.0 { 1.35 } else { 1.0 };
            penalties.push(normalized * close_gap_multiplier);
        } else {
            penalties.push(0.0);
        }
    }

    if penalties.is_empty() {
        return 0.0;
    }
    let mean = penalties.iter().sum::<f64>() / penalties.len() as f64;
    let max = penalties.iter().copied().fold(0.0_f64, f64::max);
    mean * 0.70 + max * 0.30
}

fn median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let mid = sorted.len() / 2;
    if sorted.len() % 2 == 0 {
        0.5 * (sorted[mid - 1] + sorted[mid])
    } else {
        sorted[mid]
    }
}

fn curvature_score(ladder_sizes: &[f64], scans: &[usize]) -> f64 {
    if ladder_sizes.len() != scans.len() || ladder_sizes.len() < 3 {
        return f64::INFINITY;
    }

    ladder_sizes
        .windows(3)
        .zip(scans.windows(3))
        .map(|(x_window, y_window)| {
            let x0 = x_window[0];
            let x1 = x_window[1];
            let x2 = x_window[2];
            let y0 = y_window[0] as f64;
            let y1 = y_window[1] as f64;
            let y2 = y_window[2] as f64;
            let left_dx = x1 - x0;
            let right_dx = x2 - x1;
            let span = x2 - x0;
            if left_dx <= f64::EPSILON || right_dx <= f64::EPSILON || span <= f64::EPSILON {
                return f64::INFINITY;
            }
            let left_slope = (y1 - y0) / left_dx;
            let right_slope = (y2 - y1) / right_dx;
            (2.0 * (right_slope - left_slope) / span).abs()
        })
        .fold(0.0_f64, f64::max)
}

fn fit_best_sizing_model(
    scans: &[usize],
    ladder_sizes: &[f64],
    sample_trace: &[f64],
) -> Option<SizingModelPreview> {
    if scans.len() != ladder_sizes.len() || scans.len() < 2 {
        return None;
    }

    let x = scans.iter().map(|value| *value as f64).collect::<Vec<_>>();
    if let Some(model) = fit_monotone_spline_sizing_model(&x, ladder_sizes, sample_trace) {
        return Some(model);
    }

    let max_degree = (scans.len().saturating_sub(1)).min(3);
    for degree in (1..=max_degree).rev() {
        let Some(coefficients) = fit_polynomial_least_squares(&x, ladder_sizes, degree) else {
            continue;
        };
        let predicted = x
            .iter()
            .map(|value| eval_polynomial(&coefficients, *value))
            .collect::<Vec<_>>();
        let qc_metrics = compute_ladder_qc_metrics(&x, ladder_sizes, &predicted);
        if qc_metrics.monotonic_on_ladder {
            let sample_basepairs = (0..sample_trace.len())
                .map(|time| eval_polynomial(&coefficients, time as f64))
                .collect::<Vec<_>>();
            let sample_mapping = build_sample_mapping_preview(sample_trace, &sample_basepairs);
            return Some(SizingModelPreview {
                strategy: "polynomial_fallback".to_owned(),
                degree,
                coefficients,
                predicted_ladder_basepairs: predicted,
                qc_metrics,
                sample_mapping,
            });
        }
    }
    None
}

fn fit_monotone_spline_sizing_model(
    x: &[f64],
    ladder_sizes: &[f64],
    sample_trace: &[f64],
) -> Option<SizingModelPreview> {
    let tangents = monotone_cubic_tangents(x, ladder_sizes)?;
    let predicted = x
        .iter()
        .map(|value| eval_monotone_cubic_spline(x, ladder_sizes, &tangents, *value))
        .collect::<Vec<_>>();
    let qc_metrics = compute_ladder_qc_metrics(x, ladder_sizes, &predicted);
    if !qc_metrics.monotonic_on_ladder {
        return None;
    }

    let sample_basepairs = (0..sample_trace.len())
        .map(|time| eval_monotone_cubic_spline(x, ladder_sizes, &tangents, time as f64))
        .collect::<Vec<_>>();
    let sample_mapping = build_sample_mapping_preview(sample_trace, &sample_basepairs);

    Some(SizingModelPreview {
        strategy: "willros_monotone_spline".to_owned(),
        degree: 3,
        coefficients: tangents,
        predicted_ladder_basepairs: predicted,
        qc_metrics,
        sample_mapping,
    })
}

fn fit_polynomial_least_squares(x: &[f64], y: &[f64], degree: usize) -> Option<Vec<f64>> {
    if x.len() != y.len() || x.is_empty() {
        return None;
    }
    let order = degree + 1;
    let mut normal = vec![vec![0.0; order]; order];
    let mut rhs = vec![0.0; order];

    for row in 0..order {
        for col in 0..order {
            let power = (row + col) as i32;
            normal[row][col] = x.iter().map(|value| value.powi(power)).sum::<f64>();
        }
        rhs[row] = x
            .iter()
            .zip(y.iter())
            .map(|(x_value, y_value)| y_value * x_value.powi(row as i32))
            .sum::<f64>();
    }

    solve_linear_system(normal, rhs)
}

fn solve_linear_system(mut matrix: Vec<Vec<f64>>, mut rhs: Vec<f64>) -> Option<Vec<f64>> {
    let n = rhs.len();
    if matrix.len() != n || matrix.iter().any(|row| row.len() != n) {
        return None;
    }

    for pivot_index in 0..n {
        let (best_row, best_value) = (pivot_index..n)
            .map(|row| (row, matrix[row][pivot_index].abs()))
            .max_by(|left, right| {
                left.1
                    .partial_cmp(&right.1)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })?;
        if best_value <= f64::EPSILON {
            return None;
        }
        if best_row != pivot_index {
            matrix.swap(best_row, pivot_index);
            rhs.swap(best_row, pivot_index);
        }

        let pivot = matrix[pivot_index][pivot_index];
        for col in pivot_index..n {
            matrix[pivot_index][col] /= pivot;
        }
        rhs[pivot_index] /= pivot;

        for row in 0..n {
            if row == pivot_index {
                continue;
            }
            let factor = matrix[row][pivot_index];
            if factor.abs() <= f64::EPSILON {
                continue;
            }
            for col in pivot_index..n {
                matrix[row][col] -= factor * matrix[pivot_index][col];
            }
            rhs[row] -= factor * rhs[pivot_index];
        }
    }

    Some(rhs)
}

fn monotone_cubic_tangents(x: &[f64], y: &[f64]) -> Option<Vec<f64>> {
    if x.len() != y.len() || x.len() < 2 {
        return None;
    }

    let n = x.len();
    let mut h = Vec::with_capacity(n - 1);
    let mut delta = Vec::with_capacity(n - 1);
    for index in 0..n - 1 {
        let step = x[index + 1] - x[index];
        if step <= f64::EPSILON {
            return None;
        }
        h.push(step);
        delta.push((y[index + 1] - y[index]) / step);
    }

    let mut tangents = vec![0.0; n];
    tangents[0] = delta[0];
    tangents[n - 1] = delta[n - 2];

    for index in 1..n - 1 {
        if delta[index - 1] == 0.0
            || delta[index] == 0.0
            || delta[index - 1].signum() != delta[index].signum()
        {
            tangents[index] = 0.0;
            continue;
        }

        let w1 = 2.0 * h[index] + h[index - 1];
        let w2 = h[index] + 2.0 * h[index - 1];
        tangents[index] = (w1 + w2) / ((w1 / delta[index - 1]) + (w2 / delta[index]));
    }

    Some(tangents)
}

fn eval_monotone_cubic_spline(x: &[f64], y: &[f64], tangents: &[f64], xq: f64) -> f64 {
    if x.len() == 1 {
        return y[0];
    }
    if xq <= x[0] {
        return y[0] + tangents[0] * (xq - x[0]);
    }
    if xq >= x[x.len() - 1] {
        return y[y.len() - 1] + tangents[tangents.len() - 1] * (xq - x[x.len() - 1]);
    }

    let upper = x.partition_point(|value| *value <= xq);
    let index = upper.saturating_sub(1).min(x.len() - 2);
    let h = x[index + 1] - x[index];
    let t = (xq - x[index]) / h;
    let t2 = t * t;
    let t3 = t2 * t;

    let h00 = 2.0 * t3 - 3.0 * t2 + 1.0;
    let h10 = t3 - 2.0 * t2 + t;
    let h01 = -2.0 * t3 + 3.0 * t2;
    let h11 = t3 - t2;

    h00 * y[index] + h10 * h * tangents[index] + h01 * y[index + 1] + h11 * h * tangents[index + 1]
}

fn eval_polynomial(coefficients: &[f64], x: f64) -> f64 {
    coefficients
        .iter()
        .enumerate()
        .map(|(power, coefficient)| coefficient * x.powi(power as i32))
        .sum::<f64>()
}

fn compute_ladder_qc_metrics(
    scans: &[f64],
    expected: &[f64],
    predicted: &[f64],
) -> LadderQcMetrics {
    if scans.len() != expected.len() || expected.len() != predicted.len() || expected.is_empty() {
        return LadderQcMetrics {
            r2: f64::NEG_INFINITY,
            mean_abs_error_bp: f64::INFINITY,
            max_abs_error_bp: f64::INFINITY,
            linear_trend_mean_abs_error_bp: f64::INFINITY,
            linear_trend_max_abs_error_bp: f64::INFINITY,
            linear_trend_r2: f64::NEG_INFINITY,
            quadratic_trend_mean_abs_error_bp: f64::INFINITY,
            quadratic_trend_max_abs_error_bp: f64::INFINITY,
            quadratic_trend_r2: f64::NEG_INFINITY,
            monotonic_on_ladder: false,
        };
    }

    let mean_expected = expected.iter().sum::<f64>() / expected.len() as f64;
    let ss_tot = expected
        .iter()
        .map(|value| {
            let delta = value - mean_expected;
            delta * delta
        })
        .sum::<f64>();
    let residuals = expected
        .iter()
        .zip(predicted.iter())
        .map(|(exp, pred)| exp - pred)
        .collect::<Vec<_>>();
    let ss_res = residuals.iter().map(|value| value * value).sum::<f64>();
    let abs_errors = residuals
        .iter()
        .map(|value| value.abs())
        .collect::<Vec<_>>();
    let monotonic_on_ladder = predicted.windows(2).all(|window| window[1] > window[0]);
    let (linear_trend_mean_abs_error_bp, linear_trend_max_abs_error_bp, linear_trend_r2) =
        polynomial_trend_metrics(scans, expected, 1);
    let (quadratic_trend_mean_abs_error_bp, quadratic_trend_max_abs_error_bp, quadratic_trend_r2) =
        polynomial_trend_metrics(scans, expected, 2);

    LadderQcMetrics {
        r2: if ss_tot <= f64::EPSILON {
            f64::NEG_INFINITY
        } else {
            1.0 - (ss_res / ss_tot)
        },
        mean_abs_error_bp: abs_errors.iter().sum::<f64>() / abs_errors.len() as f64,
        max_abs_error_bp: abs_errors.into_iter().fold(0.0, f64::max),
        linear_trend_mean_abs_error_bp,
        linear_trend_max_abs_error_bp,
        linear_trend_r2,
        quadratic_trend_mean_abs_error_bp,
        quadratic_trend_max_abs_error_bp,
        quadratic_trend_r2,
        monotonic_on_ladder,
    }
}

fn build_sample_mapping_preview(
    sample_trace: &[f64],
    predicted_basepairs: &[f64],
) -> Option<SampleMappingPreview> {
    if sample_trace.is_empty() {
        return None;
    }
    if sample_trace.len() != predicted_basepairs.len() {
        return None;
    }

    let mut mapped = Vec::with_capacity(sample_trace.len());
    for (time, intensity) in sample_trace.iter().enumerate() {
        let basepair = predicted_basepairs[time];
        if !basepair.is_finite() || basepair < 0.0 {
            continue;
        }
        mapped.push(SampleMappingPoint {
            time,
            intensity: *intensity,
            basepair: round2(basepair),
        });
    }

    if mapped.is_empty() {
        return None;
    }

    let monotonic_unique = mapped
        .windows(2)
        .all(|window| window[1].basepair > window[0].basepair);
    let preview = sample_mapping_preview_points(&mapped);
    let sample_peak_preview = build_sample_peak_preview(sample_trace, &mapped);
    let assay_group_preview = build_assay_group_preview(&sample_peak_preview);
    let min_basepair = mapped.first().map(|point| point.basepair).unwrap_or(0.0);
    let max_basepair = mapped.last().map(|point| point.basepair).unwrap_or(0.0);

    Some(SampleMappingPreview {
        points_retained: mapped.len(),
        min_basepair,
        max_basepair,
        monotonic_unique,
        preview,
        sample_peak_preview,
        assay_group_preview,
    })
}

fn sample_mapping_preview_points(mapped: &[SampleMappingPoint]) -> Vec<SampleMappingPoint> {
    if mapped.len() <= 12 {
        return mapped.to_vec();
    }

    let mut preview = Vec::with_capacity(12);
    preview.extend_from_slice(&mapped[..4]);
    let mid = mapped.len() / 2;
    let middle_start = mid.saturating_sub(2);
    let middle_end = (middle_start + 4).min(mapped.len());
    preview.extend_from_slice(&mapped[middle_start..middle_end]);
    preview.extend_from_slice(&mapped[mapped.len().saturating_sub(4)..]);
    preview
}

fn round2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

fn build_sample_peak_preview(
    sample_trace: &[f64],
    mapped: &[SampleMappingPoint],
) -> Vec<SamplePeakPreview> {
    if sample_trace.is_empty() || mapped.is_empty() {
        return Vec::new();
    }

    let min_height = estimate_sample_peak_min_height(sample_trace);
    let peaks = find_peaks(sample_trace, min_height, 8);
    let mut preview = peaks
        .into_iter()
        .filter_map(|peak| {
            mapped
                .binary_search_by_key(&peak.index, |point| point.time)
                .ok()
                .and_then(|mapped_index| mapped.get(mapped_index))
                .map(|point| SamplePeakPreview {
                    time: peak.index,
                    intensity: round2(peak.height),
                    basepair: point.basepair,
                    area: round2(peak.prominence * peak.width),
                })
        })
        .collect::<Vec<_>>();

    preview.sort_by(|left, right| {
        right
            .intensity
            .partial_cmp(&left.intensity)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                left.basepair
                    .partial_cmp(&right.basepair)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });
    if preview.len() > SAMPLE_PEAK_PREVIEW_LIMIT {
        preview.truncate(SAMPLE_PEAK_PREVIEW_LIMIT);
    }
    preview.sort_by(|left, right| {
        left.basepair
            .partial_cmp(&right.basepair)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    preview
}

fn build_channel_peak_previews(
    record: &AbifRecord,
    data_channels: &[String],
    size_standard_channel: &str,
    ladder: LadderKind,
    preview: &LadderFitPreview,
) -> BTreeMap<String, Vec<SamplePeakPreview>> {
    let Some(model) = preview.sizing_model.as_ref() else {
        return BTreeMap::new();
    };
    let scan_indices = preview
        .refinement
        .as_ref()
        .filter(|refinement| !refinement.refined_scan_indices.is_empty())
        .map(|refinement| refinement.refined_scan_indices.as_slice())
        .unwrap_or(preview.best_scan_indices.as_slice());
    if scan_indices.len() != ladder.sizes().len() {
        return BTreeMap::new();
    }
    let x = scan_indices
        .iter()
        .map(|value| *value as f64)
        .collect::<Vec<_>>();
    let mut channels = BTreeMap::new();
    for channel in data_channels {
        if channel == size_standard_channel {
            continue;
        }
        let Some(trace) = record.channel_values(channel) else {
            continue;
        };
        if trace.is_empty() {
            continue;
        }
        let predicted = (0..trace.len())
            .map(|time| predict_basepair_from_sizing_model(model, &x, ladder.sizes(), time as f64))
            .collect::<Vec<_>>();
        if let Some(mapping) = build_sample_mapping_preview(&trace, &predicted) {
            channels.insert(channel.clone(), mapping.sample_peak_preview);
        }
    }
    channels
}

fn predict_basepair_from_sizing_model(
    model: &SizingModelPreview,
    scan_indices: &[f64],
    ladder_sizes: &[f64],
    time: f64,
) -> f64 {
    if model.strategy == "willros_monotone_spline"
        && scan_indices.len() == ladder_sizes.len()
        && model.coefficients.len() == ladder_sizes.len()
    {
        return eval_monotone_cubic_spline(scan_indices, ladder_sizes, &model.coefficients, time);
    }
    if model.strategy == "polynomial_fallback" && !model.coefficients.is_empty() {
        return eval_polynomial(&model.coefficients, time);
    }
    f64::NAN
}

fn estimate_sample_peak_min_height(sample_trace: &[f64]) -> f64 {
    let mut positives = sample_trace
        .iter()
        .copied()
        .filter(|value| *value > 0.0)
        .collect::<Vec<_>>();
    if positives.is_empty() {
        return 1.0;
    }
    positives.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let median = positives[positives.len() / 2];
    let max_value = positives.last().copied().unwrap_or(median);
    let adaptive_floor = (max_value * 0.05).max(median * 3.0);
    adaptive_floor.max(25.0)
}

fn build_assay_group_preview(peaks: &[SamplePeakPreview]) -> Vec<SamplePeakGroupPreview> {
    if peaks.is_empty() {
        return Vec::new();
    }

    let mut sorted = peaks.to_vec();
    sorted.sort_by(|left, right| {
        left.basepair
            .partial_cmp(&right.basepair)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut groups: Vec<Vec<SamplePeakPreview>> = Vec::new();
    for peak in sorted {
        let should_start_new = groups
            .last()
            .and_then(|group| group.last())
            .map(|last| peak.basepair - last.basepair > SAMPLE_ASSAY_GROUP_DISTANCE_BP)
            .unwrap_or(true);
        if should_start_new {
            groups.push(vec![peak]);
        } else if let Some(group) = groups.last_mut() {
            group.push(peak);
        }
    }

    groups
        .into_iter()
        .enumerate()
        .filter_map(|(index, group)| {
            let max_intensity = group
                .iter()
                .map(|peak| peak.intensity)
                .fold(f64::NEG_INFINITY, f64::max);
            if !max_intensity.is_finite() || max_intensity <= 0.0 {
                return None;
            }

            let kept = group
                .into_iter()
                .filter(|peak| peak.intensity / max_intensity >= SAMPLE_ASSAY_MIN_RATIO)
                .collect::<Vec<_>>();
            if kept.is_empty() {
                return None;
            }

            let start_basepair = kept.first().map(|peak| peak.basepair).unwrap_or(0.0);
            let end_basepair = kept
                .last()
                .map(|peak| peak.basepair)
                .unwrap_or(start_basepair);
            let cluster_width_bp = round2((end_basepair - start_basepair).max(0.0));
            let dominant_peak = kept
                .iter()
                .max_by(|left, right| {
                    left.intensity
                        .partial_cmp(&right.intensity)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .cloned()?;
            let mut sorted_by_intensity = kept.clone();
            sorted_by_intensity.sort_by(|left, right| {
                right
                    .intensity
                    .partial_cmp(&left.intensity)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            let dominant_ratio_vs_second = sorted_by_intensity
                .get(1)
                .map(|second| dominant_peak.intensity / second.intensity.max(1.0));
            let clonal_candidate = kept.len() <= CLONAL_MAX_LABELLED_PEAKS
                && dominant_ratio_vs_second
                    .map(|ratio| ratio >= CLONAL_DOMINANCE_RATIO)
                    .unwrap_or(true);
            Some(SamplePeakGroupPreview {
                group_id: index + 1,
                start_basepair,
                end_basepair,
                cluster_width_bp,
                max_intensity: round2(max_intensity),
                dominant_peak_basepair: round2(dominant_peak.basepair),
                dominant_peak_intensity: round2(dominant_peak.intensity),
                dominant_peak_area: round2(dominant_peak.area),
                dominant_ratio_vs_second: dominant_ratio_vs_second.map(round2),
                kept_peak_count: kept.len(),
                clonal_candidate,
                peaks: kept,
            })
        })
        .collect()
}

#[derive(Debug, Clone, Copy)]
struct ClonalityAssayDef {
    name: &'static str,
    channels: &'static [&'static str],
    bp_min: f64,
    bp_max: f64,
    aliases: &'static [&'static str],
}

const CLONALITY_ASSAYS: &[ClonalityAssayDef] = &[
    ClonalityAssayDef {
        name: "FR1",
        channels: &["DATA1"],
        bp_min: 280.0,
        bp_max: 420.0,
        aliases: &["FR1"],
    },
    ClonalityAssayDef {
        name: "FR2",
        channels: &["DATA1"],
        bp_min: 200.0,
        bp_max: 400.0,
        aliases: &["FR2"],
    },
    ClonalityAssayDef {
        name: "FR3",
        channels: &["DATA2"],
        bp_min: 60.0,
        bp_max: 220.0,
        aliases: &["FR3"],
    },
    ClonalityAssayDef {
        name: "IGK",
        channels: &["DATA1", "DATA2"],
        bp_min: 90.0,
        bp_max: 330.0,
        aliases: &["IGK"],
    },
    ClonalityAssayDef {
        name: "KDE",
        channels: &["DATA3"],
        bp_min: 190.0,
        bp_max: 410.0,
        aliases: &["KDE"],
    },
    ClonalityAssayDef {
        name: "TCRgA",
        channels: &["DATA1", "DATA2"],
        bp_min: 110.0,
        bp_max: 290.0,
        aliases: &["TCRGA", "TCRG"],
    },
    ClonalityAssayDef {
        name: "TCRgB",
        channels: &["DATA1", "DATA2"],
        bp_min: 60.0,
        bp_max: 250.0,
        aliases: &["TCRGB", "TCRG"],
    },
    ClonalityAssayDef {
        name: "DHJH_D",
        channels: &["DATA2"],
        bp_min: 90.0,
        bp_max: 440.0,
        aliases: &["DHJHD", "DHJH"],
    },
    ClonalityAssayDef {
        name: "DHJH_E",
        channels: &["DATA1"],
        bp_min: 65.0,
        bp_max: 160.0,
        aliases: &["DHJHE", "DHJH"],
    },
    ClonalityAssayDef {
        name: "TCRbA",
        channels: &["DATA1", "DATA2"],
        bp_min: 210.0,
        bp_max: 310.0,
        aliases: &["TCRBA", "TCRB"],
    },
    ClonalityAssayDef {
        name: "TCRbB",
        channels: &["DATA1", "DATA2"],
        bp_min: 210.0,
        bp_max: 310.0,
        aliases: &["TCRBB", "TCRB"],
    },
    ClonalityAssayDef {
        name: "TCRbC",
        channels: &["DATA1", "DATA2"],
        bp_min: 140.0,
        bp_max: 360.0,
        aliases: &["TCRBC", "TCRB"],
    },
];

const FLT3_ASSAYS: &[Flt3AssayDef] = &[
    Flt3AssayDef {
        name: "FLT3-ITD",
        channels: &["DATA1", "DATA2"],
        bp_min: 50.0,
        bp_max: 1000.0,
        wt_bp: 330.0,
        wt_tolerance_bp: 8.0,
        mutant_bp_min: 335.0,
        mutant_bp_max: 1000.0,
        positive_ratio: 0.02,
        aliases: &["FLT3ITD", "ITD", "ITDR", "RATIO"],
    },
    Flt3AssayDef {
        name: "FLT3-D835",
        channels: &["DATA3"],
        bp_min: 50.0,
        bp_max: 250.0,
        wt_bp: 80.0,
        wt_tolerance_bp: 4.0,
        mutant_bp_min: 121.0,
        mutant_bp_max: 130.5,
        positive_ratio: 0.05,
        aliases: &["FLT3D835", "D835", "TKD", "KUTTING"],
    },
    Flt3AssayDef {
        name: "NPM1",
        channels: &["DATA3"],
        bp_min: 50.0,
        bp_max: 1000.0,
        wt_bp: 300.0,
        wt_tolerance_bp: 3.0,
        mutant_bp_min: 303.0,
        mutant_bp_max: 305.0,
        positive_ratio: 0.01,
        aliases: &["NPM1", "NPM"],
    },
];

fn build_clonality_preview(
    file_name: &str,
    sample_channel: &str,
    assay_groups: &[SamplePeakGroupPreview],
    channel_peak_previews: BTreeMap<String, Vec<SamplePeakPreview>>,
) -> ClonalityPreview {
    let normalized_file_name = normalize_assay_token(file_name);
    let mut ranked_assays = CLONALITY_ASSAYS
        .iter()
        .filter_map(|assay| {
            let compatible_channel = assay.channels.contains(&sample_channel);
            let matched_by_filename = assay
                .aliases
                .iter()
                .any(|alias| normalized_file_name.contains(&normalize_assay_token(alias)));

            let matched_groups = assay_groups
                .iter()
                .filter_map(|group| {
                    let overlap_start = group.start_basepair.max(assay.bp_min);
                    let overlap_end = group.end_basepair.min(assay.bp_max);
                    if overlap_end < overlap_start {
                        return None;
                    }
                    Some(ClonalityGroupMatch {
                        group_id: group.group_id,
                        overlap_start_bp: round2(overlap_start),
                        overlap_end_bp: round2(overlap_end),
                        peak_count: group.kept_peak_count,
                        cluster_width_bp: group.cluster_width_bp,
                        dominant_peak_basepair: group.dominant_peak_basepair,
                        dominant_peak_intensity: group.dominant_peak_intensity,
                        dominant_peak_area: group.dominant_peak_area,
                        dominant_ratio_vs_second: group.dominant_ratio_vs_second,
                        clonal_candidate: group.clonal_candidate,
                    })
                })
                .collect::<Vec<_>>();

            if !matched_by_filename && matched_groups.is_empty() && !compatible_channel {
                return None;
            }

            let mut score = 0.0;
            if compatible_channel {
                score += 1.0;
            }
            if matched_by_filename {
                score += 3.0;
            }
            score += matched_groups.len() as f64 * 2.0;
            let clonal_group_count = matched_groups
                .iter()
                .filter(|group| group.clonal_candidate)
                .count();
            score += clonal_group_count as f64 * 1.5;
            let best_dominant_ratio = matched_groups
                .iter()
                .filter_map(|group| group.dominant_ratio_vs_second)
                .max_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
            if let Some(ratio) = best_dominant_ratio {
                score += (ratio - 1.0).max(0.0).min(4.0);
            }
            score += matched_groups
                .iter()
                .map(|group| group.overlap_end_bp - group.overlap_start_bp)
                .sum::<f64>()
                / 100.0;

            Some(ClonalityAssayMatch {
                assay_name: assay.name.to_owned(),
                channels: assay
                    .channels
                    .iter()
                    .map(|channel| channel.to_string())
                    .collect(),
                assay_bp_min: assay.bp_min,
                assay_bp_max: assay.bp_max,
                matched_by_filename,
                compatible_channel,
                score: round2(score),
                clonal_group_count,
                best_dominant_ratio: best_dominant_ratio.map(round2),
                matched_groups,
            })
        })
        .collect::<Vec<_>>();

    ranked_assays.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.assay_name.cmp(&right.assay_name))
    });
    ranked_assays.truncate(5);

    ClonalityPreview {
        sample_channel: sample_channel.to_owned(),
        ranked_assays,
        channel_peak_previews,
    }
}

fn detect_flt3_assay(file_name: &str) -> Option<&'static Flt3AssayDef> {
    let token = normalize_assay_token(file_name);
    FLT3_ASSAYS.iter().find(|assay| {
        assay
            .aliases
            .iter()
            .any(|alias| token.contains(&normalize_assay_token(alias)))
    })
}

fn build_flt3_preview(
    file_name: &str,
    sample_channel: &str,
    sample_peaks: &[SamplePeakPreview],
) -> Flt3Preview {
    let assay = detect_flt3_assay(file_name)
        .copied()
        .unwrap_or(FLT3_ASSAYS[0]);
    let compatible_channel = assay.channels.contains(&sample_channel);
    let matched_by_filename = detect_flt3_assay(file_name)
        .map(|detected| detected.name == assay.name)
        .unwrap_or(false);

    let assay_peaks = sample_peaks
        .iter()
        .filter(|peak| peak.basepair >= assay.bp_min && peak.basepair <= assay.bp_max)
        .cloned()
        .collect::<Vec<_>>();

    let wt_peak = assay_peaks
        .iter()
        .filter(|peak| (peak.basepair - assay.wt_bp).abs() <= assay.wt_tolerance_bp)
        .min_by(|left, right| {
            (left.basepair - assay.wt_bp)
                .abs()
                .partial_cmp(&(right.basepair - assay.wt_bp).abs())
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    right
                        .intensity
                        .partial_cmp(&left.intensity)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
        })
        .cloned();

    let mut mutant_peaks = assay_peaks
        .into_iter()
        .filter(|peak| peak.basepair >= assay.mutant_bp_min && peak.basepair <= assay.mutant_bp_max)
        .collect::<Vec<_>>();
    mutant_peaks.sort_by(|left, right| {
        right
            .intensity
            .partial_cmp(&left.intensity)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if mutant_peaks.len() > 3 {
        mutant_peaks.truncate(3);
    }

    let strongest_mutant_ratio = wt_peak.as_ref().and_then(|wt| {
        mutant_peaks
            .first()
            .map(|mutant| round2(mutant.intensity / wt.intensity.max(1.0)))
    });
    let positive_call = if let Some(ratio) = strongest_mutant_ratio {
        ratio >= assay.positive_ratio && !mutant_peaks.is_empty()
    } else {
        !mutant_peaks.is_empty()
    };

    Flt3Preview {
        assay_name: assay.name.to_owned(),
        matched_by_filename,
        compatible_channel,
        assay_bp_min: assay.bp_min,
        assay_bp_max: assay.bp_max,
        wt_peak,
        mutant_peaks,
        strongest_mutant_ratio,
        positive_call,
    }
}

fn normalize_assay_token(value: &str) -> String {
    value
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .flat_map(|ch| {
            ch.to_ascii_uppercase()
                .to_string()
                .chars()
                .collect::<Vec<_>>()
        })
        .collect()
}

#[derive(Debug, Clone, PartialEq)]
struct RefinementCandidate {
    changed_step_indices: Vec<usize>,
    original_scan_indices: Vec<usize>,
    refined_scan_indices: Vec<usize>,
    sizing_model: SizingModelPreview,
}

fn refine_best_combination(
    peak_pool: &[usize],
    current_scans: &[usize],
    ladder_sizes: &[f64],
    current_model: &SizingModelPreview,
) -> Option<RefinementCandidate> {
    if current_scans.len() != ladder_sizes.len() || current_scans.len() < 3 {
        return None;
    }

    let residuals = ladder_sizes
        .iter()
        .zip(current_model.predicted_ladder_basepairs.iter())
        .map(|(expected, predicted)| expected - predicted)
        .collect::<Vec<_>>();
    let mut ranked_steps = residuals
        .iter()
        .enumerate()
        .map(|(index, residual)| (index, residual.abs()))
        .filter(|(_, abs_residual)| *abs_residual >= MIN_REFINEMENT_TRIGGER_BP)
        .collect::<Vec<_>>();
    ranked_steps.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    ranked_steps.truncate(MAX_REFINEMENT_STEPS);
    if ranked_steps.is_empty() {
        return None;
    }

    let mut option_buckets = Vec::new();
    let mut changed_indices = Vec::new();

    for (step_index, _) in ranked_steps {
        let current_scan = current_scans[step_index] as f64;
        let slope = local_bp_per_scan(
            current_scans,
            &current_model.predicted_ladder_basepairs,
            step_index,
        );
        if !slope.is_finite() || slope.abs() <= 1e-6 {
            continue;
        }
        let target_scan = current_scan + (residuals[step_index] / slope);
        let lower_bound = if step_index == 0 {
            f64::NEG_INFINITY
        } else {
            current_scans[step_index - 1] as f64 + 6.0
        };
        let upper_bound = if step_index + 1 >= current_scans.len() {
            f64::INFINITY
        } else {
            current_scans[step_index + 1] as f64 - 6.0
        };
        let options = refinement_options(
            peak_pool,
            current_scan,
            target_scan,
            lower_bound,
            upper_bound,
        );
        if options.len() < 2 {
            continue;
        }
        changed_indices.push(step_index);
        option_buckets.push(options);
    }

    if option_buckets.is_empty() {
        return None;
    }

    let baseline_score = model_score(&current_model.qc_metrics);
    let mut best_candidate: Option<RefinementCandidate> = None;
    let mut best_score = baseline_score;
    let mut current_trial = current_scans.to_vec();
    try_refinement_combinations(
        0,
        &changed_indices,
        &option_buckets,
        &mut current_trial,
        current_scans,
        ladder_sizes,
        &mut best_candidate,
        &mut best_score,
    );
    best_candidate
}

fn try_refinement_combinations(
    bucket_index: usize,
    changed_indices: &[usize],
    option_buckets: &[Vec<usize>],
    trial_scans: &mut Vec<usize>,
    original_scans: &[usize],
    ladder_sizes: &[f64],
    best_candidate: &mut Option<RefinementCandidate>,
    best_score: &mut (f64, f64, f64),
) {
    if bucket_index == changed_indices.len() {
        if trial_scans == original_scans {
            return;
        }
        if !trial_scans.windows(2).all(|window| window[1] > window[0]) {
            return;
        }
        let Some(model) = fit_best_sizing_model(trial_scans, ladder_sizes, &[]) else {
            return;
        };
        let score = model_score(&model.qc_metrics);
        if score < *best_score {
            *best_score = score;
            *best_candidate = Some(RefinementCandidate {
                changed_step_indices: changed_indices.to_vec(),
                original_scan_indices: original_scans.to_vec(),
                refined_scan_indices: trial_scans.clone(),
                sizing_model: model,
            });
        }
        return;
    }

    let step_index = changed_indices[bucket_index];
    let original_value = trial_scans[step_index];
    for candidate in &option_buckets[bucket_index] {
        trial_scans[step_index] = *candidate;
        if step_index > 0 && trial_scans[step_index] <= trial_scans[step_index - 1] {
            continue;
        }
        if step_index + 1 < trial_scans.len()
            && trial_scans[step_index] >= trial_scans[step_index + 1]
        {
            continue;
        }
        try_refinement_combinations(
            bucket_index + 1,
            changed_indices,
            option_buckets,
            trial_scans,
            original_scans,
            ladder_sizes,
            best_candidate,
            best_score,
        );
    }
    trial_scans[step_index] = original_value;
}

fn refinement_options(
    peak_pool: &[usize],
    current_scan: f64,
    target_scan: f64,
    lower_bound: f64,
    upper_bound: f64,
) -> Vec<usize> {
    let mut options = peak_pool
        .iter()
        .copied()
        .filter(|scan| {
            let scan_f64 = *scan as f64;
            scan_f64 >= lower_bound
                && scan_f64 <= upper_bound
                && (scan_f64 - current_scan).abs() <= MAX_REFINEMENT_RADIUS_SCANS
                || (scan_f64 - target_scan).abs() <= MAX_REFINEMENT_RADIUS_SCANS
        })
        .collect::<Vec<_>>();

    options.sort_by(|left, right| {
        let left_score = (
            (*left as f64 - target_scan).abs(),
            (*left as f64 - current_scan).abs(),
        );
        let right_score = (
            (*right as f64 - target_scan).abs(),
            (*right as f64 - current_scan).abs(),
        );
        left_score
            .partial_cmp(&right_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    options.dedup();

    let current_scan_usize = current_scan.round() as usize;
    if !options.contains(&current_scan_usize) {
        options.insert(0, current_scan_usize);
    }
    options.truncate(MAX_REFINEMENT_OPTIONS_PER_STEP);
    if options.is_empty() {
        vec![current_scan_usize]
    } else {
        options
    }
}

fn local_bp_per_scan(scans: &[usize], predicted_bps: &[f64], index: usize) -> f64 {
    if scans.len() != predicted_bps.len() || scans.len() < 2 {
        return f64::NAN;
    }

    if index == 0 {
        let dx = scans[1] as f64 - scans[0] as f64;
        return (predicted_bps[1] - predicted_bps[0]) / dx;
    }
    if index + 1 >= scans.len() {
        let last = scans.len() - 1;
        let dx = scans[last] as f64 - scans[last - 1] as f64;
        return (predicted_bps[last] - predicted_bps[last - 1]) / dx;
    }

    let dx = scans[index + 1] as f64 - scans[index - 1] as f64;
    (predicted_bps[index + 1] - predicted_bps[index - 1]) / dx
}

fn model_score(metrics: &LadderQcMetrics) -> (f64, f64, f64) {
    (
        -metrics.r2,
        metrics.max_abs_error_bp,
        metrics.mean_abs_error_bp,
    )
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use crate::ladders::LadderKind;
    use crate::signal::Peak;

    use super::{
        CombinationScore, LadderFitPreview, LadderQcMetrics, SamplePeakGroupPreview,
        SamplePeakPreview, SizingModelPreview, apply_ladder_apex_recenter,
        bp_trend_metrics_for_indices, build_assay_group_preview, build_clonality_preview,
        build_flt3_preview, build_ladder_fit_preview, build_ladder_fit_preview_with_candidate_pool,
        build_ladder_review_assessment, build_sample_mapping_preview, compute_ladder_qc_metrics,
        curvature_score, estimate_combination_count_capped, eval_polynomial,
        expected_clonality_ladder_kind, filter_liz_peak_pool_for_fit, filter_rox_peak_pool_for_fit,
        fit_polynomial_least_squares, generate_peak_combinations, ladder_domain_penalty,
        ladder_gap_template_penalty, ladder_peak_sequence_penalty,
        liz_initial_fit_can_skip_repairs, liz_linear_first_candidate_is_acceptable,
        liz_preview_is_high_confidence_bounded, local_peak_quality_penalty, quadratic_fit_r2,
        refine_best_combination, repair_anchor_block_sequence,
        repair_gs500rox_start_anchor_sequence, repair_liz_consistent_height_family_sequence,
        repair_liz_first_anchor_family_sequence, repair_liz_linear_first_start_sequence,
        repair_liz_mid_triplet_outlier_only_sequence, repair_liz_start_triplet_shift_sequence,
        repair_liz_tail_neighbor_shift_sequence, repair_liz_tail_pair_split_sequence,
        repair_liz_weak_tail_apex_sequence, repair_rox_clean_early_family_sequence,
        repair_rox_consistent_height_family_sequence, repair_rox_large_50_60_gap_sequence,
        repair_rox_large_100_120_gap_sequence, repair_rox_nonlinear_start_pair_sequence,
        repair_rox_start_pair_sequence, repair_rox_start_prefix_pair_sequence,
        repair_rox_strong_family_window_sequence, repair_rox_tail_family_sequence,
        rox_early_window_peak_candidates, rox_post_blob_pool_override,
        rox_start_pair_candidate_improves_current, rox_tail_family_candidate_improves_current,
        score_combination, select_best_combination, select_ladder_peaks,
    };

    fn make_test_peak(index: usize, prominence: f64) -> Peak {
        Peak {
            index,
            height: prominence + 20.0,
            prominence,
            width: 4.0,
            local_baseline: 0.0,
            score: prominence * 2.0,
        }
    }

    fn make_rox_peak(index: usize, height: f64) -> Peak {
        Peak {
            index,
            height,
            prominence: height * 0.95,
            width: 4.0,
            local_baseline: 0.0,
            score: height * 3.0,
        }
    }

    fn make_test_preview(
        best_scan_indices: Vec<usize>,
        best_curvature_score: f64,
        r2: f64,
        mean_abs_error_bp: f64,
        max_abs_error_bp: f64,
    ) -> LadderFitPreview {
        LadderFitPreview {
            search_tier: "test".to_owned(),
            max_allowed_peak_gap: 100,
            gap_expansions: 0,
            estimated_combination_count: 1,
            candidate_generation_capped: false,
            evaluated_combination_count: 1,
            best_scan_indices,
            best_curvature_score: Some(best_curvature_score),
            best_quadratic_r2: Some(r2),
            sizing_model: Some(SizingModelPreview {
                strategy: "test".to_owned(),
                degree: 3,
                coefficients: vec![0.0, 1.0],
                predicted_ladder_basepairs: Vec::new(),
                qc_metrics: LadderQcMetrics {
                    r2,
                    mean_abs_error_bp,
                    max_abs_error_bp,
                    linear_trend_mean_abs_error_bp: 0.0,
                    linear_trend_max_abs_error_bp: 0.0,
                    linear_trend_r2: r2,
                    quadratic_trend_mean_abs_error_bp: 0.0,
                    quadratic_trend_max_abs_error_bp: 0.0,
                    quadratic_trend_r2: r2,
                    monotonic_on_ladder: true,
                },
                sample_mapping: None,
            }),
            refinement: None,
        }
    }

    #[test]
    fn quadratic_fit_scores_perfect_curve() {
        let x = vec![0.0, 1.0, 2.0, 3.0, 4.0];
        let y = vec![1.0, 3.0, 7.0, 13.0, 21.0];
        let r2 = quadratic_fit_r2(&x, &y);
        assert!(r2 > 0.999);
    }

    #[test]
    fn generate_peak_combinations_respects_gap_and_target_length() {
        let peaks = vec![100, 205, 310, 415, 900];
        let combinations = generate_peak_combinations(&peaks, 4, 130, 100);
        assert_eq!(combinations, vec![vec![100, 205, 310, 415]]);
    }

    #[test]
    fn combination_estimator_caps_large_search_spaces() {
        let peaks = (0..30).map(|index| 100 + index * 10).collect::<Vec<_>>();
        let count = estimate_combination_count_capped(&peaks, 10, 40, 500);
        assert_eq!(count, 500);
    }

    #[test]
    fn select_best_combination_picks_lowest_curvature_candidate() {
        let ladder_sizes = vec![35.0, 50.0, 75.0, 100.0];
        let combinations = vec![vec![100, 200, 300, 400], vec![100, 200, 380, 620]];
        let best = select_best_combination(
            &combinations,
            &ladder_sizes,
            LadderKind::Liz500250,
            &[],
            &[],
        )
        .expect("a best combination should be selected");
        assert_eq!(best.indices, vec![100, 200, 380, 620]);
        assert!(curvature_score(&ladder_sizes, &best.indices).is_finite());
    }

    #[test]
    fn select_ladder_peaks_prefers_raw_trace_before_baseline_fallback() {
        let raw = vec![0.0, 10.0, 400.0, 20.0, 0.0, 10.0, 450.0, 10.0, 0.0];
        let corrected = vec![0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0];
        let peaks = select_ladder_peaks(
            &raw,
            &corrected,
            &corrected,
            &corrected,
            &corrected,
            100.0,
            60.0,
            2,
            10,
            4,
            LadderKind::Liz500250,
        );
        let indices = peaks.iter().map(|peak| peak.index).collect::<Vec<_>>();
        assert_eq!(indices, vec![2, 6]);
    }

    #[test]
    fn select_ladder_peaks_prefers_corrected_when_raw_has_only_blob_peaks() {
        let raw = vec![0.0, 0.0, 900.0, 0.0, 0.0, 850.0, 0.0, 0.0, 0.0, 0.0, 0.0];
        let corrected = vec![
            0.0, 120.0, 0.0, 130.0, 0.0, 125.0, 0.0, 140.0, 0.0, 135.0, 0.0,
        ];
        let peaks = select_ladder_peaks(
            &raw,
            &corrected,
            &corrected,
            &corrected,
            &corrected,
            100.0,
            60.0,
            1,
            10,
            5,
            LadderKind::Liz500250,
        );
        let indices = peaks.iter().map(|peak| peak.index).collect::<Vec<_>>();
        for expected in [1usize, 3, 5, 7, 9] {
            assert!(indices.contains(&expected));
        }
    }

    #[test]
    fn select_ladder_peaks_uses_gs500rox_baseline_candidate_supplements() {
        let mut raw = vec![0.0; 5_000];
        for index in [
            1_550usize, 1_830, 2_120, 2_410, 2_700, 3_000, 3_300, 3_620, 3_950, 4_280,
        ] {
            raw[index] = 350.0;
        }
        let corrected = raw.clone();
        let quantile = raw.clone();
        let mut morph = vec![0.0; 5_000];
        morph[2_500] = 650.0;
        let mut snip = vec![0.0; 5_000];
        snip[2_650] = 700.0;

        let peaks = select_ladder_peaks(
            &raw,
            &corrected,
            &quantile,
            &morph,
            &snip,
            100.0,
            60.0,
            20,
            40,
            16,
            LadderKind::Gs500Rox,
        );
        let indices = peaks.iter().map(|peak| peak.index).collect::<Vec<_>>();

        assert!(indices.contains(&2_500));
        assert!(indices.contains(&2_650));
        assert!(indices.contains(&1_550));
        assert!(indices.contains(&4_280));
    }

    #[test]
    fn select_ladder_peaks_filters_gs500rox_candidates_outside_scan_window() {
        let mut raw = vec![0.0; 7_000];
        for index in [
            543usize, 763, 1_163, 1_483, 1_552, 1_830, 2_120, 2_410, 2_700, 3_000, 3_300, 3_620,
            3_950, 4_280, 6_250,
        ] {
            raw[index] = 350.0;
        }
        let corrected = raw.clone();
        let quantile = raw.clone();

        let peaks = select_ladder_peaks(
            &raw,
            &corrected,
            &quantile,
            &corrected,
            &corrected,
            100.0,
            60.0,
            15,
            40,
            16,
            LadderKind::Gs500Rox,
        );
        let indices = peaks.iter().map(|peak| peak.index).collect::<Vec<_>>();

        assert!(!indices.iter().any(|index| *index < 1_300));
        assert!(!indices.iter().any(|index| *index > 6_000));
        assert!(indices.contains(&1_483));
        assert!(indices.contains(&4_280));
    }

    #[test]
    fn ladder_domain_penalty_applies_early_anchor_checks_for_liz() {
        let peak = Peak {
            index: 2100,
            height: 120.0,
            prominence: 100.0,
            width: 5.0,
            local_baseline: 0.0,
            score: 120.0,
        };
        let peak_map = [(2100usize, peak.clone())].into_iter().collect();
        let penalty = super::ladder_domain_penalty(
            LadderKind::Liz500250,
            &[2100, 2300, 2500, 2700],
            &peak_map,
            &[peak],
        );
        assert!(penalty > 0.0);
    }

    #[test]
    fn top_peak_candidates_prefers_scored_peak_shape_over_raw_height() {
        let values = vec![0.0, 160.0, 0.0, 70.0, 110.0, 130.0, 110.0, 70.0, 0.0];
        let peaks = super::top_peak_candidates(&values, 50.0, 1, 1);
        assert_eq!(peaks.len(), 1);
        assert_eq!(peaks[0].index, 5);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_crowded_dirty_start() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1680usize, 1734, 1901, 1960, 2073, 2250, 2310, 2428, 2488, 2548, 2671, 2791, 2915,
            3041, 3103, 3165, 3290, 3414, 3538, 3662, 3784,
        ];
        let crowded = vec![
            1516usize, 1640, 1901, 1960, 2073, 2250, 2310, 2428, 2488, 2548, 2671, 2791, 2915,
            3041, 3103, 3165, 3290, 3414, 3538, 3662, 3784,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 240.0,
                    prominence: 220.0,
                    width: 4.0,
                    local_baseline: 10.0,
                    score: 260.0,
                },
            );
        }
        peak_map.insert(
            1516,
            Peak {
                index: 1516,
                height: 260.0,
                prominence: 80.0,
                width: 12.0,
                local_baseline: 150.0,
                score: 110.0,
            },
        );
        peak_map.insert(
            1640,
            Peak {
                index: 1640,
                height: 230.0,
                prominence: 120.0,
                width: 8.0,
                local_baseline: 90.0,
                score: 135.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let crowded_penalty = ladder_peak_sequence_penalty(
            &crowded,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(crowded_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_blob_height_outlier_at_start() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1651usize, 1706, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let blobbed = vec![
            1510usize, 1706, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1200.0,
                    prominence: 1050.0,
                    width: 4.0,
                    local_baseline: 90.0,
                    score: 1200.0,
                },
            );
        }
        peak_map.insert(
            1510,
            Peak {
                index: 1510,
                height: 26000.0,
                prominence: 1400.0,
                width: 13.0,
                local_baseline: 21000.0,
                score: 1800.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let blob_penalty = ladder_peak_sequence_penalty(
            &blobbed,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(blob_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_large_intensity_outlier() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let scans = vec![
            1651usize, 1706, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let mut balanced_map = BTreeMap::new();
        let mut outlier_map = BTreeMap::new();
        for (i, scan) in scans.iter().enumerate() {
            let balanced_peak = Peak {
                index: *scan,
                height: 1400.0,
                prominence: 1250.0,
                width: 4.0,
                local_baseline: 70.0,
                score: 1250.0,
            };
            balanced_map.insert(*scan, balanced_peak.clone());
            let mut outlier_peak = balanced_peak;
            if i == 1 {
                outlier_peak.height = 18000.0;
                outlier_peak.prominence = 15000.0;
                outlier_peak.local_baseline = 800.0;
                outlier_peak.score = 4200.0;
            }
            outlier_map.insert(*scan, outlier_peak);
        }
        let balanced_features = balanced_map.values().cloned().collect::<Vec<_>>();
        let outlier_features = outlier_map.values().cloned().collect::<Vec<_>>();
        let balanced_penalty = ladder_peak_sequence_penalty(
            &scans,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &balanced_map,
            &balanced_features,
        );
        let outlier_penalty = ladder_peak_sequence_penalty(
            &scans,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &outlier_map,
            &outlier_features,
        );
        assert!(outlier_penalty > balanced_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_rox_bridge_skip_at_start() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1651usize, 1706, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let skipped = vec![
            1506usize, 1651, 1706, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1200.0,
                    prominence: 1020.0,
                    width: 4.0,
                    local_baseline: 80.0,
                    score: 1100.0,
                },
            );
        }
        peak_map.insert(
            1506,
            Peak {
                index: 1506,
                height: 2100.0,
                prominence: 420.0,
                width: 10.0,
                local_baseline: 1300.0,
                score: 260.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let skipped_penalty = ladder_peak_sequence_penalty(
            &skipped,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(skipped_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_rox_blob_cluster_start() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1648usize, 1703, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let clustered = vec![
            1504usize, 1522, 1669, 1725, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788,
            2910, 3034, 3158, 3280, 3405, 3530, 3655, 3780,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1100.0,
                    prominence: 950.0,
                    width: 4.0,
                    local_baseline: 85.0,
                    score: 1020.0,
                },
            );
        }
        peak_map.insert(
            1504,
            Peak {
                index: 1504,
                height: 2400.0,
                prominence: 320.0,
                width: 9.0,
                local_baseline: 1750.0,
                score: 255.0,
            },
        );
        peak_map.insert(
            1522,
            Peak {
                index: 1522,
                height: 2200.0,
                prominence: 280.0,
                width: 8.0,
                local_baseline: 1680.0,
                score: 230.0,
            },
        );
        peak_map.insert(
            1669,
            Peak {
                index: 1669,
                height: 1200.0,
                prominence: 1000.0,
                width: 4.0,
                local_baseline: 90.0,
                score: 1080.0,
            },
        );
        peak_map.insert(
            1725,
            Peak {
                index: 1725,
                height: 1180.0,
                prominence: 970.0,
                width: 4.0,
                local_baseline: 90.0,
                score: 1040.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let clustered_penalty = ladder_peak_sequence_penalty(
            &clustered,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(clustered_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_rox_early_peaks_that_do_not_match_sequence_balance() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1690usize, 1745, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let weak_early = vec![
            1496usize, 1544, 1870, 1931, 2048, 2172, 2295, 2420, 2541, 2663, 2788, 2910, 3034,
            3158, 3280, 3405, 3530, 3655, 3780, 3904, 4029,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1050.0,
                    prominence: 930.0,
                    width: 4.0,
                    local_baseline: 80.0,
                    score: 1000.0,
                },
            );
        }
        peak_map.insert(
            1496,
            Peak {
                index: 1496,
                height: 6.0,
                prominence: 6.0,
                width: 2.0,
                local_baseline: 0.0,
                score: 6.5,
            },
        );
        peak_map.insert(
            1544,
            Peak {
                index: 1544,
                height: 101.0,
                prominence: 101.0,
                width: 3.0,
                local_baseline: 0.0,
                score: 110.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let weak_penalty = ladder_peak_sequence_penalty(
            &weak_early,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(weak_penalty > clean_penalty);
    }

    #[test]
    fn ladder_domain_penalty_dislikes_liz_starting_too_late_and_skipping_first_anchor() {
        let clean = vec![
            1500usize, 1576, 1654, 1732, 1810, 1888, 1966, 2044, 2122, 2200, 2278, 2356, 2434,
            2512, 2590, 2668, 2746, 2824, 2902, 2980, 3058, 3136, 3214, 3292, 3370, 3448, 3526,
            3604, 3682, 3760, 3838, 3916, 3994, 4072, 4150, 4228,
        ];
        let skipped = vec![
            1660usize, 1738, 1816, 1894, 1972, 2050, 2128, 2206, 2284, 2362, 2440, 2518, 2596,
            2674, 2752, 2830, 2908, 2986, 3064, 3142, 3220, 3298, 3376, 3454, 3532, 3610, 3688,
            3766, 3844, 3922, 4000, 4078, 4156, 4234, 4312, 4390,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 950.0,
                    prominence: 830.0,
                    width: 4.0,
                    local_baseline: 60.0,
                    score: 920.0,
                },
            );
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty =
            ladder_domain_penalty(LadderKind::Liz500250, &clean, &peak_map, &peak_features);
        let skipped_penalty =
            ladder_domain_penalty(LadderKind::Liz500250, &skipped, &peak_map, &peak_features);
        assert!(skipped_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_liz_mid_triplet_skip() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let clean = vec![
            1518usize, 1594, 1716, 1838, 1998, 2066, 2144, 2342, 2604, 2866, 3064, 3132, 3394,
            3656, 3854, 3922,
        ];
        let skipped = vec![
            1518usize, 1594, 1716, 1838, 1998, 2144, 2222, 2342, 2604, 2866, 3064, 3132, 3394,
            3656, 3854, 3922,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 900.0,
                    prominence: 760.0,
                    width: 4.0,
                    local_baseline: 55.0,
                    score: 860.0,
                },
            );
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let skipped_penalty = ladder_peak_sequence_penalty(
            &skipped,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(skipped_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_liz_early_baseline_peaks() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let clean = vec![
            1501usize, 1576, 1698, 1820, 1980, 2048, 2126, 2324, 2586, 2848, 3046, 3114, 3376,
            3638, 3836, 3904,
        ];
        let dirty = vec![
            1496usize, 1576, 1698, 1820, 1980, 2048, 2126, 2324, 2586, 2848, 3046, 3114, 3376,
            3638, 3836, 3904,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 940.0,
                    prominence: 800.0,
                    width: 4.0,
                    local_baseline: 70.0,
                    score: 900.0,
                },
            );
        }
        peak_map.insert(
            1496,
            Peak {
                index: 1496,
                height: 38.0,
                prominence: 14.0,
                width: 3.0,
                local_baseline: 31.0,
                score: 16.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let dirty_penalty = ladder_peak_sequence_penalty(
            &dirty,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(dirty_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_liz_shifted_start_block() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let clean = vec![
            1488usize, 1565, 1707, 1845, 2067, 2123, 2180, 2415, 2703, 3015, 3249, 3307, 3609,
            3886, 4110, 4156,
        ];
        let shifted = vec![
            1481usize, 1585, 1803, 2116, 2359, 2421, 2482, 2736, 3041, 3381, 3631, 3697, 4031,
            4340, 4595, 4647,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in clean.iter().chain(shifted.iter()) {
            peak_map.entry(*scan).or_insert(Peak {
                index: *scan,
                height: 950.0,
                prominence: 820.0,
                width: 4.0,
                local_baseline: 55.0,
                score: 900.0,
            });
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let shifted_penalty = ladder_peak_sequence_penalty(
            &shifted,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(shifted_penalty > clean_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_very_early_liz_first_anchor_when_later_family_anchor_exists()
     {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let preferred = vec![
            1530usize, 1562, 1706, 1844, 2067, 2123, 2180, 2417, 2704, 3022, 3257, 3316, 3623,
            3899, 4123, 4169,
        ];
        let too_early = vec![
            1422usize, 1562, 1706, 1844, 2067, 2123, 2180, 2417, 2704, 3022, 3257, 3316, 3623,
            3899, 4123, 4169,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in preferred.iter().chain(too_early.iter()) {
            peak_map.entry(*scan).or_insert(Peak {
                index: *scan,
                height: 210.0,
                prominence: 170.0,
                width: 4.0,
                local_baseline: 18.0,
                score: 190.0,
            });
        }
        peak_map.insert(
            1422,
            Peak {
                index: 1422,
                height: 84.0,
                prominence: 42.0,
                width: 5.0,
                local_baseline: 28.0,
                score: 68.0,
            },
        );
        peak_map.insert(
            1530,
            Peak {
                index: 1530,
                height: 198.0,
                prominence: 162.0,
                width: 4.0,
                local_baseline: 10.0,
                score: 182.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let preferred_penalty = ladder_peak_sequence_penalty(
            &preferred,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let early_penalty = ladder_peak_sequence_penalty(
            &too_early,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(early_penalty > preferred_penalty);
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_liz_tail_skip() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let clean = vec![
            1518usize, 1594, 1716, 1838, 1998, 2066, 2144, 2342, 2604, 2866, 3064, 3132, 3394,
            3656, 3854, 3922,
        ];
        let skipped = vec![
            1518usize, 1594, 1716, 1838, 1998, 2066, 2144, 2342, 2604, 2866, 3064, 3132, 3394,
            3656, 3922, 4178,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 360.0,
                    prominence: 300.0,
                    width: 4.0,
                    local_baseline: 18.0,
                    score: 320.0,
                },
            );
        }
        peak_map.insert(
            3854,
            Peak {
                index: 3854,
                height: 297.0,
                prominence: 255.0,
                width: 4.0,
                local_baseline: 20.0,
                score: 286.0,
            },
        );
        peak_map.insert(
            3922,
            Peak {
                index: 3922,
                height: 291.0,
                prominence: 248.0,
                width: 4.0,
                local_baseline: 20.0,
                score: 280.0,
            },
        );
        peak_map.insert(
            4178,
            Peak {
                index: 4178,
                height: 115.0,
                prominence: 62.0,
                width: 5.0,
                local_baseline: 16.0,
                score: 55.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let skipped_penalty = ladder_peak_sequence_penalty(
            &skipped,
            LadderKind::Liz500250,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(skipped_penalty > clean_penalty);
    }

    #[test]
    fn polynomial_fit_recovers_linear_mapping() {
        let x = vec![100.0, 200.0, 300.0, 400.0];
        let y = vec![50.0, 100.0, 150.0, 200.0];
        let coeffs =
            fit_polynomial_least_squares(&x, &y, 1).expect("linear least squares should succeed");
        let predicted = x
            .iter()
            .map(|value| eval_polynomial(&coeffs, *value))
            .collect::<Vec<_>>();
        let qc = compute_ladder_qc_metrics(&x, &y, &predicted);
        assert!(qc.r2 > 0.999999);
        assert!(qc.mean_abs_error_bp < 1e-6);
        assert!(qc.linear_trend_mean_abs_error_bp < 1e-6);
        assert!(qc.linear_trend_max_abs_error_bp < 1e-6);
        assert!(qc.linear_trend_r2 > 0.999999);
        assert!(qc.monotonic_on_ladder);
    }

    #[test]
    fn local_refinement_can_improve_a_nearby_candidate() {
        let ladder_sizes = vec![35.0, 50.0, 75.0, 100.0];
        let scans = vec![100, 200, 320, 405];
        let model = SizingModelPreview {
            strategy: "test".to_owned(),
            degree: 1,
            coefficients: fit_polynomial_least_squares(
                &scans.iter().map(|value| *value as f64).collect::<Vec<_>>(),
                &ladder_sizes,
                1,
            )
            .expect("fit should work"),
            predicted_ladder_basepairs: scans.iter().map(|value| *value as f64).collect::<Vec<_>>(),
            qc_metrics: compute_ladder_qc_metrics(
                &scans.iter().map(|value| *value as f64).collect::<Vec<_>>(),
                &ladder_sizes,
                &[35.0, 50.0, 80.0, 101.5],
            ),
            sample_mapping: None,
        };
        let peak_pool = vec![100, 200, 300, 320, 405];
        let refined = refine_best_combination(&peak_pool, &scans, &ladder_sizes, &model)
            .expect("refinement should find an improvement");
        assert_eq!(refined.refined_scan_indices, vec![100, 200, 300, 405]);
        assert!(
            refined.sizing_model.qc_metrics.max_abs_error_bp < model.qc_metrics.max_abs_error_bp
        );
    }

    #[test]
    fn repair_anchor_block_sequence_can_fix_liz_tail_block() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1509usize, 1587, 1732, 1872, 2098, 2155, 2214, 2452, 2746, 3064, 3302, 3361, 3669,
            3951, 4071, 4224,
        ];
        let expected = vec![
            1509usize, 1587, 1732, 1872, 2098, 2155, 2214, 2452, 2746, 3064, 3302, 3361, 3669,
            3951, 4178, 4224,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 320.0,
                    prominence: 280.0,
                    width: 4.0,
                    local_baseline: 18.0,
                    score: 320.0,
                },
            );
        }
        peak_map.insert(
            4071,
            Peak {
                index: 4071,
                height: 42.0,
                prominence: 18.0,
                width: 3.0,
                local_baseline: 16.0,
                score: 20.0,
            },
        );
        peak_map.insert(
            4178,
            Peak {
                index: 4178,
                height: 297.0,
                prominence: 255.0,
                width: 5.0,
                local_baseline: 14.0,
                score: 286.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_anchor_block_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("tail block repair should find a better candidate");

        assert_ne!(repaired.indices, current);
        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_r2 + 0.0004 >= current_score.linear_r2);
    }

    #[test]
    fn repair_anchor_block_sequence_can_fix_liz_early_block() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1416usize, 1547, 1914, 2107, 2300, 2360, 2421, 2672, 2978, 3312, 3559, 3622, 3946,
            4124, 4242, 4487,
        ];
        let expected = vec![
            1452usize, 1761, 1914, 2062, 2300, 2360, 2421, 2672, 2978, 3312, 3559, 3622, 3946,
            4124, 4242, 4487,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 360.0,
                    prominence: 310.0,
                    width: 4.0,
                    local_baseline: 14.0,
                    score: 340.0,
                },
            );
        }
        peak_map.insert(
            1416,
            Peak {
                index: 1416,
                height: 58.0,
                prominence: 24.0,
                width: 5.0,
                local_baseline: 20.0,
                score: 28.0,
            },
        );
        peak_map.insert(
            1547,
            Peak {
                index: 1547,
                height: 70.0,
                prominence: 25.0,
                width: 5.0,
                local_baseline: 26.0,
                score: 30.0,
            },
        );
        peak_map.insert(
            2107,
            Peak {
                index: 2107,
                height: 85.0,
                prominence: 32.0,
                width: 4.0,
                local_baseline: 25.0,
                score: 36.0,
            },
        );
        peak_map.insert(
            1679,
            Peak {
                index: 1679,
                height: 210.0,
                prominence: 160.0,
                width: 4.0,
                local_baseline: 14.0,
                score: 165.0,
            },
        );
        peak_map.insert(
            1661,
            Peak {
                index: 1661,
                height: 176.0,
                prominence: 141.0,
                width: 4.0,
                local_baseline: 15.0,
                score: 148.0,
            },
        );
        peak_map.insert(
            1592,
            Peak {
                index: 1592,
                height: 160.0,
                prominence: 120.0,
                width: 4.0,
                local_baseline: 16.0,
                score: 126.0,
            },
        );
        peak_map.insert(
            1610,
            Peak {
                index: 1610,
                height: 150.0,
                prominence: 112.0,
                width: 5.0,
                local_baseline: 18.0,
                score: 118.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_anchor_block_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("early block repair should find a better candidate");

        assert_ne!(repaired.indices, current);
        assert!(repaired.indices.contains(&2062));
        assert!(repaired.indices[0] >= current[0]);
        assert!(repaired.indices[1] >= current[1]);
        assert!(repaired.indices[1] <= expected[1]);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp < current_score.linear_mean_abs_error_bp);
    }

    #[test]
    fn repair_liz_linear_first_start_sequence_prefers_better_linear_start_block() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1585usize, 1632, 1803, 1964, 2359, 2421, 2461, 2736, 3041, 3414, 3631, 3697, 4031,
            4340, 4595, 4647,
        ];
        let expected = vec![
            1706usize, 1803, 1964, 2116, 2359, 2421, 2461, 2736, 3041, 3414, 3631, 3697, 4031,
            4340, 4595, 4647,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 700.0,
                    prominence: 670.0,
                    width: 4.0,
                    local_baseline: 15.0,
                    score: 700.0,
                },
            );
        }
        for (scan, height, prom, base, score) in [
            (1481usize, 1300.0, 1395.0, -95.0, 5733.0),
            (1534, 394.0, 334.0, 60.0, 845.0),
            (1585, 2086.0, 1957.0, 128.0, 5911.0),
            (1603, 292.0, 100.0, 192.0, 109.0),
            (1632, 12935.0, 9868.0, 3066.0, 19276.0),
            (1652, 31099.0, 31131.0, -32.0, 116945.0),
            (1684, 680.0, 251.0, 428.0, 280.0),
            (1722, 970.0, 852.0, 117.0, 2056.0),
            (1803, 993.0, 993.0, 0.0, 3410.0),
            (1964, 1130.0, 1151.0, -21.0, 3584.0),
            (2116, 1249.0, 1268.0, -19.0, 3940.0),
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height,
                    prominence: prom,
                    width: 4.0,
                    local_baseline: base,
                    score,
                },
            );
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_linear_first_start_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("linear-first start repair should find a better candidate");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp < current_score.linear_mean_abs_error_bp);
        assert!(repaired.linear_r2 > current_score.linear_r2);
    }

    #[test]
    fn repair_rox_start_pair_sequence_prefers_family_matched_start_peaks() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1607usize, 1695, 1926, 1988, 2105, 2290, 2353, 2476, 2539, 2602, 2731, 2858, 2988,
            3119, 3184, 3250, 3379, 3508, 3637, 3764, 3889,
        ];
        let expected = vec![
            1695usize, 1753, 1926, 1988, 2105, 2290, 2353, 2476, 2539, 2602, 2731, 2858, 2988,
            3119, 3184, 3250, 3379, 3508, 3637, 3764, 3889,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1520.0,
                    prominence: 1580.0,
                    width: 3.0,
                    local_baseline: -55.0,
                    score: 4350.0,
                },
            );
        }
        peak_map.insert(
            1607,
            Peak {
                index: 1607,
                height: 3969.0,
                prominence: 4836.0,
                width: 3.0,
                local_baseline: -867.0,
                score: 14620.0,
            },
        );
        peak_map.insert(
            1476,
            Peak {
                index: 1476,
                height: 7100.0,
                prominence: 7982.0,
                width: 2.0,
                local_baseline: -882.0,
                score: 18832.0,
            },
        );
        peak_map.insert(
            1510,
            Peak {
                index: 1510,
                height: 31154.0,
                prominence: 32107.0,
                width: 16.0,
                local_baseline: -953.0,
                score: 79635.0,
            },
        );
        peak_map.insert(
            1543,
            Peak {
                index: 1543,
                height: 671.0,
                prominence: 622.0,
                width: 4.0,
                local_baseline: 49.0,
                score: 1647.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_rox_start_pair_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("ROX start-pair repair should find a cleaner start family");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_r2 >= current_score.linear_r2);
    }

    #[test]
    fn repair_rox_start_pair_sequence_can_shift_pair_when_wrong_second_reveals_family_shift() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1602usize, 1668, 1934, 1998, 2117, 2298, 2362, 2487, 2550, 2612, 2742, 2868, 2998,
            3128, 3193, 3258, 3388, 3517, 3647, 3774, 3900,
        ];
        let expected = vec![
            1668usize, 1712, 1934, 1998, 2117, 2298, 2362, 2487, 2550, 2612, 2742, 2868, 2998,
            3128, 3193, 3258, 3388, 3517, 3647, 3774, 3900,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1480.0,
                    prominence: 1510.0,
                    width: 3.0,
                    local_baseline: -30.0,
                    score: 4200.0,
                },
            );
        }
        peak_map.insert(
            1602,
            Peak {
                index: 1602,
                height: 1480.0,
                prominence: 1510.0,
                width: 3.0,
                local_baseline: -30.0,
                score: 4200.0,
            },
        );
        peak_map.insert(
            1668,
            Peak {
                index: 1668,
                height: 870.0,
                prominence: 760.0,
                width: 4.0,
                local_baseline: 110.0,
                score: 6580.0,
            },
        );
        peak_map.insert(
            1555,
            Peak {
                index: 1555,
                height: 640.0,
                prominence: 610.0,
                width: 4.0,
                local_baseline: 30.0,
                score: 1800.0,
            },
        );
        peak_map.insert(
            1754,
            Peak {
                index: 1754,
                height: 1240.0,
                prominence: 1320.0,
                width: 4.0,
                local_baseline: -28.0,
                score: 3980.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_rox_start_pair_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("ROX start-pair repair should fix a wrong second peak");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp < current_score.linear_mean_abs_error_bp);
        assert!(repaired.linear_r2 >= current_score.linear_r2);
    }

    #[test]
    fn repair_rox_start_pair_sequence_accepts_clean_lower_amplitude_second_peak() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1607usize, 1622, 1909, 1970, 2088, 2278, 2342, 2469, 2533, 2597, 2731, 2863, 3000,
            3139, 3209, 3280, 3421, 3562, 3706, 3848, 3990,
        ];
        let expected_second = 1679usize;

        let mut peak_map = BTreeMap::new();
        for scan in &[
            1607usize,
            1622,
            expected_second,
            1909,
            1970,
            2088,
            2278,
            2342,
            2469,
            2533,
            2597,
            2731,
            2863,
            3000,
            3139,
            3209,
            3280,
            3421,
            3562,
            3706,
            3848,
            3990,
        ] {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1500.0,
                    prominence: 1540.0,
                    width: 3.0,
                    local_baseline: -30.0,
                    score: 4300.0,
                },
            );
        }
        peak_map.insert(
            1622,
            Peak {
                index: 1622,
                height: 820.0,
                prominence: 770.0,
                width: 4.0,
                local_baseline: 135.0,
                score: 6400.0,
            },
        );
        peak_map.insert(
            1679,
            Peak {
                index: 1679,
                height: 635.0,
                prominence: 635.0,
                width: 4.0,
                local_baseline: 0.0,
                score: 1850.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_rox_start_pair_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("ROX start-pair repair should accept a cleaner lower-amplitude second peak");

        assert_eq!(repaired.indices[1], expected_second);
        assert!(repaired.indices[0] >= 1607);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_r2 >= current_score.linear_r2);
    }

    #[test]
    fn repair_rox_start_pair_sequence_can_shift_family_later_when_first_is_early() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1587usize, 1675, 1902, 1962, 2077, 2259, 2320, 2441, 2502, 2563, 2690, 2814, 2941,
            3069, 3133, 3197, 3324, 3450, 3576, 3701, 3824,
        ];
        let expected = vec![
            1675usize, 1731, 1902, 1962, 2077, 2259, 2320, 2441, 2502, 2563, 2690, 2814, 2941,
            3069, 3133, 3197, 3324, 3450, 3576, 3701, 3824,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 920.0,
                    prominence: 1180.0,
                    width: 3.0,
                    local_baseline: -75.0,
                    score: 3600.0,
                },
            );
        }
        peak_map.insert(
            1587,
            Peak {
                index: 1587,
                height: 625.0,
                prominence: 1467.0,
                width: 2.0,
                local_baseline: -842.0,
                score: 3654.0,
            },
        );

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_rox_start_pair_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("ROX start-pair repair should allow a shifted family win");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_r2 >= current_score.linear_r2 - 0.00005);
    }

    #[test]
    fn repair_gs500rox_start_anchor_sequence_moves_late_blob_anchor_to_cleaner_family() {
        let ladder_sizes = LadderKind::Gs500Rox.sizes().to_vec();
        let current = vec![
            1728usize, 1809, 1972, 2127, 2379, 2442, 2506, 2770, 3089, 3443, 3702, 3769, 4112,
            4427, 4683, 4736,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(*scan, make_rox_peak(*scan, 900.0));
        }
        peak_map.insert(
            1686,
            Peak {
                index: 1686,
                height: 329.52325,
                prominence: 45.4615,
                width: 3.0,
                local_baseline: 284.06175,
                score: 49.0,
            },
        );
        peak_map.insert(
            1701,
            Peak {
                index: 1701,
                height: 135.0,
                prominence: 56.0,
                width: 3.0,
                local_baseline: 79.0,
                score: 58.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Gs500Rox,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_gs500rox_start_anchor_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Gs500Rox,
            &peak_map,
            &peak_features,
        )
        .expect("late GS500ROX start should move to the cleaner earlier anchor");

        assert_eq!(repaired.indices[0], 1701);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_r2 > current_score.linear_r2);
    }

    #[test]
    fn repair_gs500rox_start_anchor_sequence_can_shift_saturated_35_right() {
        let ladder_sizes = LadderKind::Gs500Rox.sizes().to_vec();
        let current = vec![
            1457usize, 1585, 1726, 1863, 2086, 2143, 2201, 2438, 2730, 3048, 3288, 3347, 3658,
            3945, 4180, 4228,
        ];
        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(*scan, make_rox_peak(*scan, 260.0));
        }
        peak_map.insert(
            1457,
            Peak {
                index: 1457,
                height: 18_000.0,
                prominence: 18_200.0,
                width: 2.0,
                local_baseline: -200.0,
                score: 56_000.0,
            },
        );
        peak_map.insert(1512, make_rox_peak(1512, 210.0));
        peak_map.insert(1585, make_rox_peak(1585, 245.0));

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Gs500Rox,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_gs500rox_start_anchor_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Gs500Rox,
            &peak_map,
            &peak_features,
        )
        .expect("saturated GS500ROX 35 bp anchor should shift right to the cleaner family");

        assert_eq!(repaired.indices[0], 1512);
        assert_eq!(repaired.indices[1], 1585);
        assert!(repaired.linear_max_abs_error_bp <= 6.25);
        assert!(repaired.linear_r2 >= 0.99955);
    }

    #[test]
    fn repair_rox_nonlinear_start_pair_can_follow_curved_rox_family() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1887usize, 1951, 2291, 2369, 2515, 2754, 2834, 2997, 3080, 3164, 3343, 3519, 3701,
            3886, 3984, 4082, 4274, 4475, 4676, 4882, 5084,
        ];
        let expected = vec![
            2007usize, 2076, 2291, 2369, 2515, 2754, 2834, 2997, 3080, 3164, 3343, 3519, 3701,
            3886, 3984, 4082, 4274, 4475, 4676, 4882, 5084,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(*scan, make_rox_peak(*scan, 170.0));
        }
        peak_map.insert(2007, make_rox_peak(2007, 430.0));
        peak_map.insert(2076, make_rox_peak(2076, 355.0));
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_rox_nonlinear_start_pair_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("nonlinear ROX start-pair repair should find the curved family");

        assert_eq!(repaired.indices, expected);
        let (_current_d3_mean, current_d3_max, _current_d3_r2) =
            bp_trend_metrics_for_indices(&current, &ladder_sizes, 3);
        let (_repaired_d3_mean, repaired_d3_max, _repaired_d3_r2) =
            bp_trend_metrics_for_indices(&repaired.indices, &ladder_sizes, 3);
        assert!(repaired_d3_max + 1.0 < current_d3_max);
    }

    #[test]
    fn repair_liz_first_anchor_family_sequence_prefers_earlier_family_matched_peak() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1560usize, 1626, 1775, 1920, 2150, 2209, 2269, 2512, 2811, 3135, 3378, 3439, 3754,
            4048, 4287, 4337,
        ];
        let expected = vec![
            1529usize, 1626, 1775, 1920, 2150, 2209, 2269, 2512, 2811, 3135, 3378, 3439, 3754,
            4048, 4287, 4337,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1450.0,
                    prominence: 1450.0,
                    width: 4.0,
                    local_baseline: 0.0,
                    score: 3800.0,
                },
            );
        }
        peak_map.insert(
            1560,
            Peak {
                index: 1560,
                height: 1912.4,
                prominence: 1846.4,
                width: 4.0,
                local_baseline: 66.0,
                score: 3783.6,
            },
        );
        peak_map.insert(
            1529,
            Peak {
                index: 1529,
                height: 1278.9,
                prominence: 975.8,
                width: 4.0,
                local_baseline: 303.0,
                score: 2311.9,
            },
        );
        peak_map.insert(
            1626,
            Peak {
                index: 1626,
                height: 1269.5,
                prominence: 1269.5,
                width: 4.0,
                local_baseline: 0.0,
                score: 3399.7,
            },
        );
        for (scan, height, prominence, baseline, score) in [
            (1481usize, 32767.0, 32827.0, -60.0, 123375.3),
            (1510, 944.9, 256.9, 688.1, 241.7),
            (1589, 86.1, 66.7, 19.3, 116.2),
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height,
                    prominence,
                    width: 4.0,
                    local_baseline: baseline,
                    score,
                },
            );
        }

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_first_anchor_family_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired =
            repaired.expect("LIZ first-anchor repair should find earlier family-matched peak");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.10);
    }

    #[test]
    fn repair_liz_mid_triplet_outlier_only_replaces_blob_160_without_moving_tail() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1594usize, 1699, 1856, 2008, 2252, 2315, 2491, 2636, 2953, 3299, 3557, 3622, 3956,
            4260, 4507, 4557,
        ];
        let expected = vec![
            1594usize, 1699, 1856, 2008, 2222, 2252, 2315, 2636, 2953, 3299, 3557, 3622, 3956,
            4260, 4507, 4557,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in current.iter().chain(expected.iter()).copied() {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 2100.0,
                    prominence: 2050.0,
                    width: 4.0,
                    local_baseline: 0.0,
                    score: 6200.0,
                },
            );
        }
        for (scan, height, prominence, score) in [
            (2222usize, 36.0, 36.0, 123.0),
            (2252, 2470.0, 2470.0, 6615.0),
            (2315, 2598.0, 2598.0, 6957.0),
            (2491, 18772.0, 18772.0, 50273.0),
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height,
                    prominence,
                    width: 4.0,
                    local_baseline: 0.0,
                    score,
                },
            );
        }

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_mid_triplet_outlier_only_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("blob-like 160 bp triplet outlier should be replaceable");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp + 2.0 < current_score.linear_max_abs_error_bp);
        assert_eq!(&repaired.indices[7..], &current[7..]);
    }

    #[test]
    fn repair_liz_tail_pair_split_sequence_splits_collapsed_490_500_pair() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1547usize, 1610, 1761, 1914, 2234, 2300, 2360, 2672, 2978, 3312, 3559, 3622, 3946,
            4242, 4537, 4549,
        ];
        let expected = vec![
            1547usize, 1610, 1761, 1914, 2234, 2300, 2360, 2672, 2978, 3312, 3559, 3622, 3946,
            4242, 4487, 4537,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in current.iter().chain(expected.iter()).copied() {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 330.0,
                    prominence: 320.0,
                    width: 5.0,
                    local_baseline: 0.0,
                    score: 1000.0,
                },
            );
        }
        for (scan, height, prominence, score) in [
            (4487usize, 303.0, 304.0, 1018.0),
            (4537, 299.0, 299.0, 1000.0),
            (4549, 22.0, 14.0, 12.0),
            (4910, 5143.0, 5144.0, 11325.0),
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height,
                    prominence,
                    width: 5.0,
                    local_baseline: 0.0,
                    score,
                },
            );
        }

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_tail_pair_split_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("collapsed 490/500 pair should split to the cleaner tail pair");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.quadratic_r2 > current_score.quadratic_r2);
        assert!(repaired.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.70);
    }

    #[test]
    fn repair_liz_start_triplet_shift_sequence_can_shift_blob_start_family() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1547usize, 1610, 1761, 1914, 2234, 2300, 2360, 2672, 2978, 3312, 3559, 3622, 3946,
            4242, 4487, 4537,
        ];
        let expected = vec![
            1610usize, 1761, 1914, 2062, 2300, 2360, 2421, 2672, 2978, 3312, 3559, 3622, 3946,
            4242, 4487, 4537,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in current.iter().chain(expected.iter()).copied() {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 380.0,
                    prominence: 370.0,
                    width: 5.0,
                    local_baseline: 0.0,
                    score: 1200.0,
                },
            );
        }
        for scan in [2062usize, 2421] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 450.0,
                    prominence: 440.0,
                    width: 5.0,
                    local_baseline: 0.0,
                    score: 1500.0,
                },
            );
        }

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_start_triplet_shift_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("shifted LIZ start/triplet family should be accepted when linear profile improves");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp + 1.0 < current_score.linear_mean_abs_error_bp);
    }

    #[test]
    fn repair_liz_weak_tail_apex_sequence_moves_baseline_feet_to_tail_apexes() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1544usize, 1696, 1854, 2005, 2247, 2308, 2370, 2623, 2883, 3229, 3521, 3585, 3866,
            4157, 4378, 4475,
        ];
        let expected = vec![
            1544usize, 1696, 1854, 2005, 2247, 2308, 2370, 2623, 2883, 3229, 3521, 3585, 3916,
            4224, 4475, 4528,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in current.iter().chain(expected.iter()).copied() {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 2100.0,
                    prominence: 2050.0,
                    width: 5.0,
                    local_baseline: 0.0,
                    score: 6200.0,
                },
            );
        }
        for scan in [3229usize, 3866, 4157, 4378] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 45.0,
                    prominence: 43.0,
                    width: 6.0,
                    local_baseline: 1.0,
                    score: 150.0,
                },
            );
        }
        for scan in [3916usize, 4224, 4475, 4528] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 2300.0,
                    prominence: 2280.0,
                    width: 5.0,
                    local_baseline: 0.0,
                    score: 7600.0,
                },
            );
        }

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_weak_tail_apex_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("weak LIZ tail feet should move to stronger nearby apexes");

        assert_eq!(&repaired.indices[12..16], &expected[12..16]);
        assert!(repaired.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.75);
    }

    #[test]
    fn repair_liz_tail_neighbor_shift_sequence_can_move_500_to_next_peak() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1544usize, 1696, 1854, 2005, 2247, 2308, 2370, 2623, 2883, 3229, 3521, 3585, 3866,
            4157, 4378, 4475,
        ];
        let expected = vec![
            1544usize, 1696, 1854, 2005, 2247, 2308, 2370, 2623, 2883, 3229, 3521, 3585, 3866,
            4157, 4475, 4528,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in current.iter().chain(expected.iter()).copied() {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 2100.0,
                    prominence: 2050.0,
                    width: 5.0,
                    local_baseline: 0.0,
                    score: 6200.0,
                },
            );
        }
        peak_map.insert(
            4378,
            Peak {
                index: 4378,
                height: 32.0,
                prominence: 31.0,
                width: 5.0,
                local_baseline: 1.0,
                score: 120.0,
            },
        );
        peak_map.insert(
            4528,
            Peak {
                index: 4528,
                height: 2300.0,
                prominence: 2280.0,
                width: 5.0,
                local_baseline: 0.0,
                score: 7600.0,
            },
        );

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_liz_tail_neighbor_shift_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("weak 490 should move to current 500 when a clean next 500 peak exists");

        assert_eq!(&repaired.indices[14..16], &expected[14..16]);
        assert!(repaired.linear_max_abs_error_bp <= current_score.linear_max_abs_error_bp + 2.4);
    }

    #[test]
    fn rox_start_pair_candidate_improves_current_allows_big_max_win_with_small_mean_cost() {
        let current = CombinationScore {
            indices: vec![1587, 1675, 1902, 1962],
            curvature_score: 0.0,
            quadratic_r2: 1.0,
            linear_mean_abs_error_bp: 1.1573,
            linear_max_abs_error_bp: 5.8207,
            linear_r2: 0.999657,
            domain_penalty: 0.0,
            peak_penalty: 0.0,
            blended_score: 0.0,
        };
        let candidate = CombinationScore {
            indices: vec![1675, 1731, 1902, 1962],
            curvature_score: 0.0,
            quadratic_r2: 1.0,
            linear_mean_abs_error_bp: 1.4820,
            linear_max_abs_error_bp: 4.1570,
            linear_r2: 0.999714,
            domain_penalty: 0.2,
            peak_penalty: 0.2,
            blended_score: 0.2,
        };
        assert!(rox_start_pair_candidate_improves_current(
            &current, &candidate
        ));
    }

    #[test]
    fn rox_tail_family_candidate_improves_current_allows_big_max_win_with_small_mean_cost() {
        let current = CombinationScore {
            indices: vec![
                1571usize, 1623, 1833, 1938, 2157, 2490, 2600, 2713, 2827, 2941, 3165, 3277, 3498,
                3779, 3916, 4045, 4241, 4433, 4455, 4634, 4805,
            ],
            curvature_score: 0.8,
            quadratic_r2: 1.0,
            linear_mean_abs_error_bp: 5.8985,
            linear_max_abs_error_bp: 11.1599,
            linear_r2: 0.995782,
            domain_penalty: 0.8,
            peak_penalty: 0.8,
            blended_score: 2.0,
        };
        let candidate = CombinationScore {
            indices: vec![
                1571usize, 1623, 1833, 1938, 2157, 2490, 2600, 2713, 2827, 2941, 3165, 3277, 3498,
                3779, 3916, 4045, 4241, 4388, 4520, 4666, 4824,
            ],
            curvature_score: 1.1,
            quadratic_r2: 1.0,
            linear_mean_abs_error_bp: 6.02,
            linear_max_abs_error_bp: 10.35,
            linear_r2: 0.99650,
            domain_penalty: 1.0,
            peak_penalty: 1.0,
            blended_score: 2.6,
        };

        assert!(rox_tail_family_candidate_improves_current(
            &current, &candidate
        ));
    }

    #[test]
    fn apex_recenter_rox_moves_baseline_flank_to_stronger_apex() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let mut current = ladder_sizes
            .iter()
            .map(|bp| (bp * 10.0 + 1100.0).round() as usize)
            .collect::<Vec<_>>();
        let apex_scan = current[15];
        current[15] = apex_scan - 9;

        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 600.0,
                    prominence: 580.0,
                    width: 4.0,
                    local_baseline: 10.0,
                    score: 2200.0,
                },
            );
        }
        peak_map.insert(
            current[15],
            Peak {
                index: current[15],
                height: 330.0,
                prominence: 150.0,
                width: 4.0,
                local_baseline: 120.0,
                score: 500.0,
            },
        );
        peak_map.insert(
            apex_scan,
            Peak {
                index: apex_scan,
                height: 690.0,
                prominence: 660.0,
                width: 4.0,
                local_baseline: 12.0,
                score: 2600.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );

        let recentered = apply_ladder_apex_recenter(
            Some(current_score),
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("ROX apex recenter should return a fit");

        assert_eq!(recentered.indices[15], apex_scan);
        assert!(recentered.linear_max_abs_error_bp <= 6.0);
        assert!(recentered.linear_mean_abs_error_bp <= 5.0);
    }

    #[test]
    fn apex_recenter_liz_moves_to_stronger_apex_when_gap_template_holds() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1500usize, 1576, 1724, 1863, 2086, 2142, 2199, 2433, 2716, 3028, 3259, 3318, 3621,
            3899, 4125, 4171,
        ];
        let apex_scan = 2147usize;

        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 620.0,
                    prominence: 590.0,
                    width: 4.0,
                    local_baseline: 12.0,
                    score: 2300.0,
                },
            );
        }
        peak_map.insert(
            current[5],
            Peak {
                index: current[5],
                height: 360.0,
                prominence: 170.0,
                width: 4.0,
                local_baseline: 110.0,
                score: 550.0,
            },
        );
        peak_map.insert(
            apex_scan,
            Peak {
                index: apex_scan,
                height: 660.0,
                prominence: 640.0,
                width: 4.0,
                local_baseline: 10.0,
                score: 2600.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );

        let recentered = apply_ladder_apex_recenter(
            Some(current_score),
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("LIZ apex recenter should return a fit");

        assert_eq!(recentered.indices[5], apex_scan);
        assert!(recentered.linear_max_abs_error_bp <= 6.0);
        assert!(recentered.linear_mean_abs_error_bp <= 5.0);
    }

    #[test]
    fn apex_recenter_liz_allows_soft_watch_fit_to_move_from_foot_to_apex() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let mut current = vec![
            1544usize, 1669, 1854, 2005, 2247, 2308, 2370, 2623, 2883, 3229, 3521, 3585, 3866,
            4157, 4378, 4479,
        ];
        let foot_scan = current[9];
        let apex_scan = foot_scan + 14;

        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 900.0,
                    prominence: 850.0,
                    width: 4.0,
                    local_baseline: 15.0,
                    score: 2600.0,
                },
            );
        }
        peak_map.insert(
            foot_scan,
            Peak {
                index: foot_scan,
                height: 240.0,
                prominence: 110.0,
                width: 4.0,
                local_baseline: 120.0,
                score: 420.0,
            },
        );
        peak_map.insert(
            apex_scan,
            Peak {
                index: apex_scan,
                height: 980.0,
                prominence: 940.0,
                width: 4.0,
                local_baseline: 12.0,
                score: 3100.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );
        assert!(current_score.linear_max_abs_error_bp > super::APEX_RECENTER_LINEAR_MAX_GUARD_BP);
        assert!(
            current_score.linear_max_abs_error_bp <= super::LIZ_APEX_RECENTER_LINEAR_MAX_GUARD_BP
        );

        let recentered = apply_ladder_apex_recenter(
            Some(current_score),
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("LIZ apex recenter should return a fit");

        current[9] = apex_scan;
        assert_eq!(recentered.indices, current);
        assert!(recentered.linear_max_abs_error_bp <= super::LIZ_APEX_RECENTER_LINEAR_MAX_GUARD_BP);
        assert!(
            recentered.linear_mean_abs_error_bp <= super::LIZ_APEX_RECENTER_LINEAR_MEAN_GUARD_BP
        );
    }

    #[test]
    fn apex_recenter_liz_allows_family_weak_foot_with_small_linear_tradeoff() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1544usize, 1669, 1854, 2005, 2247, 2308, 2370, 2623, 2883, 3229, 3521, 3585, 3866,
            4157, 4378, 4479,
        ];
        let weak_foot_scan = current[1];
        let apex_scan = 1696usize;

        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1900.0,
                    prominence: 1800.0,
                    width: 4.0,
                    local_baseline: 10.0,
                    score: 2600.0,
                },
            );
        }
        peak_map.insert(
            weak_foot_scan,
            Peak {
                index: weak_foot_scan,
                height: 46.0,
                prominence: 46.0,
                width: 9.0,
                local_baseline: 0.0,
                score: 181.0,
            },
        );
        peak_map.insert(
            apex_scan,
            Peak {
                index: apex_scan,
                height: 1087.0,
                prominence: 1083.0,
                width: 5.0,
                local_baseline: 4.0,
                score: 3686.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );

        let recentered = apply_ladder_apex_recenter(
            Some(current_score.clone()),
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("LIZ weak family foot recenter should return a fit");

        assert_eq!(recentered.indices[1], apex_scan);
        assert!(recentered.linear_max_abs_error_bp <= current_score.linear_max_abs_error_bp + 1.05);
        assert!(
            recentered.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.75
        );
    }

    #[test]
    fn apex_recenter_liz_rejects_blob_snap_that_breaks_gap_template() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let current = vec![
            1500usize, 1576, 1724, 1863, 2086, 2142, 2199, 2433, 2716, 3028, 3259, 3318, 3621,
            3899, 4125, 4171,
        ];
        let blob_scan = 1475usize;

        let mut peak_map = BTreeMap::new();
        for scan in &current {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 620.0,
                    prominence: 590.0,
                    width: 4.0,
                    local_baseline: 12.0,
                    score: 2300.0,
                },
            );
        }
        peak_map.insert(
            blob_scan,
            Peak {
                index: blob_scan,
                height: 980.0,
                prominence: 940.0,
                width: 7.0,
                local_baseline: 40.0,
                score: 3400.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );

        let recentered = apply_ladder_apex_recenter(
            Some(current_score),
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        )
        .expect("LIZ apex recenter should return a fit");

        assert_eq!(recentered.indices, current);
    }

    #[test]
    fn repair_rox_strong_family_window_sequence_accepts_clean_21_peak_family() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let family = vec![
            1571usize, 1623, 1779, 1833, 1938, 2102, 2157, 2266, 2321, 2376, 2490, 2600, 2713,
            2827, 2884, 2941, 3053, 3165, 3277, 3388, 3498,
        ];
        let mut peak_map = BTreeMap::new();
        for (scan, height, prominence) in [
            (1571usize, 616.0, 711.0),
            (1623, 620.0, 748.0),
            (1779, 552.0, 687.0),
            (1833, 516.0, 632.0),
            (1938, 589.0, 723.0),
            (2102, 609.0, 731.0),
            (2157, 619.0, 762.0),
            (2266, 626.0, 759.0),
            (2321, 625.0, 754.0),
            (2376, 650.0, 1206.0),
            (2490, 630.0, 772.0),
            (2600, 580.0, 726.0),
            (2713, 577.0, 733.0),
            (2827, 607.0, 769.0),
            (2884, 576.0, 726.0),
            (2941, 581.0, 742.0),
            (3053, 533.0, 984.0),
            (3165, 504.0, 678.0),
            (3277, 480.0, 651.0),
            (3388, 442.0, 612.0),
            (3498, 463.0, 626.0),
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height,
                    prominence,
                    width: 4.0,
                    local_baseline: -100.0,
                    score: prominence * 2.0,
                },
            );
        }
        let current = CombinationScore {
            indices: vec![
                1571usize, 1623, 1779, 1938, 2157, 2490, 2600, 2713, 2827, 2941, 3165, 3277, 3498,
                3779, 3916, 4045, 4241, 4429, 4466, 4666, 4824,
            ],
            curvature_score: 0.4,
            quadratic_r2: 0.99,
            linear_mean_abs_error_bp: 5.84,
            linear_max_abs_error_bp: 10.43,
            linear_r2: 0.9959,
            domain_penalty: 0.5,
            peak_penalty: 0.5,
            blended_score: 1.0,
        };

        let repaired = repair_rox_strong_family_window_sequence(
            Some(&current),
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
        )
        .expect("strong ROX family window should be accepted");

        assert_eq!(repaired.indices, family);
        assert!(repaired.linear_max_abs_error_bp < 5.0);
        assert!(repaired.linear_mean_abs_error_bp < 2.5);
        assert!(repaired.linear_r2 > 0.9995);
    }

    #[test]
    fn repair_rox_consistent_height_family_sequence_rejects_baseline_foot_points() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1579usize, 1630, 1786, 1841, 1946, 2111, 2166, 2276, 2331, 2387, 2501, 2613, 2688,
            2806, 2844, 2902, 2986, 3076, 3191, 3306, 3420,
        ];
        let strong_family = vec![
            1579usize, 1630, 1786, 1841, 1946, 2111, 2166, 2276, 2331, 2387, 2501, 2613, 2728,
            2844, 2902, 2960, 3076, 3191, 3306, 3420, 3533,
        ];
        let mut peak_map = BTreeMap::new();
        for (offset, scan) in strong_family.iter().enumerate() {
            let height = 1_180.0 + (offset as f64 % 7.0) * 24.0;
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height,
                    prominence: height * 0.95,
                    width: 4.0,
                    local_baseline: 10.0,
                    score: height * 2.0,
                },
            );
        }
        for scan in [2688usize, 2806, 2986] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 65.0,
                    prominence: 22.0,
                    width: 4.0,
                    local_baseline: 43.0,
                    score: 44.0,
                },
            );
        }
        peak_map.insert(
            2037,
            Peak {
                index: 2037,
                height: 2_470.0,
                prominence: 2_430.0,
                width: 4.0,
                local_baseline: 20.0,
                score: 4_800.0,
            },
        );
        peak_map.insert(
            2420,
            Peak {
                index: 2420,
                height: 820.0,
                prominence: 790.0,
                width: 4.0,
                local_baseline: 10.0,
                score: 1_600.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );

        let repaired = repair_rox_consistent_height_family_sequence(
            Some(&current_score),
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
        );

        assert!(
            repaired.is_none(),
            "consistent-height ROX repair should not rewrite mid-family foot points in otherwise short, low-residual fits"
        );
    }

    #[test]
    fn repair_rox_clean_early_family_replaces_false_late_tail() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let early_family = vec![
            1559usize, 1611, 1770, 1826, 1933, 2102, 2159, 2272, 2330, 2386, 2502, 2615, 2732,
            2850, 2909, 2968, 3087, 3205, 3324, 3442, 3559,
        ];
        let current = vec![
            1611usize, 1770, 2102, 2272, 2544, 2732, 2850, 3087, 3205, 3324, 3559, 3660, 3887,
            4108, 4382, 4495, 4843, 5000, 5258, 5390, 5665,
        ];

        let mut peak_map = BTreeMap::new();
        for (offset, scan) in early_family.iter().enumerate() {
            let height = 360.0 + (offset as f64 % 6.0) * 18.0;
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height,
                    prominence: height * 0.96,
                    width: 4.0,
                    local_baseline: 2.0,
                    score: height * 2.0,
                },
            );
        }
        peak_map.insert(
            2544,
            Peak {
                index: 2544,
                height: 475.0,
                prominence: 475.0,
                width: 4.0,
                local_baseline: 2.0,
                score: 950.0,
            },
        );
        for scan in [3660usize, 3887, 4495, 4843, 5000, 5258, 5390, 5665] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 500.0,
                    prominence: 42.0,
                    width: 4.0,
                    local_baseline: 455.0,
                    score: 84.0,
                },
            );
        }
        peak_map.insert(
            4108,
            Peak {
                index: 4108,
                height: 25.0,
                prominence: 16.0,
                width: 4.0,
                local_baseline: 9.0,
                score: 32.0,
            },
        );
        peak_map.insert(
            4382,
            Peak {
                index: 4382,
                height: 110.0,
                prominence: 105.0,
                width: 4.0,
                local_baseline: 5.0,
                score: 210.0,
            },
        );

        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        assert!(current_score.linear_max_abs_error_bp > 8.0);

        let repaired = repair_rox_clean_early_family_sequence(
            Some(&current_score),
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
        )
        .expect("clean early ROX family should replace false late baseline tail");

        assert_eq!(repaired.indices, early_family);
        assert!(repaired.linear_max_abs_error_bp < 5.0);
        assert!(repaired.linear_mean_abs_error_bp < 2.4);
        assert!(repaired.linear_r2 > 0.9994);
    }

    #[test]
    fn repair_rox_large_50_60_gap_moves_second_anchor_earlier() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let correct = vec![
            1555usize, 1627, 1784, 1841, 1949, 2113, 2170, 2284, 2342, 2399, 2514, 2629, 2746,
            2863, 2922, 2980, 3098, 3216, 3334, 3452, 3570,
        ];
        let mut current = correct.clone();
        current[1] = 1651;

        let mut peak_map = BTreeMap::new();
        for (offset, scan) in correct.iter().enumerate() {
            let height = 520.0 + (offset as f64 % 5.0) * 16.0;
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height,
                    prominence: height * 0.92,
                    width: 4.0,
                    local_baseline: 12.0,
                    score: height * 2.0,
                },
            );
        }
        peak_map.insert(
            1651,
            Peak {
                index: 1651,
                height: 505.0,
                prominence: 470.0,
                width: 4.0,
                local_baseline: 12.0,
                score: 940.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );

        let repaired = repair_rox_large_50_60_gap_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("large 50->60 gap should move only 60 bp to earlier clean peak");

        assert_eq!(repaired.indices, correct);
        assert!(repaired.linear_max_abs_error_bp + 0.35 < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.15);
        assert!(repaired.linear_r2 + 0.00008 >= current_score.linear_r2);
    }

    #[test]
    fn repair_rox_large_100_120_gap_moves_120_to_stronger_earlier_peak() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let correct = vec![
            1584usize, 1634, 1791, 1846, 1952, 2118, 2174, 2285, 2341, 2396, 2512, 2625, 2741,
            2857, 2916, 2974, 3092, 3209, 3326, 3442, 3558,
        ];
        let mut current = correct.clone();
        current[4] = 1987;

        let mut peak_map = BTreeMap::new();
        for (offset, scan) in correct.iter().enumerate() {
            let height = 560.0 + (offset as f64 % 5.0) * 18.0;
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height,
                    prominence: height * 0.92,
                    width: 4.0,
                    local_baseline: 10.0,
                    score: height * 2.0,
                },
            );
        }
        peak_map.insert(
            1987,
            Peak {
                index: 1987,
                height: 190.0,
                prominence: 190.0,
                width: 4.0,
                local_baseline: 0.0,
                score: 380.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );

        let repaired = repair_rox_large_100_120_gap_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("large 100->120 gap should move 120 bp to stronger earlier peak");

        assert_eq!(repaired.indices, correct);
        assert!(repaired.linear_max_abs_error_bp + 0.25 < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.10);
        assert!(repaired.linear_r2 + 0.00008 >= current_score.linear_r2);
    }

    #[test]
    #[ignore = "start-prefix repair is currently guarded to low-residual live cases"]
    fn repair_rox_start_prefix_pair_can_rebase_50_60_before_long_60_90_gap() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let correct = vec![
            1497usize, 1562, 1805, 1861, 1969, 2133, 2189, 2301, 2357, 2413, 2528, 2642, 2757,
            2873, 2931, 2989, 3105, 3220, 3335, 3449, 3563,
        ];
        let mut current = correct.clone();
        current[0] = 1529;
        current[1] = 1613;

        let mut peak_map = BTreeMap::new();
        for (offset, scan) in correct.iter().enumerate() {
            let height = 650.0 + (offset as f64 % 5.0) * 18.0;
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height,
                    prominence: height * 0.95,
                    width: 4.0,
                    local_baseline: 5.0,
                    score: height * 2.0,
                },
            );
        }
        for scan in [1529usize, 1613] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 420.0,
                    prominence: 420.0,
                    width: 4.0,
                    local_baseline: 4.0,
                    score: 840.0,
                },
            );
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );

        let repaired = repair_rox_start_prefix_pair_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("start prefix pair should rebase 50/60 before long 60->90 gap");

        assert!(
            repaired.indices[0] != current_score.indices[0]
                || repaired.indices[1] != current_score.indices[1]
        );
        assert!((35..=75).contains(&repaired.indices[1].saturating_sub(repaired.indices[0])));
        assert!(repaired.linear_max_abs_error_bp + 0.30 < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp <= current_score.linear_mean_abs_error_bp + 0.08);
        assert!(repaired.linear_r2 + 0.00005 >= current_score.linear_r2);
    }

    #[test]
    fn repair_liz_consistent_height_family_sequence_ignores_sub_80_baseline_peaks() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let family = ladder_sizes
            .iter()
            .map(|bp| (1300.0 + bp * 6.0).round() as usize)
            .collect::<Vec<_>>();
        let mut current = family.clone();
        current[5] = current[5].saturating_sub(42);
        current[10] = current[10].saturating_sub(55);

        let mut peak_map = BTreeMap::new();
        for (offset, scan) in family.iter().enumerate() {
            let height = 430.0 + (offset as f64 % 5.0) * 18.0;
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height,
                    prominence: height * 0.88,
                    width: 5.0,
                    local_baseline: 18.0,
                    score: height * 1.8,
                },
            );
        }
        for scan in [current[5], current[10]] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 62.0,
                    prominence: 24.0,
                    width: 5.0,
                    local_baseline: 38.0,
                    score: 28.0,
                },
            );
        }
        peak_map.insert(
            family[8] + 19,
            Peak {
                index: family[8] + 19,
                height: 1_250.0,
                prominence: 1_180.0,
                width: 5.0,
                local_baseline: 12.0,
                score: 2_350.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
            &peak_features,
        );

        let repaired = repair_liz_consistent_height_family_sequence(
            Some(&current_score),
            &ladder_sizes,
            LadderKind::Liz500250,
            &peak_map,
        )
        .expect("LIZ median family should ignore sub-80 baseline peaks");

        assert_eq!(repaired.indices, family);
        assert!(!repaired.indices.contains(&current[5]));
        assert!(!repaired.indices.contains(&current[10]));
        assert!(!repaired.indices.contains(&(family[8] + 19)));
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp < current_score.linear_mean_abs_error_bp);
        assert!(repaired.linear_r2 > current_score.linear_r2);
    }

    #[test]
    fn rox_post_blob_pool_override_prefers_complete_post_blob_family() {
        let mut merged = vec![make_rox_peak(1388, 760.0)];
        merged.extend(
            [
                1560usize, 1612, 1770, 1826, 2102, 2159, 2271, 2329, 2385, 2504, 2619, 2737, 2857,
                2916, 2976, 3094, 3212, 3330, 3446, 3560,
            ]
            .into_iter()
            .map(|index| make_rox_peak(index, 65.0)),
        );

        let filtered = [
            1560usize, 1612, 1770, 1826, 1934, 2102, 2159, 2271, 2329, 2385, 2504, 2619, 2737,
            2857, 2916, 2976, 3094, 3212, 3330, 3446, 3560,
        ]
        .into_iter()
        .map(|index| make_rox_peak(index, 65.0))
        .collect::<Vec<_>>();

        let override_pool = rox_post_blob_pool_override(&merged, &filtered, 21)
            .expect("post-blob ROX family should override blob-dependent pool");
        let indices = override_pool
            .iter()
            .map(|peak| peak.index)
            .collect::<Vec<_>>();
        assert_eq!(indices[0], 1560);
        assert!(indices.iter().all(|index| *index >= 1520));
        assert!(indices.contains(&1934));
        assert_eq!(indices.len(), 21);
    }

    #[test]
    fn repair_rox_tail_family_sequence_can_fix_shifted_tail_family() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let current = vec![
            1571usize, 1623, 1833, 1938, 2157, 2490, 2600, 2713, 2827, 2941, 3165, 3277, 3498,
            3779, 3916, 4045, 4241, 4433, 4455, 4634, 4805,
        ];
        let expected = vec![
            1571usize, 1623, 1833, 1938, 2157, 2490, 2600, 2713, 2827, 2941, 3165, 3277, 3498,
            3779, 3916, 4045, 4241, 4388, 4520, 4666, 4824,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &expected {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 620.0,
                    prominence: 760.0,
                    width: 4.0,
                    local_baseline: -120.0,
                    score: 2400.0,
                },
            );
        }
        for (scan, height, prominence, baseline, score) in [
            (4433usize, 1941.4, 546.4, 1395.0, 742.9),
            (4455, 1926.2, 284.5, 1641.7, 321.9),
            (4634, 490.0, 250.0, 240.0, 290.4),
            (4805, 107.4, 107.4, 0.0, 403.1),
            (4553, 1563.6, 1563.6, 0.0, 5369.6),
            (4388, 2520.0, 2660.0, -140.0, 9937.0),
            (4520, 1958.2, 862.8, 1095.4, 1038.7),
            (4666, 351.1, 246.7, 104.4, 380.5),
            (4824, 109.5, 109.5, 0.0, 337.3),
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height,
                    prominence,
                    width: 4.0,
                    local_baseline: baseline,
                    score,
                },
            );
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let current_score = score_combination(
            &current,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let repaired = repair_rox_tail_family_sequence(
            &current_score,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        )
        .expect("ROX tail-family repair should find a cleaner tail sequence");

        assert_eq!(repaired.indices, expected);
        assert!(repaired.linear_max_abs_error_bp < current_score.linear_max_abs_error_bp);
        assert!(repaired.linear_mean_abs_error_bp < current_score.linear_mean_abs_error_bp);
        assert!(repaired.linear_r2 > current_score.linear_r2);
    }

    #[test]
    fn local_peak_quality_penalty_dislikes_baseline_heavy_and_width_outlier_peaks() {
        let clean = vec![1600usize, 1700, 1900, 2000];
        let noisy = vec![1600usize, 1700, 1900, 2050];
        let mut peak_map = BTreeMap::new();

        for scan in clean.iter().take(3) {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 620.0,
                    prominence: 610.0,
                    width: 4.0,
                    local_baseline: 14.0,
                    score: 2500.0,
                },
            );
        }
        peak_map.insert(
            2000,
            Peak {
                index: 2000,
                height: 590.0,
                prominence: 575.0,
                width: 4.0,
                local_baseline: 16.0,
                score: 2400.0,
            },
        );
        peak_map.insert(
            2050,
            Peak {
                index: 2050,
                height: 260.0,
                prominence: 95.0,
                width: 11.0,
                local_baseline: 155.0,
                score: 900.0,
            },
        );

        let clean_penalty = local_peak_quality_penalty(&clean, &peak_map);
        let noisy_penalty = local_peak_quality_penalty(&noisy, &peak_map);
        assert!(noisy_penalty > clean_penalty + 0.15);
    }

    #[test]
    fn score_combination_prefers_cleaner_local_peak_family_when_geometry_is_similar() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1600usize, 1700, 1900, 2000, 2120, 2300, 2360, 2485, 2550, 2615, 2745, 2875, 3010,
            3145, 3210, 3280, 3415, 3550, 3685, 3820, 3950,
        ];
        let noisy = vec![
            1600usize, 1700, 1900, 2050, 2120, 2300, 2360, 2485, 2550, 2615, 2745, 2875, 3010,
            3145, 3210, 3280, 3415, 3550, 3685, 3820, 3950,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 620.0,
                    prominence: 605.0,
                    width: 4.0,
                    local_baseline: 16.0,
                    score: 2450.0,
                },
            );
        }
        peak_map.insert(
            2050,
            Peak {
                index: 2050,
                height: 260.0,
                prominence: 95.0,
                width: 11.0,
                local_baseline: 155.0,
                score: 900.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_score = score_combination(
            &clean,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        let noisy_score = score_combination(
            &noisy,
            &ladder_sizes,
            LadderKind::Rox400Hd,
            &peak_map,
            &peak_features,
        );
        assert!(clean_score.peak_penalty < noisy_score.peak_penalty);
        assert!(clean_score.blended_score < noisy_score.blended_score);
    }

    #[test]
    fn liz_linear_first_candidate_accepts_compelling_linear_win_despite_higher_penalties() {
        let mut peak_map = BTreeMap::new();
        for scan in [
            1585usize, 1632, 1803, 1964, 2359, 2421, 2461, 2736, 3041, 3414, 3631, 3697, 4031,
            4340, 4595, 4647, 1706, 2116,
        ] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: 700.0,
                    prominence: 660.0,
                    width: 4.0,
                    local_baseline: 20.0,
                    score: 700.0,
                },
            );
        }
        let current = CombinationScore {
            indices: vec![
                1585usize, 1632, 1803, 1964, 2359, 2421, 2461, 2736, 3041, 3414, 3631, 3697, 4031,
                4340, 4595, 4647,
            ],
            curvature_score: 0.18,
            quadratic_r2: 0.9991,
            linear_mean_abs_error_bp: 5.42,
            linear_max_abs_error_bp: 10.79,
            linear_r2: 0.99822,
            domain_penalty: 2.0,
            peak_penalty: 2.2,
            blended_score: 9.0,
        };
        let candidate = CombinationScore {
            indices: vec![
                1706usize, 1803, 1964, 2116, 2359, 2421, 2461, 2736, 3041, 3414, 3631, 3697, 4031,
                4340, 4595, 4647,
            ],
            curvature_score: 0.32,
            quadratic_r2: 0.9989,
            linear_mean_abs_error_bp: 1.76,
            linear_max_abs_error_bp: 4.96,
            linear_r2: 0.99978,
            domain_penalty: 5.6,
            peak_penalty: 5.9,
            blended_score: 11.0,
        };

        assert!(liz_linear_first_candidate_is_acceptable(
            &current, &candidate, &peak_map
        ));
    }

    #[test]
    fn filter_liz_peak_pool_for_fit_rejects_weak_baseline_peaks() {
        let mut peaks = vec![
            Peak {
                index: 1465,
                height: 980.0,
                prominence: 760.0,
                width: 6.0,
                local_baseline: 170.0,
                score: 980.0,
            },
            Peak {
                index: 1510,
                height: 310.0,
                prominence: 250.0,
                width: 4.0,
                local_baseline: 18.0,
                score: 320.0,
            },
            Peak {
                index: 1580,
                height: 92.0,
                prominence: 74.0,
                width: 4.0,
                local_baseline: 10.0,
                score: 96.0,
            },
            Peak {
                index: 1620,
                height: 58.0,
                prominence: 18.0,
                width: 5.0,
                local_baseline: 31.0,
                score: 24.0,
            },
            Peak {
                index: 1760,
                height: 295.0,
                prominence: 240.0,
                width: 4.0,
                local_baseline: 16.0,
                score: 305.0,
            },
        ];
        for offset in 0..12usize {
            peaks.push(Peak {
                index: 1900 + offset * 180,
                height: 280.0 + (offset % 3) as f64 * 25.0,
                prominence: 225.0 + (offset % 3) as f64 * 20.0,
                width: 4.0,
                local_baseline: 14.0,
                score: 295.0 + (offset % 3) as f64 * 24.0,
            });
        }

        let filtered = filter_liz_peak_pool_for_fit(&peaks, 14);
        assert!(filtered.iter().any(|peak| peak.index == 1580));
        assert!(!filtered.iter().any(|peak| peak.index == 1620));
        assert!(!filtered.iter().any(|peak| peak.index == 1465));
    }

    #[test]
    fn filter_liz_peak_pool_for_fit_rejects_local_low_outlier_when_stronger_neighbor_exists() {
        let mut peaks = vec![
            Peak {
                index: 1514,
                height: 3917.4,
                prominence: 2836.3,
                width: 8.0,
                local_baseline: 1081.1,
                score: 7201.9,
            },
            Peak {
                index: 1561,
                height: 32654.0,
                prominence: 32645.0,
                width: 7.0,
                local_baseline: 9.0,
                score: 122483.9,
            },
            Peak {
                index: 1717,
                height: 1245.7,
                prominence: 1221.5,
                width: 4.0,
                local_baseline: 24.2,
                score: 3140.0,
            },
            Peak {
                index: 1877,
                height: 1399.1,
                prominence: 1399.1,
                width: 4.0,
                local_baseline: 0.0,
                score: 4309.2,
            },
            Peak {
                index: 1968,
                height: 120.4,
                prominence: 120.4,
                width: 4.0,
                local_baseline: 0.0,
                score: 452.0,
            },
            Peak {
                index: 2032,
                height: 1645.6,
                prominence: 1645.6,
                width: 4.0,
                local_baseline: 0.0,
                score: 4407.1,
            },
        ];
        for offset in 0..11usize {
            peaks.push(Peak {
                index: 2280 + offset * 180,
                height: 1500.0 + (offset % 3) as f64 * 150.0,
                prominence: 1500.0 + (offset % 3) as f64 * 150.0,
                width: 4.0,
                local_baseline: 0.0,
                score: 4700.0 + (offset % 3) as f64 * 120.0,
            });
        }

        let filtered = filter_liz_peak_pool_for_fit(&peaks, 14);
        assert!(filtered.iter().any(|peak| peak.index == 1877));
        assert!(filtered.iter().any(|peak| peak.index == 2032));
        assert!(!filtered.iter().any(|peak| peak.index == 1968));
    }

    #[test]
    fn filter_rox_peak_pool_for_fit_rejects_early_blob_and_weak_tail_outliers() {
        let mut peaks = vec![
            Peak {
                index: 1512,
                height: 7200.0,
                prominence: 920.0,
                width: 10.0,
                local_baseline: 1800.0,
                score: 980.0,
            },
            Peak {
                index: 1588,
                height: 520.0,
                prominence: 470.0,
                width: 4.0,
                local_baseline: 25.0,
                score: 530.0,
            },
            Peak {
                index: 1640,
                height: 505.0,
                prominence: 455.0,
                width: 4.0,
                local_baseline: 24.0,
                score: 515.0,
            },
            Peak {
                index: 1795,
                height: 498.0,
                prominence: 446.0,
                width: 4.0,
                local_baseline: 23.0,
                score: 505.0,
            },
            Peak {
                index: 1970,
                height: 486.0,
                prominence: 432.0,
                width: 4.0,
                local_baseline: 22.0,
                score: 495.0,
            },
            Peak {
                index: 2190,
                height: 470.0,
                prominence: 425.0,
                width: 4.0,
                local_baseline: 22.0,
                score: 485.0,
            },
            Peak {
                index: 2399,
                height: 452.0,
                prominence: 406.0,
                width: 4.0,
                local_baseline: 20.0,
                score: 462.0,
            },
            Peak {
                index: 3672,
                height: 11.0,
                prominence: 9.0,
                width: 3.0,
                local_baseline: 6.0,
                score: 10.0,
            },
            Peak {
                index: 3938,
                height: 8.0,
                prominence: 7.0,
                width: 3.0,
                local_baseline: 4.0,
                score: 7.5,
            },
            Peak {
                index: 4025,
                height: 430.0,
                prominence: 395.0,
                width: 4.0,
                local_baseline: 18.0,
                score: 440.0,
            },
            Peak {
                index: 4140,
                height: 418.0,
                prominence: 382.0,
                width: 4.0,
                local_baseline: 18.0,
                score: 428.0,
            },
            Peak {
                index: 4255,
                height: 406.0,
                prominence: 370.0,
                width: 4.0,
                local_baseline: 17.0,
                score: 416.0,
            },
        ];
        peaks.sort_by_key(|peak| peak.index);

        let filtered = filter_rox_peak_pool_for_fit(&peaks, 8);
        assert!(filtered.iter().all(|peak| peak.index != 1512));
        assert!(filtered.iter().all(|peak| peak.index != 3672));
        assert!(filtered.iter().all(|peak| peak.index != 3938));
        assert!(filtered.iter().any(|peak| peak.index == 1588));
        assert!(filtered.iter().any(|peak| peak.index == 4025));
    }

    #[test]
    fn rox_early_window_peak_candidates_keeps_dense_early_family() {
        let mut corrected = vec![0.0; 2600];
        for (index, height) in [
            (1602usize, 180.0),
            (1655, 170.0),
            (1810, 165.0),
            (1865, 158.0),
            (1972, 162.0),
            (2140, 160.0),
        ] {
            corrected[index - 1] = height * 0.65;
            corrected[index] = height;
            corrected[index + 1] = height * 0.7;
        }
        let quantile = corrected.clone();

        let candidates = rox_early_window_peak_candidates(&corrected, &quantile, 48);
        let indices = candidates.iter().map(|peak| peak.index).collect::<Vec<_>>();
        assert!(indices.contains(&1602));
        assert!(indices.contains(&1655));
        assert!(indices.contains(&1810));
        assert!(indices.contains(&1865));
    }

    #[test]
    fn ladder_peak_sequence_penalty_dislikes_rox_family_signal_mismatch() {
        let ladder_sizes = LadderKind::Rox400Hd.sizes().to_vec();
        let clean = vec![
            1588usize, 1640, 1795, 1849, 1970, 2086, 2190, 2289, 2399, 2511, 2624, 2738, 2850,
            2964, 3078, 3190, 3304, 3418, 3532, 3646, 4025,
        ];
        let dirty = vec![
            1512usize, 1640, 1795, 1849, 1970, 2086, 2190, 2289, 2003, 2511, 2624, 2738, 2850,
            2964, 3078, 3190, 3304, 3418, 3672, 3938, 4025,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 520.0,
                    prominence: 470.0,
                    width: 4.0,
                    local_baseline: 24.0,
                    score: 530.0,
                },
            );
        }
        peak_map.insert(
            1512,
            Peak {
                index: 1512,
                height: 7200.0,
                prominence: 920.0,
                width: 10.0,
                local_baseline: 1800.0,
                score: 980.0,
            },
        );
        for scan in [2003usize, 3672, 3938] {
            peak_map.insert(
                scan,
                Peak {
                    index: scan,
                    height: if scan == 2003 { 16.0 } else { 10.0 },
                    prominence: if scan == 2003 { 12.0 } else { 8.0 },
                    width: 3.0,
                    local_baseline: 5.0,
                    score: if scan == 2003 { 13.0 } else { 8.5 },
                },
            );
        }
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();
        let clean_penalty = ladder_peak_sequence_penalty(
            &clean,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        let dirty_penalty = ladder_peak_sequence_penalty(
            &dirty,
            LadderKind::Rox400Hd,
            &ladder_sizes,
            &peak_map,
            &peak_features,
        );
        assert!(dirty_penalty > clean_penalty);
    }

    #[test]
    fn ladder_domain_penalty_dislikes_liz_lone_low_baseline_peak() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let clean = vec![
            1510usize, 1582, 1760, 1910, 2060, 2300, 2360, 2421, 2672, 2978, 3312, 3559, 3622,
            3946, 4124, 4242,
        ];
        let weak = vec![
            1510usize, 1582, 1760, 1910, 2060, 2300, 2360, 2421, 2672, 2978, 3312, 3559, 3622,
            3946, 4124, 4302,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 320.0,
                    prominence: 265.0,
                    width: 4.0,
                    local_baseline: 16.0,
                    score: 310.0,
                },
            );
        }
        peak_map.insert(
            4302,
            Peak {
                index: 4302,
                height: 54.0,
                prominence: 19.0,
                width: 4.0,
                local_baseline: 24.0,
                score: 22.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();

        let clean_penalty =
            ladder_domain_penalty(LadderKind::Liz500250, &clean, &peak_map, &peak_features)
                + ladder_peak_sequence_penalty(
                    &clean,
                    LadderKind::Liz500250,
                    &ladder_sizes,
                    &peak_map,
                    &peak_features,
                );
        let weak_penalty =
            ladder_domain_penalty(LadderKind::Liz500250, &weak, &peak_map, &peak_features)
                + ladder_peak_sequence_penalty(
                    &weak,
                    LadderKind::Liz500250,
                    &ladder_sizes,
                    &peak_map,
                    &peak_features,
                );

        assert!(weak_penalty > clean_penalty);
    }

    #[test]
    fn ladder_domain_penalty_dislikes_liz_isolated_low_peak_among_strong_neighbors() {
        let ladder_sizes = LadderKind::Liz500250.sizes().to_vec();
        let clean = vec![
            1563usize, 1614, 1717, 1879, 2283, 2347, 2411, 2674, 2997, 3342, 3603, 3668, 4008,
            4322, 4577, 4631,
        ];
        let weak = vec![
            1563usize, 1614, 1717, 1968, 2283, 2347, 2411, 2674, 2997, 3342, 3603, 3668, 4008,
            4322, 4577, 4631,
        ];

        let mut peak_map = BTreeMap::new();
        for scan in &clean {
            peak_map.insert(
                *scan,
                Peak {
                    index: *scan,
                    height: 1480.0,
                    prominence: 1360.0,
                    width: 4.0,
                    local_baseline: 0.0,
                    score: 4200.0,
                },
            );
        }
        peak_map.insert(
            1968,
            Peak {
                index: 1968,
                height: 118.0,
                prominence: 114.0,
                width: 4.0,
                local_baseline: 0.0,
                score: 430.0,
            },
        );
        let peak_features = peak_map.values().cloned().collect::<Vec<_>>();

        let clean_penalty =
            ladder_domain_penalty(LadderKind::Liz500250, &clean, &peak_map, &peak_features)
                + ladder_peak_sequence_penalty(
                    &clean,
                    LadderKind::Liz500250,
                    &ladder_sizes,
                    &peak_map,
                    &peak_features,
                );
        let weak_penalty =
            ladder_domain_penalty(LadderKind::Liz500250, &weak, &peak_map, &peak_features)
                + ladder_peak_sequence_penalty(
                    &weak,
                    LadderKind::Liz500250,
                    &ladder_sizes,
                    &peak_map,
                    &peak_features,
                );

        assert!(weak_penalty > clean_penalty + 0.25);
    }

    #[test]
    fn sample_mapping_preview_filters_negative_basepairs_and_stays_monotonic() {
        let trace = vec![10.0, 20.0, 30.0, 40.0, 50.0];
        let predicted = vec![-1.0, 1.0, 3.0, 5.0, 7.0];
        let preview = build_sample_mapping_preview(&trace, &predicted)
            .expect("sample mapping preview should be created");
        assert_eq!(preview.points_retained, 4);
        assert_eq!(preview.min_basepair, 1.0);
        assert!(preview.monotonic_unique);
    }

    #[test]
    fn sample_mapping_preview_includes_detected_sample_peaks() {
        let trace = vec![
            0.0, 10.0, 200.0, 15.0, 0.0, 5.0, 0.0, 4.0, 0.0, 20.0, 250.0, 10.0, 0.0,
        ];
        let predicted = (0..trace.len())
            .map(|value| value as f64)
            .collect::<Vec<_>>();
        let preview = build_sample_mapping_preview(&trace, &predicted)
            .expect("sample mapping preview should be created");
        assert_eq!(preview.sample_peak_preview.len(), 2);
        assert_eq!(preview.sample_peak_preview[0].time, 2);
        assert_eq!(preview.sample_peak_preview[1].time, 10);
    }

    #[test]
    fn assay_group_preview_clusters_nearby_peaks_and_filters_weak_ones() {
        let peaks = vec![
            SamplePeakPreview {
                time: 10,
                intensity: 100.0,
                basepair: 100.0,
                area: 0.0,
            },
            SamplePeakPreview {
                time: 12,
                intensity: 20.0,
                basepair: 104.0,
                area: 0.0,
            },
            SamplePeakPreview {
                time: 20,
                intensity: 50.0,
                basepair: 130.0,
                area: 0.0,
            },
            SamplePeakPreview {
                time: 22,
                intensity: 30.0,
                basepair: 138.0,
                area: 0.0,
            },
        ];
        let groups = build_assay_group_preview(&peaks);
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].kept_peak_count, 1);
        assert_eq!(groups[1].kept_peak_count, 2);
        assert!(groups[0].clonal_candidate);
        assert_eq!(groups[0].dominant_ratio_vs_second, None);
        assert_eq!(groups[1].dominant_ratio_vs_second, Some(1.67));
        assert!(!groups[1].clonal_candidate);
    }

    #[test]
    fn clonality_preview_prefers_filename_and_group_overlap_matches() {
        let groups = vec![SamplePeakGroupPreview {
            group_id: 1,
            start_basepair: 120.0,
            end_basepair: 150.0,
            cluster_width_bp: 30.0,
            max_intensity: 3000.0,
            dominant_peak_basepair: 140.0,
            dominant_peak_intensity: 3000.0,
            dominant_peak_area: 0.0,
            dominant_ratio_vs_second: Some(2.2),
            kept_peak_count: 1,
            clonal_candidate: true,
            peaks: vec![SamplePeakPreview {
                time: 100,
                intensity: 3000.0,
                basepair: 140.0,
                area: 0.0,
            }],
        }];
        let preview = build_clonality_preview(
            "26OUM04817_IGK_270326_B05_H9H1DI2F.fsa",
            "DATA1",
            &groups,
            BTreeMap::new(),
        );
        assert!(!preview.ranked_assays.is_empty());
        assert_eq!(preview.ranked_assays[0].assay_name, "IGK");
        assert!(preview.ranked_assays[0].matched_by_filename);
        assert_eq!(preview.ranked_assays[0].clonal_group_count, 1);
        assert_eq!(preview.ranked_assays[0].best_dominant_ratio, Some(2.2));
        assert!(preview.ranked_assays[0].matched_groups[0].clonal_candidate);
    }

    #[test]
    fn expected_clonality_ladder_kind_uses_liz_for_igk_family() {
        assert_eq!(
            expected_clonality_ladder_kind("26OUM04817_IGK_270326_B05_H9H1DI2F.fsa"),
            Some(LadderKind::Liz500250)
        );
        assert_eq!(
            expected_clonality_ladder_kind("24OUM09383_tcrgB__170624_C04_C990JWWX.fsa"),
            Some(LadderKind::Liz500250)
        );
        assert_eq!(
            expected_clonality_ladder_kind("25OUM01476_TRG_mixA__040225_A01_C9U078K2.fsa"),
            Some(LadderKind::Liz500250)
        );
        assert_eq!(
            expected_clonality_ladder_kind("25OUM01632_TRG_mixB__040225_A07_C9U078K2.fsa"),
            Some(LadderKind::Liz500250)
        );
        assert_eq!(
            expected_clonality_ladder_kind("25OUM07000_TRG_mixA_RERUN__080725_E11_H9C0U3EG.fsa"),
            Some(LadderKind::Liz500250)
        );
        assert_eq!(
            expected_clonality_ladder_kind("25OUM15593_trgA__151025_D06_H9C0ZJ6A.fsa"),
            Some(LadderKind::Liz500250)
        );
        assert_eq!(
            expected_clonality_ladder_kind("25OUM15783_trgB__151025_E08_H9C0ZJ6A.fsa"),
            Some(LadderKind::Liz500250)
        );
    }

    #[test]
    fn expected_clonality_ladder_kind_uses_rox_for_tcrb_family() {
        assert_eq!(
            expected_clonality_ladder_kind("24OUM02710_tcrbB_22022024_B04_C9R0HJYE.fsa"),
            Some(LadderKind::Rox400Hd)
        );
        assert_eq!(
            expected_clonality_ladder_kind("24OUM09619_FR2__24062024_F03_C920V4FN.fsa"),
            Some(LadderKind::Rox400Hd)
        );
    }

    #[test]
    fn flt3_preview_detects_itd_mutant_peaks_from_filename() {
        let peaks = vec![
            SamplePeakPreview {
                time: 100,
                intensity: 10000.0,
                basepair: 330.2,
                area: 0.0,
            },
            SamplePeakPreview {
                time: 120,
                intensity: 850.0,
                basepair: 351.0,
                area: 0.0,
            },
            SamplePeakPreview {
                time: 140,
                intensity: 410.0,
                basepair: 371.2,
                area: 0.0,
            },
        ];

        let preview = build_flt3_preview("ivs0000_flt3_itd_p1.fsa", "DATA1", &peaks);
        assert_eq!(preview.assay_name, "FLT3-ITD");
        assert!(preview.matched_by_filename);
        assert!(preview.compatible_channel);
        assert!(preview.positive_call);
        assert_eq!(
            preview.wt_peak.as_ref().map(|peak| peak.basepair),
            Some(330.2)
        );
        assert_eq!(preview.mutant_peaks.len(), 2);
        assert!(preview.strongest_mutant_ratio.is_some());
    }

    #[test]
    fn ladder_review_waives_weak_start_for_high_confidence_complete_liz_fit() {
        let scans = vec![
            1550usize, 1630, 1710, 1790, 1870, 1950, 2030, 2110, 2190, 2270, 2350, 2430, 2510,
            2590, 2670, 2750,
        ];
        let mut peaks = vec![make_test_peak(scans[0], 30.0)];
        peaks.extend(
            scans
                .iter()
                .skip(1)
                .map(|scan| make_test_peak(*scan, 120.0)),
        );
        let preview = make_test_preview(scans, 0.92, 1.0, 0.0, 0.0);

        let assessment =
            build_ladder_review_assessment(LadderKind::Liz500250, &peaks, Some(&preview));

        assert!(
            !assessment.suggested_review,
            "unexpected review assessment: {assessment:?}"
        );
        assert!(assessment.reason_codes.is_empty());
    }

    #[test]
    fn ladder_review_never_waives_a_strongly_baseline_like_selected_anchor() {
        let scans = vec![
            1550usize, 1630, 1710, 1790, 1870, 1950, 2030, 2110, 2190, 2270, 2350, 2430, 2510,
            2590, 2670, 2750,
        ];
        let mut peaks = scans
            .iter()
            .map(|scan| make_test_peak(*scan, 120.0))
            .collect::<Vec<_>>();
        peaks[7] = Peak {
            index: scans[7],
            height: 100.0,
            prominence: 30.0,
            width: 4.0,
            local_baseline: 60.0,
            score: 35.0,
        };
        let preview = make_test_preview(scans, 0.10, 1.0, 0.0, 0.0);

        let assessment =
            build_ladder_review_assessment(LadderKind::Liz500250, &peaks, Some(&preview));

        assert!(assessment.suggested_review);
        assert_eq!(assessment.selected_strong_baseline_anchor_count, 1);
        assert!(
            assessment
                .reason_codes
                .contains(&"selected_baseline_like_ladder_peaks".to_owned())
        );
    }

    #[test]
    fn ladder_review_keeps_weak_start_when_complete_fit_is_not_high_confidence() {
        let scans = vec![
            1550usize, 1630, 1710, 1790, 1870, 1950, 2030, 2110, 2190, 2270, 2350, 2430, 2510,
            2590, 2670, 2750,
        ];
        let mut peaks = vec![make_test_peak(scans[0], 30.0)];
        peaks.extend(
            scans
                .iter()
                .skip(1)
                .map(|scan| make_test_peak(*scan, 120.0)),
        );
        let preview = make_test_preview(scans, 0.92, 0.9990, 0.60, 1.20);

        let assessment =
            build_ladder_review_assessment(LadderKind::Liz500250, &peaks, Some(&preview));

        assert!(assessment.suggested_review);
        assert!(
            assessment
                .reason_codes
                .contains(&"weak_start_region".to_owned())
        );
    }

    #[test]
    fn ladder_review_waives_borderline_rox_complete_fit_when_clean() {
        let scans = vec![
            1605usize, 1657, 1816, 1872, 1979, 2147, 2204, 2316, 2372, 2429, 2546, 2662, 2783,
            2908, 2971, 3034, 3163, 3293, 3423, 3553, 3683,
        ];
        let peaks: Vec<_> = scans
            .iter()
            .map(|scan| make_rox_peak(*scan, 900.0))
            .collect();
        let mut preview = make_test_preview(scans, 0.40, 0.9990, 0.20, 0.35);
        let metrics = &mut preview.sizing_model.as_mut().unwrap().qc_metrics;
        metrics.linear_trend_max_abs_error_bp = 7.24;
        metrics.linear_trend_mean_abs_error_bp = 3.42;
        metrics.linear_trend_r2 = 0.99858;

        let assessment =
            build_ladder_review_assessment(LadderKind::Rox400Hd, &peaks, Some(&preview));

        assert!(
            !assessment.suggested_review,
            "unexpected review assessment: {assessment:?}"
        );
        assert!(assessment.reason_codes.is_empty());
    }

    #[test]
    fn ladder_review_keeps_rox_review_when_borderline_fit_is_too_poor() {
        let scans = vec![
            1887usize, 1951, 2291, 2369, 2515, 2754, 2834, 2997, 3080, 3164, 3343, 3519, 3701,
            3886, 3984, 4082, 4274, 4475, 4676, 4882, 5084,
        ];
        let peaks: Vec<_> = scans
            .iter()
            .map(|scan| make_rox_peak(*scan, 160.0))
            .collect();
        let mut preview = make_test_preview(scans, 0.40, 0.9990, 0.20, 0.35);
        let metrics = &mut preview.sizing_model.as_mut().unwrap().qc_metrics;
        metrics.linear_trend_max_abs_error_bp = 8.67;
        metrics.linear_trend_mean_abs_error_bp = 3.92;
        metrics.linear_trend_r2 = 0.99808;

        let assessment =
            build_ladder_review_assessment(LadderKind::Rox400Hd, &peaks, Some(&preview));

        assert!(assessment.suggested_review);
        assert!(
            assessment
                .reason_codes
                .contains(&"poor_linear_rox_fit".to_owned())
        );
    }

    #[test]
    fn ladder_review_waives_rox_complete_fit_when_quadratic_qc_is_strong() {
        let scans = vec![
            2007usize, 2076, 2291, 2369, 2515, 2754, 2834, 2997, 3080, 3164, 3343, 3519, 3701,
            3886, 3984, 4082, 4274, 4475, 4676, 4882, 5084,
        ];
        let peaks: Vec<_> = scans
            .iter()
            .map(|scan| make_rox_peak(*scan, 160.0))
            .collect();
        let mut preview = make_test_preview(scans, 0.40, 0.99999, 0.20, 0.35);
        let metrics = &mut preview.sizing_model.as_mut().unwrap().qc_metrics;
        metrics.linear_trend_max_abs_error_bp = 12.34;
        metrics.linear_trend_mean_abs_error_bp = 5.32;
        metrics.linear_trend_r2 = 0.99650;
        metrics.quadratic_trend_max_abs_error_bp = 2.07;
        metrics.quadratic_trend_mean_abs_error_bp = 0.80;
        metrics.quadratic_trend_r2 = 0.99992;

        let assessment =
            build_ladder_review_assessment(LadderKind::Rox400Hd, &peaks, Some(&preview));

        assert!(
            !assessment.suggested_review,
            "unexpected review assessment: {assessment:?}"
        );
        assert!(assessment.reason_codes.is_empty());
    }

    #[test]
    fn ladder_gap_template_penalty_is_liz_only_and_dislikes_shifted_gaps() {
        let good_liz = vec![
            1523usize, 1600, 1747, 1887, 2111, 2168, 2226, 2462, 2751, 3066, 3301, 3360, 3666,
            3946, 4174, 4221,
        ];
        let mut shifted_liz = good_liz.clone();
        shifted_liz[4] += 120;

        let good_penalty = ladder_gap_template_penalty(LadderKind::Liz500250, &good_liz);
        let shifted_penalty = ladder_gap_template_penalty(LadderKind::Liz500250, &shifted_liz);

        assert!(good_penalty < 0.05);
        assert!(shifted_penalty > good_penalty + 0.10);

        let rox = vec![
            1612usize, 1665, 1827, 1884, 1992, 2161, 2218, 2331, 2387, 2444, 2562, 2676, 2793,
            2912, 2972, 3031, 3149, 3266, 3382, 3498, 3613,
        ];
        assert_eq!(ladder_gap_template_penalty(LadderKind::Rox400Hd, &rox), 0.0);
    }

    #[test]
    fn liz_bounded_acceptance_requires_complete_strong_unambiguous_fit() {
        let scans = vec![
            1523usize, 1600, 1747, 1887, 2111, 2168, 2226, 2462, 2751, 3066, 3301, 3360, 3666,
            3946, 4174, 4221,
        ];
        let peaks = scans
            .iter()
            .map(|scan| make_test_peak(*scan, 180.0))
            .collect::<Vec<_>>();
        let mut preview = make_test_preview(scans, 0.1, 0.99999, 0.2, 0.35);
        let metrics = &mut preview.sizing_model.as_mut().unwrap().qc_metrics;
        metrics.linear_trend_max_abs_error_bp = 4.0;
        metrics.linear_trend_mean_abs_error_bp = 1.8;
        metrics.linear_trend_r2 = 0.9998;

        assert!(liz_preview_is_high_confidence_bounded(&preview, &peaks));

        preview
            .sizing_model
            .as_mut()
            .unwrap()
            .qc_metrics
            .linear_trend_mean_abs_error_bp = 2.6;
        assert!(!liz_preview_is_high_confidence_bounded(&preview, &peaks));
    }

    #[test]
    fn liz_repair_fast_path_rejects_weak_selected_anchor() {
        let scans = vec![
            1523usize, 1600, 1747, 1887, 2111, 2168, 2226, 2462, 2751, 3066, 3301, 3360, 3666,
            3946, 4174, 4221,
        ];
        let mut peaks = scans
            .iter()
            .map(|scan| make_test_peak(*scan, 180.0))
            .collect::<Vec<_>>();
        let peak_map = peaks
            .iter()
            .map(|peak| (peak.index, peak.clone()))
            .collect::<BTreeMap<_, _>>();
        let clean_score = score_combination(
            &scans,
            LadderKind::Liz500250.sizes(),
            LadderKind::Liz500250,
            &peak_map,
            &peaks,
        );
        assert!(liz_initial_fit_can_skip_repairs(&clean_score, &peaks));

        peaks[7].height = 12.0;
        peaks[7].prominence = 3.0;
        peaks[7].local_baseline = 9.0;
        peaks[7].score = 3.0;
        assert!(!liz_initial_fit_can_skip_repairs(&clean_score, &peaks));
    }

    #[test]
    fn relaxed_rust_beam_recovers_full_fit_when_gap_bound_has_no_sequence() {
        let mut scans = vec![
            1500usize, 1575, 1725, 1865, 2088, 2144, 2201, 2435, 2718, 3030, 3261, 3320, 3623,
            3901, 4127, 4173,
        ];
        scans[8] += 5_000;
        for index in 9..scans.len() {
            scans[index] += 5_000;
        }
        let peaks = scans
            .iter()
            .map(|scan| make_test_peak(*scan, 180.0))
            .collect::<Vec<_>>();
        let trace = vec![0.0; 12_000];

        let preview = build_ladder_fit_preview_with_candidate_pool(
            &peaks,
            &peaks,
            &trace,
            &trace,
            LadderKind::Liz500250,
            4_000,
            false,
        )
        .expect("relaxed Rust beam should return a full candidate sequence");

        assert_eq!(preview.search_tier, "robust_relaxed_beam");
        assert_eq!(preview.best_scan_indices.len(), scans.len());
    }

    #[test]
    fn liz_ladder_anchor_selection_is_independent_of_sample_trace_peaks() {
        let expected_scans = vec![
            1523usize, 1600, 1747, 1887, 2111, 2168, 2226, 2462, 2751, 3066, 3301, 3360, 3666,
            3946, 4174, 4221,
        ];
        let mut suspicious_scans = expected_scans.clone();
        suspicious_scans[4] += 120;
        let candidate_peaks = suspicious_scans
            .iter()
            .map(|scan| make_test_peak(*scan, 180.0))
            .collect::<Vec<_>>();

        let mut ladder_trace = vec![0.0; 4600];
        for scan in &expected_scans {
            ladder_trace[*scan - 1] = 20.0;
            ladder_trace[*scan] = 500.0;
            ladder_trace[*scan + 1] = 20.0;
        }

        let quiet_sample = vec![0.0; ladder_trace.len()];
        let mut unrelated_sample = vec![0.0; ladder_trace.len()];
        for (index, scan) in expected_scans.iter().enumerate() {
            let shifted = scan + 25 + index;
            unrelated_sample[shifted - 1] = 50.0;
            unrelated_sample[shifted] = 1500.0;
            unrelated_sample[shifted + 1] = 50.0;
        }

        let quiet_preview = build_ladder_fit_preview(
            &candidate_peaks,
            &quiet_sample,
            &ladder_trace,
            LadderKind::Liz500250,
            false,
        )
        .expect("quiet sample should still produce a LIZ fit");
        let unrelated_preview = build_ladder_fit_preview(
            &candidate_peaks,
            &unrelated_sample,
            &ladder_trace,
            LadderKind::Liz500250,
            false,
        )
        .expect("unrelated sample peaks should not prevent a LIZ fit");

        assert_eq!(
            quiet_preview.best_scan_indices,
            unrelated_preview.best_scan_indices
        );
    }
}
