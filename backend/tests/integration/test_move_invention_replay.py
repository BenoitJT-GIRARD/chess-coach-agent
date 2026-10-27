"""The published move-invention table, replayed from the saved answers.

The citation reader and the artefact it judged, face to face. The saved prompts carry chunk
identifiers in place of the Wikichess passages, and the moves read from each passage are
stored beside it. Judging every saved answer again with those moves has to give back each
recorded verdict and the totals the README publishes.
"""

from __future__ import annotations

import json

import pytest

from chess_coach.utils.paths import MOVE_INVENTION_JSON
from scripts.check_move_invention import judge, totals, withheld_moves

pytestmark = [pytest.mark.integration, pytest.mark.claim]

COLUMNS = ("cited", "offered", "legal_not_offered", "illegal", "line_reference")


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(MOVE_INVENTION_JSON.read_text(encoding="utf-8"))


def test_every_saved_answer_replays_to_its_recorded_verdicts(report: dict) -> None:
    for run in report["runs"]:
        replayed = judge(run["fen"], run["answer"], run["prompt"], withheld_moves(run))
        for key, value in replayed.items():
            assert run[key] == value, f"{run['name']}, pass {run['pass']}: {key}"


def test_the_replay_gives_the_published_totals(report: dict) -> None:
    runs = [
        {**run, **judge(run["fen"], run["answer"], run["prompt"], withheld_moves(run))}
        for run in report["runs"]
    ]

    filtered, strict = totals(runs, "summary"), totals(runs, "strict_summary")

    assert [filtered[column] for column in COLUMNS] == [116, 68, 1, 2, 45]
    assert [strict[column] for column in COLUMNS] == [185, 98, 5, 37, 45]
    assert (filtered, strict) == (report["totals"], report["strict_totals"])


def test_no_saved_prompt_quotes_a_wikichess_article(report: dict) -> None:
    for run in report["runs"]:
        assert "ficgs.com" not in run["prompt"]
        assert "Contributeurs Wikichess" not in run["prompt"]
