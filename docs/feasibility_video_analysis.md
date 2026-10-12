# Feasibility note — video analysis for position search

> Video analysis for a chess agent
> Preparatory technical note: design of an advanced position-indexed video module
> Version 1.0, June 2026

---

## 1. Context and objective

The chess agent today helps players by analysing a game in progress, suggesting moves,
explaining plans, and pointing them at learning material. Video is central to that
material: YouTube holds a large amount of teaching content, including grandmaster
analyses, opening courses, theoretical endgames and annotated games. The agent already
recommends videos, but it does so through a plain text query sent to the YouTube search API.

That approach soon reaches its limit. When a user faces a specific position, say a Sicilian
Najdorf structure after the fifteenth move, the agent can only return a *thematic* video
such as "Understanding the Najdorf", forty-five minutes long, and the user has to scrub
through it hoping to find the relevant passage. What the user needs is the explanation of
that position, at the second where it is given. This note addresses the gap between the
granularity of the search (a video title) and the granularity of the need (a moment inside
a video).

**What the proposed system does.** It analyses a catalogue of teaching videos, automatically
extracts the chess positions displayed on screen, converts them to FEN
(*Forsyth–Edwards Notation*), and indexes them so that every position is bound to a
`(video, timestamp)` pair. The existing agent could then query the module with the exact
position of the game in progress and receive a video link pointing straight at the second
where that position is explained.

This document is a design feasibility note. It describes the system, its target
architecture around an MCP (Model Context Protocol) server, its benefits, limits, forecast
costs (CAPEX/OPEX) and risks, the alternatives, and a roadmap. It is not a software
delivery, and no development is committed at this stage.

**Scope.** The system targets videos showing a **synthetic 2D board**, the diagrams an
analysis tool such as Lichess, Chess.com or ChessBase generates, which is the overwhelming
majority of teaching content. Physical boards filmed in perspective and stylised 3D pieces
are treated as degraded cases (see §5).

---

## 2. Functional description

The system provides two distinct services that run in two very different execution
regimes: ingestion (offline, batched) and query (online, real time).

### 2.1 Catalogue ingestion (offline)

1. **Catalogue management.** A list of YouTube URLs is maintained (video ids, metadata:
   title, author, language, topic, licence). It can be enriched by hand or by automatic
   discovery over a vetted set of channels.
2. **Fetching the stream.** For each video, the stream is fetched at a resolution
   sufficient to read the board; 720p is ample for a 2D diagram.
3. **Frame sampling.** Using ffmpeg, one image is extracted at a fixed interval
   (reference rate: **one frame every 5 seconds**). A chess position stays on screen for
   several seconds; sampling every frame would be pointless and expensive.
4. **Board detection.** On each frame, a detector locates the region holding a board
   (cropping, perspective correction where needed). Frames with no board, such as the
   commentator's face, a title card or an advert, are discarded.
5. **Board-to-FEN conversion.** A vision model (something like *fenify-3D*, or an
   OpenCV grid-detection pipeline followed by a CNN classifying the 64 squares) recognises
   the piece on each square and produces a FEN string describing the position.
6. **Temporal deduplication.** This is structural, not an implementation detail. A teacher
   commenting on one position for eight minutes leaves the same diagram on screen: at one
   frame every five seconds, that single position would produce **96 identical records**,
   and the user would be offered the same video 96 times. Consecutive frames describing
   the same position are therefore collapsed into a single record, which keeps the
   timestamp of first appearance, the moment the teacher starts talking about it, which
   is where the user should be sent. A position that reappears later in the video, after
   several others, is a new record: the teacher has come back to it for a different
   reason.

   The user never receives a frame. Frames are processing artefacts, deleted after
   extraction; what the user gets is the (video, timestamp) pair, rendered as a
   timestamped link.
7. **Indexing.** Each position is stored as
   `(FEN, video_id, start_timestamp, end_timestamp, confidence, metadata)` in a queryable
   store.

### 2.2 Position query (online)

From the existing agent:

1. The agent already holds the current position as a FEN in its state.
2. It calls the module's search tool with that FEN.
3. The module queries the index and returns the video segments matching that position, or
   one very close to it, sorted by relevance and source quality.
4. The agent gives the user a deep link of the form
   `https://youtu.be/<id>?t=<seconds>`, with the title and the author.

The granularity drops from "a video" to "a second inside a video", which answers the problem
stated in §1.

### 2.3 Normalisation and tolerance

A full FEN carries the side to move, castling rights, the en-passant square and the move
counters. For a teaching search only the piece placement, the first FEN field, and ideally
the side to move are relevant, so what is indexed is a normalised key (placement + side to
move). Exact position search is the main function; approximate search (positions one or two
moves away, or identical pawn structures) is planned as an extension, to absorb small
recognition errors and widen recall.

---

## 3. Technical architecture (MCP server)

The architecture separates the ingestion chain (batched, compute-hungry) from the query
chain (light, real time), the two meeting on a shared position index. The agent reaches the
module through an MCP server implemented with FastMCP, which presents standardised tools
decoupled from the internals.

### 3.1 Architecture diagram

```mermaid
flowchart TD
    subgraph SRC["Sources"]
        YT["YouTube catalogue<br/>(URLs + metadata)"]
    end

    subgraph ING["Ingestion pipeline (offline, batched)"]
        FF["Frame extraction<br/>ffmpeg — 1 frame / 5 s"]
        DET["Board detection<br/>(locate + crop)"]
        FEN["Board-to-FEN<br/>(vision model: OpenCV + CNN / fenify-3D)"]
        DEDUP["Temporal deduplication<br/>+ confidence score"]
    end

    subgraph IDX["Position index"]
        DB[("SQL store: normalised FEN<br/>+ video_id + timestamp")]
        VEC[("Vector index<br/>(approximate search)")]
    end

    subgraph MCP["MCP server (FastMCP)"]
        T1["Tool: search_position(fen)"]
        T2["Tool: get_video_segment(id)"]
        T3["Tool: ingest_video(url)"]
    end

    subgraph APP["Application"]
        AGENT["LangGraph agent<br/>(the existing application)"]
        USER["User"]
    end

    YT --> FF --> DET --> FEN --> DEDUP --> DB
    DEDUP --> VEC
    DB --> T1
    VEC --> T1
    DB --> T2
    YT -.command.-> T3 -.triggers.-> FF
    AGENT -->|FEN query| T1
    T1 -->|segments + timestamps| AGENT
    AGENT --> T2
    AGENT --> USER
```

### 3.2 The same thing in words

`YouTube catalogue` → `ffmpeg (1 frame / 5 s)` → `board detection (crop / perspective)` →
`board-to-FEN (vision model)` → `deduplication + confidence` → `index (SQL FEN+timestamp
and vector index)`. Alongside, the MCP server reads that index and exposes three tools.
The LangGraph agent calls `search_position(fen)` with the current position, receives a
list of `(video, timestamp)` segments, and hands the user a timestamped link. The
ingestion command `ingest_video(url)` pushes a new video back to the head of the pipeline.

### 3.3 Components

- **Catalogue manager**: a table of videos (id, URL, title, author, language, topic,
  licence, ingestion status, last processed). It doubles as the work queue.
- **Frame extractor (ffmpeg)**: invoked with a rate filter (`-vf fps=1/5`), it produces the
  images without decoding the whole stream at full rate. CPU step.
- **Board detector**: finds the 8×8 grid, fixes orientation and framing. For a 2D diagram,
  contour and line detection (Hough / OpenCV) is enough; for a filmed board, a homography
  is estimated.
- **Board-to-FEN model**: the central component. It cuts the board into 64 squares,
  classifies each into 13 states (6 pieces × 2 colours + empty), and emits the FEN with an
  aggregate confidence score.
- **Deduplication module**: compares successive FENs, merges repeats, keeps the first
  timestamp and the highest confidence.
- **Position index**: a SQL store (`positions` table) for exact-key lookup on the
  indexed normalised FEN; an optional vector index encoding the position (a 64-square
  vector, or a structure embedding) for approximate search.
- **MCP server (FastMCP)**: the exposure layer. It holds no heavy domain logic; it
  translates tool calls into index queries or ingestion commands.

### 3.4 Exposed MCP tools

| Tool | Input | Output | Use |
|---|---|---|---|
| `search_position` | `fen` (placement + side to move), optional `tolerance` | list of `{video_id, title, author, timestamp, timestamped_url, score}` | Called by the agent with the current position |
| `get_video_segment` | `video_id`, `timestamp` | segment metadata, deep link, context (neighbouring positions) | Building what the user sees |
| `ingest_video` | `url` or `video_id` | ingestion status (queued/running/done), positions extracted | Catalogue administration |

### 3.5 Data flow: ingestion versus query

- **Ingestion**: asynchronous, batched, triggered when a video is added or on a schedule.
  Consumes GPU (board-to-FEN) and CPU (ffmpeg). Writes to the index. Latency is not
  critical: minutes per video are fine.
- **Query**: synchronous, triggered by the agent. Consumes almost no compute (one indexed
  read). Latency is critical: **target below 200 ms**, so that it stays invisible inside
  the conversation.

That separation keeps the GPU cost out of the user's response time, because all the heavy
work happens once, upstream.

---

## 4. Expected benefits

- **Precise relevance.** The user gets the exact *second* where their position is
  explained, instead of a whole video to scrub through. This is the main gain.
- **Reuse of the agent's state.** The agent already holds the FEN of the game in progress,
  so the user is asked for nothing extra.
- **Decoupling through MCP.** Exposing the module over MCP isolates it from the agent's
  internals. The same server could serve other clients, a web interface or another
  assistant, with no rewrite.
- **Value drawn from existing material.** Thousands of hours of good teaching sit on
  YouTube with no fine-grained index. The system creates a position-level access layer that
  exists nowhere else.
- **Incremental accumulation.** Every ingested video stays in the index, so the value grows
  with the catalogue, at a low marginal ingestion cost (see §6).
- **Approximate search later.** Beyond the exact position, the vector index would allow
  requests such as "show me videos about similar pawn structures", which would be a strong
  teaching feature.
- **Measurability.** Coverage, the share of current positions actually found in the index,
  and board-to-FEN accuracy are trackable metrics, so the delivered value can be expressed
  as a number.

---

## 5. Technical and business limits

- **Board-to-FEN accuracy.** This is the dominant risk. A single misclassified square
  produces a wrong FEN, hence a missing or wrong index key. 2D models on clean diagrams
  reach very high per-square accuracy, often above 99 %, but at 99 % per square a position
  with 32 occupied squares has roughly a 0.99³² ≈ **72 %** chance of being *entirely*
  correct. A confidence score and a rejection threshold are therefore required if the
  index is to stay clean.
- **Visual diversity.** Board colour themes, piece sets, overlays (arrows, highlighted
  squares, channel branding), banners and logos all disturb the classifier. Each style may
  need adaptation or partial retraining.
- **Camera angles and 3D pieces.** Videos of physical boards filmed in perspective, and
  stylised 3D renders, degrade reliability sharply. They are out of the priority scope and
  would be handled later, or dropped.
- **Storage volume.** Storage stays under control as long as raw frames are not kept. The
  arithmetic in §6 shows the index itself is light, a few gigabytes; the temporary frames
  dominate, but they can be deleted after processing.
- **GPU cost.** Board-to-FEN inference over the whole catalogue is the expensive step. It
  stays modest in absolute terms (see §6) because it is one-off and parallelisable.
- **Copyright and YouTube's terms.** This is a sensitive business point: downloading and
  storing frames from third-party videos touches copyright and YouTube's terms of use. The
  recommended strategy is to redistribute none of the content; keep only the FEN and the
  timestamp durably (*factual* data, not protectable); delete the frames after extraction;
  and return only a deep link to the original video, so the creator keeps the views and
  the monetisation. A legal review is needed before industrialisation.
- **Catalogue maintenance.** Videos get deleted, turned private, or re-uploaded with URLs
  and timestamps that no longer hold. Periodic link validation and a re-ingestion policy are
  required.
- **Ingestion latency versus freshness.** A newly published video is only searchable after
  it has gone through the pipeline. That delay is acceptable for teaching use, but it must
  be documented.
- **Incomplete coverage.** Not every position appears in a video, so the system adds to the
  existing search and cannot guarantee an answer to every query. A fallback, the classic
  text search, has to stay available.

---

## 6. Feasibility and cost estimate

### 6.1 Sizing assumptions

| Parameter | Value used | Why |
|---|---|---|
| Initial catalogue size | **1 000 videos** | Covers the main French- and English-language teaching channels |
| Average video length | **12 min** = 720 s | Typical order of magnitude for a course or analysis |
| Sampling rate | **1 frame / 5 s** | A position stays on screen for several seconds |
| Working resolution | 720p, JPEG ~**150 KB**/frame | Enough to read a 2D diagram |
| Share of frames holding a board | **~40 %** | The rest: commentator, titles, transitions |
| Unique positions after deduplication | **~12 / video** | A video runs through a limited number of key positions |
| Board-to-FEN inference (detection + 64 squares) | **~0.2 s/frame** on a GPU T4 | Detection + CNN pipeline |
| Object storage | **€0.02/GB/month** | Standard S3/Blob pricing, 2026 |
| GPU T4 | **€0.40/h** | On-demand cloud instance, 2026 |
| Loaded day rate | **€450/day** | Junior engineer, employer cost |

### 6.2 Order-of-magnitude arithmetic

**Frames extracted**: 720 s ÷ 5 s = **144 frames/video**, so 144 × 1 000 = **144 000
frames** for the catalogue.

**Frames holding a board**: 144 000 × 40 % ≈ **57 600 frames** actually worth running
board-to-FEN on. The others are dropped early, but the compute is budgeted over the whole
set to stay on the safe side.

**Indexed positions**: 12 × 1 000 = **~12 000** unique positions. That is the system's unit
of value.

**Storage.** Keeping *every* frame would be 144 000 × 150 KB ≈ **21.6 GB**, well under a
terabyte. In practice frames are deleted once the FEN is extracted; at most one
thumbnail per indexed position is kept: 12 000 × 150 KB ≈ **1.8 GB**. The SQL index (FEN +
metadata) weighs a few tens of megabytes. **Durable storage budget: ~2 GB.** Volume is not
the limiting factor.

**Ingestion GPU (initial catalogue)**: 144 000 frames × 0.2 s = 28 800 s ≈ **8 GPU hours**.
With margin for retries, double-cropped frames and overhead: **~12 GPU hours**. At €0.40/h
that is **~€5** to process all 1 000 videos. Counter-intuitively, the GPU cost is negligible,
and the ffmpeg extraction (CPU) is of the same order.

### 6.3 Setup costs — CAPEX

| Item | Description | Days | Cost (€) |
|---|---|---:|---:|
| Vision model R&D | Selecting and evaluating board-to-FEN, fine-tuning on diagram styles, annotated test set, confidence thresholds | 25 | 11 250 |
| Ingestion pipeline | Catalogue, ffmpeg extraction, batch orchestration, deduplication | 15 | 6 750 |
| Position index | SQL schema, FEN normalisation, vector index, queries | 10 | 4 500 |
| MCP server (FastMCP) | `search_position`, `get_video_segment`, `ingest_video`, tests | 12 | 5 400 |
| LangGraph integration | Wiring the tool into the agent, rendering timestamped links | 8 | 3 600 |
| Evaluation and quality | Precision/recall metrics, validation set, test bench | 10 | 4 500 |
| Documentation and deployment | Technical doc, CI/CD, first production rollout | 5 | 2 250 |
| **Labour subtotal** | | **85 d** | **38 250** |
| Initial infrastructure and R&D | Development GPU (~150 h), storage, environments | — | 2 000 |
| **CAPEX TOTAL** | | | **≈ €40 250** |

### 6.4 Monthly running costs — OPEX

Growth assumption: **+200 new videos a month** ingested, plus a partial control
re-ingestion.

| Item | Basis | Monthly (€) |
|---|---|---:|
| Object storage (index + thumbnails) | ~2 GB × €0.02/GB, growing ~0.4 GB/month | ~1 |
| Ingestion GPU | 200 videos × 144 frames × 0.2 s ≈ 1.6 h + margin ≈ 5 h × €0.40 | ~2 |
| CPU (ffmpeg) | Download and extraction, on-demand instance | ~5 |
| Managed database | Small managed SQL instance | ~25 |
| MCP server hosting | Small always-on VM (1 vCPU / 1–2 GB) | ~30 |
| YouTube API quota | Data API v3; the free quota is ample at this volume | 0 |
| Monitoring and logs | Basic supervision | ~5 |
| **OPEX TOTAL** | | **≈ €68/month** |

### 6.5 Cost per indexed position

A catalogue of **12 000 positions** in the first year.

- **First year** (CAPEX + 12 months of OPEX): (40 250 + 12 × 68) ÷ 12 000 ≈
  **€3.42/position**.
- **Steady state** (OPEX only, development excluded): ~€816/year ÷ ~40 800 positions (the
  initial 12 000 plus 200 videos × 12 positions × 12 months), on a growing catalogue ≈
  **€0.02/position/year**.

**How to read that.** Most of the cost is CAPEX, the vision model's R&D, and running the
system is very cheap: the GPU costs a few euros a month, thanks to the 1-frame-in-5-seconds
sampling and the deduplication. The recurring cost is mostly hosting (the MCP server and the
database) rather than compute. For 12 000 searchable positions the marginal cost is small,
so the economic case is favourable; what could block the project is technical feasibility,
meaning board-to-FEN accuracy (§5).

---

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Board-to-FEN not accurate enough (wrong FENs) | High | High | Confidence threshold and rejection of doubtful frames; approximate search to absorb errors; annotated test set and tracked accuracy |
| Uncovered visual styles (overlays, themes) | High | Medium | Multi-style fine-tuning; visual normalisation; restrict the catalogue first to channels with a standard look |
| 3D boards / filmed in perspective | Medium | Medium | Out of priority scope; filtered upstream; those videos flagged as not indexable |
| Copyright / YouTube terms dispute | Medium | High | Store only FEN + timestamp (factual data), delete frames, return deep links only; legal review |
| Broken links / deleted videos | High | Low | Periodic validity check; "unavailable" status; scheduled re-ingestion |
| Coverage too thin (positions absent from the catalogue) | Medium | Medium | Fall back on text search; prioritise ingestion by most-requested topics; measure coverage |
| Query latency too high | Low | Medium | Exact index on the primary key; cache; strict ingestion/query separation |
| Dependence on an external board-to-FEN library | Medium | Medium | Abstract the model behind an interface; keep it replaceable; independent test set |
| Cost drift as the catalogue grows | Low | Low | Costs dominated by fixed hosting; GPU stays linear and small |

---

## 8. Alternatives considered

### 8.1 Alternative A — No vision: YouTube chapters and transcripts

YouTube exposes chapters and a timestamped transcript (subtitles) for many videos. A purely
textual approach would index those transcripts and search by keyword, such as "Najdorf",
"the b5 push", or move names spoken aloud in algebraic notation.

- **Cost**: very low, with no GPU, no vision model and no heavy R&D. CAPEX is an order of
  magnitude smaller (~10–15 days).
- **Value**: limited and imprecise. A teacher talks about plans and moves without reading
  out the full position or enumerating 32 pieces, so a transcript can locate a theme but
  not an exact position. That barely improves on the present problem (§1).
- **Verdict**: useful as an economic base and as a fallback, but it does not solve
  position-level pointing.

### 8.2 Alternative B — Hybrid: transcripts plus targeted vision

This approach uses transcripts and chapters first to pre-filter the videos and the relevant
passages, then runs the expensive board-to-FEN only on those sub-segments, leaving the rest
of the catalogue untouched.

- **Cost**: intermediate. Pre-filtering sharply reduces the number of frames analysed, down
  to the segments where a board is probably being discussed, and with them the GPU time and
  the annotation effort. CAPEX is moderate.
- **Value**: high. It keeps vision's position-level precision where it matters, while
  using the free textual signal for coverage and semantic framing (a chapter title is a
  topic).
- **Verdict**: best value for money. This is the recommended endpoint: start with pure
  vision on a restricted catalogue to validate accuracy, then switch to the hybrid to scale
  economically.

| Criterion | Proposed solution (vision) | A, transcripts only | B, hybrid |
|---|---|---|---|
| Exact position search | Yes | No | Yes |
| CAPEX | High | Low | Medium |
| OPEX | Low | Very low | Low |
| Catalogue coverage | Medium | High | High |
| Technical complexity | High | Low | Medium-high |

---

## 9. Development roadmap

| Phase | Objective | Duration | Milestones | Gate |
|---|---|---|---|---|
| **0. Framing** | Scope, YouTube legal review, pilot channel selection | 2 weeks | 20–30 pilot videos listed, legal agreement in principle | Scope and compliance validated |
| **1. POC** | Prove board-to-FEN feasibility on 2D diagrams | 3 weeks | ffmpeg → board-to-FEN pipeline over 20 videos; per-square and per-position accuracy measured | **Position accuracy ≥ 70 %** on the pilot set |
| **2. MVP** | Full chain: ingestion → index → MCP → agent | 5 weeks | 200 videos ingested; `search_position` / `get_video_segment` working; LangGraph integration; latency < 200 ms | End-to-end demonstration: current position → correct timestamped link |
| **3. Evaluation** | Measure coverage and precision on real use | 2 weeks | Validation set, coverage rate, false-positive rate; calibrated confidence thresholds | Precision and coverage judged sufficient |
| **4. Industrialisation** | Scale (1 000+ videos), robustness, operations | 6 weeks | Hybrid approach (§8.2), scheduled ingestion, link validation, monitoring, CI/CD | In production, OPEX under control, supervision active |
| **5. Extensions** | Approximate search, multi-style, other MCP clients | ongoing | Vector index, similar pawn structures | Backlog prioritised by usage |

Cumulative duration to industrialisation: **~18 weeks** (≈ 4.5 months), consistent with the
85-day estimate in §6 for a small team.

**Why that order.** The POC clears risk number one, board-to-FEN accuracy, before any
heavy investment: if it fails, the project stops or falls back to alternative A at low cost.
The MVP validates the full chain and the end-to-end user experience. Industrialisation is
only committed once the value is demonstrated, and adopts the hybrid approach to keep cost
under control at scale.

---

## 10. Conclusion and recommendation

The proposed video-analysis system answers a real, specific need: moving from "a video about a
topic" to "the right second for the exact position". The architecture around an MCP server
is sound: it decouples the module cleanly from the existing agent, separates heavy ingestion
(GPU, offline) from light queries (real time), and exposes stable, reusable tools.

The economics are favourable: running cost is low (≈ **€68/month**), dominated by hosting
rather than compute, and in steady state it comes down to a few cents per indexed position.
The investment is concentrated in CAPEX (≈ **€40k**), which is the vision model's R&D.

The obstacle is accuracy: board-to-FEN has to cope with the diversity of real video styles.
The recommendation is therefore to validate that risk with a POC first (phase 1, target
position accuracy ≥ 70 %) before committing to industrialisation, then to adopt the hybrid
transcript-plus-vision approach (alternative B) to scale at the best value for money. A
fallback to text search must stay available for positions outside the catalogue.

**Recommendation**: commit to phases 0 and 1, framing and POC, about five weeks at low
cost, as a decision gate. The POC results decide whether to continue to MVP and
industrialisation, so the investment is staged and the value is demonstrated before any
large-scale rollout.
