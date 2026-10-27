"""Sweep the routing threshold over a frozen reading of the Explorer.

``theory_min_games`` decides the second conditional edge of the agent's graph, the one
after the theory node: from that many master games the answer comes from theory, below it
Stockfish is called and the wording changes. It was set from two positions looked at by hand.

The sweep applies the Explorer rule alone. The served agent also keeps in theory a position
below the threshold when the local opening book contains it, and that fallback is not
modelled here.

The question this answers is not "is 1000 the right number" — nothing here can say that —
but **how sharply the routing depends on it**. A threshold sitting on a plateau is robust
and saying so costs a line; a threshold on a slope is a coin toss dressed as a decision.
"""

from __future__ import annotations

from collections.abc import Sequence


#: The Explorer rule the service applies, copied here so the sweep measures that rule.
#: `lichess.py` computes `in_theory = bool(moves) and total_games >= min_games`.
def is_in_theory(position: dict, threshold: int) -> bool:
    """Would the Explorer rule call this position theory at ``threshold``?"""

    return bool(position.get("n_moves")) and position.get("total_games", 0) >= threshold


def sweep(positions: Sequence[dict], thresholds: Sequence[int]) -> list[dict]:
    """One row per threshold: how many positions are theory, and how many just flipped.

    ``thresholds`` is walked in the order given; ``flipped`` counts against the previous
    row, so the caller decides whether the sweep reads upwards or downwards.
    """

    rows: list[dict] = []
    previous: set[int] | None = None
    for threshold in thresholds:
        in_theory = {i for i, p in enumerate(positions) if is_in_theory(p, threshold)}
        rows.append(
            {
                "threshold": threshold,
                "in_theory": len(in_theory),
                "out_of_theory": len(positions) - len(in_theory),
                "flipped": 0 if previous is None else len(previous ^ in_theory),
            }
        )
        previous = in_theory
    return rows


def plateau_around(positions: Sequence[dict], threshold: int, factor: float = 3.0) -> dict:
    """How much room the served threshold has before the routing changes.

    Answers the question a reader actually asks: if this number were three times smaller,
    or three times larger, how many of these positions would be routed differently?
    """

    served = {i for i, p in enumerate(positions) if is_in_theory(p, threshold)}
    lower = {i for i, p in enumerate(positions) if is_in_theory(p, int(threshold / factor))}
    upper = {i for i, p in enumerate(positions) if is_in_theory(p, int(threshold * factor))}
    return {
        "threshold": threshold,
        "factor": factor,
        "in_theory": len(served),
        "flipped_if_divided": len(served ^ lower),
        "flipped_if_multiplied": len(served ^ upper),
        "n": len(positions),
    }
