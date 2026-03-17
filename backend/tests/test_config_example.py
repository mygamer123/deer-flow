from __future__ import annotations

from pathlib import Path

import yaml


def test_config_example_registers_public_research_tools() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config.example.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    tool_groups = {group["name"] for group in config["tool_groups"]}
    assert "research" in tool_groups

    tools_by_name = {tool["name"]: tool for tool in config["tools"]}
    assert tools_by_name["research_topic"]["group"] == "research"
    assert tools_by_name["research_topic"]["use"] == "src.community.research.tools:research_topic_tool"
    assert tools_by_name["verify_claim"]["group"] == "research"
    assert tools_by_name["verify_claim"]["use"] == "src.community.research.tools:verify_claim_tool"
    assert tools_by_name["list_research_reports"]["group"] == "research"
    assert tools_by_name["list_research_reports"]["use"] == "src.community.research.tools:list_research_reports_tool"
