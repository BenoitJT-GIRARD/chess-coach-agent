# Where the data comes from

The coach uses four sources, and only one of them is a corpus. The knowledge base is thirty-two
articles: twenty-one downloaded and eleven written for this repository. The theory comes from a
live database queried at run time. The videos come from a search API. The engine computes its
evaluations from the position alone.

This page describes each source, what its terms allow, and what the repository redistributes.

## The knowledge base

### Wikichess, twenty-one articles in English

| | |
|---|---|
| Provider | [FICGS Wikichess](https://ficgs.com/wikichess.html) |
| Read on | 2026-09-02 |
| What was taken | 21 articles, each about an opening, with its ECO code and its main line |
| Where it lands | `backend/var/wikichess/`, which git ignores |
| Index | [`backend/reports/wikichess_manifest.json`](../backend/reports/wikichess_manifest.json) |
| Terms | FICGS keeps all rights to the text of its site |

**The article files are not tracked by git, because of their licence.** The FICGS terms reserve
"the general structure, texts, images, graphism, documents, databases and every element of the
site" and allow copying games only, in PGN. The repository therefore tracks an index of the
corpus: for each article, its opening name, its ECO code, its opening moves and the page it came
from. One command downloads the articles again:

```bash
cd backend
uv run python -m scripts.fetch_wikichess
```

The download does not read the index. It follows the lines of the local opening book through
the Wikichess tree and writes every article with an opening name and at least 400 characters of
text into the folder. It then rewrites `backend/reports/wikichess_manifest.json` from every
article file in that folder. The folder is not emptied first, so an article that has disappeared
from the site stays listed for as long as its file remains. Run with `uv run` into an empty
folder, a `git diff` of the manifest shows which articles were added or lost since the committed
reading; the download date differs in any case. Run through
`docker compose run --rm`, the manifest is written inside the container and discarded with it,
because only the article folder is mounted.

### Eleven notes written in French

The notes were written for this repository, for a club player of about ten years old. They cover
the Ruy Lopez, the Italian, the Sicilian, the French, the Caro-Kann, the Scandinavian, the
Scotch, the Queen's Gambit, the King's Indian, the English and the London System. They are
stored under `backend/data/openings/` and tracked by git, because the repository wrote them.

The notes and the agent's queries are in French and the Wikichess articles are in English, so
the embedding model has to be multilingual. French queries do reach English articles. In the
ablation of `docs/protocol.md`, the Petrov, Slav and Réti cases have a single English article as
their correct answer, and the served French wording ranks it first in all three.

### What the two folders have in common, and what separates them

| | Wikichess | The written notes |
|---|---|---|
| Language | English | French |
| Tracked by git | no | yes |
| Written by | contributors of the FICGS site | this repository |
| Indexed in the same Milvus collection | yes | yes |

Each indexed passage keeps its source path, which begins with the name of its folder
(`wikichess/` or `openings/`). The API returns that path with each passage. The interface shows
the title of the article the passage comes from, in English for a downloaded article and in
French for a note.

## The theory: the Lichess Opening Explorer

| | |
|---|---|
| Provider | [Lichess Opening Explorer](https://lichess.org/api#tag/Opening-Explorer), `masters` database |
| Read at run time | yes, one call per position when a token is set |
| Frozen reading | 2026-09-07, 54 positions, in [`backend/data/eval/theory_positions.json`](../backend/data/eval/theory_positions.json) |
| Terms | according to Lichess, its data is available under the Creative Commons CC0 dedication |
| Key | optional; without one the local opening book answers |

The Explorer is a live database: the number of master games reaching a position grows as games
are added. A sweep that queried it live could not be replayed, so the fifty-four positions of the
threshold study were read once, dated and committed. The agent itself queries the live Explorer
whenever a token is set, so that the counts it quotes are current.

## The videos: the YouTube Data API

| | |
|---|---|
| Provider | [YouTube Data API v3](https://developers.google.com/youtube/v3) |
| What is requested | a search built from the opening name (`<name> chess opening tutorial explanation`), limited to embeddable videos with strict safe search |
| What is kept | the video identifier, its title, its channel, its watch URL and its thumbnail URL, for the length of the request |
| Terms | the API terms of service; the repository stores no video and no thumbnail |
| Key | optional; without one the video section stays empty |

The repository redistributes no YouTube content. The interface embeds the first video through
YouTube's own player and lists every video as a link that opens on YouTube, the form of display
the terms ask for.

## The engine: Stockfish

| | |
|---|---|
| Provider | [Stockfish](https://stockfishchess.org/), installed in the backend image |
| Licence | GPL-3.0 |
| How it is used | run as a separate process through the `stockfish` package, at depth 15 |

Stockfish computes an evaluation from the position, so it needs no data and raises no question of
provenance. It is installed from the Debian package when the image is built, and the repository
contains none of its code.

## The embedding model

| | |
|---|---|
| Model | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Provider | [Hugging Face](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) |
| Licence | Apache-2.0, as stated on the model's Hugging Face page |
| Why this one | the queries are in French and two thirds of the corpus is in English |
| Where it lands | the `hf_cache` volume, downloaded the first time the model is loaded |

## What this repository redistributes

The code and the eleven notes are under the licence in [`LICENSE`](../LICENSE). Readers download
the Wikichess articles themselves, under FICGS's terms. Apart from what the manifest records for
each article (its title, ECO code, opening moves, address and file name), nothing from the
Wikichess articles is published here.

The move-invention check saved the 42 prompts it sent to the model, in
`backend/reports/move_invention.json`. In those prompts the text of every Wikichess passage has
been swapped for the identifier of its chunk in the index the run queried, for example
`wikichess/00002-queen-s-pawn-1`, which names the article and the chunk's position in it. The
moves the citation reader found in the passage are stored beside the identifier, and `--rejudge`
counts them as given, so the published counts replay without the text. The git history still
holds earlier copies of that file and of the walkthrough notebook, and a screenshot that has since
been removed. Those contain Wikichess passages or article headers.

The Explorer counts under `backend/data/eval/` are counts of master games with the date they were
read: a measurement of the database, with no game copied from it. The screenshots under
`docs/images/` show this application. The capture of the coach shows reference games from the
Lichess masters database and the start of a passage from one of the French notes.
[`docs/images/MANIFEST.json`](images/MANIFEST.json) records for each capture what was on screen.
