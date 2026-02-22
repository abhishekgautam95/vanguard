"""Action pipeline for recommendations and notifications."""

from __future__ import annotations

from .schemas import DecisionResult


def should_trigger_reroute(final_risk: float, predicted_delay_days: float) -> bool:
    """Decision policy for proactive rerouting."""
    return final_risk > 70.0 and predicted_delay_days > 5.0


def build_cost_benefit_analysis(
    wait_days: float = 3.0,
    red_sea_days: float = 15.0,
    red_sea_cost_per_container: float = 2000.0,
    cape_days: float = 28.0,
    cape_cost_per_container: float = 3500.0,
) -> dict[str, object]:
    """Compute a simple expected value for wait vs reroute decision."""
    wait_eta = red_sea_days + wait_days
    wait_option = {
        "option": "wait",
        "eta_days": round(wait_eta, 2),
        "cost_per_container_usd": red_sea_cost_per_container,
    }
    reroute_option = {
        "option": "reroute_now",
        "eta_days": round(cape_days, 2),
        "cost_per_container_usd": cape_cost_per_container,
    }

    # If waiting remains faster and risk is expected to cool, wait is cheaper.
    recommendation = "wait_3_days" if wait_eta < cape_days else "reroute_now"
    rationale = (
        "Waiting is cheaper and still faster than Cape route."
        if recommendation == "wait_3_days"
        else "Reroute is selected because waiting does not improve ETA."
    )

    return {
        "assumptions": {
            "red_sea_eta_days": red_sea_days,
            "cape_eta_days": cape_days,
            "red_sea_cost_per_container_usd": red_sea_cost_per_container,
            "cape_cost_per_container_usd": cape_cost_per_container,
            "wait_window_days": wait_days,
        },
        "options": [wait_option, reroute_option],
        "recommendation": recommendation,
        "rationale": rationale,
    }


def draft_alert_email(result: DecisionResult) -> str:
    """Create an operator-friendly alert template."""
    cba_section = ""
    if result.cost_benefit:
        cba_section = (
            "\nCost-benefit recommendation:\n"
            f"- Decision: {result.cost_benefit.get('recommendation', 'n/a')}\n"
            f"- Rationale: {result.cost_benefit.get('rationale', 'n/a')}\n"
        )

    return (
        "Subject: [Vanguard] Supply Chain Risk Alert\n\n"
        f"Route: {result.route}\n"
        f"Final Risk: {result.final_risk}\n"
        f"Predicted Delay (days): {result.predicted_delay_days}\n"
        f"Confidence: {result.confidence:.2f}\n\n"
        f"Why this alert:\n{result.reason}\n\n"
        "Recommended alternatives:\n"
        + "\n".join(f"- {item}" for item in result.alternatives)
        + "\n"
        + cba_section
    )
