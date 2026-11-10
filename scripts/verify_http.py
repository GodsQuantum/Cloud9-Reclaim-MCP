#!/usr/bin/env python3
"""Synthetic MCP HTTP handshake, without user credentials or external network."""
import asyncio
import multiprocessing as mp

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from reclaim_mcp.server import mcp


def serve():
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000, path="/mcp", show_banner=False)


async def check():
    for attempt in range(35):
        try:
            async with streamablehttp_client("http://127.0.0.1:8000/mcp", timeout=3) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    actual = sorted(t.name for t in tools)
                    assert len(actual) == 72, f"MCP HTTP exported {len(actual)} tools instead of 72"
                    assert "create_one_on_one" in actual
                    assert "update_schedule_policy" in actual
                    print("RECLAIM_HTTP_MCP_72_TOOLS_PASS", flush=True)
                    return
        except Exception:
            if attempt == 34:
                raise
            await asyncio.sleep(0.2)


if __name__ == "__main__":
    worker = mp.Process(target=serve, daemon=True)
    worker.start()
    try:
        asyncio.run(check())
    finally:
        worker.terminate()
        worker.join(timeout=5)
