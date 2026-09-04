"""
diagnose.py — Step 1 of the agent: for each failed-payment account, reason
about WHY it likely failed (technical issue vs. churn signal), with a
confidence score, a pay-likelihood estimate, and a churn-risk label.

This is the first autonomous decision in the chain: it feeds directly into
prioritize.py's explainable scoring formula and later into
recommend_action.py's decision of what to actually do.
"""
from llm_client import call_json, LLMError
from prompts import DIAGNOSE_SYSTEM, DIAGNOSE_USER_TEMPLATE

FALLBACK_DIAGNOSIS = {
    "failure_reason": "Unable to diagnose automatically — flagged for manual review.",
    "failure_type": "technical",
    "confidence": 0.3,
    "pay_likelihood": 0.3,
    "churn_risk": "medium",
}


def diagnose_account(account: dict) -> dict:
    """Returns account merged with diagnosis fields. Never raises — on any
    LLM failure it falls back to a conservative default and tags the record
    so the UI can flag it, instead of crashing the whole batch."""
    user_prompt = DIAGNOSE_USER_TEMPLATE.format(**account)
    try:
        result = call_json(DIAGNOSE_SYSTEM, user_prompt)
        diagnosis = _validate(result)
        diagnosis["diagnosis_ok"] = True
    except (LLMError, KeyError, TypeError, ValueError):
        diagnosis = dict(FALLBACK_DIAGNOSIS)
        diagnosis["diagnosis_ok"] = False

    return {**account, **diagnosis}


def _validate(result: dict) -> dict:
    failure_type = result.get("failure_type")
    if failure_type not in ("technical", "churn_signal"):
        failure_type = "technical"

    churn_risk = result.get("churn_risk")
    if churn_risk not in ("low", "medium", "high"):
        churn_risk = "medium"

    def clamp01(x, default):
        try:
            x = float(x)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, x))

    return {
        "failure_reason": str(result.get("failure_reason") or "No reason provided.")[:300],
        "failure_type": failure_type,
        "confidence": clamp01(result.get("confidence"), 0.5),
        "pay_likelihood": clamp01(result.get("pay_likelihood"), 0.5),
        "churn_risk": churn_risk,
    }


def diagnose_all(accounts: list[dict]) -> list[dict]:
    return [diagnose_account(a) for a in accounts]


if __name__ == "__main__":
    from data_loader import load_payments
    sample = load_payments()[:2]
    for a in diagnose_all(sample):
        print(a["customer_id"], "->", a.get("failure_reason"), a.get("diagnosis_ok"))
