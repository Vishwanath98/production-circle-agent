# agents/mcp_client.py
#
# Sync bridge to an MCP stdio server. The MCP SDK is async; LangGraph nodes here
# are sync, so this runs a dedicated asyncio event loop on a background thread
# and opens ONE persistent client session (one server subprocess) for the whole
# process. Nodes call .call(tool, args) synchronously.

import asyncio
import json
import sys
import threading
from contextlib import AsyncExitStack
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def stack_close(stack):
    if stack is not None:
        await stack.aclose()



class MCPToolClient:
    def __init__(self, server_script=None, timeout=30.0, command=None, args=None,
                 cwd=None, env=None):
        self._timeout = timeout
        if server_script and not command:
            command = sys.executable
            args = [server_script]
        if not command:
            raise ValueError('an MCP command is required')
        self._params = StdioServerParameters(command=command, args=list(args or []), cwd=cwd, env=env)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._submit(self._connect()).result(timeout=timeout)

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _connect(self):
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(self._params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    def list_tools(self) -> list[str]:
        res = self._submit(self._session.list_tools()).result(timeout=self._timeout)
        return [t.name for t in res.tools]

    def describe_tools(self):
        result = self._submit(self._session.list_tools()).result(timeout=self._timeout)
        return list(result.tools)

    def call(self, tool: str, args: dict) -> dict:
        res = self._submit(self._session.call_tool(tool, args)).result(timeout=self._timeout)
        if getattr(res, 'is_error', False):
            texts = [getattr(block, 'text', '') for block in res.content]
            raise RuntimeError('MCP tool %s failed: %s' % (tool, ' '.join(texts)))
        # Prefer structured output; fall back to parsing the text content block.
        out: dict = {}
        structured = getattr(res, "structuredContent", None)
        if structured:
            out = structured.get("result", structured)
        elif res.content:
            block = res.content[0]
            text = getattr(block, "text", None)
            if text:
                try:
                    out = json.loads(text)
                except json.JSONDecodeError:
                    out = {"raw": text}
        return out

    def close(self):
        try:
            self._submit(stack_close(self._stack)).result(timeout=self._timeout)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
