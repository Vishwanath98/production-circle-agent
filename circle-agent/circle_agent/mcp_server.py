# agents/circle_agent.mcp_server.py
#
# MCP tool server (stdio transport) for the Circle MCP pass.
# Exposes crypto-payment tools as real out-of-process MCP tools, so the agent
# calls them over the protocol instead of as in-process functions — a genuine
# transport/process fault-injection boundary (tool discovery, selection, errors).
#
# Run standalone:  python circle_agent.mcp_server.py   (speaks MCP over stdio)
# Normally launched as a subprocess by circle_agent.mcp_core.

import string
from datetime import datetime

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer(
    'circle-payment-tools',
    version='2.0.0',
    instructions='Advisory validation and risk signals only. This server cannot execute payments.',
)

EVM_CHAINS = ("ethereum", "base", "polygon", "arbitrum")
SANCTIONED_ADDRESS = "0x" + "5" * 40


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=False))
def validate_address(address: str, chain: str = "") -> dict:
    """Validate a recipient wallet address and detect its chain."""
    addr = (address or "").strip()
    is_evm = addr.startswith("0x") and len(addr) == 42 and \
        all(c in "0123456789abcdefABCDEF" for c in addr[2:])
    is_solana = (32 <= len(addr) <= 44) and not addr.startswith("0x") and \
        all(c in string.ascii_letters + string.digits for c in addr)
    if chain in EVM_CHAINS:
        valid, detected = is_evm, chain
    elif chain == "solana":
        valid, detected = is_solana, "solana"
    elif is_evm:
        valid, detected = True, "base"
    elif is_solana:
        valid, detected = True, "solana"
    else:
        valid, detected = False, ""
    return {"valid": valid, "detected_chain": detected,
            "reason": "" if valid else "Unrecognized or malformed address"}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=False))
def sanctions_screen(address: str, amount_usdc: float = 0) -> dict:
    """Simulated OFAC/sanctions screening of a wallet address."""
    a = (address or "").lower()
    sanctioned = address == SANCTIONED_ADDRESS or any(
        k in a for k in ("sanction", "blocked", "ofac"))
    return {"sanctioned": sanctioned, "list": "OFAC-SDN" if sanctioned else None,
            "screened_at": datetime.now().isoformat()}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=False))
def chain_analytics(address: str, chain: str = "") -> dict:
    """Simulated on-chain risk analytics (mixer/darknet exposure scoring)."""
    a = (address or "").lower()
    # Deterministic-ish risk from address content for repeatable tests.
    high = any(k in a for k in ("mixer", "tumbler", "darknet")) or address.endswith("dead")
    risk = "high" if high else "low"
    score = 0.9 if high else 0.1
    return {"risk": risk, "risk_score": score,
            "exposures": ["mixer"] if high else [], "chain": chain}


if __name__ == "__main__":
    mcp.run()
