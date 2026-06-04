"""
Countercurrent.ai — Layer 2: Vectorization Engine
Fully powered by Google Gemini (no OpenAI dependency).
Handles text chunking, embedding generation, and Pinecone storage.
"""

import os
import json
import hashlib
import time
from typing import Optional
from dataclasses import dataclass

import tiktoken
import google.generativeai as genai
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

EMBEDDING_MODEL = "models/gemini-embedding-001"  # Google Gemini embedding model
CHUNK_SIZE      = 400    # tokens per chunk
CHUNK_OVERLAP   = 60     # token overlap between chunks
INDEX_NAME      = os.environ.get("PINECONE_INDEX_NAME", "countercurrent-signals")
EMBEDDING_DIM   = 768    # gemini-embedding-001 outputs 768 dimensions


# ── Google client setup ───────────────────────────────────────────────────────

def configure_gemini():
    """Configure Gemini with API key from .env"""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not set in .env")
    genai.configure(api_key=api_key)


# ── Pinecone ──────────────────────────────────────────────────────────────────

def get_pinecone_index():
    """Connect to Pinecone and return the index, creating it if needed."""
    api_key = os.environ.get("PINECONE_API_KEY")
    if not api_key:
        raise EnvironmentError("PINECONE_API_KEY not set in .env")

    pc = Pinecone(api_key=api_key)

    existing = [idx.name for idx in pc.list_indexes()]
    if INDEX_NAME not in existing:
        print(f"[Pinecone] Creating index '{INDEX_NAME}'...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        while not pc.describe_index(INDEX_NAME).status["ready"]:
            time.sleep(1)
        print(f"[Pinecone] Index ready")

    return pc.Index(INDEX_NAME)


# ── Chunking ──────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


def _make_chunk_id(doc_id: str, chunk_index: int) -> str:
    return hashlib.sha256(f"{doc_id}::{chunk_index}".encode()).hexdigest()[:20]


def chunk_text(
    text: str,
    doc_id: str,
    metadata: dict,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split text into overlapping token-aware chunks."""
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)

    chunks = []
    start = 0
    idx = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text_str = enc.decode(chunk_tokens)

        chunk = Chunk(
            id=_make_chunk_id(doc_id, idx),
            text=chunk_text_str,
            metadata={
                **metadata,
                "chunk_index": idx,
                "doc_id": doc_id,
            },
        )
        chunks.append(chunk)

        if end == len(tokens):
            break
        start += chunk_size - overlap
        idx += 1

    return chunks


# ── Embedding with Gemini ─────────────────────────────────────────────────────

def embed_chunks(chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
    """
    Generate embeddings for a list of chunks using Gemini text-embedding-004.
    Processes one at a time to stay within free tier rate limits.
    """
    configure_gemini()
    results = []

    for i, chunk in enumerate(chunks):
        try:
            response = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=chunk.text,
                task_type="retrieval_document",
            )
            results.append((chunk, response["embedding"]))

            if (i + 1) % 10 == 0:
                print(f"[Embed] {i + 1}/{len(chunks)} chunks embedded")

            # Small delay to respect rate limits on free tier
            time.sleep(0.1)

        except Exception as e:
            print(f"[Embed] Error on chunk {i}: {e} — skipping")
            continue

    print(f"[Embed] Done — {len(results)}/{len(chunks)} chunks embedded successfully")
    return results


# ── Upsert to Pinecone ────────────────────────────────────────────────────────

def upsert_to_pinecone(
    embedded_chunks: list[tuple[Chunk, list[float]]],
    batch_size: int = 100,
) -> int:
    """Push embedded chunks to Pinecone. Returns count upserted."""
    index = get_pinecone_index()

    vectors = [
        {
            "id": chunk.id,
            "values": embedding,
            "metadata": {**chunk.metadata, "text": chunk.text[:1000]},
        }
        for chunk, embedding in embedded_chunks
    ]

    upserted = 0
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch)
        upserted += len(batch)

    print(f"[Pinecone] Upserted {upserted} vectors")
    return upserted


# ── Semantic Search ───────────────────────────────────────────────────────────

def query_knowledge_base(
    query: str,
    top_k: int = 8,
    filter_metadata: Optional[dict] = None,
) -> list[dict]:
    """
    Semantic search against the vector DB using Gemini embeddings.

    filter_metadata examples:
        {"client_tag": "BrandX"}
        {"source": "pdf"}
        {"doc_type": "foundational"}
    """
    configure_gemini()

    # Embed the query
    response = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=query,
        task_type="retrieval_query",
    )
    query_vector = response["embedding"]

    # Search Pinecone
    index = get_pinecone_index()
    kwargs = dict(vector=query_vector, top_k=top_k, include_metadata=True)
    if filter_metadata:
        kwargs["filter"] = filter_metadata

    results = index.query(**kwargs)

    return [
        {
            "score": match.score,
            "text": match.metadata.get("text", ""),
            "source": match.metadata.get("source", ""),
            "title": match.metadata.get("title", ""),
            "url": match.metadata.get("url", ""),
            "client_tag": match.metadata.get("client_tag", ""),
            "doc_type": match.metadata.get("doc_type", ""),
            "timestamp": match.metadata.get("timestamp", ""),
        }
        for match in results.matches
    ]


# ── High-level Pipeline ───────────────────────────────────────────────────────

class VectorizationPipeline:
    """
    Orchestrates the full flow: text -> chunks -> embeddings -> Pinecone.
    Called by the Streamlit upload UI and by the signals batch processor.
    """

    def process_text(self, text: str, doc_id: str, metadata: dict) -> int:
        """Process a raw text string into Pinecone. Returns vectors upserted."""
        if not text.strip():
            return 0
        chunks = chunk_text(text, doc_id, metadata)
        print(f"[Pipeline] {len(chunks)} chunks from '{doc_id}'")
        embedded = embed_chunks(chunks)
        return upsert_to_pinecone(embedded)

    def process_pdf(self, file_bytes: bytes, filename: str, metadata: dict) -> int:
        """Extract text from PDF bytes and vectorize."""
        import io
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise ImportError("Install pypdf: pip install pypdf")

        doc_id = hashlib.sha256(file_bytes[:1000]).hexdigest()[:16]
        metadata = {**metadata, "source": "pdf", "filename": filename}
        print(f"[Pipeline] PDF '{filename}' -> {len(text)} chars extracted")
        return self.process_text(text, doc_id, metadata)

    def process_signals_batch(
        self,
        signals_path: str = "data/signals.jsonl",
        already_vectorized_path: str = "data/vectorized_ids.txt",
    ) -> int:
        """
        Read signals.jsonl and vectorize any signals not yet in Pinecone.
        Tracks processed IDs to avoid re-embedding on repeat runs.
        """
        done_ids = set()
        if os.path.exists(already_vectorized_path):
            with open(already_vectorized_path) as f:
                done_ids = set(f.read().splitlines())

        if not os.path.exists(signals_path):
            print("[Pipeline] No signals.jsonl found. Run ingestion.py first.")
            return 0

        new_signals = []
        with open(signals_path) as f:
            for line in f:
                try:
                    sig = json.loads(line)
                    if sig["id"] not in done_ids:
                        new_signals.append(sig)
                except Exception:
                    pass

        if not new_signals:
            print("[Pipeline] All signals already vectorized.")
            return 0

        print(f"[Pipeline] Vectorizing {len(new_signals)} new signals...")
        total = 0

        for sig in new_signals:
            text = f"{sig.get('title', '')}\n\n{sig.get('content', '')}"
            metadata = {
                "source":     sig.get("source", ""),
                "title":      sig.get("title", ""),
                "url":        sig.get("url", ""),
                "timestamp":  sig.get("timestamp", ""),
                "client_tag": sig.get("client_tag", ""),
                "doc_type":   "signal",
            }
            total += self.process_text(text, sig["id"], metadata)

            with open(already_vectorized_path, "a") as f:
                f.write(sig["id"] + "\n")

        print(f"[Pipeline] {total} vectors added from signals")
        return total


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pipeline = VectorizationPipeline()
    pipeline.process_signals_batch()
