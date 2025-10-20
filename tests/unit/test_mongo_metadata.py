import unittest

from integrations.database.chunk.mongo_db import MongoDB
from integrations.mongo_metadata import MongoDBMetadataStorage


class TestMongoDBMetadataStorage(unittest.TestCase):

    @classmethod
    def setUpClass(self):
        self.kb_id = "kb_test"
        self.collection_name = "kb_metadata"
        self.db_name = "test_mongo_db"
        self.uri = "mongodb://localhost:27017"
        self.db = MongoDBMetadataStorage(
            self.db_name,
            self.uri,
            self.collection_name
        )
        # return super().setUp()

    @classmethod
    def tearDownClass(self):
        self.db.delete(self.kb_id)
        # return super().tearDownClass()

    def test__load_and_save(self):
        data = self.db.load(self.kb_id)
        self.assertEqual({}, data)

        metadata = {
                    "language": "es",
                    "vector_db": {
                            "sample": 1
                        }
                    }

        self.db.save(metadata, self.kb_id)
        data = self.db.load(self.kb_id)
        self.assertEqual(metadata, data)

    def test__save_existing(self):
        metadata = {
                    "language": "es",
                    "vector_db": {
                        "sample": 1,
                        "test": "test__save_existing"
                        }
                    }

        self.db.save(metadata, self.kb_id)
        data = self.db.load(self.kb_id)
        self.assertEqual(metadata, data)

        new_metadata = {
            "language": "en",
            "vector_db": {
                "sample": 2,
                "test": "test__save_existing_2"
            }
        }

        self.db.save(new_metadata, self.kb_id)
        data = self.db.load(self.kb_id)
        self.assertEqual(new_metadata, data)

    def test__delete(self):
        metadata = {
            "language": "es",
            "vector_db": {
                "sample": 1,
                "test": "test__save_existing"
            }
        }

        self.db.save(metadata, self.kb_id)
        self.db.delete(self.kb_id)
        data = self.db.load(self.kb_id)
        self.assertEqual({}, data)

# Run all tests
if __name__ == "__main__":
    unittest.main()