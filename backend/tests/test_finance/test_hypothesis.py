"""Tests for src.community.finance.hypothesis — HypothesisTracker."""

from __future__ import annotations

import pytest

from src.community.finance.hypothesis import HypothesisTracker
from src.community.finance.models import DataGap, QuantitativeFindings


class TestFormHypothesis:
    def test_creates_hypothesis(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "Strong signal suggests good trade")
        assert h.statement == "Strong signal suggests good trade"
        assert h.confidence == pytest.approx(0.3)

    def test_custom_initial_confidence(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("entry", "Entry was optimal", initial_confidence=0.7)
        assert h.confidence == pytest.approx(0.7)

    def test_multiple_hypotheses_per_module(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("selection", "H1")
        tracker.form_hypothesis("selection", "H2")
        assert len(tracker.get_hypotheses("selection")) == 2


class TestUpdateWithFindings:
    def test_updates_confidence_on_relevant_observation(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "Strong signal score suggests good selection")

        findings = QuantitativeFindings(
            lens_name="basic_bars",
            iteration=1,
            observations=["Strong signal score (10.9)"],
        )
        tracker.update_with_findings("selection", findings)

        # Confidence should increase (some keyword overlap with "Strong signal score")
        assert h.confidence > 0.3
        assert len(h.evidence_for) > 0

    def test_no_update_on_irrelevant_observation(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "Strong signal score suggests good selection")

        findings = QuantitativeFindings(
            lens_name="basic_bars",
            iteration=1,
            observations=["Completely unrelated observation about weather"],
        )
        tracker.update_with_findings("selection", findings)
        assert h.confidence == pytest.approx(0.3)

    def test_data_gaps_accumulated(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("selection", "test")

        gap = DataGap(dimension="volume_profile", description="Missing volume data")
        findings = QuantitativeFindings(
            lens_name="test",
            iteration=1,
            data_gaps=[gap],
        )
        tracker.update_with_findings("selection", findings)
        assert len(tracker.get_all_gaps()) == 1
        assert tracker.get_all_gaps()[0].dimension == "volume_profile"


class TestGetHypotheses:
    def test_get_by_module(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("selection", "S1")
        tracker.form_hypothesis("entry", "E1")
        assert len(tracker.get_hypotheses("selection")) == 1
        assert len(tracker.get_hypotheses("entry")) == 1

    def test_get_all(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("selection", "S1")
        tracker.form_hypothesis("entry", "E1")
        tracker.form_hypothesis("exit", "X1")
        assert len(tracker.get_hypotheses()) == 3

    def test_empty_module(self):
        tracker = HypothesisTracker()
        assert tracker.get_hypotheses("nonexistent") == []


class TestDataGapManagement:
    def test_detect_gaps(self):
        tracker = HypothesisTracker()
        gaps = tracker.detect_gaps(available_data_keys={"minute_bars"}, required_data_keys={"minute_bars", "spy_bars", "qqq_bars"})
        assert len(gaps) == 2
        dimensions = {g.dimension for g in gaps}
        assert dimensions == {"spy_bars", "qqq_bars"}

    def test_no_gaps_when_all_available(self):
        tracker = HypothesisTracker()
        gaps = tracker.detect_gaps(available_data_keys={"a", "b"}, required_data_keys={"a", "b"})
        assert gaps == []

    def test_mark_gap_resolved(self):
        tracker = HypothesisTracker()
        tracker.detect_gaps(available_data_keys=set(), required_data_keys={"volume"})
        assert len(tracker.get_unresolved_gaps()) == 1

        tracker.mark_gap_resolved("volume")
        assert len(tracker.get_unresolved_gaps()) == 0
        assert len(tracker.get_all_gaps()) == 1  # Still exists, just resolved


class TestOverallConfidence:
    def test_zero_without_hypotheses(self):
        tracker = HypothesisTracker()
        assert tracker.overall_confidence() == 0.0

    def test_average_confidence(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("sel", "H1", initial_confidence=0.6)
        tracker.form_hypothesis("sel", "H2", initial_confidence=0.4)
        assert tracker.overall_confidence() == pytest.approx(0.5)


class TestAddCounterEvidence:
    def test_adds_counter_evidence(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "Strong signal suggests good trade", initial_confidence=0.8)

        tracker.add_counter_evidence("selection", "Strong signal", "Volume was actually low")
        assert "Volume was actually low" in h.evidence_against
        assert h.confidence < 0.8

    def test_no_match_no_change(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "Strong signal", initial_confidence=0.8)

        tracker.add_counter_evidence("selection", "completely different", "some evidence")
        assert len(h.evidence_against) == 0
        assert h.confidence == pytest.approx(0.8)

    def test_confidence_floor_at_zero(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "Strong signal", initial_confidence=0.05)
        tracker.add_counter_evidence("selection", "Strong signal", "Bad evidence")
        assert h.confidence >= 0.0


class TestFinalize:
    def test_marks_high_confidence_verified(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("selection", "test", initial_confidence=0.8)
        result = tracker.finalize()
        assert len(result) == 1
        assert result[0].verified is True

    def test_marks_low_confidence_rejected(self):
        tracker = HypothesisTracker()
        tracker.form_hypothesis("selection", "test", initial_confidence=0.2)
        result = tracker.finalize()
        assert result[0].verified is False

    def test_does_not_overwrite_manual_verification(self):
        tracker = HypothesisTracker()
        h = tracker.form_hypothesis("selection", "test", initial_confidence=0.2)
        h.verified = True  # Manually set
        result = tracker.finalize()
        assert result[0].verified is True  # Should not be overwritten
