from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.trading_research.evidence_service import EvidenceService
from src.trading_research.models import EvidenceItem, EvidenceSourceType


def test_evidence_service_registers_and_loads_stable_evidence(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        service = EvidenceService()
        item = EvidenceItem(
            evidence_type="setup_source",
            title="Test source",
            content="Important snippet",
            source_type=EvidenceSourceType.WEB_SOURCE,
            source_ref="https://example.com",
            provenance={"symbol": "AMPX", "setup_type": "intraday_breakout"},
            as_of=datetime(2026, 3, 5, 10, 0),
        )

        first = service.register(item)
        second = service.register(item)
        loaded = service.get(first.evidence_id)

        assert first.evidence_id == second.evidence_id
        assert loaded is not None
        assert loaded.source_ref == "https://example.com"


def test_evidence_service_hash_ignores_as_of_when_other_provenance_matches(tmp_path: Path) -> None:
    with patch("src.trading_research.evidence_service._EVIDENCE_DIR", tmp_path):
        service = EvidenceService()
        first = service.register(
            EvidenceItem(
                evidence_type="setup_source",
                title="Source",
                content="Snippet",
                source_type=EvidenceSourceType.WEB_SOURCE,
                source_ref="https://example.com",
                provenance={"symbol": "AMPX", "setup_type": "intraday_breakout"},
                as_of=datetime(2026, 3, 5, 10, 0),
            )
        )
        second = service.register(
            EvidenceItem(
                evidence_type="setup_source",
                title="Source",
                content="Snippet",
                source_type=EvidenceSourceType.WEB_SOURCE,
                source_ref="https://example.com",
                provenance={"symbol": "AMPX", "setup_type": "intraday_breakout"},
                as_of=datetime(2026, 3, 6, 10, 0),
            )
        )

        assert first.evidence_id == second.evidence_id
