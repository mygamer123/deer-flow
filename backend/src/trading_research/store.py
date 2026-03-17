from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from src.config.paths import get_paths

from .models import AggregatedReviewResult, ReviewResult, SetupResearchResult, StrategyChangeRecord, StrategyImprovementLoopResult, StructuredResult

_RESULTS_DIR = get_paths().base_dir / "trading-research" / "reports"


def save_result(result: StructuredResult) -> Path:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _resolve_unique_path(_RESULTS_DIR / _filename_for(result))
    payload = asdict(result) if is_dataclass(result) else result
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, default=_json_default, indent=2, ensure_ascii=False)
    return path


def save_strategy_improvement_result(result: StrategyImprovementLoopResult) -> Path:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = result.as_of.strftime("%Y%m%d_%H%M%S")
    path = _resolve_unique_path(_RESULTS_DIR / f"strategy_improvement_{timestamp}.json")
    payload = asdict(result)
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, default=_json_default, indent=2, ensure_ascii=False)
    return path


def list_saved_results() -> list[str]:
    if not _RESULTS_DIR.exists():
        return []
    return sorted(path.name for path in _RESULTS_DIR.iterdir() if path.suffix == ".json")


def load_saved_result(filename: str) -> dict[str, object] | None:
    path = _RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as file_obj:
        return json.load(file_obj)


def save_strategy_change_records(records: list[StrategyChangeRecord]) -> list[Path]:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for record in records:
        timestamp = record.created_at.strftime("%Y%m%d_%H%M%S")
        slug = _slugify(record.record_id)
        path = _resolve_unique_path(_RESULTS_DIR / f"strategy_change_{slug}_{timestamp}.json")
        payload = asdict(record)
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, default=_json_default, indent=2, ensure_ascii=False)
        paths.append(path)
    return paths


def list_strategy_change_records() -> list[str]:
    if not _RESULTS_DIR.exists():
        return []
    return sorted(path.name for path in _RESULTS_DIR.iterdir() if path.name.startswith("strategy_change_") and path.suffix == ".json")


def load_strategy_change_record(filename: str) -> dict[str, object] | None:
    path = _RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _filename_for(result: StructuredResult) -> str:
    timestamp = result.as_of.strftime("%Y%m%d_%H%M%S")
    if isinstance(result, ReviewResult):
        symbol = _slugify(result.symbol or result.subject)
        trading_date = result.trading_date.isoformat() if result.trading_date else "unknown-date"
        log_source = f"_{_slugify(result.log_source)}" if result.log_source else ""
        return f"trade_review_{symbol}_{trading_date}{log_source}_{timestamp}.json"
    if isinstance(result, AggregatedReviewResult):
        key = _slugify(result.grouping_key or result.subject)
        return f"aggregate_trade_review_{key}_{timestamp}.json"
    if isinstance(result, SetupResearchResult):
        topic = _slugify(result.topic or result.subject)
        return f"setup_research_{topic}_{timestamp}.json"
    return f"{result.workflow.value}_{_slugify(result.subject)}_{timestamp}.json"


def _slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value)
    compact = "_".join(part for part in slug.split("_") if part)
    return compact[:80] or "result"


def _resolve_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
