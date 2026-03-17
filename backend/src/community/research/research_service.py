# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from typing import Any

from tavily import TavilyClient
from tavily.errors import InvalidAPIKeyError, MissingAPIKeyError

from src.config import get_app_config
from src.community.tavily.tools import _format_tavily_error

from .models import Claim, Evidence, ResearchReport, SourceType, VerificationStatus

logger = logging.getLogger(__name__)

_MAX_SEARCH_RESULTS = 8
_MAX_FETCH_CHARS = 4096
_MAX_SEARCH_ROUNDS = 3


class TavilyAuthError(RuntimeError):
    pass


class ResearchService:
    def __init__(self, *, tavily_api_key: str | None = None):
        api_key = tavily_api_key
        if api_key is None:
            config = get_app_config().get_tool_config("web_search")
            if config and config.model_extra:
                api_key = config.model_extra.get("api_key")
        self._client = TavilyClient(api_key=api_key)

    def research_topic(self, topic: str, *, depth: int = 2) -> ResearchReport:
        report = ResearchReport(topic=topic)

        search_queries = self._generate_queries(topic, depth)
        report.search_queries = search_queries

        all_results: list[dict[str, Any]] = []
        for query in search_queries:
            results = self._search(query)
            all_results.extend(results)

        seen_urls: set[str] = set()
        unique_results: list[dict[str, Any]] = []
        for r in all_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(r)

        for r in unique_results:
            evidence = Evidence(
                snippet=r.get("content", "")[:500],
                source_url=r.get("url", ""),
                source_title=r.get("title", ""),
                source_type=SourceType.WEB_SEARCH,
            )
            report.sources.append(evidence)

        top_urls = [r.get("url", "") for r in unique_results[:depth] if r.get("url")]
        for url in top_urls:
            fetched = self._fetch(url)
            if fetched:
                report.pages_fetched += 1
                evidence = Evidence(
                    snippet=fetched[:500],
                    source_url=url,
                    source_title="",
                    source_type=SourceType.WEB_FETCH,
                )
                report.sources.append(evidence)

        report.claims = self._extract_claims(report.sources)
        report.summary = self._build_summary(report)

        return report

    def verify_claim(self, statement: str) -> Claim:
        claim = Claim(statement=statement)

        results = self._search(f"verify: {statement}")
        if not results:
            return claim

        statement_lower = statement.lower()
        for r in results:
            snippet = r.get("content", "")
            evidence = Evidence(
                snippet=snippet[:500],
                source_url=r.get("url", ""),
                source_title=r.get("title", ""),
                source_type=SourceType.WEB_SEARCH,
            )

            if self._snippet_contradicts(snippet, statement_lower):
                claim.contradicting_evidence.append(evidence)
            elif self._snippet_supports(snippet, statement_lower):
                claim.supporting_evidence.append(evidence)

        claim.status = self._determine_status(claim)
        claim.confidence = self._compute_confidence(claim)

        return claim

    def _generate_queries(self, topic: str, depth: int) -> list[str]:
        queries = [topic]
        if depth >= 2:
            queries.append(f"{topic} latest research findings")
        if depth >= 3:
            queries.append(f"{topic} criticism controversy debate")
        return queries[:_MAX_SEARCH_ROUNDS]

    def _search(self, query: str) -> list[dict[str, Any]]:
        try:
            res = self._client.search(query, max_results=_MAX_SEARCH_RESULTS)
            return res.get("results", [])
        except (MissingAPIKeyError, InvalidAPIKeyError) as error:
            logger.error("Tavily API key is missing or invalid")
            raise TavilyAuthError(_format_tavily_error(error)) from error
        except Exception:
            logger.exception("Tavily search failed for query: %s", query)
            return []

    def _fetch(self, url: str) -> str | None:
        try:
            res = self._client.extract([url])
            if res.get("results"):
                return res["results"][0].get("raw_content", "")[:_MAX_FETCH_CHARS]
            return None
        except (MissingAPIKeyError, InvalidAPIKeyError) as error:
            logger.error("Tavily API key is missing or invalid")
            raise TavilyAuthError(_format_tavily_error(error)) from error
        except Exception:
            logger.exception("Tavily fetch failed for URL: %s", url)
            return None

    def _extract_claims(self, sources: list[Evidence]) -> list[Claim]:
        claims: list[Claim] = []
        seen_snippets: set[str] = set()

        for source in sources:
            if not source.snippet or source.snippet in seen_snippets:
                continue
            seen_snippets.add(source.snippet)

            sentences = [s.strip() for s in source.snippet.replace("\n", ". ").split(". ") if len(s.strip()) > 30]

            for sentence in sentences[:3]:
                if not self._looks_like_claim(sentence):
                    continue
                claim = Claim(
                    statement=sentence,
                    supporting_evidence=[source],
                    status=VerificationStatus.INSUFFICIENT,
                )
                claims.append(claim)

        return claims[:10]

    def _looks_like_claim(self, sentence: str) -> bool:
        if len(sentence) < 20 or len(sentence) > 300:
            return False
        non_claim_starts = ("click", "subscribe", "sign up", "cookie", "privacy", "©", "all rights")
        return not sentence.lower().startswith(non_claim_starts)

    def _snippet_supports(self, snippet: str, statement_lower: str) -> bool:
        words = [w for w in statement_lower.split() if len(w) > 3]
        if not words:
            return False
        snippet_lower = snippet.lower()
        matching = sum(1 for w in words if w in snippet_lower)
        return matching / len(words) > 0.4

    def _snippet_contradicts(self, snippet: str, statement_lower: str) -> bool:
        contradiction_markers = ["however", "not true", "false", "debunked", "myth", "incorrect", "misleading", "contrary"]
        snippet_lower = snippet.lower()
        has_contradiction_marker = any(m in snippet_lower for m in contradiction_markers)
        if not has_contradiction_marker:
            return False
        words = [w for w in statement_lower.split() if len(w) > 3]
        if not words:
            return False
        matching = sum(1 for w in words if w in snippet_lower)
        return matching / len(words) > 0.3

    def _determine_status(self, claim: Claim) -> VerificationStatus:
        has_support = len(claim.supporting_evidence) > 0
        has_contradiction = len(claim.contradicting_evidence) > 0

        if has_support and has_contradiction:
            return VerificationStatus.MIXED
        if has_support:
            return VerificationStatus.SUPPORTED
        if has_contradiction:
            return VerificationStatus.CONTRADICTED
        return VerificationStatus.INSUFFICIENT

    def _compute_confidence(self, claim: Claim) -> float:
        total = len(claim.supporting_evidence) + len(claim.contradicting_evidence)
        if total == 0:
            return 0.0
        support_ratio = len(claim.supporting_evidence) / total
        volume_factor = min(total / 5.0, 1.0)
        return round(support_ratio * volume_factor, 2)

    def _build_summary(self, report: ResearchReport) -> str:
        parts = [f"Research on '{report.topic}' found {len(report.sources)} sources."]
        if report.claims:
            parts.append(f"Extracted {len(report.claims)} claims from the sources.")
        if report.pages_fetched:
            parts.append(f"Fetched and analyzed {report.pages_fetched} full pages.")
        return " ".join(parts)
