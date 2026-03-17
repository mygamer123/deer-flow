from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from src.config.paths import get_paths

from .models import EvidenceItem, EvidenceSourceType

_EVIDENCE_DIR = get_paths().base_dir / "trading-research" / "evidence"


class EvidenceService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir: Path = base_dir or _EVIDENCE_DIR

    def register(self, item: EvidenceItem) -> EvidenceItem:
        evidence_id = item.evidence_id or self._build_evidence_id(item)
        stored_item = EvidenceItem(
            evidence_id=evidence_id,
            evidence_type=item.evidence_type,
            title=item.title,
            content=item.content,
            source_type=item.source_type,
            source_ref=item.source_ref,
            provenance=_normalize_mapping(item.provenance),
            as_of=item.as_of,
            confidence=item.confidence,
            sample_size=item.sample_size,
            limitations=list(item.limitations),
            metadata=dict(item.metadata),
            schema_version=item.schema_version,
            observed_at=item.observed_at,
            effective_start=item.effective_start,
            effective_end=item.effective_end,
        )

        self._ensure_dir()
        path = self._path_for(evidence_id)
        if not path.exists():
            with open(path, "w", encoding="utf-8") as file_obj:
                json.dump(asdict(stored_item), file_obj, default=_json_default, indent=2, ensure_ascii=False)
        return stored_item

    def register_many(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        return [self.register(item) for item in items]

    def get(self, evidence_id: str) -> EvidenceItem | None:
        path = self._path_for(evidence_id)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        return EvidenceItem(
            evidence_id=data["evidence_id"],
            evidence_type=data.get("evidence_type", "generic_evidence"),
            title=data.get("title", ""),
            content=data.get("content", ""),
            source_type=EvidenceSourceType(data.get("source_type", EvidenceSourceType.REVIEW_SUMMARY.value)),
            source_ref=data.get("source_ref", ""),
            provenance=dict(data.get("provenance", {})),
            as_of=_parse_datetime(data.get("as_of")),
            confidence=data.get("confidence"),
            sample_size=data.get("sample_size"),
            limitations=list(data.get("limitations", [])),
            metadata=dict(data.get("metadata", {})),
            schema_version=data.get("schema_version", "v1"),
            observed_at=_parse_datetime(data.get("observed_at")),
            effective_start=_parse_datetime(data.get("effective_start")),
            effective_end=_parse_datetime(data.get("effective_end")),
        )

    def get_many(self, evidence_ids: list[str]) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for evidence_id in evidence_ids:
            item = self.get(evidence_id)
            if item is not None:
                items.append(item)
        return items

    def _build_evidence_id(self, item: EvidenceItem) -> str:
        payload = {
            "schema_version": item.schema_version,
            "evidence_type": item.evidence_type,
            "source_type": item.source_type.value,
            "source_ref": _normalize_text(item.source_ref),
            "content": _normalize_text(item.content),
            "provenance": _normalize_mapping(item.provenance),
        }
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")).hexdigest()
        return f"ev_{digest[:12]}"

    def _ensure_dir(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, evidence_id: str) -> Path:
        return self._base_dir / f"{evidence_id}.json"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value)


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _normalize_mapping(value: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key in sorted(value):
        item = value[key]
        if isinstance(item, str):
            normalized[key] = _normalize_text(item)
        elif isinstance(item, dict):
            normalized[key] = _normalize_mapping({str(child_key): child_value for child_key, child_value in item.items()})
        elif isinstance(item, list):
            normalized[key] = [_normalize_text(element) if isinstance(element, str) else element for element in item]
        else:
            normalized[key] = item
    return normalized
