# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""JSON persistence for research reports."""

from __future__ import annotations

import json
import logging
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .models import ResearchReport

logger = logging.getLogger(__name__)

_STORE_DIR = Path.home() / ".deer-flow" / "research" / "reports"


class _ResearchEncoder(json.JSONEncoder):
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


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert topic text to a filesystem-safe slug."""
    slug = text.lower().replace(" ", "_")
    safe = "".join(c for c in slug if c.isalnum() or c == "_")
    return safe[:max_len]


def save_research_report(report: ResearchReport) -> Path:
    """Serialize a ResearchReport to JSON on disk. Returns the file path."""
    store = _ensure_store_dir()
    timestamp = report.created_at.strftime("%Y%m%d_%H%M%S")
    slug = _slugify(report.topic)
    filename = f"research_{slug}_{timestamp}.json"
    path = store / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, cls=_ResearchEncoder, indent=2, ensure_ascii=False)
    logger.info("Saved research report to %s", path)
    return path


def list_saved_reports() -> list[str]:
    """Return filenames of all saved research reports."""
    if not _STORE_DIR.exists():
        return []
    return sorted(p.name for p in _STORE_DIR.iterdir() if p.suffix == ".json")
