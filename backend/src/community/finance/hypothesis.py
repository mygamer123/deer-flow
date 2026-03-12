# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

from .models import DataGap, Hypothesis, QuantitativeFindings

# ---------------------------------------------------------------------------
# Hypothesis tracker — manages hypotheses across iterations
# ---------------------------------------------------------------------------


class HypothesisTracker:
    """Tracks hypotheses across the iterative convergence loop.

    Each review module (selection, entry, exit, failure) can form hypotheses
    early and refine them as new evidence arrives from subsequent lenses.
    """

    def __init__(self) -> None:
        self._hypotheses: dict[str, list[Hypothesis]] = {}  # module_name -> hypotheses
        self._data_gaps: list[DataGap] = []

    def form_hypothesis(self, module: str, statement: str, initial_confidence: float = 0.3) -> Hypothesis:
        h = Hypothesis(statement=statement, confidence=initial_confidence)
        self._hypotheses.setdefault(module, []).append(h)
        return h

    def update_with_findings(self, module: str, findings: QuantitativeFindings) -> None:
        """Refine existing hypotheses for *module* based on new findings."""
        hypotheses = self._hypotheses.get(module, [])
        for h in hypotheses:
            for obs in findings.observations:
                obs_lower = obs.lower()
                stmt_lower = h.statement.lower()
                # Simple keyword overlap heuristic — real implementation would use embeddings
                overlap_words = set(stmt_lower.split()) & set(obs_lower.split())
                relevance = len(overlap_words) / max(len(stmt_lower.split()), 1)
                if relevance > 0.15:
                    h.evidence_for.append(obs)
                    h.confidence = min(1.0, h.confidence + 0.05 * relevance * 10)

        self._data_gaps.extend(findings.data_gaps)

    def get_hypotheses(self, module: str | None = None) -> list[Hypothesis]:
        if module:
            return list(self._hypotheses.get(module, []))
        all_h: list[Hypothesis] = []
        for hyps in self._hypotheses.values():
            all_h.extend(hyps)
        return all_h

    def get_unresolved_gaps(self) -> list[DataGap]:
        return [g for g in self._data_gaps if not g.resolved]

    def get_all_gaps(self) -> list[DataGap]:
        return list(self._data_gaps)

    def mark_gap_resolved(self, dimension: str) -> None:
        for g in self._data_gaps:
            if g.dimension == dimension:
                g.resolved = True

    def detect_gaps(self, available_data_keys: set[str], required_data_keys: set[str]) -> list[DataGap]:
        """Identify missing data dimensions and register them as gaps."""
        missing = required_data_keys - available_data_keys
        new_gaps: list[DataGap] = []
        for dim in missing:
            gap = DataGap(dimension=dim, description=f"Missing data: {dim}", priority=0.5)
            self._data_gaps.append(gap)
            new_gaps.append(gap)
        return new_gaps

    def overall_confidence(self) -> float:
        """Weighted average confidence across all hypotheses."""
        all_h = self.get_hypotheses()
        if not all_h:
            return 0.0
        return sum(h.confidence for h in all_h) / len(all_h)

    def add_counter_evidence(self, module: str, statement_fragment: str, evidence: str) -> None:
        """Add counter-evidence to hypotheses whose statement contains *statement_fragment*."""
        for h in self._hypotheses.get(module, []):
            if statement_fragment.lower() in h.statement.lower():
                h.evidence_against.append(evidence)
                h.confidence = max(0.0, h.confidence - 0.1)

    def finalize(self) -> list[Hypothesis]:
        """Mark all hypotheses as verified/rejected based on final confidence."""
        all_h = self.get_hypotheses()
        for h in all_h:
            if h.verified is None:
                h.verified = h.confidence >= 0.5
        return all_h
