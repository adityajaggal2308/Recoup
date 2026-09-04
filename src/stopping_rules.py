"""
stopping_rules.py — deterministic policy that decides when the agent must
NOT attempt automated outreach and instead hand the account to a human.

This is what makes the agent's action bounded rather than unrestricted: no
matter what the diagnosis or drafting steps would otherwise decide, an
account that trips a stopping rule never gets automated LLM-drafted
outreach — it's routed straight to "escalate", deterministically, in code
that runs before any drafting LLM call.

Only one rule is implemented for this demo (failed_attempts over a
configurable ceiling), by design: this is a single-pass batch run with no
persisted state between runs, so a rule like "stop after successful
payment" or "stop after N automated contacts" would need cross-run
customer state this project doesn't keep. The failed_attempts rule uses
data that's already present per account, so it's meaningful without that
infrastructure. Additional rules (opt-out signal, contact-count ceiling
across runs) are documented in the README as the natural next step once
the system is stateful.
"""
import os

MAX_AUTOMATED_ATTEMPTS = int(os.environ.get("MAX_AUTOMATED_ATTEMPTS", 3))


def check_stopping_rule(account: dict) -> str | None:
    """Returns a human-readable reason string if automated outreach should
    be stopped for this account, or None if it's clear to proceed."""
    failed_attempts = account.get("failed_attempts", 0)
    if failed_attempts >= MAX_AUTOMATED_ATTEMPTS:
        return (
            f"{failed_attempts} prior failed payment attempts >= automated limit "
            f"({MAX_AUTOMATED_ATTEMPTS}) — routed to manual review instead of further automated outreach."
        )
    return None
