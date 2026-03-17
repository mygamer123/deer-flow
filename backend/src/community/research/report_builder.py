# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

from .models import Claim, ResearchReport, VerificationStatus


def build_research_report(report: ResearchReport) -> str:
    lines: list[str] = []
    lines.append(f"# Research Report: {report.topic}")
    lines.append("")

    if report.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(report.summary)
        lines.append("")

    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Sources consulted | {len(report.sources)} |")
    lines.append(f"| Claims extracted | {len(report.claims)} |")
    lines.append(f"| Pages fetched | {report.pages_fetched} |")
    lines.append(f"| Search queries | {len(report.search_queries)} |")
    lines.append("")

    if report.search_queries:
        lines.append("### Queries Used")
        lines.append("")
        for q in report.search_queries:
            lines.append(f"- `{q}`")
        lines.append("")

    if report.claims:
        lines.append("## Claims")
        lines.append("")
        for i, claim in enumerate(report.claims, 1):
            lines.append(f"### Claim {i}")
            lines.append("")
            lines.append(_build_claim_section(claim))
            lines.append("")

    if report.sources:
        lines.append("## Sources")
        lines.append("")
        for i, ev in enumerate(report.sources, 1):
            title = ev.source_title or ev.source_url or "(untitled)"
            url_part = f" — {ev.source_url}" if ev.source_url else ""
            lines.append(f"{i}. **{title}**{url_part}")
        lines.append("")

    return "\n".join(lines)


def build_claim_report(claim: Claim) -> str:
    lines: list[str] = []
    lines.append(f"# Claim Verification: {claim.statement[:80]}")
    lines.append("")
    lines.append(_build_claim_section(claim))
    return "\n".join(lines)


def _build_claim_section(claim: Claim) -> str:
    lines: list[str] = []
    status_emoji = _status_label(claim.status)
    lines.append(f"**{claim.statement}**")
    lines.append("")
    lines.append(f"Status: **{status_emoji}** | Confidence: {claim.confidence:.0%}")
    lines.append("")

    if claim.supporting_evidence:
        lines.append("**Supporting evidence:**")
        for ev in claim.supporting_evidence:
            source = ev.source_title or ev.source_url or "unknown"
            lines.append(f"- [{source}]({ev.source_url}): {ev.snippet[:200]}")
        lines.append("")

    if claim.contradicting_evidence:
        lines.append("**Contradicting evidence:**")
        for ev in claim.contradicting_evidence:
            source = ev.source_title or ev.source_url or "unknown"
            lines.append(f"- [{source}]({ev.source_url}): {ev.snippet[:200]}")
        lines.append("")

    return "\n".join(lines)


def _status_label(status: VerificationStatus) -> str:
    labels = {
        VerificationStatus.SUPPORTED: "Supported",
        VerificationStatus.CONTRADICTED: "Contradicted",
        VerificationStatus.INSUFFICIENT: "Insufficient Evidence",
        VerificationStatus.MIXED: "Mixed Evidence",
    }
    return labels.get(status, status.value)
