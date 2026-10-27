"""Load the opening knowledge base into Milvus.

Usage (from the ``backend/`` folder or inside the backend container)::

    python -m scripts.ingest_wikichess

The Wikichess articles are not tracked by git. ``scripts.fetch_wikichess``
downloads them into ``var/wikichess`` first, and this step reads them from disk
with the notes of ``data/openings``. Embedding the chunks needs the embedding
model, which is downloaded on first use when it is not in the local cache.
"""

from __future__ import annotations

from chess_coach.config import get_settings
from chess_coach.rag.ingest import ingest, knowledge_directories


def main() -> None:
    settings = get_settings()
    print(f"Embedding model : {settings.embedding_model}")
    print(f"Milvus          : {settings.milvus_host}:{settings.milvus_port}")
    print("Knowledge base:")
    for directory in knowledge_directories(settings):
        print(f"  - {directory}")

    count = ingest()
    print(f"\n{count} chunks indexed in collection '{settings.milvus_collection}'.")


if __name__ == "__main__":
    main()
