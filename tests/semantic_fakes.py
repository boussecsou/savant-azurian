"""Explicitly simulated structured approval model for integration tests.

The phrase map is test data only; production authorization is delegated to the
structured-output model behind SemanticApprovalGuardrail.
"""

import json
import re

from langchain_core.messages import AIMessage

from savant.semantic_approval import ApprovalDecision, SemanticApprovalGuardrail


class SimulatedApprovalModel:
    decisions = {
        "oui": "APPROVE",
        "oui, je confirme": "APPROVE",
        "je confirme": "APPROVE",
        "oui, fais-le": "APPROVE",
        "oui vas-y": "APPROVE",
        "ui": "APPROVE",
        "ui, lance": "APPROVE",
        "ok": "APPROVE",
        "vas-y": "APPROVE",
        "lance": "APPROVE",
        "yes": "APPROVE",
        "yes, do it": "APPROVE",
        "yes for sure": "APPROVE",
        "i approve": "APPROVE",
        "do it": "APPROVE",
        "non, annule": "REJECT",
        "annule": "REJECT",
        "no": "REJECT",
        "cancel": "REJECT",
    }

    def with_structured_output(self, schema, *, method, strict, include_raw):
        assert schema is ApprovalDecision
        assert method == "json_schema"
        assert strict is True
        assert include_raw is True
        return self

    async def ainvoke(self, messages, config=None):
        payload = json.loads(messages[-1].content)
        text = payload.get("latest_user_message")
        decision = self.decisions.get(text.strip().casefold(), "CLARIFY") if isinstance(text, str) else "CLARIFY"
        return {
            "raw": AIMessage(content="", response_metadata={"status": "completed"}),
            "parsed": ApprovalDecision(decision=decision),
            "parsing_error": None,
        }


def simulated_guardrail():
    return SemanticApprovalGuardrail(SimulatedApprovalModel())


def asks_confirmation(text: str) -> bool:
    """A server-worded confirmation question, in French or English: it ends on a question mark and
    names the action (the exact wording follows the owner's language)."""
    return text.rstrip().endswith("?") and bool(
        re.search(r"to the trash|do you (want|confirm)|corbeille|tu (veux|confirmes)", text, re.IGNORECASE)
    )
