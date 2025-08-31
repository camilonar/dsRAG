import os
import unittest
from pathlib import Path

from pdf2image import convert_from_path

from integrations.dsparse.file_parsing.cloud_storage_file_system import CloudStorageFileSystem


class TestCloudStorageFileSystem(unittest.TestCase):

    @classmethod
    def setUpClass(self):
        self.kb_id = "test_kb"
        self.doc_id = "test_doc"
        self.base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../data/dsparse_file_system_test'))
        self.cloud_storage_fs = CloudStorageFileSystem(
            base_path=self.base_path,
            bucket_name=os.environ["BUCKET_NAME"]
        )

    def test__001_create_directory(self):

        self.cloud_storage_fs.create_directory(self.kb_id, self.doc_id)
        # Nothing actually happens, but it shouldn't cause any errors

    def test__002_save_json(self):

        test_json = {
            "test_key": "test_value",
            "test_key_2": "test_value_2"
        }
        file_name = "elements.json"
        self.cloud_storage_fs.save_json(self.kb_id, self.doc_id, file_name, test_json)

    def test__003_save_image(self):

        pdf_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../tests/data/mck_energy_first_5_pages.pdf'))
        images = convert_from_path(pdf_path, dpi=150)

        file_name = "page_0.jpg"
        self.cloud_storage_fs.save_image(self.kb_id, self.doc_id, file_name, images[0])
        file_name = "page_1.jpg"
        self.cloud_storage_fs.save_image(self.kb_id, self.doc_id, file_name, images[1])

    def test__004_get_files(self):

        files = self.cloud_storage_fs.get_files(self.kb_id, self.doc_id, page_start=0, page_end=1)
        self.assertTrue(len(files) == 2)
        # Make sure the file was saved locally to the base path
        self.assertTrue(os.path.exists(os.path.join(self.base_path, self.kb_id, self.doc_id, "page_0.jpg")))

        # Try it again with the file already saved locally (Shouldn't cause any issues)
        files = self.cloud_storage_fs.get_files(self.kb_id, self.doc_id, page_start=0, page_end=1)
        self.assertTrue(len(files) == 2)

        # Test for a page that doesn't exist
        files = self.cloud_storage_fs.get_files(self.kb_id, self.doc_id, page_start=2, page_end=2)
        self.assertTrue(len(files) == 0)

    def test__005_get_all_jpg_files(self):

        files = self.cloud_storage_fs.get_all_jpg_files(self.kb_id, self.doc_id)
        self.assertTrue(len(files) == 2)
        print(files[0])
        print(os.path.join(self.base_path, self.kb_id, self.doc_id, "page_0.jpg"))
        # The only files returned should be page_0.jpg and page_1.jpg
        self.assertTrue(Path(files[0]) == Path(os.path.join(self.base_path, self.kb_id, self.doc_id, "page_0.jpg")))
        self.assertTrue(Path(files[1]) == Path(os.path.join(self.base_path, self.kb_id, self.doc_id, "page_1.jpg")))

    def test__006_delete_directory(self):

        objects_deleted = self.cloud_storage_fs.delete_directory(self.kb_id, self.doc_id)
        self.assertTrue(len(objects_deleted) == 3)
        self.assertTrue(objects_deleted[0]["key"] == f"{self.kb_id}/{self.doc_id}/elements.json")
        self.assertTrue(objects_deleted[1]["key"] == f"{self.kb_id}/{self.doc_id}/page_0.jpg")

        # Try to delete a directory that doesn't exist
        objects_deleted = self.cloud_storage_fs.delete_directory(self.kb_id, self.doc_id)
        self.assertTrue(len(objects_deleted) == 0)

    def test__007_delete_kb(self):
        self.cloud_storage_fs.create_directory(self.kb_id, self.doc_id)

        # Add a file to the directory
        pdf_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../tests/data/mck_energy_first_5_pages.pdf'))
        images = convert_from_path(pdf_path, dpi=150)

        file_name = "page_0.jpg"
        self.cloud_storage_fs.save_image(self.kb_id, self.doc_id, file_name, images[0])

        objects_deleted = self.cloud_storage_fs.delete_kb(self.kb_id)
        self.assertTrue(len(objects_deleted) == 1)
        self.assertTrue(objects_deleted[0]['key'] == f"{self.kb_id}/{self.doc_id}/page_0.jpg")

    @classmethod
    def tearDownClass(self):
        try:
            os.system(f"rm -rf {self.base_path}")
        except:
            pass


if __name__ == '__main__':
    unittest.main()