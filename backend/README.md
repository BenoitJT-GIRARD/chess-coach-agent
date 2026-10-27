# Backend: the FastAPI service and the LangGraph agent

This directory holds all the Python code: the agent, its tools, the API that exposes them, and
the scripts that measure the agent's two decisions. The Angular interface is in `../frontend`,
and `../docker-compose.yml` runs the two together with the databases.

## Layout

```
backend/
├── src/chess_coach/
│   ├── config.py          # every setting, read from the environment
│   ├── utils/paths.py     # every path, resolved from the directory that holds pyproject.toml
│   ├── artifacts.py       # the three writers the measurement scripts use for their files
│   ├── services/          # domain services, most of them wrapping one external system
│   ├── rag/               # chunking and indexing of the corpus
│   ├── agent/             # LangGraph state, nodes, graph, synthesis
│   ├── evaluation/        # metrics, query variants, threshold sweep, citation reader
│   └── api/               # routes, schemas, and the mapping between them
├── data/
│   ├── openings/          # 11 notes written in French
│   └── eval/              # the frozen inputs the measurements replay
├── reports/               # measurement results, figures, coverage and the run evidence
├── notebooks/             # the walkthrough, from a FEN to the agent's prompt
├── scripts/               # download, ingestion, measurements, figures, the smoke run
├── tests/                 # unit, integration, system
├── var/                   # what a run leaves behind; git ignores it
├── Dockerfile
└── pyproject.toml
```

The API and the agent call the services, and the services import neither of them. The
`evaluation/` package imports the agent. Nothing under `src/` imports `evaluation/`; only the
measurement scripts and their unit tests do.

## Running the backend on its own

From this directory:

```powershell
uv sync --extra dev                          # uv reads .python-version and uv.lock
uv run pytest
uv run uvicorn chess_coach.api.main:app --reload   # search and history need Milvus and MongoDB
```

Interactive API documentation: <http://localhost:8000/docs>.

The settings read `.env` from the current folder, here `backend/.env`, and default to the
Compose host names `milvus` and `mongo`, which resolve only on the Compose network. To reach the
databases that `docker compose up` publishes on this machine, set `MILVUS_HOST=localhost` and
`MONGODB_URI=mongodb://localhost:27017` in `backend/.env` or in the environment. The ingestion and
the retrieval ablation below need the same setting.

The test suite has three tiers, separated by what each one may reach. `tests/unit/` patches the
socket connection functions, so that a connection to any host other than the local machine
raises an error naming that host. `tests/integration/` wires two real components together.
`tests/system/` launches uvicorn in a child process with `MILVUS_PORT=1` on `127.0.0.1`, blank
Lichess, YouTube and model keys, and queries the API over HTTP. It also points `MONGODB_URI` at
port 1 on `127.0.0.1` and sets `HF_HUB_OFFLINE=1`, so the embedding model can only come from the
local Hugging Face cache.

## Loading the knowledge base

```powershell
uv run python -m scripts.fetch_wikichess     # downloads the Wikichess articles
uv run python -m scripts.ingest_wikichess    # chunks and indexes them into Milvus
```

The Wikichess articles are not tracked by git, because FICGS reserves the rights to their text,
so the first command creates the corpus on disk. The second command indexes it. Run it whenever the
Milvus volume is new: the volume keeps the index across restarts, and a new volume starts empty.

## Reproducing the measurements

```powershell
uv run python -m scripts.run_retrieval_ablation   # four query wordings, 14 cases
uv run python -m scripts.sweep_theory_threshold   # replays the frozen Explorer reading
uv run python -m scripts.sample_theory_positions  # takes a new reading; needs a Lichess token
uv run python -m scripts.check_move_invention --rejudge   # judges the saved answers again
```

The ablation needs the stack running and the corpus ingested. The sweep makes no network call.
It reads `data/eval/theory_positions.json`, the dated reading of the Explorer committed for that
purpose, because the Explorer's counts change over time.

The latency bench runs inside the backend container, where Stockfish is installed:

```powershell
docker compose exec backend python -m scripts.bench_agent
```

The scripts write their results to `reports/`, and the root README quotes them.
`../docs/protocol.md` describes what each design can and cannot settle.

## The evidence of a run

```powershell
uv run python scripts/smoke.py
```

The script runs one position through the agent with every service unreachable, replays the
threshold sweep, and judges the 42 saved model answers again. These steps rewrite four tracked
files under `reports/`. If any of them differs from its committed version, the script names it,
exits with an error and leaves `reports/run-evidence.json` untouched. When all four match, it
writes that file with the command, the date, the git revision and the versions of the main
tools.

## Rebuilding the notebook

```powershell
uv run python scripts/run_notebooks.py           # executes it in one clean kernel, in place
uv run python scripts/run_notebooks.py --check   # fails if the saved outputs are not one run
```

## Quality gates

| Tool | Command |
| --- | --- |
| Ruff (lint) | `uv run ruff check .` |
| Ruff (format) | `uv run ruff format --check .` |
| Bandit | `uv run bandit -c pyproject.toml -r src` |
| Pytest | `uv run pytest` |

Warnings are errors: `filterwarnings = ["error"]`, with no exemption. Before that, the
configuration silenced three warning categories in full, DeprecationWarning included, although
the stack depends on six libraries that change quickly. DeprecationWarning is the category
libraries use to announce a breaking change.
