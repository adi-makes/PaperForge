import unittest
import tempfile
from paperforge.index import HybridIndex, MAX_BATCH_SIZE, validate_and_sanitize_batch
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
            callbacks_received = []

            def progress_cb(b_num, b_tot, b_msg):
                callbacks_received.append((b_num, b_tot, b_msg))

            evidences = [
                {"id": i, "extracted_content": f"content {i}", "location_json": {"line": i}, "evidence_type": "text", "source_id": 1}
                for i in range(4500)
            ]
            index.add_evidences(evidences, batch_progress_callback=progress_cb)
            self.assertEqual(index.collection.count(), 4500)
            self.assertEqual(len(index.bm25_documents), 4500)
            self.assertEqual(len(callbacks_received), 3)

    def test_validation_mismatched_lengths(self):
        ids = ["1", "2"]
        docs = ["doc1"]
        with self.assertRaises(ValueError) as ctx:
            validate_and_sanitize_batch(ids, docs)
        self.assertIn("Batch length mismatch", str(ctx.exception))

    def test_validation_duplicate_ids(self):
        ids = ["1", "1"]
        docs = ["doc1", "doc2"]
        with self.assertRaises(ValueError) as ctx:
            validate_and_sanitize_batch(ids, docs)
        self.assertIn("Duplicate ID found", str(ctx.exception))

    def test_validation_dimension_mismatch(self):
        ids = ["1", "2"]
        docs = ["doc1", "doc2"]
        embeddings = [[0.1, 0.2], [0.1, 0.2, 0.3]]
        with self.assertRaises(ValueError) as ctx:
            validate_and_sanitize_batch(ids, docs, embeddings=embeddings)
        self.assertIn("Embedding dimension mismatch", str(ctx.exception))

    def test_validation_metadata_sanitization(self):
        ids = ["1"]
        docs = ["doc1"]
        metadatas = [{"nested": {"a": 1}, "number": 123, "none_val": None}]
        result = validate_and_sanitize_batch(ids, docs, metadatas=metadatas)
        sanitized_meta = result["metadatas"][0]
        self.assertEqual(sanitized_meta["number"], 123)
        self.assertEqual(sanitized_meta["none_val"], "")
        self.assertEqual(sanitized_meta["nested"], "{'a': 1}")


if __name__ == "__main__":
    unittest.main()

