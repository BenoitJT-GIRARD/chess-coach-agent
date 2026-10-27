# Running it

One command starts six containers, and the API answers before all of them are ready. This page
covers that interval: what is running, what is ready, what each missing key changes, and what to
check when an answer stops arriving.

## Starting it

```powershell
copy .env.example .env       # every key in it is optional
docker compose up -d --build

# the articles are not tracked by git; this downloads them into backend/var/
docker compose run --rm backend python -m scripts.fetch_wikichess

# index them into Milvus once; the named volume keeps the collection
docker compose run --rm backend python -m scripts.ingest_wikichess
```

| | |
|---|---|
| Interface | <http://localhost:4200> |
| API documentation | <http://localhost:8000/docs> |
| Liveness probe | <http://localhost:8000/api/v1/healthcheck> |
| Milvus health | <http://localhost:9091/healthz> |

**Milvus takes the longest to start.** It waits until etcd and MinIO are healthy, and its own
healthcheck has a ninety-second start period during which Compose does not count failures. The
backend waits until Milvus and MongoDB are healthy, and the frontend waits for the backend. As a
result `docker compose up` shows little activity for a while, and then the services appear
together. A stack that looks stuck two minutes after the start is usually waiting for Milvus.

## Liveness and readiness

The service answers `/api/v1/healthcheck` as soon as uvicorn has bound its port. That route is
the liveness probe: the healthcheck of the backend image calls it, and Compose starts the
frontend only once that healthcheck passes. Readiness differs from one route to the next:

| Route | Works with nothing behind it |
|---|---|
| `/api/v1/healthcheck` | yes |
| `/api/v1/position/{fen}` | yes, the description of the board is pure computation |
| `/api/v1/moves/{fen}` | yes, from the local opening book |
| `/api/v1/evaluate/{fen}` | needs the Stockfish binary, which is in the image |
| `/api/v1/vector-search` | needs the embedding model, Milvus, and a collection that has been ingested |
| `/api/v1/videos/{opening}` | needs a YouTube key; answers 503 without one |
| `/api/v1/agent` | answers, with fewer sources, when a key, Milvus, MongoDB, Stockfish or the embedding model is missing |
| `/api/v1/history` | needs MongoDB; answers with an empty history otherwise |

**The embedding model is loaded at startup, in a background thread.** When the load succeeds the
service logs `Embedding model ready`, and when it fails it logs `Embedding model not warmed up`
with the reason. The process keeps the loaded model, and the agent and `/api/v1/vector-search`
both use that copy. A search that arrives while the load is still running waits for it to finish.
After a failed load, the next search tries again. While the model cannot be loaded, the agent
answers without passages and `/api/v1/vector-search` answers 503. Before this warm-up existed, the
first request that needed the model paid for the whole load: about ten seconds on a warm cache,
and a download of a few hundred megabytes on a cold one.

## What each missing key changes

Everything works without any key. A missing key changes which source answers.

| Missing | What happens |
|---|---|
| `LICHESS_TOKEN` | the Explorer is not called, and the local opening book answers; the book holds seventeen lines, where the Explorer covers the whole master database |
| `YOUTUBE_API_KEY` | the video section stays empty, and neither the template nor the model's prompt mentions videos |
| `LLM_API_KEY`, or `LLM_ENABLED=false` | a deterministic French template writes the recommendation from the same facts |
| the Wikichess download | `scripts.ingest_wikichess` refuses to run, and the agent answers without passages until the articles are downloaded and indexed |

The YouTube and model keys are empty in `.env.example`, so a copy of it runs the stack without
them until they are filled in.

The ingestion refuses on purpose. An index built from the eleven notes alone would answer every
question plausibly, while describing a different corpus from the one `docs/protocol.md`
measures. When the Wikichess folder holds no article, the ingestion stops and names the command
that downloads the articles.

## Getting the keys

Each key is personal, and the repository ships none.

| Key | Issuer | Creating one |
|---|---|---|
| `LICHESS_TOKEN` | Lichess | [lichess.org/account/oauth/token/create](https://lichess.org/account/oauth/token/create), with no scope ticked: the Explorer only needs to know who is asking |
| `YOUTUBE_API_KEY` | Google Cloud | in a project of your own, enable *YouTube Data API v3*, then *Credentials*, *Create credentials*, *API key*, restricted to that API |
| `LLM_API_KEY` | OpenAI, or any OpenAI-compatible provider | [platform.openai.com/api-keys](https://platform.openai.com/api-keys), a project key; the account needs credit on its balance |

All three go in the `.env` file at the root, copied from `.env.example`, and Docker Compose
passes that file to the API container. When the demonstration is over, delete each key on the
page that created it, so that no unused key can still reach an account.

## When something stops answering

**A search hangs.** Check `docker compose logs milvus`. Each call to the vector store is allowed
three seconds (`MILVUS_TIMEOUT`). After that the route answers 503, and the message gives the
Milvus address when the connection itself failed. Without that limit, according to a comment in
`config.py`, pymilvus keeps retrying a closed port for about ten seconds. A search sent while the
embedding model is still loading at start-up also waits for that load.

**The interface shows no passage.** Either the collection has not been created, because the
volume is new and the ingestion has not run, or the embedding model could not be loaded, which
the backend log reports as `Embedding model not warmed up`. The agent then answers without
passages, and `/api/v1/vector-search` answers 503. `docker compose run --rm backend python -m scripts.ingest_wikichess` creates the
collection and prints how many articles it found in each folder.

**The history stays empty.** Persistence is best effort. When MongoDB is unavailable the backend
logs a warning, and the player still gets an answer. Look for
`Could not persist interaction to MongoDB` in `docker compose logs backend`.

**The coach says a position is out of theory when it is not.** There are two possible causes.
With no Lichess token, or when the Explorer call fails, only the local book answers, and it holds
seventeen lines. Otherwise the position has fewer than `THEORY_MIN_GAMES` master games. The panel
tells the two cases apart: when the Explorer answered with at least one game, the panel shows how
many master games reached the position. `docs/protocol.md` sweeps the threshold and reports how
many positions each value moves.

**The interface cannot reach the agent.** nginx serves the built Angular application and
forwards `/api/` to the backend. If the page loads and the panel says it cannot contact the
agent, check the proxy and the backend with `docker compose logs frontend` and
`docker compose logs backend`.

## Restarting, and what survives

Five named volumes hold the state: `milvus_data`, `etcd_data` and `minio_data` for the vector
store, `mongo_data` for the history, and `hf_cache` for the downloaded embedding model.
`docker compose restart` keeps all five, so the demonstration comes back without a new
ingestion.

`docker compose down -v` removes them. The corpus then has to be ingested again, and the
embedding model downloaded again. The downloaded articles stay, because they live on the host
under `backend/var/wikichess/`, which is mounted into the container.

## Deployment

The stack has not been deployed. It runs on one machine with Docker Compose, and every address
above is a localhost port. The repository has no orchestration manifest, ingress, secret manager
or horizontal scaling. None of these was ever exercised, and an orchestration manifest that had
not been run would document an untested deployment.

The stack does include the parts a deployment would need first: a liveness probe, a healthcheck
and a non-root user in each of the two images the repository builds, healthchecks for the four
other services in `docker-compose.yml`, a start-up order between the six services, and every
setting read from an environment variable.
