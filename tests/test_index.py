import unittest
import tempfile
from paperforge.index import HybridIndex, MAX_BATCH_SIZE
from paperforge.providers.embedding import EmbeddingProvider

class DummyEmbeddingProvider(EmbeddingProvider):
    def embed_text(self, text: str):
        return [0.1] * 384

    def embed_batch(self, texts):
        return [[0.1] * 384 for _ in texts]

    def check_health(self):
        return {"status": True}


class TestHybridIndexBatching(unittest.TestCase):
    def test_small_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index = HybridIndex(chroma_dir=tmpdir, max_batch_size=5000)
            evidences = [
                {"id": i, "extracted_content": f"content {i}", "location_json": {"line": i}, "evidence_type": "text", "source_id": 1}
                for i in range(100)
            ]
            index.add_evidences(evidences)
            self.assertEqual(index.collection.count(), 100)
            self.assertEqual(len(index.bm25_documents), 100)

    def test_large_dataset_batching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test batching with max_batch_size=1000 for 3500 items
            index = HybridIndex(chroma_dir=tmpdir, max_batch_size=1000)
            evidences = [
                {"id": i, "extracted_content": f"content {i}", "location_json": {"line": i}, "evidence_type": "text", "source_id": 1}
                for i in range(3500)
            ]
            index.add_evidences(evidences)
            self.assertEqual(index.collection.count(), 3500)
            self.assertEqual(len(index.bm25_documents), 3500)

    def test_with_embedding_provider_batching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = DummyEmbeddingProvider()
            index = HybridIndex(chroma_dir=tmpdir, embedding_provider=provider, max_batch_size=2000)
            evidences = [
                {"id": i, "extracted_content": f"content {i}", "location_json": {"line": i}, "evidence_type": "text", "source_id": 1}
                for i in range(6500)
            ]
            index.add_evidences(evidences)
            self.assertEqual(index.collection.count(), 6500)
            self.assertEqual(len(index.bm25_documents), 6500)


if __name__ == "__main__":
    unittest.main()
