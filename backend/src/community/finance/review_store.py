# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""JSON persistence for trade and day reviews."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .models import DayReview, TradeReview

logger = logging.getLogger(__name__)

_STORE_DIR = Path.home() / ".deer-flow" / "finance" / "reviews"


class _ReviewEncoder(json.JSONEncoder):
    """Handles dataclasses, enums, dates, and datetimes."""

    def default(self, o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return self._dataclass_to_dict(o)
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        return super().default(o)

    def _dataclass_to_dict(self, obj: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in fields(obj):
            val = getattr(obj, f.name)
            if is_dataclass(val) and not isinstance(val, type):
                result[f.name] = self._dataclass_to_dict(val)
            elif isinstance(val, list):
                result[f.name] = [self._convert(item) for item in val]
            elif isinstance(val, dict):
                result[f.name] = {k: self._convert(v) for k, v in val.items()}
            elif isinstance(val, Enum):
                result[f.name] = val.value
            elif isinstance(val, (datetime, date)):
                result[f.name] = val.isoformat()
            else:
                result[f.name] = val
        return result

    def _convert(self, val: Any) -> Any:
        if is_dataclass(val) and not isinstance(val, type):
            return self._dataclass_to_dict(val)
        if isinstance(val, Enum):
            return val.value
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if isinstance(val, list):
            return [self._convert(item) for item in val]
        if isinstance(val, dict):
            return {k: self._convert(v) for k, v in val.items()}
        return val


def _ensure_store_dir() -> Path:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    return _STORE_DIR


def _review_filename(prefix: str, *, trading_date: date, log_source: str | None = None, symbol: str | None = None) -> str:
    source_suffix = f"_{log_source}" if log_source else ""
    symbol_prefix = f"{symbol}_" if symbol else ""
    return f"{prefix}_{symbol_prefix}{trading_date.isoformat()}{source_suffix}.json"


def save_day_review(review: DayReview, *, log_source: str | None = None) -> Path:
    """Serialize a DayReview to JSON on disk.  Returns the file path."""
    store = _ensure_store_dir()
    filename = _review_filename("day_review", trading_date=review.trading_date, log_source=log_source)
    path = store / filename
    data = _ReviewEncoder().default(review) if is_dataclass(review) else asdict(review)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=_ReviewEncoder, indent=2, ensure_ascii=False)
    logger.info("Saved day review to %s", path)
    return path


def load_day_review_json(
    trading_date: date,
    *,
    log_source: str | None = None,
) -> dict[str, Any] | None:
    """Load a previously saved day review as a raw dict (no deserialization into models)."""
    path = _STORE_DIR / _review_filename(
        "day_review",
        trading_date=trading_date,
        log_source=log_source,
    )
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_trade_review(review: TradeReview, *, log_source: str | None = None) -> Path:
    """Serialize a single TradeReview to JSON on disk."""
    store = _ensure_store_dir()
    symbol = review.trade.symbol
    filename = _review_filename(
        "trade_review",
        symbol=symbol,
        trading_date=review.trade.trading_date,
        log_source=log_source,
    )
    path = store / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(review, f, cls=_ReviewEncoder, indent=2, ensure_ascii=False)
    logger.info("Saved trade review to %s", path)
    return path


def load_trade_review_json(
    symbol: str,
    trading_date: date,
    *,
    log_source: str | None = None,
) -> dict[str, Any] | None:
    """Load a previously saved trade review as a raw dict."""
    path = _STORE_DIR / _review_filename(
        "trade_review",
        symbol=symbol,
        trading_date=trading_date,
        log_source=log_source,
    )
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_saved_reviews() -> list[str]:
    """Return filenames of all saved reviews."""
    if not _STORE_DIR.exists():
        return []
    return sorted(p.name for p in _STORE_DIR.iterdir() if p.suffix == ".json")
