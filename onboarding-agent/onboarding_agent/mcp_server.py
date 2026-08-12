# agents/onboarding_agent.mcp_server.py
#
# MCP tool server (stdio transport) for the onboarding MCP pass.
# Exposes the onboarding tools as real out-of-process MCP tools, so the agent
# calls them over the protocol instead of as in-process functions. This is the
# new fault-injection boundary the MCP pass adds: tool discovery, tool
# selection, and a genuine process/transport edge.
#
# Run standalone:  python onboarding_agent.mcp_server.py   (speaks MCP over stdio)
# Normally it is launched as a subprocess by onboarding_agent.mcp_core.

from datetime import datetime

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer('onboarding-tools', version='2.0.0',
                instructions='Advisory KYB signals only. This server cannot approve or provision accounts.')
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=READ_ONLY)
def verify_identity(business_name: str, business_type: str, email: str,
                    rigor: str = "standard") -> dict:
    """Simulated KYB identity verification. rigor: light|standard|enhanced."""
    score = 0.85
    if any(kw in business_name.lower() for kw in ("test", "fake", "demo", "temp")):
        score = 0.3
    return {
        "verified": score > 0.7,
        "score": round(score, 2),
        "rigor": rigor,
        "checks_passed": ["email_format", "business_name_length", "domain_check"],
        "checks_failed": [] if score > 0.7 else ["business_registry"],
        "timestamp": datetime.now().isoformat(),
    }


@mcp.tool(annotations=READ_ONLY)
def sanctions_screen(business_name: str, email: str) -> dict:
    """Simulated OFAC/sanctions screening."""
    flagged = any(k in business_name.lower() for k in ("sanction", "blocked", "ofac", "embargo"))
    return {
        "sanctioned": flagged,
        "list": "OFAC-SDN" if flagged else None,
        "screened_at": datetime.now().isoformat(),
    }


@mcp.tool(annotations=READ_ONLY)
def business_registry_lookup(business_name: str, business_type: str) -> dict:
    """Simulated business-registry existence check."""
    registered = "fake" not in business_name.lower() and "unregistered" not in business_name.lower()
    return {
        "registered": registered,
        "registry_id": "REG-DETERMINISTIC" if registered else None,
        "entity_type": business_type,
    }


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
