# agents/mock_llm.py
#
# Deterministic, offline stand-in for ChatAnthropic. Exposes .invoke(messages)
# returning an object with .content, so it drops into any agent here via the
# `llm_override` argument (or by patching the module-level `llm`).
#
# Purpose: exercise full graph paths with no API cost and no live model — handy
# for the test/eval framework and for local path-coverage checks.

import json


class _Resp:
    def __init__(self, content: str):
        self.content = content


class MockLLM:
    """Routes on the system prompt to return plausible canned completions."""

    def invoke(self, messages):
        system = messages[0].content if messages else ""
        human = messages[-1].content if messages else ""

        # ── Onboarding agent prompts ──
        if "extract structured data" in system:
            return _Resp(self._extract(human))
        if "newly approved" in system:
            return _Resp("Your API account is approved and ready. Account ID and plan are on file. Welcome aboard.")
        if "compliance reviewer" in system:
            return _Resp("High-volume account with elevated risk indicators; verify business registry and confirm intended message recipients before approval.")
        if "rejected API application" in system:
            return _Resp("We're unable to approve your application at this time. Please contact support for details.")

        # ── Circle payment agent prompts ──
        if "payment intent" in system:
            return _Resp(self._payment_intent(human))
        if "payment receipt" in system:
            return _Resp("Payment confirmed and submitted on-chain. Funds are on the way.")
        if "step-up identity verification" in system:
            return _Resp("This payment exceeds our threshold and needs step-up identity verification before it can settle.")
        if "payment rejection" in system:
            return _Resp("This payment could not be processed. Please review the details and contact support.")

        return _Resp("OK")

    def _payment_intent(self, human: str) -> str:
        ptype = "transfer"
        for line in human.splitlines():
            if line.startswith("Payment type hint:"):
                hint = line.split(":", 1)[1].strip().lower()
                if hint in ("payout", "transfer", "refund"):
                    ptype = hint
                break
        return json.dumps({"payment_type": ptype, "normalized_memo": "n/a", "risk_notes": []})

    def _extract(self, human: str) -> str:
        use_case = ""
        for line in human.splitlines():
            if line.startswith("Use case:"):
                use_case = line.split(":", 1)[1].strip().lower()
                break

        already_clarified = "clarified:" in use_case
        vague = (not already_clarified) and (("stuff" in use_case) or (len(use_case) < 20))
        risk = ["gambling/casino promotional content"] if ("gambling" in use_case or "casino" in use_case) else []

        return json.dumps({
            "business_category": "General",
            "use_case_summary": (use_case[:80] or "n/a"),
            "use_case_type": "transactional",
            "risk_indicators": risk,
            "estimated_legitimacy": "low" if risk else "medium",
            "needs_clarification": vague,
            "clarifying_question": "What exactly will you send, and to whom?",
        })
