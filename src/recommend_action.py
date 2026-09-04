"""
recommend_action.py — Step 4-5 of the agent: for each top-priority account,
(a) check the deterministic stopping rule, (b) if clear, decide a bounded
recovery action and draft a personalized message, then (c) have the agent
grade its OWN draft against a rubric and revise once if it fails.

This is the visible agentic QA loop: the second LLM call doesn't just
generate more text, it evaluates the first call's output and can override
it. The stopping-rule check is what bounds the agent's authority — an
account that trips it never reaches the drafting LLM call at all.

Every account processed here also gets a `trace` list: an ordered,
step-by-step record of what happened and why, tagged as "llm" or
"deterministic". This trace is what the frontend renders as the agent's
execution trace, and what the audit log is built from.
"""
from llm_client import call_json, LLMError
from prompts import (
    ACTION_SYSTEM, ACTION_USER_TEMPLATE,
    CRITIQUE_SYSTEM, CRITIQUE_USER_TEMPLATE,
    ALLOWED_ACTIONS, ACTION_DISPLAY_LABELS,
)
from stopping_rules import check_stopping_rule

FALLBACK_ACTION = "reminder"
FALLBACK_MESSAGE = (
    "We noticed a recent issue processing your payment. Could you take a moment "
    "to review your account details? We're happy to help if anything needs updating."
)


def _validate_action(raw_action) -> tuple[str, bool]:
    """Returns (action, was_valid). Coerces anything outside the fixed
    action set to the safe default rather than trusting the model."""
    if raw_action in ALLOWED_ACTIONS:
        return raw_action, True
    return FALLBACK_ACTION, False


def decide_and_draft(account: dict, rank: int, total: int) -> dict:
    user_prompt = ACTION_USER_TEMPLATE.format(
        customer_id=account["customer_id"],
        plan_amount=account["plan_amount"],
        failure_reason=account.get("failure_reason", "unknown"),
        failure_type=account.get("failure_type", "technical"),
        churn_risk=account.get("churn_risk", "medium"),
        rank=rank,
        total=total,
    )
    try:
        result = call_json(ACTION_SYSTEM, user_prompt)
        action, action_valid = _validate_action(result.get("action"))
        message = str(result.get("message") or FALLBACK_MESSAGE)[:2000]
        return {"action": action, "action_valid": action_valid, "message": message, "draft_ok": True}
    except (LLMError, KeyError, TypeError, ValueError):
        return {"action": FALLBACK_ACTION, "action_valid": False, "message": FALLBACK_MESSAGE, "draft_ok": False}


def self_critique(account: dict, draft: dict) -> dict:
    """Second, independent LLM call: grade the draft message against a fixed
    rubric and revise it once if it fails. Returns critique metadata plus
    the final message to actually send."""
    if not draft.get("draft_ok"):
        return {
            "critique_passed": None,
            "critique_note": "Skipped — draft used fallback template.",
            "final_message": draft["message"],
            "revised": False,
        }

    user_prompt = CRITIQUE_USER_TEMPLATE.format(
        failure_type=account.get("failure_type", "technical"),
        churn_risk=account.get("churn_risk", "medium"),
        message=draft["message"],
    )
    try:
        result = call_json(CRITIQUE_SYSTEM, user_prompt)
        passes = bool(result.get("passes"))
        note = str(result.get("critique_note") or "")[:300]
        revised_message = str(result.get("revised_message") or draft["message"])[:2000]
        return {
            "critique_passed": passes,
            "critique_note": note,
            "final_message": revised_message if not passes else draft["message"],
            "revised": not passes,
        }
    except (LLMError, KeyError, TypeError, ValueError):
        return {
            "critique_passed": None,
            "critique_note": "Self-critique step failed — using original draft unrevised.",
            "final_message": draft["message"],
            "revised": False,
        }


def _escalated_record(account: dict, stop_reason: str) -> dict:
    """Deterministic path for an account that trips the stopping rule —
    never reaches the drafting LLM call at all."""
    internal_note = (
        f"Automated outreach paused by stopping rule: {stop_reason} "
        f"Recommend manual follow-up."
    )
    return {
        **account,
        "action": "escalate",
        "action_label": ACTION_DISPLAY_LABELS["escalate"],
        "action_valid": True,
        "drafted_message": internal_note,
        "draft_ok": True,
        "critique_passed": None,
        "critique_note": "Skipped — stopping rule routed this account to manual review before drafting.",
        "final_message": internal_note,
        "message_revised": False,
        "stopped_by_rule": stop_reason,
        "trace": [
            {"step": "stopping_rule_check", "type": "deterministic", "detail": stop_reason},
        ],
    }


def recommend_for_top_accounts(prioritized_accounts: list[dict], top_n: int) -> list[dict]:
    total = len(prioritized_accounts)
    top = prioritized_accounts[:top_n]
    results = []

    for account in top:
        stop_reason = check_stopping_rule(account)
        if stop_reason:
            results.append(_escalated_record(account, stop_reason))
            continue

        trace = [{"step": "stopping_rule_check", "type": "deterministic", "detail": "clear — proceeding to drafting"}]

        draft = decide_and_draft(account, account["rank"], total)
        trace.append({
            "step": "decide_and_draft",
            "type": "llm",
            "detail": f"action={draft['action']}" + ("" if draft["action_valid"] else " (model returned an out-of-set action; coerced to default)"),
        })

        critique = self_critique(account, draft)
        if critique["critique_passed"] is None:
            critique_detail = critique["critique_note"]
        elif critique["critique_passed"]:
            critique_detail = "passed rubric on first draft"
        else:
            critique_detail = f"revised after failing rubric: {critique['critique_note']}"
        trace.append({"step": "self_critique", "type": "llm", "detail": critique_detail})

        results.append({
            **account,
            "action": draft["action"],
            "action_label": ACTION_DISPLAY_LABELS.get(draft["action"], draft["action"]),
            "action_valid": draft["action_valid"],
            "drafted_message": draft["message"],
            "draft_ok": draft["draft_ok"],
            "critique_passed": critique["critique_passed"],
            "critique_note": critique["critique_note"],
            "final_message": critique["final_message"],
            "message_revised": critique["revised"],
            "stopped_by_rule": None,
            "trace": trace,
        })
    return results


if __name__ == "__main__":
    from data_loader import load_payments
    from diagnose import diagnose_all
    from prioritize import prioritize

    accounts = prioritize(diagnose_all(load_payments()[:3]))
    for r in recommend_for_top_accounts(accounts, top_n=3):
        print(r["rank"], r["customer_id"], "->", r["action_label"], "| revised:", r["message_revised"], "| stopped:", r["stopped_by_rule"])
        print("   ", r["final_message"][:80])
