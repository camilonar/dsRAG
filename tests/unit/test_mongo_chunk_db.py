import unittest

from integrations.database.chunk.mongo_db import MongoDB


class TestMongoDB(unittest.TestCase):

    @classmethod
    def setUpClass(self):
        self.collection_name = "test_mongo_kb_chunks"
        self.db_name = "test_mongo_db"
        self.kb_id = "test_mongo_kb"
        self.uri = "mongodb://localhost:27017"
        self.db = MongoDB(
            self.db_name,
            self.kb_id,
            self.uri,
            self.collection_name
        )
        # return super().setUp()

    @classmethod
    def tearDownClass(self):
        self.db.delete()
        # return super().tearDownClass()

    def test__add_and_get_chunk_text(self):
        doc_id = "doc1"
        chunks = {
            0: {
                "chunk_text": "Content of chunk 1",
                "document_title": "Title of document 1",
                "document_summary": "Summary of document 1",
                "section_title": "Section title 1",
                "section_summary": "Section summary 1",
            },
            1: {
                "chunk_text": "Content of chunk 2",
                "document_title": "Title of document 2",
                "document_summary": "Summary of document 2",
                "section_title": "Section title 2",
                "section_summary": "Section summary 2",
            },
        }
        self.db.add_document(doc_id, chunks)
        retrieved_chunk = self.db.get_chunk_text(doc_id, 0)
        self.assertEqual(retrieved_chunk, chunks[0]["chunk_text"])

    def test__get_chunk_page_numbers(self):
        # db = self.db
        doc_id = "doc1"

        chunks = {
            0: {
                "chunk_text": "Content of chunk 1",
                "document_title": "Title of document 1",
                "document_summary": "Summary of document 1",
                "section_title": "Section title 1",
                "section_summary": "Section summary 1",
                "chunk_page_start": 1,
                "chunk_page_end": 2,
            },
            1: {
                "chunk_text": "Content of chunk 2",
                "document_title": "Title of document 2",
                "document_summary": "Summary of document 2",
                "section_title": "Section title 2",
                "section_summary": "Section summary 2",
            },
        }
        self.db.add_document(doc_id, chunks)
        page_numbers = self.db.get_chunk_page_numbers(doc_id, 0)
        self.assertEqual(page_numbers, (1, 2))

        page_numbers = self.db.get_chunk_page_numbers(doc_id, 1)
        self.assertEqual(page_numbers, (None, None))

    def test__get_document_title(self):
        doc_id = "doc1"
        chunks = {0: {"document_title": "Title 1", "chunk_text": "Content of chunk 1"}}
        self.db.add_document(doc_id, chunks)
        title = self.db.get_document_title(doc_id, 0)
        self.assertEqual(title, "Title 1")

    def test__get_document_summary(self):
        doc_id = "doc1"
        chunks = {
            0: {"document_summary": "Summary 1", "chunk_text": "Content of chunk 1"}
        }
        self.db.add_document(doc_id, chunks)
        summary = self.db.get_document_summary(doc_id, 0)
        self.assertEqual(summary, "Summary 1")

    def test__get_document_content(self):
        doc_id = "doc1"
        chunks = {
            0: {"chunk_text": "Content of chunk 1"},
            1: {"chunk_text": "Content of chunk 2"},
        }
        self.db.add_document(doc_id, chunks)
        content = self.db.get_document(doc_id, include_content=True)
        self.assertEqual(content["content"], "Content of chunk 1\nContent of chunk 2")

    def test__get_section_title(self):
        doc_id = "doc1"
        chunks = {0: {"section_title": "Title 1", "chunk_text": "Content of chunk 1"}}
        self.db.add_document(doc_id, chunks)
        title = self.db.get_section_title(doc_id, 0)
        self.assertEqual(title, "Title 1")

    def test__get_section_summary(self):
        doc_id = "doc1"
        chunks = {
            0: {"section_summary": "Summary 1", "chunk_text": "Content of chunk 1"}
        }
        self.db.add_document(doc_id, chunks)
        summary = self.db.get_section_summary(doc_id, 0)
        self.assertEqual(summary, "Summary 1")

    def test__get_by_supp_id(self):
        doc_id = "doc1"
        supp_id = "Supp ID 1"
        chunks = {
            0: {"chunk_text": "Content of chunk 1"},
        }
        self.db.add_document(doc_id=doc_id, chunks=chunks, supp_id=supp_id)
        doc_id = "doc2"
        chunks = {
            0: {"chunk_text": "Content of chunk 2"},
        }
        self.db.add_document(doc_id=doc_id, chunks=chunks)
        docs = self.db.get_all_doc_ids("Supp ID 1")
        # There should only be one document with the supp_id 'Supp ID 1'
        self.assertEqual(len(docs), 1)

    def test__remove_document(self):
        doc_id = "doc1"
        chunks = {0: {"chunk_text": "Content of chunk 1"}}
        self.db.add_document(doc_id, chunks)
        self.db.remove_document(doc_id)
        results = self.db.get_document(doc_id)
        # Make sure the document does not exist, it should just be None
        self.assertIsNone(results)

    def test__save_and_load_from_dict(self):
        db = MongoDB(
            self.db_name,
            self.kb_id,
            collection_name=self.collection_name,
            uri=self.uri
        )
        config = db.to_dict()
        db2 = MongoDB.from_dict(config)
        assert db2.kb_id == db.kb_id, "Failed to load kb_id from dict."
        self.assertEqual(db2.kb_id, db.kb_id)

# Run all tests
if __name__ == "__main__":
    unittest.main()