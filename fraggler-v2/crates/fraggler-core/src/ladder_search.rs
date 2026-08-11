use std::cmp::Ordering;

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
}
