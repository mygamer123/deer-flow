from __future__ import annotations

from pathlib import Path

from src.config import get_app_config

DEFAULT_LOG_SOURCE = "prod"
DEFAULT_LOG_DIR = Path.home() / "Documents" / "prod" / "fms" / "logs"


def _get_finance_config() -> dict[str, object]:
    extra = get_app_config().model_extra
    if not isinstance(extra, dict):
        return {}
    finance_config = extra.get("finance")
    return finance_config if isinstance(finance_config, dict) else {}


def has_configured_log_sources() -> bool:
    finance_config = _get_finance_config()
    return "log_sources" in finance_config or "default_log_source" in finance_config


def get_default_log_source() -> str:
    finance_config = _get_finance_config()
    configured_default = finance_config.get("default_log_source")
    return configured_default if isinstance(configured_default, str) and configured_default else DEFAULT_LOG_SOURCE


def list_log_sources() -> list[str]:
    finance_config = _get_finance_config()
    configured_sources = finance_config.get("log_sources")
    if not isinstance(configured_sources, dict) or not configured_sources:
        return [DEFAULT_LOG_SOURCE]

    sources = {str(name) for name in configured_sources}
    return sorted(sources)


def get_log_source_path(log_source: str | None = None) -> Path:
    finance_config = _get_finance_config()
    source_name = log_source or get_default_log_source()
    configured_sources = finance_config.get("log_sources")

    if isinstance(configured_sources, dict) and configured_sources:
        if source_name not in configured_sources:
            available = ", ".join(list_log_sources())
            raise ValueError(f"Unknown finance log source '{source_name}'. Available sources: {available}.")
        configured_path = configured_sources.get(source_name)
        if isinstance(configured_path, str) and configured_path:
            return Path(configured_path).expanduser()
        raise ValueError(f"Finance log source '{source_name}' is configured without a valid path.")

    if source_name == DEFAULT_LOG_SOURCE:
        return DEFAULT_LOG_DIR

    available = ", ".join(list_log_sources())
    raise ValueError(f"Unknown finance log source '{source_name}'. Available sources: {available}.")
