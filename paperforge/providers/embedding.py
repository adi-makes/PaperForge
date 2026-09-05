import torch
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

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
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", device: Optional[str] = None):
        self.model_name = model_name
        if device is None or device.lower() == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)

    def check_health(self) -> Dict[str, Any]:
        try:
            from sentence_transformers import SentenceTransformer
            device_name = self.device
            if self.device == "cuda" and torch.cuda.is_available():
                device_name = f"cuda ({torch.cuda.get_device_name(0)})"
            return {
                "status": True, 
                "message": f"Local SentenceTransformer available ({self.model_name}) on device: {device_name}"
            }
        except Exception as e:
            return {"status": False, "message": f"Failed to load sentence_transformers: {str(e)}"}

    def embed_text(self, text: str) -> List[float]:
        self._load()
        with torch.inference_mode():
            vec = self._model.encode(text, convert_to_numpy=True, device=self.device)
        return vec.tolist()

    def embed_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        if not texts:
            return []
        self._load()
        with torch.inference_mode():
            vecs = self._model.encode(
                texts, 
                batch_size=batch_size, 
                show_progress_bar=False, 
                convert_to_numpy=True, 
                device=self.device
            )
        return vecs.tolist()


def get_embedding_provider(config: Dict[str, Any]) -> EmbeddingProvider:
    emb_cfg = config.get("embeddings", {})
    provider = emb_cfg.get("provider", "local").lower()
    device = emb_cfg.get("device", "auto")
    
    if provider in ["local", "huggingface", "sentence_transformers"]:
        model_name = emb_cfg.get("model", "BAAI/bge-small-en-v1.5")
        return LocalSentenceTransformerProvider(model_name=model_name, device=device)
    else:
        # Default to local
        return LocalSentenceTransformerProvider(device=device)

