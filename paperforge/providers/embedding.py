from abc import ABC, abstractmethod
from typing import List, Dict, Any

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        pass


class LocalSentenceTransformerProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)

    def check_health(self) -> Dict[str, Any]:
        try:
            # Check if model can be initialized or imported
            from sentence_transformers import SentenceTransformer
            return {"status": True, "message": f"Local SentenceTransformer available ({self.model_name})"}
        except Exception as e:
            return {"status": False, "message": f"Failed to load sentence_transformers: {str(e)}"}

    def embed_text(self, text: str) -> List[float]:
        self._load()
        vec = self._model.encode(text, convert_to_numpy=True)
        return vec.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._load()
        vecs = self._model.encode(texts, convert_to_numpy=True)
        return vecs.tolist()


def get_embedding_provider(config: Dict[str, Any]) -> EmbeddingProvider:
    emb_cfg = config.get("embeddings", {})
    provider = emb_cfg.get("provider", "local").lower()
    
    if provider in ["local", "huggingface", "sentence_transformers"]:
        model_name = emb_cfg.get("model", "BAAI/bge-small-en-v1.5")
        return LocalSentenceTransformerProvider(model_name=model_name)
    else:
        # Default to local
        return LocalSentenceTransformerProvider()
