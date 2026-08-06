"""ChromaDB index over one uploaded document's chunks.

Adapted from the Chatbot project's src/store.py. Two real differences from
that version, both because Constellate has no single persistent "handbook"
the way Chatbot does:

- `build_index` takes chunks + a target directory directly, rather than a
  handbook path -- every upload gets its own ephemeral collection (see
  assistant.py), there's no one persistent index to rebuild.
- `handbook_vocabulary()` is dropped entirely. It only ever existed to feed
  the scope gate's coarse "is this corpus-adjacent at all" pre-check, and
  Constellate has no scope gate -- see retriever.py's module docstring for
  why.
"""

import chromadb
from chromadb.utils import embedding_functions

from .chunker import Chunk


def _client(chroma_dir):
    return chromadb.PersistentClient(path=str(chroma_dir))


def _embedding_fn():
    # Local ONNX MiniLM. Downloads ~80MB into ~/.cache/chroma on first use,
    # then runs entirely offline. No API key, no per-query cost -- same
    # choice Chatbot made and the same reasoning applies here: NVIDIA's
    # free tier is for the part that actually needs a language model
    # (generation), not for turning text into vectors.
    return embedding_functions.DefaultEmbeddingFunction()


def build_index(chunks, chroma_dir, collection_name, source_label, verbose=False):
    """Index one document's chunks into a fresh collection at chroma_dir.
    Destructive by design if the collection already exists there, but in
    practice chroma_dir is always a fresh temp directory (see
    assistant.py.upload_document), so there's nothing to collide with.
    """
    if not chunks:
        raise ValueError("No content to index — chunking produced zero chunks")

    collection = _client(chroma_dir).get_or_create_collection(
        name=collection_name,
        embedding_function=_embedding_fn(),
        configuration={"hnsw": {"space": "cosine"}},
    )
    collection.add(
        ids=[c.id for c in chunks],
        # Embed headings + body, but keep the clean body in metadata so the
        # assistant hands the LLM clean prose, not the heading breadcrumb.
        documents=[c.embed_text for c in chunks],
        metadatas=[
            {
                "topic": c.topic,
                "topic_label": c.topic_label,
                "section": c.section,
                "body": c.text,
                "source": source_label,
            }
            for c in chunks
        ],
    )

    if verbose:
        print(f"Indexed {len(chunks)} chunks from {source_label}")
    return len(chunks)


def get_collection(chroma_dir, collection_name):
    return _client(chroma_dir).get_collection(
        name=collection_name,
        embedding_function=_embedding_fn(),
    )


def chunk_from_result(doc, meta, chunk_id):
    # Prefer the stored body over the indexed document, which carries the
    # heading prefix used for embedding.
    return Chunk(
        id=chunk_id,
        text=meta.get("body") or doc,
        topic=meta.get("topic", ""),
        topic_label=meta.get("topic_label", ""),
        section=meta.get("section", ""),
        source=meta.get("source", "Document"),
    )
