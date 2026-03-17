# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Data models for topic research and claim verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VerificationStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    MIXED = "mixed"


class SourceType(StrEnum):
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    """A single piece of evidence retrieved from a source."""

    snippet: str
    source_url: str = ""
    source_title: str = ""
    source_type: SourceType = SourceType.WEB_SEARCH
    fetched_at: datetime = field(default_factory=datetime.now)
    relevance: float = 0.0  # 0.0-1.0, how relevant to the claim/topic


@dataclass
class Claim:
    """A factual claim extracted from research or submitted for verification."""

    statement: str
    status: VerificationStatus = VerificationStatus.INSUFFICIENT
    supporting_evidence: list[Evidence] = field(default_factory=list)
    contradicting_evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0


@dataclass
class ResearchReport:
    """Output of a topic research session."""

    topic: str
    summary: str = ""
    claims: list[Claim] = field(default_factory=list)
    sources: list[Evidence] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    search_queries: list[str] = field(default_factory=list)
    pages_fetched: int = 0
