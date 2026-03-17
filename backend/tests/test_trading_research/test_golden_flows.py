from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src.trading_research.aggregate_review_service import AggregatedTradeReviewRequest, AggregateReviewService
from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import ClaimStatus
from src.trading_research.report_service import build_aggregate_review_markdown, build_review_markdown, build_setup_research_markdown
from src.trading_research.setup_research_service import SetupResearchService
from src.trading_research.trade_review_service import TradeReviewService

from .test_setup_research_service import _make_research_report
from .test_trade_review_service import _make_trade_review


def test_trade_review_golden_flow(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path / "evidence"):
        with patch(
            "src.trading_research.trade_review_service.DecisionReviewService.review_single_trade",
            return_value=_make_trade_review(),
        ):
            evidence_service = EvidenceService()
            result = TradeReviewService(evidence_service=evidence_service).review_trade(
                symbol="AMPX",
                trading_date=date(2026, 3, 5),
                log_source="prod",
            )
            markdown = build_review_markdown(result, evidence_service)

        assert result.claims
        assert result.evidence_ids
        assert evidence_service.get(result.evidence_ids[0]) is not None
        assert result.verifier is not None and result.verifier.passed is False
        assert result.verifier.sample_size_downgraded_claim_ids
        assert result.recommendations == []
        assert "## Findings" in markdown
        assert "## Claims" in markdown
        assert "## Recommendations" in markdown
        assert "## Evidence References" in markdown
        assert "## Verifier Summary" in markdown


def test_setup_research_golden_flow(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path / "evidence"):
        with patch(
            "src.trading_research.setup_research_service.ResearchService.research_topic",
            return_value=_make_research_report(),
        ):
            evidence_service = EvidenceService()
            result = SetupResearchService(evidence_service=evidence_service).research_setup(
                symbol="AMPX",
                setup_type="intraday_breakout",
                trade_date=date(2026, 3, 5),
            )
            markdown = build_setup_research_markdown(result, evidence_service)

        assert result.claims
        assert result.evidence_ids
        assert evidence_service.get(result.evidence_ids[0]) is not None
        assert result.verifier is not None and result.verifier.passed is False
        assert result.verifier.sample_size_downgraded_claim_ids
        assert result.recommendations == []
        assert "## Findings" in markdown
        assert "## Claims" in markdown
        assert "## Recommendations" in markdown
        assert "## Evidence References" in markdown
        assert "## Verifier Summary" in markdown


def _make_saved_review_dict(result_id: str, overall_verdict: str = "good_trade") -> dict[str, object]:
    return {
        "result_id": result_id,
        "workflow": "trade_review",
        "title": "Trade Review: AMPX",
        "subject": "AMPX 2026-03-05",
        "as_of": "2026-03-05T10:00:00",
        "symbol": "AMPX",
        "trading_date": "2026-03-05",
        "log_source": "prod",
        "boundary_time": "2026-03-05T10:00:00",
        "metadata": {
            "pattern": "strong_uptrending",
            "overall_verdict": overall_verdict,
            "quality_tier": "good",
            "outcome": "tp_filled",
            "total_iterations": 1,
        },
        "findings": [],
        "claims": [
            {
                "claim_id": f"claim_selection_{result_id}",
                "statement": "The trade should have been taken based on strong signal score.",
                "status": "observation",
                "evidence_ids": [f"ev_{result_id}_sel"],
                "confidence": 0.8,
                "sample_size": 1,
            },
            {
                "claim_id": f"claim_entry_{result_id}",
                "statement": "Entry was suboptimal — waited too long.",
                "status": "observation",
                "evidence_ids": [f"ev_{result_id}_ent"],
                "confidence": 0.7,
                "sample_size": 1,
            },
            {
                "claim_id": f"claim_exit_{result_id}",
                "statement": "Evidence favors `trailing_stop` exit policy.",
                "status": "observation",
                "evidence_ids": [f"ev_{result_id}_ext"],
                "confidence": 0.75,
                "sample_size": 1,
            },
        ],
        "recommendations": [],
        "evidence_ids": [f"ev_{result_id}_sel", f"ev_{result_id}_ent", f"ev_{result_id}_ext"],
        "limitations": [],
    }


def test_aggregate_review_golden_flow(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review_dict("r1"),
        _make_saved_review_dict("r2", overall_verdict="acceptable"),
        _make_saved_review_dict("r3"),
    ]
    filenames = [f"trade_review_{r['result_id']}.json" for r in reviews]

    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
        with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=filenames):
            with patch(
                "src.trading_research.aggregate_review_service.load_saved_result",
                side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname))),
            ):
                evidence_service = EvidenceService()
                service = AggregateReviewService(evidence_service=evidence_service)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))
                markdown = build_aggregate_review_markdown(result, evidence_service)

    assert result.trade_count == 3
    assert result.contributing_result_ids == ["r1", "r2", "r3"]
    assert result.grouping_key == "strong_uptrending"
    assert result.claims
    assert result.evidence_ids

    supported_claims = [c for c in result.claims if c.status == ClaimStatus.SUPPORTED]
    assert supported_claims

    assert result.recommendations
    assert result.verifier is not None

    assert "## Cohort Summary" in markdown
    assert "## Findings" in markdown
    assert "## Claims" in markdown
    assert "## Recommendations" in markdown
    assert "## Evidence References" in markdown
    assert "## Verifier Summary" in markdown
