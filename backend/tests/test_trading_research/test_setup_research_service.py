from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.community.research.models import Claim as RawClaim
from src.community.research.models import Evidence as RawEvidence
from src.community.research.models import ResearchReport, SourceType, VerificationStatus
from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import SetupType
from src.trading_research.setup_research_service import SetupResearchService


def _make_research_report() -> ResearchReport:
    source = RawEvidence(
        snippet="Analysts noted a momentum continuation setup in EV names after strong relative volume.",
        source_url="https://example.com/research",
        source_title="Momentum note",
        source_type=SourceType.WEB_SEARCH,
        fetched_at=datetime(2026, 3, 5, 12, 0),
        relevance=0.7,
    )
    claim = RawClaim(
        statement="EV momentum setups showed strong relative volume during the session.",
        status=VerificationStatus.INSUFFICIENT,
        supporting_evidence=[source],
        confidence=0.4,
    )
    return ResearchReport(
        topic="EV momentum setup",
        summary="Research found several momentum-oriented source excerpts.",
        claims=[claim],
        sources=[source],
        created_at=datetime(2026, 3, 5, 12, 0),
        search_queries=["EV momentum setup"],
        pages_fetched=1,
    )


def test_setup_research_service_builds_structured_verified_result(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        with patch(
            "src.trading_research.setup_research_service.ResearchService.research_topic",
            return_value=_make_research_report(),
        ):
            service = SetupResearchService(evidence_service=EvidenceService())
            result = service.research_setup(symbol="AMPX", setup_type="intraday_breakout")

        assert result.workflow.value == "setup_research"
        assert result.symbol == "AMPX"
        assert result.setup_type == SetupType.INTRADAY_BREAKOUT
        assert result.findings
        assert result.claims[0].status.value == "observation"
        assert result.evidence_ids
        assert result.verifier is not None
        assert result.verifier.passed is False
        assert len(result.verifier.sample_size_downgraded_claim_ids) == len(result.claims)
        assert result.recommendations == []
