"""The saved prompts of the move-invention check, with their Wikichess passages withheld.

The text of the Wikichess articles belongs to FICGS, so a saved prompt keeps the chunk
identifier of each Wikichess passage in place of its text, and the moves the reader found in
it. Judging the saved prompt with those moves has to give the verdicts the whole prompt gave,
or the published table would stop replaying. The passage below is invented for the test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_move_invention as check

# The Italian Game (1.e4 e5 2.Nf3 Nc6 3.Bc4), with Black to move.
ITALIAN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"

PASSAGE = "Black usually answers with Bc5, while Be7 keeps things quieter."
REFERENCE = "wikichess/00048-giuoco-piano-0"

PROMPT = (
    f"FEN : {ITALIAN}\n"
    "Trait aux : black\n"
    "Coups légaux : Nf6, d6\n"
    "\n"
    "Extraits de la base de connaissances :\n"
    "  - (Ouverture italienne) Le fou blanc vise la case f7.\n"
    f"  - (Giuoco Piano) {PASSAGE}\n"
)

ANSWER = "Les Noirs peuvent jouer Bc5, ou Be7 pour rester solides, ou encore Nf6."


def test_a_withheld_passage_leaves_its_reference_and_its_moves() -> None:
    saved, withheld = check.withhold(ITALIAN, PROMPT, [(PASSAGE, REFERENCE)])

    assert PASSAGE not in saved
    assert f"  - (Giuoco Piano) [Wikichess passage withheld: {REFERENCE}]\n" in saved
    assert "Le fou blanc vise la case f7." in saved
    assert withheld == [{"reference": REFERENCE, "moves": ["Bc5", "Be7"]}]


def test_the_saved_prompt_with_its_moves_is_judged_as_the_whole_prompt_was() -> None:
    saved, withheld = check.withhold(ITALIAN, PROMPT, [(PASSAGE, REFERENCE)])
    moves = check.withheld_moves({"withheld_passages": withheld})

    whole = check.judge(ITALIAN, ANSWER, PROMPT)

    assert check.judge(ITALIAN, ANSWER, saved, moves) == whole
    assert [c["verdict"] for c in whole["citations"]] == ["offered", "offered", "offered"]
    # Without the stored moves the two moves of the passage would read as unprompted.
    assert check.judge(ITALIAN, ANSWER, saved)["summary"]["legal_not_offered"] == 2


def test_a_passage_missing_from_the_prompt_is_refused() -> None:
    with pytest.raises(ValueError, match=REFERENCE):
        check.withhold(ITALIAN, PROMPT, [("A passage the prompt never carried.", REFERENCE)])


def test_only_the_wikichess_passages_of_the_prompt_are_withheld() -> None:
    """The notes were written for this repository and stay; the third hit never reaches the prompt."""
    state = {
        "passages": [
            {"text": "Le fou blanc vise la case f7.", "source": "openings/ouverture-italienne.md"},
            {"text": PASSAGE, "source": "wikichess/00048-giuoco-piano.md"},
            {"text": "Not in the prompt.", "source": "wikichess/00045-king-s-pawn-game.md"},
        ]
    }
    chunk_ids = {("wikichess/00048-giuoco-piano.md", PASSAGE): REFERENCE}

    assert check.wikichess_passages(state, chunk_ids) == [(PASSAGE, REFERENCE)]


def test_the_replay_reads_the_stored_moves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    saved, withheld = check.withhold(ITALIAN, PROMPT, [(PASSAGE, REFERENCE)])
    report = {
        "measured": "2026-09-08",
        "model": "a model",
        "positions": 1,
        "passes": 1,
        "calls": 1,
        "note": check.NOTE,
        "totals": {},
        "strict_totals": {},
        "runs": [
            {
                "name": "Italian Game",
                "ply": 6,
                "fen": ITALIAN,
                "pass": 1,
                "in_theory": True,
                "used_llm": True,
                "prompt": saved,
                "withheld_passages": withheld,
                "answer": ANSWER,
            }
        ],
    }
    published = tmp_path / "move_invention.json"
    published.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(check, "OUT_JSON", published)
    monkeypatch.setattr(check, "OUT_MD", tmp_path / "move_invention.md")

    check.rejudge()

    replayed = json.loads(published.read_text(encoding="utf-8"))
    assert replayed["totals"]["offered"] == 3
    assert replayed["totals"]["legal_not_offered"] == 0
    assert replayed["runs"][0]["prompt"] == saved
