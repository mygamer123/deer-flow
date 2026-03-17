from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.aggregate_review_service import AggregatedTradeReviewRequest, AggregateReviewService
from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import ClaimStatus
from src.trading_research.verifier_service import MIN_RECOMMENDATION_SAMPLE_SIZE, MIN_SUPPORTED_CLAIM_SAMPLE_SIZE


def _make_saved_review(
    *,
    result_id: str,
    symbol: str = "AMPX",
    trading_date: str = "2026-03-05",
    pattern: str = "strong_uptrending",
    overall_verdict: str = "good_trade",
    quality_tier: str = "good",
    outcome: str = "tp_filled",
    log_source: str = "prod",
    boundary_time: str | None = None,
    claims: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if claims is None:
        claims = [
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
        ]
    return {
        "result_id": result_id,
        "workflow": "trade_review",
        "title": f"Trade Review: {symbol}",
        "subject": f"{symbol} {trading_date}",
        "as_of": "2026-03-05T10:00:00",
        "symbol": symbol,
        "trading_date": trading_date,
        "log_source": log_source,
        "boundary_time": boundary_time or "2026-03-05T10:00:00",
        "metadata": {
            "pattern": pattern,
            "overall_verdict": overall_verdict,
            "quality_tier": quality_tier,
            "outcome": outcome,
            "total_iterations": 1,
        },
        "findings": [],
        "claims": claims,
        "recommendations": [],
        "evidence_ids": [f"ev_{result_id}_sel", f"ev_{result_id}_ent", f"ev_{result_id}_ext"],
        "limitations": [],
    }


def _populate_store(tmp_path: Path, reviews: list[dict[str, object]]) -> None:
    for review in reviews:
        filename = f"trade_review_{review['result_id']}.json"
        with open(tmp_path / filename, "w", encoding="utf-8") as f:
            json.dump(review, f)


def _make_service(evidence_dir: Path) -> AggregateReviewService:
    evidence_service = EvidenceService(base_dir=evidence_dir)
    return AggregateReviewService(evidence_service=evidence_service)


# ---------------------------------------------------------------------------
# A. Aggregation core
# ---------------------------------------------------------------------------


def test_deterministic_aggregation_with_three_trades(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    evidence_dir = tmp_path / "evidence"

    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2", overall_verdict="acceptable"),
        _make_saved_review(result_id="r3", overall_verdict="bad_trade"),
    ]
    _populate_store(store_dir, reviews)

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.trade_count == 3
    assert len(result.contributing_result_ids) == 3
    assert result.grouping_key == "strong_uptrending"
    assert result.workflow.value == "aggregate_trade_review"
    assert result.claims


def test_sample_size_equals_distinct_trade_count(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2"),
        _make_saved_review(result_id="r3"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    for claim in result.claims:
        assert claim.sample_size is not None
        assert claim.sample_size <= 3


def test_dedup_by_result_id(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=["trade_review_r1.json", "trade_review_r1_dup.json", "trade_review_r2.json"]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(reviews[["trade_review_r1.json", "trade_review_r1_dup.json", "trade_review_r2.json"].index(fname)]))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.trade_count == 2
    assert len(result.contributing_result_ids) == 2


def test_empty_input_produces_empty_result(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[]):
        with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
            service = _make_service(evidence_dir)
            result = service.aggregate(AggregatedTradeReviewRequest(pattern="nonexistent"))

    assert result.trade_count == 0
    assert result.contributing_result_ids == []
    assert result.limitations
    assert result.claims == []
    assert result.recommendations == []


# ---------------------------------------------------------------------------
# B. Recommendation gating
# ---------------------------------------------------------------------------


def test_three_trades_can_produce_recommendations(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2"),
        _make_saved_review(result_id="r3"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.trade_count >= MIN_RECOMMENDATION_SAMPLE_SIZE
    supported_claims = [c for c in result.claims if c.status == ClaimStatus.SUPPORTED]
    assert supported_claims
    assert result.recommendations


def test_two_trades_produce_supported_claims_but_no_recommendations(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.trade_count == 2
    assert result.trade_count >= MIN_SUPPORTED_CLAIM_SAMPLE_SIZE
    assert result.trade_count < MIN_RECOMMENDATION_SAMPLE_SIZE

    assert result.verifier is not None
    assert result.recommendations == []
    assert result.verifier.dropped_recommendation_ids


def test_one_trade_downgrades_all_claims(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=["trade_review_r1.json"]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", return_value=json.loads(json.dumps(reviews[0]))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.trade_count == 1
    assert result.verifier is not None
    assert result.recommendations == []
    assert result.verifier.sample_size_downgraded_claim_ids


# ---------------------------------------------------------------------------
# C. Filtering
# ---------------------------------------------------------------------------


def test_symbol_filter(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1", symbol="AMPX"),
        _make_saved_review(result_id="r2", symbol="TSLA"),
        _make_saved_review(result_id="r3", symbol="AMPX"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(symbol="AMPX", pattern="strong_uptrending"))

    assert result.trade_count == 2
    assert all(rid in ["r1", "r3"] for rid in result.contributing_result_ids)


def test_max_trades_cap(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [_make_saved_review(result_id=f"r{i}") for i in range(5)]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending", max_trades=3))

    assert result.trade_count == 3


def test_explicit_result_ids(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1"),
        _make_saved_review(result_id="r2"),
        _make_saved_review(result_id="r3"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(trade_result_ids=["r1", "r3"]))

    assert result.trade_count == 2
    assert set(result.contributing_result_ids) == {"r1", "r3"}


# ---------------------------------------------------------------------------
# D. Cohort stats
# ---------------------------------------------------------------------------


def test_cohort_stats_contain_distributions(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1", overall_verdict="good_trade"),
        _make_saved_review(result_id="r2", overall_verdict="acceptable"),
        _make_saved_review(result_id="r3", overall_verdict="bad_trade"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.cohort_stats
    assert result.cohort_stats["trade_count"] == 3
    verdict_dist = result.cohort_stats["verdict_distribution"]
    assert isinstance(verdict_dist, dict)
    assert verdict_dist.get("good_trade") == 1
    assert verdict_dist.get("acceptable") == 1
    assert verdict_dist.get("bad_trade") == 1


# ---------------------------------------------------------------------------
# E. Boundary time
# ---------------------------------------------------------------------------


def test_aggregate_boundary_is_latest_contributing(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1", boundary_time="2026-03-05T09:00:00"),
        _make_saved_review(result_id="r2", boundary_time="2026-03-05T11:00:00"),
        _make_saved_review(result_id="r3", boundary_time="2026-03-05T10:00:00"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(AggregatedTradeReviewRequest(pattern="strong_uptrending"))

    assert result.boundary_time == datetime(2026, 3, 5, 11, 0, 0)


# ---------------------------------------------------------------------------
# F. Grouping modes
# ---------------------------------------------------------------------------


def test_by_symbol_pattern_grouping_key(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    reviews = [
        _make_saved_review(result_id="r1", symbol="AMPX"),
        _make_saved_review(result_id="r2", symbol="AMPX"),
        _make_saved_review(result_id="r3", symbol="AMPX"),
    ]

    with patch("src.trading_research.aggregate_review_service.list_saved_results", return_value=[f"trade_review_{r['result_id']}.json" for r in reviews]):
        with patch("src.trading_research.aggregate_review_service.load_saved_result", side_effect=lambda fname: json.loads(json.dumps(next(r for r in reviews if f"trade_review_{r['result_id']}.json" == fname)))):
            with patch("src.trading_research.evidence_service._EVIDENCE_DIR", evidence_dir):
                service = _make_service(evidence_dir)
                result = service.aggregate(
                    AggregatedTradeReviewRequest(
                        symbol="AMPX",
                        pattern="strong_uptrending",
                        aggregation_mode="by_symbol_pattern",
                    )
                )

    assert result.grouping_key == "AMPX:strong_uptrending"
