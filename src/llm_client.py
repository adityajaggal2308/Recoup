"""
llm_client.py — single choke point for all Anthropic API calls.

Centralizing this means:
  - the API key is read from the environment exactly once
  - every call site gets the same defensive JSON parsing (a malformed or
    truncated LLM response never crashes the pipeline)
  - it's the one place to swap models / add retries later
"""
import hashlib
import json
import os
import re
import time

MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 2  # 1 initial call + 1 bounded retry on transient/parse failure
RETRY_DELAY_SECONDS = 0.6

_client = None


class LLMError(Exception):
    """Raised when the LLM call fails or its response can't be used at all."""


def _seeded_random(*parts: str) -> float:
    """Deterministic pseudo-random float in [0, 1) from arbitrary strings, so
    mock responses vary per-account but are stable across repeated runs."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _field(user: str, key: str, pattern: str = r"([^\n]+)") -> str:
    match = re.search(rf"{re.escape(key)}[^:]*:\s*{pattern}", user)
    return match.group(1).strip() if match else ""


def _mock_diagnose(user: str) -> dict:
    customer_id = _field(user, "customer_id")
    payment_method = _field(user, "payment_method")
    contract_type = _field(user, "contract_type")
    card_expiry_days = _field(user, "card_expiry_days", r"(-?\d+)")
    failed_attempts = _field(user, "failed_attempts", r"(\d+)")

    is_technical = card_expiry_days.startswith("-") or "check" not in payment_method.lower()
    is_month_to_month = "month-to-month" in contract_type.lower()
    r = _seeded_random(customer_id, "diagnose")

    if is_technical:
        failure_type = "technical"
        failure_reason = "Card appears expired near the billing date — a routine technical failure, not a churn signal."
        churn_risk = "low" if not is_month_to_month else "medium"
        pay_likelihood = 0.65 + 0.25 * r
    else:
        failure_type = "churn_signal"
        failure_reason = "Payment method has a history of processing issues and engagement looks soft — reads as a churn signal."
        churn_risk = "high" if is_month_to_month else "medium"
        pay_likelihood = 0.25 + 0.35 * r

    if int(failed_attempts or 0) >= 3:
        churn_risk = "high"
        pay_likelihood *= 0.6

    return {
        "failure_reason": f"[MOCK] {failure_reason}",
        "failure_type": failure_type,
        "confidence": round(0.6 + 0.35 * r, 2),
        "pay_likelihood": round(min(pay_likelihood, 0.95), 2),
        "churn_risk": churn_risk,
    }


def _mock_action(user: str) -> dict:
    customer_id = _field(user, "customer_id")
    failure_type = _field(user, "Failure type")
    churn_risk = _field(user, "Churn risk")
    plan_amount = _field(user, "Amount owed", r"\$?([\d.]+)")
    r = _seeded_random(customer_id, "action")

    if churn_risk in ("medium", "high"):
        action = "empathetic_outreach"
        message = (
            f"[MOCK DRAFT] Hi — we noticed your recent payment of ${plan_amount} didn't go "
            "through, and we'd really hate to lose you over something this fixable. No rush "
            "and no pressure — just reply or update your payment details whenever works, and "
            "we're here if anything's changed on your end."
        )
    elif failure_type == "technical" and r > 0.15:
        action = "payment_link_retry"
        message = (
            f"[MOCK DRAFT] Your last payment of ${plan_amount} didn't process — looks like a "
            "card issue. Here's a quick link to update your payment method and retry in under "
            "a minute, no other changes needed."
        )
    else:
        action = "reminder"
        message = (
            f"[MOCK DRAFT] Just a heads up — your payment of ${plan_amount} didn't go through. "
            "Could you take a moment to check your account details? Happy to help if anything "
            "needs updating."
        )

    return {"action": action, "message": message}


def _mock_critique(user: str) -> dict:
    message = _field(user, '"""', r'([\s\S]*?)"""')
    r = _seeded_random(message[:40], "critique")
    if r < 0.25:
        return {
            "passes": False,
            "critique_note": "[MOCK] Slightly vague about the next concrete step — tightened the call to action.",
            "revised_message": (message or "").replace("Happy to help", "Just tap the link below to fix it in one step, and we're happy to help"),
        }
    return {
        "passes": True,
        "critique_note": "[MOCK] Warm, clear, and makes no unauthorized promises.",
        "revised_message": message,
    }


def _mock_response(system: str, user: str) -> dict:
    """Deterministic, locally-generated stand-in for a real Claude response,
    used only when MOCK_LLM=1 — lets the full pipeline run for free with
    varied, plausible-looking output instead of hitting the real API."""
    if "payments-risk analyst" in system:
        return _mock_diagnose(user)
    if "deciding how to win back" in system:
        return _mock_action(user)
    if "QA reviewer" in system:
        return _mock_critique(user)
    raise LLMError("MOCK_LLM=1 but no mock matches this prompt.")


def _get_client():
    # Imported lazily so the rest of the pipeline (and its tests) can run
    # even in environments where the anthropic package isn't installed yet
    # (e.g. before `pip install -r requirements.txt`) — the error surfaces
    # as a normal LLMError instead of an import crash at module load time.
    global _client
    if _client is None:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("The 'anthropic' package is not installed. Run: pip install -r requirements.txt") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set in the environment.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from an LLM response, even if
    it wrapped the JSON in markdown fences or added stray whitespace/prose
    around it. Raises LLMError if nothing parseable is found."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences if present.
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: grab the first {...} block in the text.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise LLMError(f"Could not parse JSON from LLM response: {text[:300]!r}")


def call_json(system: str, user: str, max_tokens: int = 1000) -> dict:
    """Call the model with a system + user prompt and parse the reply as JSON.
    Makes one bounded retry (MAX_ATTEMPTS total) on a transient API error or
    an unparseable response before giving up — a single dropped connection
    or a one-off malformed generation shouldn't be enough to fall back to
    the conservative default. Raises LLMError only after all attempts are
    exhausted; callers are expected to catch that and degrade gracefully
    rather than let it propagate to a 500."""
    if os.environ.get("MOCK_LLM") == "1":
        return _mock_response(system, user)

    client = _get_client()
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            full_text = "\n".join(text_parts)
            if not full_text.strip():
                raise LLMError("LLM response contained no text content.")
            return _extract_json(full_text)
        except Exception as e:
            # Covers anthropic.APIError, transport failures, and our own
            # LLMError from empty/unparseable responses.
            last_error = e
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

    raise LLMError(f"Anthropic API error after {MAX_ATTEMPTS} attempts: {last_error}") from last_error
