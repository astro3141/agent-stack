# VENDORED verbatim from paper-trading-harness trader/arch/valuation.py
# source sha256 (first16): 1a80c78d22cdd82e | vendored 2026-09-24
# PURE functions only (no I/O). The deterministic financial math the port
# runs as a SCRIPT step, never in a prompt (§12: the AI has no authority
# over deterministic valuation). Re-vendor + re-pin on any harness change.

"""Lane I — deterministic valuation core, phase I-P2 (Lane I doc
§7/§11/§12/§13).

The AI chooses methods/assumptions/scenarios; ALL arithmetic lives
here (§12: the AI has no authority over deterministic financial math).
Pure functions, no I/O, no randomness — same inputs, same outputs,
always. Version lh-valuation-v0.1; the adopted method and its fixed
assumptions are frozen per thesis at creation (§12), and this module's
version is part of the Lane I pre-registration (I-P5).

MarketImpliedExpectationSet support (§7): reverse valuation is an
APPROXIMATION — a price is compatible with many growth/margin/discount
combinations, so the solver returns the implied value of ONE declared
free variable under DECLARED fixed assumptions, plus sensitivity
re-solves. Never "the market's single belief".

METHOD LINKAGE CONTRACT (owner Lane-I review 2026-09-19): the implied
set and the scenario valuation MUST use the same method_id, metric,
horizon, and accounting basis — comparing a DCF-implied expectation
against a PER-based scenario would let the METHOD difference
masquerade as a variant view. Every ImpliedSolve and ScenarioValuation
carries method_id; the core pre-computes implied results per supported
method (inputs permitting) and the variant-view comparison may only
use the result whose method_id equals the analyst's chosen method.
Fixed assumptions per method come from pre-registered defaults (I-P5)
and are never adjusted after seeing results.

SCOPE OF THE LINKAGE GUARANTEE (owner review 2026-09-20): sharing one
method/definition on both sides removes METHOD mismatch only. It does
NOT cancel distortions from the cash-flow definition itself (e.g. the
unadjusted CFO−capex proxy) — a mis-included or double-counted cash
flow shifts the implied growth AND the scenario values in the same
direction, so the comparison stays internally consistent while the
margin of safety is still distorted. The definition's limits must ride
with every result (see the equity-bridge record), never be treated as
cancelled out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

VALUATION_VERSION = "lh-valuation-v0.1"
METHOD_DCF_FCF = "dcf_fcf_growth"      # implied var: constant FCF growth


class ValuationError(ValueError):
    """Invalid valuation inputs (e.g. terminal growth >= discount
    rate) — fail loudly, never substitute a convenient number."""


# ── WACC ─────────────────────────────────────────────────────────────

def wacc(risk_free: float, equity_risk_premium: float, beta: float,
         cost_of_debt_pretax: float, tax_rate: float,
         equity_weight: float) -> float:
    """Standard weighted average cost of capital. equity_weight is
    E/(D+E) in [0,1]."""
    if not (0.0 <= equity_weight <= 1.0):
        raise ValuationError(f"equity_weight out of range: {equity_weight}")
    cost_equity = risk_free + beta * equity_risk_premium
    cost_debt = cost_of_debt_pretax * (1.0 - tax_rate)
    return equity_weight * cost_equity + (1.0 - equity_weight) * cost_debt


# ── DCF ──────────────────────────────────────────────────────────────

def dcf_enterprise_value(fcf_path: list[float], discount_rate: float,
                         terminal_growth: float) -> float:
    """Enterprise value of an explicit FCF path + Gordon terminal value
    on the final year's FCF. fcf_path[0] is year-1 FCF (already grown,
    i.e. the caller builds the path from drivers)."""
    if not fcf_path:
        raise ValuationError("empty FCF path")
    if terminal_growth >= discount_rate:
        raise ValuationError(
            f"terminal growth {terminal_growth} >= discount rate "
            f"{discount_rate}")
    ev = 0.0
    for t, fcf in enumerate(fcf_path, start=1):
        ev += fcf / (1.0 + discount_rate) ** t
    terminal_fcf = fcf_path[-1] * (1.0 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    ev += terminal_value / (1.0 + discount_rate) ** len(fcf_path)
    return ev


def fcf_path_constant_growth(fcf0: float, growth: float,
                             years: int) -> list[float]:
    if years < 1:
        raise ValuationError("years must be >= 1")
    return [fcf0 * (1.0 + growth) ** t for t in range(1, years + 1)]


def dcf_value_per_share(fcf0: float, growth: float, years: int,
                        discount_rate: float, terminal_growth: float,
                        net_debt: float, shares: float) -> float:
    """Single-stage DCF: constant growth for `years`, Gordon terminal.
    Equity value per share = (EV − net_debt) / shares."""
    if shares <= 0:
        raise ValuationError("shares must be positive")
    ev = dcf_enterprise_value(
        fcf_path_constant_growth(fcf0, growth, years),
        discount_rate, terminal_growth)
    return (ev - net_debt) / shares


# ── multiples ────────────────────────────────────────────────────────

def multiple_value_per_share(metric_per_share: float,
                             multiple: float) -> float:
    """PER×EPS, PBR×BPS, FCF-yield⁻¹×FCF/share … the caller names the
    metric and the multiple's provenance in the artifact."""
    return metric_per_share * multiple


def ev_multiple_value_per_share(metric_total: float, multiple: float,
                                net_debt: float,
                                shares: float) -> float:
    """EV/EBITDA-style: equity per share = (metric×multiple − net_debt)
    / shares."""
    if shares <= 0:
        raise ValuationError("shares must be positive")
    return (metric_total * multiple - net_debt) / shares


# ── scenario table (§11/§13) ─────────────────────────────────────────

@dataclass(frozen=True)
class ScenarioValuation:
    scenario: str                  # bear | base | bull
    method_id: str
    inputs: dict
    value_per_share: float


def scenario_dcf_table(fcf0: float, scenarios: dict[str, dict],
                       years: int, discount_rate: float,
                       terminal_growth: float, net_debt: float,
                       shares: float) -> list[ScenarioValuation]:
    """scenarios: {"bear": {"growth": -0.05}, "base": …, "bull": …} —
    frozen at thesis creation, never edited after results (§11)."""
    out = []
    for name in sorted(scenarios):
        g = scenarios[name]["growth"]
        out.append(ScenarioValuation(
            scenario=name,
            method_id=METHOD_DCF_FCF,
            inputs={"growth": g, "years": years,
                    "discount_rate": discount_rate,
                    "terminal_growth": terminal_growth},
            value_per_share=dcf_value_per_share(
                fcf0, g, years, discount_rate, terminal_growth,
                net_debt, shares)))
    return out


def payoff_summary(current_price: float,
                   table: list[ScenarioValuation]) -> dict:
    """Downside / base upside / tail upside vs the current price
    (§13) — descriptive, not probabilities."""
    by = {s.scenario: s.value_per_share for s in table}
    out = {"current_price": current_price}
    for name, v in by.items():
        out[f"{name}_value"] = round(v, 4)
        out[f"{name}_return"] = round(v / current_price - 1.0, 6) \
            if current_price > 0 else None
    return out


# ── reverse valuation (§7) ───────────────────────────────────────────

def _bisect(f: Callable[[float], float], lo: float, hi: float,
            tol: float = 1e-9, max_iter: int = 200) -> Optional[float]:
    flo, fhi = f(lo), f(hi)
    if flo == 0.0:
        return lo
    if fhi == 0.0:
        return hi
    if flo * fhi > 0:
        return None                    # not bracketed → non-identifiable
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) / 2.0 < tol:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2.0


@dataclass(frozen=True)
class ImpliedSolve:
    """One reverse-valuation solve: the implied value of ONE declared
    free variable under declared fixed assumptions (§7.1). status
    NON_IDENTIFIABLE means no value in the search bounds reproduces
    the price — recorded, never replaced by an arbitrary number.
    method_id ties this solve to the scenario valuation it may be
    compared with (method linkage contract above)."""

    method_id: str
    free_variable: str
    implied_value: Optional[float]
    status: str                        # OK | NON_IDENTIFIABLE
    search_bounds: tuple
    fixed_assumptions: dict


def implied_fcf_growth(price: float, fcf0: float, years: int,
                       discount_rate: float, terminal_growth: float,
                       net_debt: float, shares: float,
                       bounds: tuple = (-0.5, 0.5)) -> ImpliedSolve:
    """What constant FCF growth (over `years`, with the declared
    terminal assumptions) is compatible with the current price?"""
    fixed = {"fcf0": fcf0, "years": years,
             "discount_rate": discount_rate,
             "terminal_growth": terminal_growth,
             "net_debt": net_debt, "shares": shares,
             "valuation_version": VALUATION_VERSION}
    if price <= 0 or fcf0 == 0:
        return ImpliedSolve(METHOD_DCF_FCF, "fcf_growth", None,
                            "NON_IDENTIFIABLE", bounds, fixed)

    def gap(g: float) -> float:
        return dcf_value_per_share(fcf0, g, years, discount_rate,
                                   terminal_growth, net_debt,
                                   shares) - price

    root = _bisect(gap, bounds[0], bounds[1])
    if root is None:
        return ImpliedSolve(METHOD_DCF_FCF, "fcf_growth", None,
                            "NON_IDENTIFIABLE", bounds, fixed)
    return ImpliedSolve(METHOD_DCF_FCF, "fcf_growth", round(root, 8),
                        "OK", bounds, fixed)


def implied_growth_sensitivity(price: float, fcf0: float, years: int,
                               discount_rates: list[float],
                               terminal_growths: list[float],
                               net_debt: float, shares: float,
                               ) -> list[dict]:
    """Sensitivity re-solves over declared discount/terminal cases
    (§7.1 sensitivity_cases) — shows whether the implied growth (and
    any variant-view gap) survives reasonable assumption changes."""
    out = []
    for dr in discount_rates:
        for tg in terminal_growths:
            if tg >= dr:
                out.append({"discount_rate": dr, "terminal_growth": tg,
                            "implied_growth": None,
                            "status": "INVALID_COMBINATION"})
                continue
            s = implied_fcf_growth(price, fcf0, years, dr, tg,
                                   net_debt, shares)
            out.append({"discount_rate": dr, "terminal_growth": tg,
                        "implied_growth": s.implied_value,
                        "status": s.status})
    return out
