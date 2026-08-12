use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::time::Instant;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FitTier {
    Fast,
    #[serde(rename = "rescue_2s")]
    Rescue2s,
    #[serde(rename = "deep_rescue_10s")]
    DeepRescue10s,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SearchBudget {
    pub fit_tier: FitTier,
    pub expansion_limit: usize,
    pub watchdog_ms: u64,
}

impl SearchBudget {
    pub const fn new(fit_tier: FitTier, expansion_limit: usize, watchdog_ms: u64) -> Self {
        Self {
            fit_tier,
            expansion_limit,
            watchdog_ms,
        }
    }

    pub const fn allows_expansion(&self, expansions_used: usize) -> bool {
        expansions_used < self.expansion_limit
    }

    pub const fn tier_one() -> Self {
        Self::new(FitTier::Rescue2s, 50_000, 2_000)
    }

    pub const fn tier_two() -> Self {
        Self::new(FitTier::DeepRescue10s, 500_000, 10_000)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SearchDiagnostics {
    pub fit_tier: FitTier,
    pub expansions_used: usize,
    pub expansion_limit: usize,
    pub elapsed_us: u64,
    pub complete_candidate_count: usize,
    pub best_score: Option<f64>,
    pub runner_up_score: Option<f64>,
    pub score_margin: Option<f64>,
    pub rescue_triggers: Vec<String>,
    pub watchdog_reached: bool,
}

impl SearchDiagnostics {
    pub fn empty(fit_tier: FitTier, expansion_limit: usize) -> Self {
        Self {
            fit_tier,
            expansions_used: 0,
            expansion_limit,
            elapsed_us: 0,
            complete_candidate_count: 0,
            best_score: None,
            runner_up_score: None,
            score_margin: None,
            rescue_triggers: Vec::new(),
            watchdog_reached: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SearchCandidate {
    pub fit_tier: FitTier,
    pub scan_indices: Vec<usize>,
    pub score: f64,
}

impl SearchCandidate {
    pub fn stable_cmp(left: &Self, right: &Self) -> Ordering {
        left.score
            .total_cmp(&right.score)
            .then_with(|| left.scan_indices.cmp(&right.scan_indices))
            .then_with(|| (left.fit_tier as u8).cmp(&(right.fit_tier as u8)))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SearchOutcome {
    pub candidate: SearchCandidate,
    pub diagnostics: SearchDiagnostics,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PeakEvidence {
    pub scan: usize,
    pub height: f64,
    pub prominence: f64,
    pub local_baseline: f64,
    pub width: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LadderRescueInput {
    pub expected_basepairs: Vec<f64>,
    pub current_scan_indices: Vec<usize>,
    pub peaks: Vec<PeakEvidence>,
}

impl LadderRescueInput {
    pub fn new(
        expected_basepairs: Vec<f64>,
        current_scan_indices: Vec<usize>,
        peaks: Vec<PeakEvidence>,
    ) -> Self {
        Self {
            expected_basepairs,
            current_scan_indices,
            peaks,
        }
    }
}

fn median(values: &mut [f64]) -> f64 {
    values.sort_by(f64::total_cmp);
    let middle = values.len() / 2;
    if values.len() % 2 == 0 {
        (values[middle - 1] + values[middle]) * 0.5
    } else {
        values[middle]
    }
}

pub fn score_candidate_sequence(input: &LadderRescueInput, scans: &[usize]) -> Option<f64> {
    if scans.len() != input.expected_basepairs.len()
        || scans.len() < 3
        || !scans.windows(2).all(|pair| pair[1] > pair[0])
        || !input
            .expected_basepairs
            .windows(2)
            .all(|pair| pair[1] > pair[0])
    {
        return None;
    }
    let mut scales = scans
        .windows(2)
        .zip(input.expected_basepairs.windows(2))
        .map(|(scan, bp)| (scan[1] - scan[0]) as f64 / (bp[1] - bp[0]))
        .collect::<Vec<_>>();
    let scale = median(&mut scales).max(1e-9);
    let geometry = scales
        .iter()
        .map(|value| ((value / scale) - 1.0).abs())
        .sum::<f64>()
        / scales.len() as f64;
    let by_scan = input
        .peaks
        .iter()
        .map(|peak| (peak.scan, peak))
        .collect::<BTreeMap<_, _>>();
    let feature_penalty = scans
        .iter()
        .map(|scan| {
            let Some(peak) = by_scan.get(scan) else {
                return 4.0;
            };
            let height = peak.height.max(1.0);
            let purity = (peak.prominence.max(0.0) / height).clamp(0.0, 1.0);
            let baseline_ratio = (peak.local_baseline.max(0.0) / height).clamp(0.0, 1.5);
            (1.0 - purity) * 0.35 + baseline_ratio * 0.65
        })
        .sum::<f64>()
        / scans.len() as f64;
    Some(geometry * 10.0 + feature_penalty)
}

pub fn arbiter_select_candidate(
    current: &SearchCandidate,
    candidates: &[SearchCandidate],
    minimum_margin: f64,
) -> SearchCandidate {
    let best = candidates
        .iter()
        .min_by(|left, right| SearchCandidate::stable_cmp(left, right));
    match best {
        Some(candidate) if candidate.score + minimum_margin < current.score => candidate.clone(),
        _ => current.clone(),
    }
}

pub fn liz_local_rescue_candidates(
    input: &LadderRescueInput,
    budget: SearchBudget,
) -> Option<SearchOutcome> {
    let current_score = score_candidate_sequence(input, &input.current_scan_indices)?;
    let current = SearchCandidate {
        fit_tier: FitTier::Fast,
        scan_indices: input.current_scan_indices.clone(),
        score: current_score,
    };
    let second = *input.current_scan_indices.get(1)?;
    let third = *input.current_scan_indices.get(2)?;
    let reference_gap = third.saturating_sub(second).max(1) as f64;
    let mut candidates = Vec::new();
    let mut expansions = 0usize;
    for peak in &input.peaks {
        if !budget.allows_expansion(expansions) {
            break;
        }
        expansions += 1;
        if peak.scan >= second {
            continue;
        }
        let ratio = (second - peak.scan) as f64 / reference_gap;
        if !(0.22..=0.82).contains(&ratio) {
            continue;
        }
        let mut scans = input.current_scan_indices.clone();
        scans[0] = peak.scan;
        if let Some(score) = score_candidate_sequence(input, &scans) {
            candidates.push(SearchCandidate {
                fit_tier: FitTier::Rescue2s,
                scan_indices: scans,
                score,
            });
        }
    }
    candidates.sort_by(SearchCandidate::stable_cmp);
    candidates.dedup_by(|left, right| left.scan_indices == right.scan_indices);
    let selected = arbiter_select_candidate(&current, &candidates, 0.05);
    let runner_up = candidates
        .iter()
        .find(|candidate| candidate.scan_indices != selected.scan_indices)
        .map(|candidate| candidate.score);
    let mut diagnostics = SearchDiagnostics::empty(budget.fit_tier, budget.expansion_limit);
    diagnostics.expansions_used = expansions;
    diagnostics.complete_candidate_count = candidates.len();
    diagnostics.best_score = Some(selected.score);
    diagnostics.runner_up_score = runner_up;
    diagnostics.score_margin = runner_up.map(|score| score - selected.score);
    Some(SearchOutcome {
        candidate: selected,
        diagnostics,
    })
}

pub fn liz_core_rescue_candidates(
    input: &LadderRescueInput,
    budget: SearchBudget,
    beam_width: usize,
) -> Option<SearchOutcome> {
    let first_scan = *input.current_scan_indices.first()?;
    if input.expected_basepairs.len() != input.current_scan_indices.len()
        || input.current_scan_indices.len() < 4
    {
        return None;
    }
    let core_input = LadderRescueInput::new(
        input.expected_basepairs[1..].to_vec(),
        input.current_scan_indices[1..].to_vec(),
        input
            .peaks
            .iter()
            .filter(|peak| peak.scan > first_scan)
            .cloned()
            .collect(),
    );
    let mut outcome = deep_rescue_candidates(&core_input, budget, beam_width)?;
    let mut full_sequence = Vec::with_capacity(input.current_scan_indices.len());
    full_sequence.push(first_scan);
    full_sequence.extend(outcome.candidate.scan_indices);
    outcome.candidate.scan_indices = full_sequence;
    Some(outcome)
}

pub fn rox_local_rescue_candidates(
    input: &LadderRescueInput,
    budget: SearchBudget,
) -> Option<SearchOutcome> {
    let current_score = score_candidate_sequence(input, &input.current_scan_indices)?;
    let current = SearchCandidate {
        fit_tier: FitTier::Fast,
        scan_indices: input.current_scan_indices.clone(),
        score: current_score,
    };
    let mut candidates = Vec::new();
    let mut expansions = 0usize;
    for peak in &input.peaks {
        if input.current_scan_indices.contains(&peak.scan) {
            continue;
        }
        let mut expanded = input.current_scan_indices.clone();
        expanded.push(peak.scan);
        expanded.sort_unstable();
        expanded.dedup();
        if expanded.len() != input.current_scan_indices.len() + 1 {
            continue;
        }
        for drop_index in 0..expanded.len() {
            if !budget.allows_expansion(expansions) {
                break;
            }
            expansions += 1;
            let mut scans = expanded.clone();
            scans.remove(drop_index);
            if let Some(score) = score_candidate_sequence(input, &scans) {
                candidates.push(SearchCandidate {
                    fit_tier: FitTier::Rescue2s,
                    scan_indices: scans,
                    score,
                });
            }
        }
    }
    candidates.sort_by(SearchCandidate::stable_cmp);
    candidates.dedup_by(|left, right| left.scan_indices == right.scan_indices);
    let selected = arbiter_select_candidate(&current, &candidates, 0.01);
    let runner_up = candidates
        .iter()
        .find(|candidate| candidate.scan_indices != selected.scan_indices)
        .map(|candidate| candidate.score);
    let mut diagnostics = SearchDiagnostics::empty(budget.fit_tier, budget.expansion_limit);
    diagnostics.expansions_used = expansions;
    diagnostics.complete_candidate_count = candidates.len();
    diagnostics.best_score = Some(selected.score);
    diagnostics.runner_up_score = runner_up;
    diagnostics.score_margin = runner_up.map(|score| score - selected.score);
    Some(SearchOutcome {
        candidate: selected,
        diagnostics,
    })
}

#[derive(Debug, Clone, PartialEq)]
struct BeamState {
    next_peak_position: usize,
    scan_indices: Vec<usize>,
    accumulated_score: f64,
}

pub fn deep_rescue_candidates(
    input: &LadderRescueInput,
    budget: SearchBudget,
    beam_width: usize,
) -> Option<SearchOutcome> {
    let current_score = score_candidate_sequence(input, &input.current_scan_indices)?;
    let current = SearchCandidate {
        fit_tier: FitTier::Fast,
        scan_indices: input.current_scan_indices.clone(),
        score: current_score,
    };
    let mut peaks = input.peaks.clone();
    peaks.sort_by_key(|peak| peak.scan);
    peaks.dedup_by_key(|peak| peak.scan);
    let target_len = input.expected_basepairs.len();
    if target_len < 3 || peaks.len() < target_len {
        return completed_tier_or_previous(Some(current), None, false);
    }
    let width = beam_width.max(1);
    let started = Instant::now();
    let mut expansions = 0usize;
    let mut watchdog_reached = false;
    let mut states = vec![BeamState {
        next_peak_position: 0,
        scan_indices: Vec::new(),
        accumulated_score: 0.0,
    }];
    for step in 0..target_len {
        let remaining_after = target_len - step - 1;
        let mut next = Vec::new();
        for state in &states {
            let last_start = peaks.len().saturating_sub(remaining_after);
            for position in state.next_peak_position..last_start {
                if !budget.allows_expansion(expansions) {
                    break;
                }
                if started.elapsed().as_millis() >= u128::from(budget.watchdog_ms) {
                    watchdog_reached = true;
                    break;
                }
                expansions += 1;
                let mut scans = state.scan_indices.clone();
                scans.push(peaks[position].scan);
                let prefix_input = LadderRescueInput {
                    expected_basepairs: input.expected_basepairs[..scans.len()].to_vec(),
                    current_scan_indices: scans.clone(),
                    peaks: peaks.clone(),
                };
                let score = if scans.len() >= 3 {
                    score_candidate_sequence(&prefix_input, &scans).unwrap_or(f64::INFINITY)
                } else {
                    0.0
                };
                next.push(BeamState {
                    next_peak_position: position + 1,
                    scan_indices: scans,
                    accumulated_score: score,
                });
            }
            if watchdog_reached || !budget.allows_expansion(expansions) {
                break;
            }
        }
        if watchdog_reached || !budget.allows_expansion(expansions) || next.is_empty() {
            let mut outcome = completed_tier_or_previous(Some(current), None, watchdog_reached)?;
            outcome.diagnostics.fit_tier = budget.fit_tier;
            outcome.diagnostics.expansions_used = expansions;
            outcome.diagnostics.expansion_limit = budget.expansion_limit;
            outcome
                .diagnostics
                .rescue_triggers
                .push(if watchdog_reached {
                    "watchdog_reached".to_owned()
                } else {
                    "expansion_limit_reached".to_owned()
                });
            return Some(outcome);
        }
        next.sort_by(|left, right| {
            left.accumulated_score
                .total_cmp(&right.accumulated_score)
                .then_with(|| left.scan_indices.cmp(&right.scan_indices))
        });
        next.truncate(width);
        states = next;
    }
    let mut candidates = states
        .into_iter()
        .filter_map(|state| {
            score_candidate_sequence(input, &state.scan_indices).map(|score| SearchCandidate {
                fit_tier: budget.fit_tier,
                scan_indices: state.scan_indices,
                score,
            })
        })
        .collect::<Vec<_>>();
    candidates.sort_by(SearchCandidate::stable_cmp);
    let selected = arbiter_select_candidate(&current, &candidates, 0.10);
    let runner_up = candidates
        .iter()
        .find(|candidate| candidate.scan_indices != selected.scan_indices)
        .map(|candidate| candidate.score);
    let mut diagnostics = SearchDiagnostics::empty(budget.fit_tier, budget.expansion_limit);
    diagnostics.expansions_used = expansions;
    diagnostics.elapsed_us = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
    diagnostics.complete_candidate_count = candidates.len();
    diagnostics.best_score = Some(selected.score);
    diagnostics.runner_up_score = runner_up;
    diagnostics.score_margin = runner_up.map(|score| score - selected.score);
    Some(SearchOutcome {
        candidate: selected,
        diagnostics,
    })
}

pub fn completed_tier_or_previous(
    previous: Option<SearchCandidate>,
    completed: Option<SearchOutcome>,
    watchdog_reached: bool,
) -> Option<SearchOutcome> {
    if let Some(mut outcome) = completed {
        outcome.diagnostics.watchdog_reached |= watchdog_reached;
        return Some(outcome);
    }
    previous.map(|candidate| {
        let mut diagnostics = SearchDiagnostics::empty(candidate.fit_tier, 0);
        diagnostics.watchdog_reached = watchdog_reached;
        diagnostics.complete_candidate_count = 1;
        diagnostics.best_score = Some(candidate.score);
        SearchOutcome {
            candidate,
            diagnostics,
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(tier: FitTier, scans: &[usize], score: f64) -> SearchCandidate {
        SearchCandidate {
            fit_tier: tier,
            scan_indices: scans.to_vec(),
            score,
        }
    }

    #[test]
    fn interrupted_deep_tier_returns_last_completed_tier() {
        let fast = candidate(FitTier::Fast, &[100, 200, 300], 4.0);
        let outcome = completed_tier_or_previous(Some(fast.clone()), None, true).unwrap();
        assert_eq!(outcome.candidate, fast);
        assert!(outcome.diagnostics.watchdog_reached);
    }

    #[test]
    fn search_candidate_order_is_score_then_scan_sequence() {
        let mut values = vec![
            candidate(FitTier::Rescue2s, &[10, 30], 4.0),
            candidate(FitTier::Rescue2s, &[10, 20], 4.0),
        ];
        values.sort_by(SearchCandidate::stable_cmp);
        assert_eq!(values[0].scan_indices, vec![10, 20]);
    }

    #[test]
    fn search_budget_is_deterministic_and_bounded() {
        let budget = SearchBudget::new(FitTier::Rescue2s, 50_000, 2_000);
        assert!(budget.allows_expansion(49_999));
        assert!(!budget.allows_expansion(50_000));
    }

    #[test]
    fn diagnostics_round_trip_with_snake_case_tier() {
        let diagnostics = SearchDiagnostics::empty(FitTier::DeepRescue10s, 100_000);
        let value = serde_json::to_value(&diagnostics).unwrap();
        assert_eq!(value["fit_tier"], "deep_rescue_10s");
        assert_eq!(
            serde_json::from_value::<SearchDiagnostics>(value).unwrap(),
            diagnostics
        );
    }

    fn evidence(scan: usize, height: f64, prominence: f64) -> PeakEvidence {
        PeakEvidence {
            scan,
            height,
            prominence,
            local_baseline: 0.0,
            width: 3.0,
        }
    }

    #[test]
    fn liz_rescue_replaces_wrong_first_anchor_without_moving_stable_interior() {
        let expected_bp = vec![35.0, 50.0, 75.0, 100.0, 139.0, 150.0];
        let current = vec![1505, 1640, 1790, 1940, 2174, 2240];
        let peaks = vec![
            evidence(1505, 250.0, 80.0),
            evidence(1544, 900.0, 850.0),
            evidence(1640, 1000.0, 950.0),
            evidence(1790, 1100.0, 1050.0),
            evidence(1940, 1000.0, 950.0),
            evidence(2174, 950.0, 900.0),
            evidence(2240, 900.0, 850.0),
        ];
        let input = LadderRescueInput::new(expected_bp, current.clone(), peaks);
        let outcome = liz_local_rescue_candidates(&input, SearchBudget::tier_one()).unwrap();
        assert_eq!(outcome.candidate.scan_indices[0], 1544);
        assert_eq!(&outcome.candidate.scan_indices[1..], &current[1..]);
    }

    #[test]
    fn liz_core_rescue_repairs_core_before_reattaching_unchanged_35() {
        let expected_bp = vec![35.0, 50.0, 75.0, 100.0, 139.0, 150.0];
        let current = vec![1500, 1640, 1790, 1940, 2200, 2240];
        let expected = vec![1500, 1640, 1790, 1940, 2174, 2240];
        let peaks = vec![1500, 1640, 1790, 1940, 2174, 2200, 2240]
            .into_iter()
            .map(|scan| evidence(scan, 1000.0, 950.0))
            .collect();
        let input = LadderRescueInput::new(expected_bp, current, peaks);

        let outcome = liz_core_rescue_candidates(&input, SearchBudget::tier_one(), 64).unwrap();

        assert_eq!(outcome.candidate.scan_indices, expected);
        assert_eq!(outcome.candidate.scan_indices[0], 1500);
    }

    #[test]
    fn liz_core_rescue_never_moves_35_when_core_is_unchanged() {
        let expected_bp = vec![35.0, 50.0, 75.0, 100.0, 139.0, 150.0];
        let current = vec![1544, 1640, 1790, 1940, 2174, 2240];
        let peaks = current
            .iter()
            .copied()
            .chain(std::iter::once(1505))
            .map(|scan| evidence(scan, 1000.0, 950.0))
            .collect();
        let input = LadderRescueInput::new(expected_bp, current.clone(), peaks);

        let outcome = liz_core_rescue_candidates(&input, SearchBudget::tier_one(), 64).unwrap();

        assert_eq!(outcome.candidate.scan_indices, current);
    }

    #[test]
    fn arbiter_keeps_current_on_equal_score() {
        let current = candidate(FitTier::Fast, &[10, 20], 2.0);
        let rescue = candidate(FitTier::Rescue2s, &[10, 21], 2.0);
        assert_eq!(arbiter_select_candidate(&current, &[rescue], 0.1), current);
    }

    #[test]
    fn rox_rescue_considers_one_step_insertion_after_stable_prefix() {
        let expected_bp = vec![50.0, 60.0, 90.0, 100.0, 120.0, 150.0];
        let expected = vec![1605, 1659, 1821, 1878, 1988, 2139];
        let current = vec![1605, 1659, 1821, 1878, 1988, 2161];
        let peaks = expected
            .iter()
            .map(|scan| evidence(*scan, 1000.0, 950.0))
            .chain(std::iter::once(PeakEvidence {
                scan: 2161,
                height: 300.0,
                prominence: 20.0,
                local_baseline: 300.0,
                width: 8.0,
            }))
            .collect();
        let input = LadderRescueInput::new(expected_bp, current, peaks);
        let outcome = rox_local_rescue_candidates(&input, SearchBudget::tier_one()).unwrap();
        assert_eq!(outcome.candidate.scan_indices, expected);
    }

    #[test]
    fn deep_rescue_recovers_complete_monotonic_sequence() {
        let expected_bp = vec![50.0, 60.0, 90.0, 100.0, 120.0];
        let expected = vec![2000, 2050, 2200, 2250, 2350];
        let current = vec![1800, 1900, 2000, 2050, 2200];
        let peaks = vec![1800, 1900, 2000, 2050, 2200, 2250, 2350]
            .into_iter()
            .map(|scan| evidence(scan, 1000.0, 950.0))
            .collect();
        let input = LadderRescueInput::new(expected_bp, current, peaks);
        let outcome = deep_rescue_candidates(&input, SearchBudget::tier_two(), 64).unwrap();
        assert_eq!(outcome.candidate.scan_indices, expected);
    }

    #[test]
    fn deep_rescue_discards_incomplete_budget_limited_tier() {
        let input = LadderRescueInput::new(
            vec![50.0, 60.0, 90.0],
            vec![100, 150, 300],
            (100..=400)
                .step_by(25)
                .map(|scan| evidence(scan, 1000.0, 950.0))
                .collect(),
        );
        let outcome = deep_rescue_candidates(
            &input,
            SearchBudget::new(FitTier::DeepRescue10s, 1, 10_000),
            64,
        )
        .unwrap();
        assert_eq!(outcome.candidate.scan_indices, input.current_scan_indices);
        assert_eq!(outcome.diagnostics.expansions_used, 1);
    }
}
