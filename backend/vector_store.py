"""Vector store: lightweight TF-IDF based text retrieval (no external services)."""
import logging
import os
import json
import pickle

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "tfidf_index")
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50

_index_data = None  # {"chunks": [...], "metadatas": [...], "ids": [...]}
_vectorizer = None
_tfidf_matrix = None


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def _load_index():
    """Load saved index from disk."""
    global _index_data, _vectorizer, _tfidf_matrix
    index_path = os.path.join(INDEX_DIR, "index.pkl")
    if os.path.exists(index_path):
        with open(index_path, "rb") as f:
            saved = pickle.load(f)
            _index_data = saved.get("index_data", {"chunks": [], "metadatas": [], "ids": []})
            _vectorizer = saved.get("vectorizer")
            _tfidf_matrix = saved.get("tfidf_matrix")
    else:
        _index_data = {"chunks": [], "metadatas": [], "ids": []}
        _vectorizer = None
        _tfidf_matrix = None


def _save_index():
    """Persist index to disk."""
    os.makedirs(INDEX_DIR, exist_ok=True)
    index_path = os.path.join(INDEX_DIR, "index.pkl")
    with open(index_path, "wb") as f:
        pickle.dump({
            "index_data": _index_data,
            "vectorizer": _vectorizer,
            "tfidf_matrix": _tfidf_matrix,
        }, f)


_load_index()


# ---------------------------------------------------------------------------
# Index texts
# ---------------------------------------------------------------------------

def index_texts(texts):
    """Index a list of texts into TF-IDF vector store.

    Args:
        texts: list of (text, metadata_dict) tuples or list of strings
    """
    global _index_data, _vectorizer, _tfidf_matrix

    if not texts:
        return {"indexed_chunks": 0, "indexed_sources": 0}

    # Chunk all texts
    all_chunks = []
    all_metadatas = []
    all_ids = []

    for i, item in enumerate(texts):
        if isinstance(item, tuple):
            text, meta = item
        else:
            text, meta = item, {}

        source_id = meta.get("source_id", str(i))
        chunks = chunk_text(text)

        for j, chunk in enumerate(chunks):
            chunk_id = f"src{source_id}_chunk{j}"
            all_ids.append(chunk_id)
            all_chunks.append(chunk)
            all_metadatas.append({
                "source_id": str(source_id),
                "chunk_index": j,
                "total_chunks": len(chunks),
                **meta,
            })

    # Build TF-IDF vectorizer
    log.info("Building TF-IDF index for %d chunks...", len(all_chunks))
    _vectorizer = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),
        analyzer="char_wb",
    )
    _tfidf_matrix = _vectorizer.fit_transform(all_chunks)

    _index_data = {
        "chunks": all_chunks,
        "metadatas": all_metadatas,
        "ids": all_ids,
    }
    _save_index()

    log.info("Indexed %d chunks from %d sources", len(all_chunks), len(texts))
    return {"indexed_chunks": len(all_chunks), "indexed_sources": len(texts)}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query, top_k=5):
    """Search for most relevant chunks using TF-IDF cosine similarity."""
    global _index_data, _vectorizer, _tfidf_matrix

    if _tfidf_matrix is None or _tfidf_matrix.shape[0] == 0:
        return []

    # Vectorize query
    query_vec = _vectorizer.transform([query])

    # Compute cosine similarity
    from sklearn.metrics.pairwise import cosine_similarity
    scores = cosine_similarity(query_vec, _tfidf_matrix).flatten()

    # Get top-k
    top_indices = np.argsort(scores)[::-1][:top_k]
    top_indices = [i for i in top_indices if scores[i] > 0]

    chunks = _index_data.get("chunks", [])
    metadatas = _index_data.get("metadatas", [])
    ids = _index_data.get("ids", [])

    output = []
    for idx in top_indices:
        if idx < len(chunks):
            output.append({
                "id": ids[idx] if idx < len(ids) else "",
                "document": chunks[idx],
                "metadata": metadatas[idx] if idx < len(metadatas) else {},
                "distance": float(1.0 - scores[idx]),  # 0 = identical
            })

    return output


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------

def clear_collection(name="text_chunks"):
    global _index_data, _vectorizer, _tfidf_matrix
    _index_data = {"chunks": [], "metadatas": [], "ids": []}
    _vectorizer = None
    _tfidf_matrix = None
    # Remove saved index
    index_path = os.path.join(INDEX_DIR, "index.pkl")
    if os.path.exists(index_path):
        os.remove(index_path)
    return {"status": "cleared"}


def get_stats():
    chunks = _index_data.get("chunks", []) if _index_data else []
    return {
        "chunk_count": len(chunks),
        "name": "tfidf_index",
        "engine": "TF-IDF (scikit-learn)",
    }
