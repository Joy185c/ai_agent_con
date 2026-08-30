"""
RAG module: turn confirmed document text into searchable chunks, and pull
back the most relevant ones for a given question.

Embeddings run locally via sentence-transformers — no API key, no quota,
no per-request cost. ChromaDB persists to disk so documents survive a
server restart.
"""

import os
from typing import List

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

CHROMA_PATH = os.environ.get("CHROMA_PATH", "./chroma_data")
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

CHUNK_SIZE = 800      # characters per chunk — a rough proxy for ~150-200 tokens
CHUNK_OVERLAP = 100   # characters of overlap so context isn't cut mid-thought

_embedder: SentenceTransformer | None = None
_chroma_client = None
_collection = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedder


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PATH, settings=Settings(anonymized_telemetry=False)
        )
        _collection = _chroma_client.get_or_create_collection(name="documents")
    return _collection


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start < 0:
            start = 0
        if end >= len(text):
            break
    return [c.strip() for c in chunks if c.strip()]


def ingest_document(document_id: str, user_id: int, conversation_id: int, text: str) -> int:
    """Chunk, embed, and store a confirmed document. Returns chunk count."""
    chunks = chunk_text(text)
    if not chunks:
        return 0

    embedder = _get_embedder()
    embeddings = embedder.encode(chunks, convert_to_numpy=True).tolist()

    collection = _get_collection()
    ids = [f"{document_id}:{i}" for i in range(len(chunks))]
    metadatas = [
        {"document_id": document_id, "user_id": user_id, "conversation_id": conversation_id, "chunk_index": i}
        for i in range(len(chunks))
    ]
    collection.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    return len(chunks)


def retrieve_relevant_chunks(query: str, document_id: str, top_k: int = 4) -> List[str]:
    collection = _get_collection()
    embedder = _get_embedder()
    query_embedding = embedder.encode([query], convert_to_numpy=True).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        where={"document_id": document_id},
    )
    documents = results.get("documents", [[]])
    return documents[0] if documents else []


def delete_document(document_id: str):
    collection = _get_collection()
    collection.delete(where={"document_id": document_id})
