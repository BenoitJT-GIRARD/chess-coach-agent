"""Does the model cite only the moves it was given?

One line of the system prompt forbids inventing a move, and that line is the strongest claim
this repository makes about its last node. It went unchecked for a long time: a suite with a
faked model can only show that the prompt carries the rule, never that anything obeys it.

This script checks the rule itself, on the real agent and the real model: every position
of the frozen reading that left theory, plus the first twelve that stayed in it, each run
twice. Around forty billed calls to ``LLM_MODEL``. It is the only measurement here that
costs money, which is why it is a script and not a test.

Every answer is read for move citations, and each citation is judged against the prompt
that produced it and against the board — see :mod:`chess_coach.evaluation.moves` for the
three traps that make a naive count wrong. Anything cited that the prompt did not give is
written out with the sentence that carried it, so a flag can be read rather than trusted.

The answers are kept in the artefact, so the reading can be replayed for nothing. The prompts
are kept too, with one change: each Wikichess passage is replaced by the identifier of its
chunk, because FICGS reserves the rights on the text of its articles. The moves the reader
found in a passage are stored beside that identifier, and a replay counts them as given.

Start the stack with `docker compose up -d`, then run the module inside the backend
container: `docker compose exec backend python -m scripts.check_move_invention` for a
fresh, billed run, or the same command with `--rejudge` to read the saved answers again.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chess

from chess_coach.agent.graph import build_default_agent
from chess_coach.agent.synthesize import PROMPT_PASSAGES, build_llm_prompt, passage_in_prompt
from chess_coach.artifacts import write_json, write_text
from chess_coach.config import get_settings
from chess_coach.evaluation.moves import classify, offered_moves, summarise
from chess_coach.evaluation.threshold import is_in_theory
from chess_coach.rag.preprocess import build_chunks, load_articles
from chess_coach.utils.paths import MOVE_INVENTION_JSON, MOVE_INVENTION_TABLE, THEORY_POSITIONS

POSITIONS = THEORY_POSITIONS
OUT_JSON = MOVE_INVENTION_JSON
OUT_MD = MOVE_INVENTION_TABLE

#: Every position that left theory, plus the first twelve that stayed in it. The graph
#: takes a different path for each — one answers from the Explorer, the other from
#: Stockfish — and the instruction has to hold on both.
IN_THEORY_SAMPLE = 12
PASSES = 2

#: What a Wikichess passage becomes in a saved prompt. The reference is the identifier of the
#: chunk the prompt quoted, which names the article and the chunk's place in it.
WITHHELD = "[Wikichess passage withheld: {reference}]"

NOTE = (
    "Citations are judged against the prompt that produced them. A move written in "
    "French notation is translated before being compared; a bare square that the "
    "prose names as a place is not read as a move, and the unfiltered reading is "
    "given beside the filtered one as an upper bound. In the saved prompts each "
    "Wikichess passage is replaced by the identifier of its chunk, because FICGS "
    "reserves the rights on the text; the moves read from the passage before it was "
    "removed are stored under `withheld_passages`, and they count as given."
)


def sample(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick the positions to run, deterministically, from the frozen Explorer reading."""

    threshold = payload["served_threshold"]
    in_theory, out_of_theory = [], []
    for position in payload["positions"]:
        (in_theory if is_in_theory(position, threshold) else out_of_theory).append(position)

    ordered = sorted(in_theory, key=lambda p: (p["ply"], p["name"]))[:IN_THEORY_SAMPLE]
    return ordered + sorted(out_of_theory, key=lambda p: (p["ply"], p["name"]))


def sentence_of(text: str, token: str) -> str:
    """The sentence that carried ``token``, so a flagged citation can be read in context.

    The split ignores the dot of a move number: « commence par 1.e4 d5 » is one sentence,
    and cutting it at the `1.` would hide the very thing the reader is meant to check.
    """

    for sentence in re.split(r"(?<=[^\d][.!?])\s+", text):
        if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", sentence):
            return sentence.strip()
    return text.strip()[:200]


def withhold(
    fen: str, prompt: str, passages: Iterable[tuple[str, str]]
) -> tuple[str, list[dict[str, Any]]]:
    """Replace each passage of ``prompt`` by its reference, and keep the moves it gave.

    ``passages`` pairs the text of a passage, exactly as the prompt carries it, with the
    reference that replaces it, in the order the prompt lists them. The moves are read
    before the text goes, in the context of the whole prompt, so that judging the saved
    prompt with them gives the verdicts the whole prompt gave.
    """

    board = chess.Board(fen)
    pieces: list[str] = []
    withheld: list[dict[str, Any]] = []
    cursor = 0
    for text, reference in passages:
        start = prompt.find(text, cursor)
        if start < 0:
            raise ValueError(f"{reference}: the passage is not in the prompt")
        end = start + len(text)
        moves = offered_moves(board, prompt, within=(start, end))
        withheld.append({"reference": reference, "moves": sorted(moves)})
        pieces += [prompt[cursor:start], WITHHELD.format(reference=reference)]
        cursor = end
    return "".join([*pieces, prompt[cursor:]]), withheld


def withheld_moves(run: dict[str, Any]) -> set[str]:
    """Every move read from the passages a saved prompt no longer carries."""

    return {move for passage in run.get("withheld_passages", ()) for move in passage["moves"]}


def wikichess_passages(
    state: dict[str, Any], chunk_ids: dict[tuple[str, str], str]
) -> list[tuple[str, str]]:
    """The Wikichess passages of the prompt, as it carries them, with their chunk identifier.

    A retrieved passage carries its source file and its text but not its chunk, so the
    identifier is found by matching the two against the corpus on disk.
    """

    found = []
    for passage in (state.get("passages") or [])[:PROMPT_PASSAGES]:
        if passage["source"].startswith("wikichess/"):
            reference = chunk_ids.get((passage["source"], passage["text"]), passage["source"])
            found.append((passage_in_prompt(passage), reference))
    return found


def judge(fen: str, answer: str, prompt: str, withheld: Iterable[str] = ()) -> dict[str, Any]:
    """Read one answer for move citations. No model, no network: a pure function.

    Kept apart from the run so the saved answers can be judged again — a fix to the
    reader costs nothing, and the published artefact replays without spending.
    ``withheld`` holds the moves of the passages the saved prompt no longer carries.
    """

    withheld = frozenset(withheld)
    citations = classify(fen, answer, prompt, withheld_moves=withheld)
    strict = classify(fen, answer, prompt, strict=True, withheld_moves=withheld)
    return {
        "summary": summarise(citations),
        "strict_summary": summarise(strict),
        "citations": [
            {"token": c.token, "san": c.san, "verdict": c.verdict, "notation": c.notation}
            for c in citations
        ],
        "flagged": [
            {
                "token": c.token,
                "san": c.san,
                "verdict": c.verdict,
                "sentence": sentence_of(answer, c.token),
            }
            for c in citations
            if c.verdict in {"legal", "illegal"}
        ],
    }


def run_once(
    agent, position: dict[str, Any], attempt: int, chunk_ids: dict[tuple[str, str], str]
) -> dict[str, Any]:
    """Run the agent on one position, judge the answer it wrote, and keep both."""

    state = agent.run(position["fen"])
    answer = " ".join(
        part for part in (state.get("opening_summary"), state.get("recommendation")) if part
    ).strip()
    prompt = build_llm_prompt(state)
    saved_prompt, withheld = withhold(position["fen"], prompt, wikichess_passages(state, chunk_ids))

    return {
        "name": position["name"],
        "ply": position["ply"],
        "fen": position["fen"],
        "pass": attempt,
        "in_theory": bool(state.get("in_theory")),
        "used_llm": "llm" in (state.get("sources_used") or []),
        **judge(position["fen"], answer, prompt),
        "prompt": saved_prompt,
        "withheld_passages": withheld,
        "answer": answer,
    }


def totals(runs: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Add up one of the two readings over the runs the model actually answered."""

    counted = [run[key] for run in runs if run["used_llm"]]
    fields = (
        "cited",
        "offered",
        "legal_not_offered",
        "illegal",
        "line_reference",
        "in_french_notation",
    )
    return {field: sum(entry[field] for entry in counted) for field in fields}


def notation_line(in_french: int) -> str:
    """Say what the French-notation reading found, including when it found nothing."""

    if in_french:
        return (
            f"{in_french} of those citations came back in French notation (`Cf3` for the "
            "`Nf3` it was given). Read as English they would have looked like moves that "
            "do not exist."
        )
    return (
        "None of those citations came back in French notation: this model answered in the "
        "notation it was handed. The translation step is still in the reader, and an "
        "answer written `Cf3` would be counted as the `Nf3` it was given rather than as "
        "an invention."
    )


def to_markdown(payload: dict[str, Any]) -> str:
    """Write the report a reader opens before the JSON."""

    filtered, strict = payload["totals"], payload["strict_totals"]
    lines = [
        "# Does the model cite only the moves it was given?",
        "",
        f"Measured {payload['measured']} · model `{payload['model']}` · "
        f"{payload['positions']} positions, {payload['passes']} passes, "
        f"{payload['calls']} calls.",
        "",
        "| Citations | Given in the prompt | Legal, not given | No such move | Told as a line |",
        "|---|---|---|---|---|",
        f"| {filtered['cited']} | {filtered['offered']} | {filtered['legal_not_offered']} | "
        f"{filtered['illegal']} | {filtered['line_reference']} |",
        "",
        "> **How to read it.** One row, and the columns say where each cited move came from. "
        "`Given in",
        "> the prompt` is a move the prompt contained, whether a tool's output carried it or it "
        "was among",
        "> the twelve legal moves listed for the position. `Legal, not given` is a move that "
        "exists in the",
        "> position and reached the answer from somewhere else. `No such move` could not be "
        "played at",
        "> all. `Told as a line` is the opening's own sequence quoted behind its move number.",
        "",
        notation_line(filtered["in_french_notation"]),
        "",
        "The last column is the opening's own sequence, cited behind its move number: "
        "already played, and left out of the invention count.",
        "",
        "Unfiltered reading, counting every square-looking token as a move, including the "
        "ones the prose names as places:",
        "",
        "| Citations | Given in the prompt | Legal, not given | No such move | Told as a line |",
        "|---|---|---|---|---|",
        f"| {strict['cited']} | {strict['offered']} | {strict['legal_not_offered']} | "
        f"{strict['illegal']} | {strict['line_reference']} |",
        "",
        "> **How to read it.** The same five columns, counted by a parser that treats every",
        "> square-looking token as a move. The totals climb because English prose names squares "
        "while",
        "> talking about them. Publishing both readings shows how much the counting rule "
        "decides, and",
        "> the filtered reading above is the one the claim rests on.",
        "",
    ]

    flagged = [
        (run["name"], run["pass"], item)
        for run in payload["runs"]
        if run["used_llm"]
        for item in run["flagged"]
    ]
    lines.append(f"## What was flagged ({len(flagged)})")
    lines.append("")
    if not flagged:
        lines.append("Nothing: every move cited over the run was one the prompt had given.")
    else:
        # The model was asked to coach in French, so its sentences are in French. They are
        # quoted inside a fenced block: they are the evidence, not the prose of this report,
        # and the language rule of the repository judges what is written here rather than
        # what was measured.
        for name, attempt, item in flagged:
            reading = f" = {item['san']}" if item["san"] else ""
            lines.append(
                f"- **{name}**, pass {attempt}. `{item['token']}`{reading}, "
                f"*{item['verdict']}*, in the model's own words:"
            )
            lines.append("")
            lines.append("  ```")
            lines.append(f"  {item['sentence']}")
            lines.append("  ```")
            lines.append("")
    lines.append("")

    fell_back = [run for run in payload["runs"] if not run["used_llm"]]
    if fell_back:
        lines.append(
            f"{len(fell_back)} run(s) answered from the template because the model call "
            "failed, and are left out of the counts."
        )
        lines.append("")
    # One final newline, the form the end-of-file hook of pre-commit keeps.
    return "\n".join(lines).rstrip("\n") + "\n"


def rejudge() -> None:
    """Read the saved answers again, without calling anything.

    The expensive half of this measurement is the forty-two answers; they are kept in the
    artefact. Judging them is a pure function of that file, so a reader who disagrees with
    how a citation was counted can change the rule and replay for nothing.
    """

    report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    for run in report["runs"]:
        run.update(judge(run["fen"], run["answer"], run["prompt"], withheld_moves(run)))
    report["totals"] = totals(report["runs"], "summary")
    report["strict_totals"] = totals(report["runs"], "strict_summary")

    write_json(OUT_JSON, report)
    write_text(OUT_MD, to_markdown(report))
    print(json.dumps(report["totals"], ensure_ascii=False))
    print(f"{len(report['runs'])} saved answers judged again, no call made")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--rejudge",
        action="store_true",
        help="read the saved answers again instead of calling the model",
    )
    if parser.parse_args().rejudge:
        rejudge()
        return

    settings = get_settings()
    if not settings.llm_enabled or not settings.llm_api_key:
        raise SystemExit(
            "This script calls a billed model: set LLM_ENABLED=true and LLM_API_KEY first."
        )

    payload = json.loads(POSITIONS.read_text(encoding="utf-8"))
    positions = sample(payload)
    agent = build_default_agent()
    chunk_ids = {
        (chunk.source, chunk.text): chunk.chunk_id
        for chunk in build_chunks(load_articles(Path(settings.wikichess_dir)))
    }

    print(
        f"{len(positions)} positions, {PASSES} passes, {len(positions) * PASSES} "
        f"calls to {settings.llm_model}"
    )
    runs = []
    for attempt in range(1, PASSES + 1):
        print(f"\nPass {attempt}")
        for position in positions:
            run = run_once(agent, position, attempt, chunk_ids)
            runs.append(run)
            flags = len(run["flagged"])
            print(
                f"  {position['name'][:34]:34s} ply {position['ply']:2d}  "
                f"{'theory' if run['in_theory'] else 'engine'}  "
                f"{run['summary']['cited']:2d} cited  {flags} flagged"
                f"{'' if run['used_llm'] else '  (template fallback)'}"
            )

    report = {
        "measured": datetime.now(UTC).date().isoformat(),
        "model": settings.llm_model,
        "positions": len(positions),
        "passes": PASSES,
        "calls": len(runs),
        "note": NOTE,
        "totals": totals(runs, "summary"),
        "strict_totals": totals(runs, "strict_summary"),
        "runs": runs,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUT_JSON, report)
    write_text(OUT_MD, to_markdown(report))

    print()
    print(json.dumps(report["totals"], ensure_ascii=False))
    print(f"written to {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
