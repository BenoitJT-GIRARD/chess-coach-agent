"""The query formulations the ablation compares.

`french-question` is not a copy of the served wording: it calls the agent's own
``build_context_query``. A variant that drifts from the code stops measuring the product
and starts measuring the harness.
"""

from __future__ import annotations

from collections.abc import Callable

from chess_coach.agent.graph import build_context_query
from chess_coach.evaluation.cases import RetrievalCase


def name_only(case: RetrievalCase) -> str:
    """The opening name, nothing else. The floor."""

    return case.opening_name


def french_question(case: RetrievalCase) -> str:
    """What the agent actually sends, through the agent's own function."""

    return build_context_query({"opening_name": case.opening_name})


def english_verbose(case: RetrievalCase) -> str:
    """A padded English wording, close to the one the agent sent before.

    Its generic words (chess, opening, ideas, plans, moves) say nothing about the opening
    asked for. In the ablation of 2026-09-15 it put the same article first in seven of the
    fourteen cases, `wikichess/00045`, whose header gives the moves 1.e4 e5 2.Nf3 Nc6 3.Bc4.
    """

    return f"chess opening {case.opening_name}: main ideas, plans and typical moves"


def name_and_eco(case: RetrievalCase) -> str:
    """The name plus its ECO code. Does the code sharpen the query, or add noise?"""

    return f"{case.opening_name} {case.eco}"


VARIANTS: dict[str, Callable[[RetrievalCase], str]] = {
    "name-only": name_only,
    "french-question": french_question,
    "english-verbose": english_verbose,
    "name-and-eco": name_and_eco,
}

#: The variant the service runs. Named so the report can mark it.
SERVED = "french-question"
