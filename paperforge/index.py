import os
from typing import List, Dict, Any
from rank_bm25 import BM25Okapi
import chromadb
from paperforge.providers.embedding import EmbeddingProvider

class HybridIndex:
    def __init__(self, chroma_dir: str = ".paperforge/chroma_db", embedding_provider: EmbeddingProvider = None):
        self.chroma_dir = os.path.abspath(chroma_dir)
        os.makedirs(self.chroma_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.chroma_dir)
        self.collection = self.client.get_or_create_collection(name="paperforge_evidences")
        self.embedding_provider = embedding_provider
        self.bm25_documents = []
        self.bm25_metadata = []
        self.bm25 = None

    def add_evidences(self, evidences: List[Dict[str, Any]]):
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
        documents = [ev["extracted_content"] for ev in evidences]
        metadatas = [
            {
                "source_id": str(ev.get("source_id", "")),
                "location_json": str(ev.get("location_json", {})),
                "evidence_type": ev.get("evidence_type", "unknown")
            }
            for ev in evidences
        ]

        # Chroma vector indexing
        if self.embedding_provider:
            embeddings = self.embedding_provider.embed_batch(documents)
            self.collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )
        else:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )

        # BM25 indexing update
        for ev, meta in zip(evidences, metadatas):
            self.bm25_documents.append(ev["extracted_content"])
            self.bm25_metadata.append({"id": str(ev["id"]), "content": ev["extracted_content"], "meta": meta})
        
        tokenized_corpus = [doc.lower().split() for doc in self.bm25_documents]
        if tokenized_corpus:
            self.bm25 = BM25Okapi(tokenized_corpus)

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
        rrf_scores = {}
        item_map = {}
        k = 60

        for rank, item in enumerate(vector_results):
            item_id = item["id"]
            rrf_scores[item_id] = rrf_scores.get(item_id, 0.0) + (1.0 / (k + rank + 1))
            item_map[item_id] = item

        for rank, item in enumerate(bm25_results):
            item_id = item["id"]
            rrf_scores[item_id] = rrf_scores.get(item_id, 0.0) + (1.0 / (k + rank + 1))
            item_map[item_id] = item

        sorted_ids = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)
        final_results = [item_map[i] for i in sorted_ids[:top_k]]
        return final_results
