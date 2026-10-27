# How the numbers were measured

The README publishes four tables. This page describes, for each of them, the design of the
measurement, the population it ran on, and the questions the design cannot settle. Each numeric
column of the tables is defined in [`metrics.yaml`](../metrics.yaml), and the detail behind each
table is in [`backend/reports/`](../backend/reports/).

Two of the four replay from a committed file, with no key, no running stack and no download:
the routing sweep, and the move-invention reading when its saved answers are judged again
(`--rejudge`; a fresh run makes 42 billed calls). The retrieval ablation queries the live index.
It needs the stack running and the corpus ingested, and therefore the Wikichess articles
downloaded first. The latency bench runs inside the deployed stack, and its published timings
include live calls to the Explorer and to YouTube.

The commands below that start with `cd backend` run on the host. There the settings come from
`backend/.env`, and the default host names `milvus` and `mongo` only exist on the Compose
network. A command that needs the stack (the ablation, or a fresh run of the invention check)
therefore needs `MILVUS_HOST=localhost` and `MONGODB_URI=mongodb://localhost:27017` in that file,
or can run inside the backend container through `docker compose exec backend`.

## 1. Retrieval: does the wording of the query matter?

### The population

The population is fourteen cases, one for each of fourteen openings. A case holds an opening
name, its ECO code, and the set of articles that answer it. Two Wikichess articles cover the Ruy
Lopez and a French note covers it as well, so a case is labelled with a *set*, and any article
of the set counts as correct. A label naming one file among equals would mark a correct
retrieval wrong.

Every case was written by hand from the corpus index, and none was generated from the text of
its target article. A case drawn from that text would turn the score into a measure of shared
vocabulary, which rises whenever the generator and the index split words the same way. The case
file states this rule at its top, and the cases are in
[`backend/data/eval/retrieval_cases.json`](../backend/data/eval/retrieval_cases.json). Each case
also carries a question in French, as a player might type it. The four variants build their
queries from the opening name and the ECO code, so these questions take no part in the score.

### The four wordings

| Variant | What is sent to the embedder |
|---|---|
| `name-only` | the opening name alone, `Ruy Lopez` |
| `french-question` | what the agent sends, `ouverture <name>, idées et plans` |
| `english-verbose` | `chess opening <name>: main ideas, plans and typical moves` |
| `name-and-eco` | the name followed by its ECO code, `Ruy Lopez C60` |

For the `french-question` row, the script calls the agent's own `build_context_query`. A unit
test checks that the variant returns what that function returns. A variant that reimplemented
the function would measure its own copy.

### What is indexed

Each article opens with a quoted header block. In the eleven notes it is one line (ECO code and
first moves). In a downloaded article it has up to five lines: ECO code, moves, FEN, source URL
and contributors. Until the measurement of 2026-09-15 that block was indexed with the prose,
which let `name-and-eco` match the code in its query against the same code in the text. The
block is now parsed into fields and removed before indexing. The README's table was measured on
2026-09-15 with that change in place, and the change was committed on 2026-09-16 (`5d5e3be`).

### The scoring

The search returns ten passages, which are reduced to distinct source files before the cut at k.
An article is stored as several chunks. Without that reduction one opening could fill the whole
top three, and every variant would score high because of the chunking.

The score needs no judge. The label is a file name, so a case is either right or wrong, and a
second run of the same variant on the same index gives the same number.

### What the design cannot settle

One case of fourteen moves recall by 0.071. This study cannot tell apart two wordings that are
closer than that, and the README says so beside the table. The base is also small, with
thirty-two articles: a high score at rank three partly reflects a corpus in which the right
article is rarely far down the list.

### Reproducing it

```bash
cd backend
uv run python -m scripts.run_retrieval_ablation     # needs the stack up and ingested
```

## 2. Routing: how much does the branch depend on its threshold?

### The population

Fifty-four positions: forty-six taken from the lines of the local opening book at depths of two
to ten plies, and eight named lines that master games rarely or never reach. The Explorer was
queried once for each position, and its answers were written to
[`backend/data/eval/theory_positions.json`](../backend/data/eval/theory_positions.json).

**The reading is frozen and dated.** The `masters` database grows, so a position with nine
hundred games today can pass a thousand later. A sweep that queried it live would publish a
different table from one month to the next with nothing changed in the agent. With the reading
frozen, only the threshold can change the table.

### What is varied, and what is read

Only the threshold varies. For each candidate value the study counts how many of the fifty-four
positions meet the Explorer rule for theory (the Explorer lists at least one move, and its count
of master games reaches the value), and how many changed side since the previous value. The
second count is the more useful one. A zero means the routing did not change between two values,
and a run of zeros around the served value means the value needs no defence against its
neighbours.

The README shows seven rows around the served value. The full sweep, from 0 to 50 000, is in
[`backend/reports/theory_threshold_sweep.md`](../backend/reports/theory_threshold_sweep.md).

The sweep counts positions by the Explorer rule only. The agent adds a second test: when the
count falls short of the threshold, it searches the local opening book, and a position found
there is still treated as theory. On these fifty-four positions the book changes nothing up to a
threshold of 10 000, because none of the positions below those values is in the book. At 25 000
and at 50 000 the book would keep 37 positions in theory, where the sweep counts 28 and 24.
No script in the repository writes these two counts. They follow from applying the lines of
`OPENING_LINES`, in `services/opening_book.py`, to the frozen reading.

### What the design cannot settle

The sweep measures how much the routing moves with the threshold. Whether it routes well is a
separate question. A position sent to theory is answered from master games, and a position sent
to the engine is answered from a search. Which of the two serves a player better is outside this
study, and answering it would need a judge.

### Reproducing it

```bash
cd backend
uv run python -m scripts.sweep_theory_threshold     # replays the frozen reading, no key
uv run python -m scripts.sample_theory_positions    # takes a new reading; needs a token
```

## 3. Synthesis: does the model cite only the moves it was handed?

### The population

Twenty-one positions, each answered twice by `gpt-4o-mini` at temperature 0.3, for forty-two
billed calls. Each answer is saved in the JSON beside the table, so the reading can be repeated
at no cost. The prompt of each answer is saved with it. A Wikichess passage in a saved prompt is
replaced by the identifier of its chunk, and the moves the reader found in the passage are stored
beside that identifier and still count as given.

The positions are selected from the frozen reading by a fixed rule: the nine positions that the
Explorer rule sends to the engine at the served threshold, and the twelve shallowest of those it
keeps in theory. In the run, the live agent routed them the same way, with 24 answers written
from theory and 18 from the engine. Both branches of the graph are exercised, which matters
because the two branches build different prompts.

### How citations are classified

Every move named in an answer is compared with two references: the board of the position, and
the moves the prompt contained, wherever they appear in it. The prompt lists the first twelve
legal moves of the position, so a move from that list counts as given. Each citation receives
one of four verdicts, and the README's table counts them.

**The reader handles three shapes that would otherwise count as moves that do not exist.** A move
that follows a numbered move belongs to the same line, although it carries no number of its own.
A square named as a place is not a move. An opening's first move quoted in its history is not a
claim about the current board. Each shape has a unit test in
`backend/tests/unit/evaluation/test_eval_moves.py`. Beside the table, the report also gives the
counts of a reader that treats every square-looking token as a move, as an upper bound on what a
stricter reader could flag.

### What the design cannot settle

The study covers one model at one temperature. The instruction also restricts any mention of the
engine to answers whose prompt carried an evaluation, and nothing counts how often the model
keeps to that restriction. The run dates from 2026-09-08. Twenty-two of the forty-two prompts
contained a retrieved passage whose header listed the opening's first moves, and those answers
hold 36 of the 45 citations of the opening's sequence. The service has since dropped that header from
the indexed text (commit `5d5e3be`), so the prompts it builds today differ from the measured
ones. The lines the model narrates are not checked either: the frozen
reading stores positions, and a position does not record the order of the moves that reached it.

### Reproducing it

```bash
cd backend
uv run python -m scripts.check_move_invention              # 42 billed calls
uv run python -m scripts.check_move_invention --rejudge    # reads the saved answers, free
```

## 4. Latency: what does a question cost?

### The population

Four positions, three repeats each, timed inside the deployed configuration. Two of the four are
out of theory, so the engine node runs on half the sample and the other nodes on all of it.

The bench calls the services behind the theory, engine, context and videos nodes directly and
times each call. It leaves out the synthesis node and its language model. The model call is
billed, its duration depends on a third party, and one slow generation would hide every local
node.

### What the numbers support

A median over twelve points on one machine is not a service level. The ordering of the nodes is
more robust: the slowest median is about nineteen times the fastest, 346 ms against 18 ms, and
the README reads that ordering from the table.

### Reproducing it

```bash
docker compose exec backend python -m scripts.bench_agent
```

## Rules common to the four measurements

**Warnings are errors.** The test suite ignores no category of warning as a whole. A deprecation
warning announces that a library is about to change an API, possibly one that a measurement
relies on.

**No measurement runs in continuous integration.** The repository has one workflow, which
someone has to start by hand. Its backend job runs Ruff, Bandit and pytest, and its frontend job
runs the Karma tests and the production build. It ingests no corpus and calls no billed
endpoint, so no published table depends on when the workflow last ran.
