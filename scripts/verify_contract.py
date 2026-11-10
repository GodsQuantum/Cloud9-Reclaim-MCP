#!/usr/bin/env python3
"""Fail closed when any exported tool name or input schema regresses."""
import asyncio
import json
import os
from reclaim_mcp.server import mcp

async def main():
    expected_path = os.getenv("MCP_TOOL_CONTRACT", "/contract-tools.json")
    with open(expected_path, encoding="utf-8") as f:
        expected = json.load(f)
    tools = await mcp.get_tools()
    actual = {name: tool.parameters for name, tool in sorted(tools.items())}
    lost = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(name for name in set(actual) & set(expected) if actual[name] != expected[name])
    if lost or extra or changed:
        raise SystemExit(f"CONTRACT FAIL lost={lost}, extra={extra}, schema_changed={changed}")
    assert len(actual) == 72, f"expected 72 tools, got {len(actual)}"
    print("RECLAIM_72_TOOLS_AND_SCHEMAS_PASS")

if __name__ == "__main__":
    asyncio.run(main())
