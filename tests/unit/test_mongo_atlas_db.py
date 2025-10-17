import time
import unittest

import numpy as np

from dsrag.database.vector import ChunkMetadata
from integrations.database.vector.mongo_atlas_db import MongoAtlasDB


class TestMongoAtlasDB(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.db_name = "test_mongo_db"
        self.kb_id = "kb_test"
        # The URI must be a connection string to MongoDB Atlas. A regular MongoDB connection won't work
        self.uri = "mongodb://localhost:27017"
        self.db = MongoAtlasDB(
            self.db_name,
            self.kb_id,
            self.uri,
            dimension=2
        )
        #return super().setUp()

    def test__001_add_vectors_and_search(self):
        vectors = [np.array([1, 0]), np.array([0, 1])]
        metadata: list[ChunkMetadata] = [
            {
                "doc_id": "1",
                "chunk_index": 0,
                "chunk_header": "Header1",
                "chunk_text": "Text1",
            },
            {
                "doc_id": "2",
                "chunk_index": 1,
                "chunk_header": "Header2",
                "chunk_text": "Text2",
            },
        ]

        self.db.add_vectors(vectors, metadata)
        time.sleep(30)
        query_vector = np.array([[1, 0]])
        results = self.db.search(query_vector, top_k=1)

        print("results", results)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["doc_id"], "1")
        self.assertGreaterEqual(results[0]["similarity"], 0.99)

    def test__002_search_with_metadata_filter(self):
        query_vector = np.array([[1, 0]])
        metadata_filter = {"field": "doc_id", "operator": "equals", "value": "1"}
        results = self.db.search(query_vector, top_k=4, metadata_filter=metadata_filter)

        print ("results", results)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["doc_id"], "1")

        # Test with the 'in' operator
        metadata_filter = {"field": "doc_id", "operator": "in", "value": ["1", "2"]}
        results = self.db.search(query_vector, top_k=4, metadata_filter=metadata_filter)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["metadata"]["doc_id"], "1")
        self.assertEqual(results[1]["metadata"]["doc_id"], "2")

    def test__002_search_with_metadata_filters(self):
        query_vector = np.array([[1, 0]])
        metadata_filters = {"filters": [{"field": "doc_id", "operator": "equals", "value": "1"},
                                        {"field": "chunk_header", "operator": "equals", "value": "Header1"}],
                            "operator": "and"}
        results = self.db.search(query_vector, top_k=4, metadata_filter=metadata_filters)

        print ("results", results)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["doc_id"], "1")

        # Test with empty results
        metadata_filters = {"filters": [{"field": "doc_id", "operator": "equals", "value": "1"},
                                        {"field": "chunk_header", "operator": "equals", "value": "Header2"}],
                            "operator": "and"}
        results = self.db.search(query_vector, top_k=4, metadata_filter=metadata_filters)
        self.assertEqual(len(results), 0)

    def test__003_remove_document(self):
        self.db.remove_document("1")
        time.sleep(1)

        num_vectors = self.db.get_num_vectors()
        print ("num_vectors", num_vectors)
        self.assertEqual(num_vectors, 1)

    def test__004_empty_search(self):
        self.db.remove_document("2")
        time.sleep(1)
        query_vector = np.array([1, 0])
        results = self.db.search(query_vector)

        self.assertEqual(len(results), 0)

    def test__005_assertion_error_on_mismatched_input_lengths(self):
        vectors = [np.array([1, 0])]
        metadata: list[ChunkMetadata] = [
            {
                "doc_id": "1",
                "chunk_index": 0,
                "chunk_header": "Header1",
                "chunk_text": "Text1",
            },
            {
                "doc_id": "2",
                "chunk_index": 1,
                "chunk_header": "Header2",
                "chunk_text": "Text2",
            },
        ]

        with self.assertRaises(ValueError) as context:
            self.db.add_vectors(vectors, metadata)
        self.assertTrue(
            "Error in add_vectors: the number of vectors and metadata items must be the same."
            in str(context.exception)
        )

    @classmethod
    def tearDownClass(self):
        # delete test data from MongoDB Atlas
        self.db.delete()
        #return super().tearDown()


if __name__ == "__main__":
    unittest.main()