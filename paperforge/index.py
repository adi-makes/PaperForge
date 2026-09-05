import os
import logging
from typing import List, Dict, Any, Optional, Callable
from rank_bm25 import BM25Okapi
import chromadb
from paperforge.providers.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 2000


def validate_and_sanitize_batch(
    ids: List[str],
    documents: List[str],
    embeddings: Optional[List[List[float]]] = None,
    metadatas: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Validates batch input lengths, ID uniqueness, document string integrity,
    vector embedding dimension alignment, and metadata scalar value types.
    """
    if len(ids) != len(documents):
        raise ValueError(f"Batch length mismatch: {len(ids)} IDs vs {len(documents)} documents")

    if embeddings is not None:
        if len(ids) != len(embeddings):
            raise ValueError(f"Batch length mismatch: {len(ids)} IDs vs {len(embeddings)} embeddings")
        if len(embeddings) > 0:
            expected_dim = len(embeddings[0])
            if expected_dim == 0:
                raise ValueError("Embeddings cannot be empty vectors")
            for idx, emb in enumerate(embeddings):
                if not isinstance(emb, (list, tuple)):
                    raise ValueError(f"Embedding at index {idx} must be a list/tuple, got {type(emb).__name__}")
                if len(emb) != expected_dim:
                    raise ValueError(f"Embedding dimension mismatch at index {idx}: expected {expected_dim}, got {len(emb)}")

    if metadatas is not None:
        if len(ids) != len(metadatas):
            raise ValueError(f"Batch length mismatch: {len(ids)} IDs vs {len(metadatas)} metadatas")

    seen_ids = set()
    sanitized_ids = []
    for idx, raw_id in enumerate(ids):
        str_id = str(raw_id).strip()
        if not str_id:
            raise ValueError(f"Invalid empty ID at index {idx}")
        if str_id in seen_ids:
            raise ValueError(f"Duplicate ID found within batch: {str_id}")
        seen_ids.add(str_id)
        sanitized_ids.append(str_id)

    sanitized_documents = []
    for idx, doc in enumerate(documents):
        if doc is None:
            sanitized_documents.append("")
        elif not isinstance(doc, str):
            sanitized_documents.append(str(doc))
        else:
            sanitized_documents.append(doc)

    sanitized_metadatas = None
    if metadatas is not None:
        sanitized_metadatas = []
        for meta in metadatas:
            clean_meta = {}
            if isinstance(meta, dict):
                for k, v in meta.items():
                    key_str = str(k)
                    if v is None:
                        clean_meta[key_str] = ""
                    elif isinstance(v, (str, int, float, bool)):
                        clean_meta[key_str] = v
                    else:
                        clean_meta[key_str] = str(v)
            sanitized_metadatas.append(clean_meta)

    return {
        "ids": sanitized_ids,
        "documents": sanitized_documents,
        "embeddings": embeddings,
        "metadatas": sanitized_metadatas
    }


class HybridIndex:
    def __init__(self, chroma_dir: str = ".paperforge/chroma_db", embedding_provider: EmbeddingProvider = None, max_batch_size: int = MAX_BATCH_SIZE):
        self.chroma_dir = os.path.abspath(chroma_dir)
        os.makedirs(self.chroma_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.chroma_dir)
        self.collection = self.client.get_or_create_collection(name="paperforge_evidences")
        self.embedding_provider = embedding_provider
        self.max_batch_size = max_batch_size
        self.bm25_documents = []
        self.bm25_metadata = []
        self.bm25 = None

    def add_evidences(
        self,
        evidences: List[Dict[str, Any]],
        batch_progress_callback: Optional[Callable[[int, int, str], None]] = None
    ):
        """
        evidences format:
        [{
           "id": str/int,
           "extracted_content": str,
           "location_json": dict,
           "source_id": int
        }]
        """
        if not evidences:
            return

        ids = [str(ev["id"]) for ev in evidences]
        documents = [str(ev.get("extracted_content", "")) for ev in evidences]
        metadatas = [
            {
                "source_id": str(ev.get("source_id", "")),
                "location_json": str(ev.get("location_json", {})),
                "evidence_type": str(ev.get("evidence_type", "unknown"))
            }
            for ev in evidences
        ]

        total_items = len(ids)
        num_batches = (total_items + self.max_batch_size - 1) // self.max_batch_size

        if self.embedding_provider:
            embeddings = self.embedding_provider.embed_batch(documents)
        else:
            embeddings = None

        for b_idx in range(num_batches):
            start = b_idx * self.max_batch_size
            end = min(start + self.max_batch_size, total_items)

            batch_ids = ids[start:end]
            batch_documents = documents[start:end]
            batch_metadatas = metadatas[start:end]
            batch_embeddings = embeddings[start:end] if embeddings else None

            msg = f"Indexing batch {b_idx + 1}/{num_batches} ({len(batch_ids)} items)..."
            if batch_progress_callback:
                batch_progress_callback(b_idx + 1, num_batches, msg)
            logger.info(msg)

            validated = validate_and_sanitize_batch(
                ids=batch_ids,
                documents=batch_documents,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas
            )

            add_kwargs = {
                "ids": validated["ids"],
                "documents": validated["documents"],
                "metadatas": validated["metadatas"]
            }
            if validated["embeddings"] is not None:
                add_kwargs["embeddings"] = validated["embeddings"]

            self.collection.add(**add_kwargs)

        # BM25 indexing update
        for ev, meta in zip(evidences, metadatas):
            self.bm25_documents.append(str(ev.get("extracted_content", "")))
            self.bm25_metadata.append({"id": str(ev["id"]), "content": str(ev.get("extracted_content", "")), "meta": meta})
        
        tokenized_corpus = [doc.lower().split() for doc in self.bm25_documents]
        if tokenized_corpus:
            self.bm25 = BM25Okapi(tokenized_corpus)

    def delete_evidences(self, ids: List[Any]):
        """Delete evidence items from ChromaDB collection by their IDs."""
        if not ids:
            return
        string_ids = [str(i) for i in ids]
        try:
            self.collection.delete(ids=string_ids)
        except Exception:
            pass

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion (RRF) search combining Chroma vector search and BM25."""
        vector_results = []
        bm25_results = []

        # 1. Vector Search
        if self.collection.count() > 0:
            if self.embedding_provider:
                q_emb = self.embedding_provider.embed_text(query)
                res = self.collection.query(query_embeddings=[q_emb], n_results=min(top_k * 2, self.collection.count()))
            else:
                res = self.collection.query(query_texts=[query], n_results=min(top_k * 2, self.collection.count()))
            
            if res and res.get("ids") and res["ids"][0]:
                for doc_id, doc, meta in zip(res["ids"][0], res["documents"][0], res["metadatas"][0]):
                    vector_results.append({"id": doc_id, "content": doc, "meta": meta})

        # 2. BM25 Search
        if self.bm25 and self.bm25_documents:
            tokenized_query = query.lower().split()
            scores = self.bm25.get_scores(tokenized_query)
            top_bm25_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k * 2]
            for idx in top_bm25_indices:
                if scores[idx] > 0:
                    bm25_results.append(self.bm25_metadata[idx])

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_score