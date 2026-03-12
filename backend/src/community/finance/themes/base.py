# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Abstract base for review themes and the global theme registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import AnalyticalLens, ParsedTrade, QuantitativeFindings, TradeReview


class ReviewTheme(ABC):
    """A theme defines *which* review modules run and in *what order*."""

    name: str
    description: str

    # --------------- configuration ---------------

    @abstractmethod
    def get_lenses(self) -> list[AnalyticalLens]:
        """Return the ordered list of analytical lenses for the iterative loop."""

    @abstractmethod
    def get_review_modules(self) -> list[str]:
        """Return module names in execution order (e.g. ['selection', 'entry', 'exit', 'failure'])."""

    # --------------- lifecycle hooks ---------------

    def should_review_trade(self, trade: ParsedTrade) -> bool:
        """Pre-filter: return False to skip a trade entirely (e.g. short positions)."""
        return True

    def post_process(self, review: TradeReview) -> TradeReview:
        """Optional post-processing after all iterations complete."""
        return review

    # --------------- convergence ---------------

    @property
    def max_iterations(self) -> int:
        """Ceiling for the convergence loop."""
        return 20

    @property
    def convergence_threshold(self) -> float:
        """Cumulative confidence above which we can stop early."""
        return 0.85

    def should_converge(self, iteration: int, confidence: float, findings: dict[str, list[QuantitativeFindings]]) -> bool:
        """Custom convergence logic — default is confidence threshold or max iters."""
        if iteration >= self.max_iterations:
            return True
        return confidence >= self.convergence_threshold


class ThemeRegistry:
    """Global singleton registry for review themes."""

    _themes: dict[str, ReviewTheme] = {}

    @classmethod
    def register(cls, theme: ReviewTheme) -> None:
        cls._themes[theme.name] = theme

    @classmethod
    def get(cls, name: str) -> ReviewTheme | None:
        return cls._themes.get(name)

    @classmethod
    def get_or_raise(cls, name: str) -> ReviewTheme:
        theme = cls._themes.get(name)
        if theme is None:
            available = ", ".join(cls._themes.keys()) or "(none)"
            raise ValueError(f"Unknown theme '{name}'. Available: {available}")
        return theme

    @classmethod
    def list_themes(cls) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "max_iterations": t.max_iterations} for t in cls._themes.values()]
