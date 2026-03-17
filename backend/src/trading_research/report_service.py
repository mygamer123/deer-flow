from __future__ import annotations

from .evidence_service import EvidenceService
from .models import AggregatedReviewResult, Claim, ReviewResult, SetupResearchResult, StrategyImprovementLoopResult, StructuredResult


def build_review_markdown(result: ReviewResult, evidence_service: EvidenceService | None = None) -> str:
    lines = [f"# Trade Review: {result.symbol} ({result.trading_date.isoformat() if result.trading_date else 'unknown date'})", ""]
    _append_common_sections(lines, result, evidence_service or EvidenceService())
    return "\n".join(lines)


def build_setup_research_markdown(
    result: SetupResearchResult,
    evidence_service: EvidenceService | None = None,
) -> str:
    lines = [f"# Setup Research: {result.topic}", ""]
    if result.search_queries:
        lines.extend(["## Query Context", ""])
        for query in result.search_queries:
            lines.append(f"- `{query}`")
        lines.append("")
    _append_common_sections(lines, result, evidence_service or EvidenceService())
    return "\n".join(lines)


def _append_common_sections(
    lines: list[str],
    result: StructuredResult,
    evidence_service: EvidenceService,
) -> None:
    lines.extend(
        [
            "## Summary",
            "",
            f"- Workflow: `{result.workflow.value}`",
            f"- Subject: `{result.subject}`",
            f"- As of: `{result.as_of.isoformat()}`",
            f"- Findings: {len(result.findings)}",
            f"- Claims: {len(result.claims)}",
            f"- Recommendations: {len(result.recommendations)}",
            "",
            "## Findings",
            "",
        ]
    )
    if result.findings:
        for finding in result.findings:
            lines.append(f"### {finding.title}")
            lines.append("")
            lines.append(finding.detail)
            lines.append("")
            lines.append(f"- Evidence IDs: {', '.join(finding.evidence_ids) if finding.evidence_ids else 'none'}")
            if finding.confidence is not None:
                lines.append(f"- Confidence: {finding.confidence:.0%}")
            if finding.sample_size is not None:
                lines.append(f"- Sample size: {finding.sample_size}")
            if finding.limitations:
                lines.append(f"- Limitations: {'; '.join(finding.limitations)}")
            lines.append("")
    else:
        lines.append("- No structured findings were produced.")
        lines.append("")

    lines.extend(["## Claims", ""])
    if result.claims:
        for claim in result.claims:
            _append_claim(lines, claim)
    else:
        lines.append("- No claims were produced.")
        lines.append("")

    lines.extend(["## Recommendations", ""])
    if result.recommendations:
        for recommendation in result.recommendations:
            lines.append(f"### {recommendation.summary}")
            lines.append("")
            lines.append(recommendation.action)
            lines.append("")
            lines.append(f"- Supported by claims: {', '.join(recommendation.supported_by_claim_ids) if recommendation.supported_by_claim_ids else 'none'}")
            lines.append(f"- Evidence IDs: {', '.join(recommendation.evidence_ids) if recommendation.evidence_ids else 'none'}")
            lines.append(f"- Priority: {recommendation.priority.value}")
            if recommendation.confidence is not None:
                lines.append(f"- Confidence: {recommendation.confidence:.0%}")
            if recommendation.limitations:
                lines.append(f"- Limitations: {'; '.join(recommendation.limitations)}")
            lines.append("")
    else:
        lines.append("- No recommendations were produced.")
        lines.append("")

    lines.extend(["## Evidence References", ""])
    evidence_items = evidence_service.get_many(result.evidence_ids)
    if evidence_items:
        for evidence in evidence_items:
            title = evidence.title or evidence.source_ref or evidence.evidence_id
            lines.append(f"- `{evidence.evidence_id}` - {title}")
            if evidence.source_ref:
                lines.append(f"  - Source: `{evidence.source_ref}`")
            if evidence.content:
                lines.append(f"  - Content: {evidence.content[:240]}")
            lines.append("")
    else:
        lines.append("- No persisted evidence references were found.")
        lines.append("")

    lines.extend(["## Verifier Summary", ""])
    if result.verifier is not None:
        lines.append(f"- Passed: {'yes' if result.verifier.passed else 'no'}")
        lines.append(f"- Checked claims: {result.verifier.checked_claim_count}")
        lines.append(f"- Checked evidence items: {result.verifier.checked_evidence_count}")
        lines.append(f"- Boundary status: {result.verifier.boundary_status}")
        lines.append(f"- Summary: {result.verifier.summary}")
        if result.verifier.boundary_violation_claim_ids:
            lines.append(f"- Boundary violations: {', '.join(result.verifier.boundary_violation_claim_ids)}")
        if result.verifier.sample_size_downgraded_claim_ids:
            lines.append(f"- Sample-size downgraded claims: {', '.join(result.verifier.sample_size_downgraded_claim_ids)}")
        if result.verifier.downgraded_claim_ids:
            lines.append(f"- Downgraded claims: {', '.join(result.verifier.downgraded_claim_ids)}")
        if result.verifier.dropped_recommendation_ids:
            lines.append(f"- Dropped recommendations: {', '.join(result.verifier.dropped_recommendation_ids)}")
        if result.verifier.issues:
            lines.append("")
            for issue in result.verifier.issues:
                claim_part = f" ({issue.claim_id})" if issue.claim_id else ""
                evidence_part = f" [{', '.join(issue.evidence_ids)}]" if issue.evidence_ids else ""
                lines.append(f"- {issue.severity.upper()} `{issue.code}`{claim_part}{evidence_part}: {issue.message}")
        lines.append("")
    else:
        lines.append("- No verifier result available.")
        lines.append("")

    lines.extend(["## Limitations", ""])
    if result.limitations:
        for limitation in result.limitations:
            lines.append(f"- {limitation}")
    else:
        lines.append("- No explicit limitations were recorded.")
    lines.append("")


def build_aggregate_review_markdown(
    result: AggregatedReviewResult,
    evidence_service: EvidenceService | None = None,
) -> str:
    lines = [f"# Aggregated Trade Review: {result.grouping_key} ({result.trade_count} trades)", ""]

    lines.extend(["## Cohort Summary", ""])
    lines.append(f"- Trade count: {result.trade_count}")
    lines.append(f"- Grouping key: `{result.grouping_key}`")
    if result.symbol:
        lines.append(f"- Symbol: `{result.symbol}`")
    if result.date_range_start or result.date_range_end:
        start = result.date_range_start.isoformat() if result.date_range_start else "?"
        end = result.date_range_end.isoformat() if result.date_range_end else "?"
        lines.append(f"- Date range: {start} to {end}")
    lines.append(f"- Contributing result IDs: {', '.join(result.contributing_result_ids) if result.contributing_result_ids else 'none'}")
    if result.cohort_stats:
        for key, value in sorted(result.cohort_stats.items()):
            if key == "trade_count":
                continue
            if isinstance(value, dict):
                formatted = ", ".join(f"{k}={v}" for k, v in sorted(value.items()))
                lines.append(f"- {key}: {formatted}")
            else:
                lines.append(f"- {key}: {value}")
    lines.append("")

    _append_common_sections(lines, result, evidence_service or EvidenceService())
    return "\n".join(lines)


def build_strategy_improvement_markdown(result: StrategyImprovementLoopResult) -> str:
    lines = [f"# Strategy Improvement Loop ({result.trade_count} trades)", ""]

    lines.extend(["## Summary", ""])
    lines.append(f"- As of: `{result.as_of.isoformat()}`")
    lines.append(f"- Trades diagnosed: {result.trade_count}")
    lines.append(f"- Patterns extracted: {result.pattern_count}")
    lines.append(f"- Action candidates: {result.candidate_count}")
    lines.append("")

    lines.extend(["## Trade Diagnostics", ""])
    if result.diagnostics:
        lines.append("| Symbol | Date | Grade | Opportunity | Execution | Extraction | Failure Reason | Dominance | Action Type |")
        lines.append("|--------|------|-------|-------------|-----------|------------|----------------|-----------|-------------|")
        for diag in result.diagnostics:
            td = diag.trading_date.isoformat() if diag.trading_date else "?"
            dominance = diag.compound_failure_dominance.value if diag.compound_failure_dominance else "\u2014"
            lines.append(
                f"| {diag.symbol} | {td} | {diag.overall_grade.value} "
                f"| {diag.opportunity_quality.value} | {diag.execution_quality.value} "
                f"| {diag.extraction_quality.value} | {diag.primary_failure_reason.value} "
                f"| {dominance} "
                f"| {diag.strategy_action_type.value} |"
            )
        lines.append("")
    else:
        lines.append("- No diagnostics were produced.")
        lines.append("")

    lines.extend(["## Aggregate Patterns", ""])
    if result.patterns:
        lines.append("| Pattern Type | Value | Count | Frequency | Sample Size |")
        lines.append("|--------------|-------|-------|-----------|-------------|")
        for pattern in result.patterns:
            lines.append(f"| {pattern.pattern_type} | {pattern.value} | {pattern.count} | {pattern.frequency_pct:.0%} | {pattern.sample_size} |")
        lines.append("")
    else:
        lines.append("- No recurring patterns were extracted.")
        lines.append("")

    lines.extend(["## Verified Aggregate Claims", ""])
    if result.verified_claims:
        lines.append("| Claim ID | Statement | Status | Sample Size | Confidence |")
        lines.append("|----------|-----------|--------|-------------|------------|")
        for claim in result.verified_claims:
            conf = f"{claim.confidence:.0%}" if claim.confidence is not None else "—"
            ss = str(claim.sample_size) if claim.sample_size is not None else "—"
            lines.append(f"| {claim.claim_id} | {claim.statement[:120]} | {claim.status.value} | {ss} | {conf} |")
        lines.append("")
    else:
        lines.append("- No verified aggregate claims were produced.")
        lines.append("")

    lines.extend(["## Strategy Action Candidates", ""])
    if result.candidates:
        lines.append("| Action ID | Type | Status | Sample Size | Min Met | Claim IDs | Rationale |")
        lines.append("|-----------|------|--------|-------------|---------|-----------|-----------|")
        for candidate in result.candidates:
            claim_ids = ", ".join(candidate.supported_by_claim_ids) if candidate.supported_by_claim_ids else "none"
            lines.append(f"| {candidate.action_id} | {candidate.action_type.value} | {candidate.status.value} | {candidate.sample_size} | {'yes' if candidate.minimum_sample_size_met else 'no'} | {claim_ids} | {candidate.rationale[:120]} |")
        lines.append("")
    else:
        lines.append("- No strategy action candidates were produced.")
        lines.append("")

    lines.extend(["## Strategy Change Records", ""])
    if result.change_records:
        lines.append("| Record ID | Action Type | Status | Source Trades | Created At |")
        lines.append("|-----------|-------------|--------|---------------|------------|")
        for record in result.change_records:
            created = record.created_at.isoformat() if record.created_at else "?"
            lines.append(f"| {record.record_id} | {record.candidate.action_type.value} | {record.candidate.status.value} | {record.source_trade_count} | {created} |")
        lines.append("")
    else:
        lines.append("- No strategy change records were produced.")
        lines.append("")

    lines.extend(["## Limitations", ""])
    if result.limitations:
        for limitation in result.limitations:
            lines.append(f"- {limitation}")
    else:
        lines.append("- No explicit limitations were recorded.")
    lines.append("")

    return "\n".join(lines)


def _append_claim(lines: list[str], claim: Claim) -> None:
    lines.append(f"### {claim.statement}")
    lines.append("")
    lines.append(f"- Status: {claim.status.value}")
    lines.append(f"- Evidence IDs: {', '.join(claim.evidence_ids) if claim.evidence_ids else 'none'}")
    if claim.confidence is not None:
        lines.append(f"- Confidence: {claim.confidence:.0%}")
    if claim.sample_size is not None:
        lines.append(f"- Sample size: {claim.sample_size}")
    if claim.limitations:
        lines.append(f"- Limitations: {'; '.join(claim.limitations)}")
    lines.append("")
