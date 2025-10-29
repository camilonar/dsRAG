import datetime
import io
import json
import os
from typing import Optional, List

from google.auth import default, compute_engine
from google.auth.transport import requests
from google.cloud import storage

from dsrag.dsparse.file_parsing.file_system import FileSystem
from integrations.utils import env, mime_utils
from integrations.utils.cloud_file_system import CloudFileSystem


class CloudStorageFileSystem(FileSystem, CloudFileSystem):
    """
    Uses Google Cloud Storage and DynamoDB to store and retrieve page image files and other data.
    This uses the default credentials that are automatically configured when you deploy an application in some Google
    Cloud environments (e.g. Cloud Run, Compute Engine, Cloud Functions) and that you can configure by setting the
    GOOGLE_CLOUD_CREDENTIALS environment variable
    """

    def __init__(self, base_path: str, bucket_name: str, in_cloud: bool = False):
        super().__init__(base_path)
        self.in_cloud = in_cloud
        self.bucket_name = bucket_name
        self.storage_client, self.signing_credentials = self.create_cloud_storage_client()

    @staticmethod
    def format_doc_id_folder(doc_id: str) -> str:
        return doc_id.rsplit(".", 1)[0]

    def create_cloud_storage_client(self) -> tuple:
        """
        Creates and authenticates the client to connect to Cloud Storage.
        The signing credentials can be used to generated signed URLs if needed.
        """
        if self.in_cloud:
            credentials, _ = default()
            auth_request = requests.Request()
            credentials.refresh(auth_request)
            _signing_credentials = compute_engine.IDTokenCredentials(
                auth_request, "", service_account_email=credentials.service_account_email
            )
        else:
            credentials = None
            _signing_credentials = None

        _storage_client = storage.Client(credentials=credentials)
        return _storage_client, _signing_credentials

    def create_directory(self, kb_id: str, doc_id: str) -> None:
        """
        This function is not needed for Cloud Storage
        """
        pass

    def delete_directory(self, kb_id: str, doc_id: str) -> List[dict]:
        """
        Delete the directory in Cloud Storage. Used when deleting a document.
        """

        prefix = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/"

        # List all objects with the specified prefix
        blobs = self.storage_client.list_blobs(bucket_or_name=self.bucket_name, prefix=prefix)
        objects_to_delete = []

        for blob in blobs:
            blob.delete()
            objects_to_delete.append({'key': blob.name})

        print(f"Deleted all objects in {prefix} from {self.bucket_name}.")
        return objects_to_delete

    def delete_kb(self, kb_id: str) -> list[dict]:
        """
        Delete the knowledge base
        """
        prefix = f"{kb_id}/"

        # List all objects with the specified prefix
        blobs = self.storage_client.list_blobs(bucket_or_name=self.bucket_name, prefix=prefix)
        objects_to_delete = []

        for blob in blobs:
            blob.delete()
            objects_to_delete.append({'key': blob.name})

        print(f"Deleted all objects in {prefix} from {self.bucket_name}.")
        return objects_to_delete

    def save_bytes(self, file_name: str, content: bytes | str, content_type: str):
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(file_name)

            blob.upload_from_string(
                content,
                content_type=content_type,
            )
            print(f"Data uploaded to {self.bucket_name}/{file_name}.")
        except Exception as e:
            raise RuntimeError(f"Failed to upload data to Cloud Storage.") from e

    def save_json(self, kb_id: str, doc_id: str, file_name: str, file: dict) -> None:
        """
        Save the JSON file to Cloud Storage
        """

        file_name = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/{file_name}"
        json_data = json.dumps(file, indent=2)  # Serialize the JSON data

        self.save_bytes(file_name, json_data, 'application/json')

    def save_image(self, kb_id: str, doc_id: str, file_name: str, file: any) -> None:
        """
        Upload the file to Cloud Storage
        """
        file_name = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/{file_name}"
        buffer = io.BytesIO()
        file.save(buffer, format='JPEG')
        buffer.seek(0)  # Rewind the buffer to the beginning

        self.save_bytes(file_name, buffer.getvalue(), content_type='image/jpeg')

    def get_files(self, kb_id: str, doc_id: str, page_start: int, page_end: int) -> List[str]:
        """
        Get the file from Cloud Storage
        - page_start: int - the starting page number
        - page_end: int - the ending page number (inclusive)
        """
        if page_start is None or page_end is None:
            return []

        file_paths = []
        bucket = self.storage_client.bucket(self.bucket_name)

        # Try multiple extensions for backward compatibility, but only return first found per page
        for i in range(page_start, page_end + 1):
            found_file = False
            for ext in ['.jpg', '.jpeg', '.png']:  # Try in order of preference
                filename = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/page_{i}{ext}"
                output_folder = os.path.join(self.base_path, kb_id, doc_id)
                if not os.path.exists(output_folder):
                    try:
                        os.makedirs(output_folder)
                    except FileExistsError:
                        # Since this function can be called in parallel, the folder may have been created by another process
                        pass
                output_filepath = os.path.join(self.base_path, filename)
                try:
                    blob = bucket.blob(filename)
                    blob.download_to_filename(output_filepath)
                    file_paths.append(output_filepath)
                    found_file = True
                    break  # Found file for this page, don't try other extensions
                except Exception as e:
                    # File doesn't exist with this extension, try next extension
                    continue

            if not found_file:
                print(f"Warning: No image file found for page {i} in Cloud Storage")

        return file_paths

    def get_all_jpg_files(self, kb_id: str, doc_id: str) -> List[str]:
        """
        Get all JPG files from a specific S3 directory and download them to local storage.
        Returns a sorted list of local file paths.

        Args:
            kb_id (str): Knowledge base ID
            doc_id (str): Document ID

        Returns:
            List[str]: Sorted list of local file paths for the downloaded images
        """
        prefix = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/"

        try:
            # List all objects with the specified prefix
            blobs = self.storage_client.list_blobs(bucket_or_name=self.bucket_name, prefix=prefix)

            # Filter for image files (support multiple formats for backward compatibility)
            blobs = [blob for blob in blobs
                         if blob.name.lower().endswith(('.jpg', '.jpeg', '.png'))]

            # Create local directory if it doesn't exist
            output_folder = os.path.join(self.base_path, kb_id, doc_id)
            os.makedirs(output_folder, exist_ok=True)

            # Download each file
            local_file_paths = []
            for blob in blobs:
                if not blob.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue

                local_path = os.path.join(self.base_path, blob.name)
                try:
                    blob.download_to_filename(local_path)
                    local_file_paths.append(local_path)
                except Exception as e:
                    print(f"Error downloading file {blob.name}: {e}")
                    continue

            # Sort the files by page number, similar to LocalFileSystem
            local_file_paths.sort(key=lambda x: int(x.split('_')[-1].split('.')[0]))
            return local_file_paths

        except Exception as e:
            print(f"Error listing/downloading files from Cloud Storage: {e}")
            return []

    def log_error(self, kb_id: str, doc_id: str, error: dict) -> None:
        print(f"Error on [{kb_id}] - [{doc_id}]: {error}")

    def save_page_content(self, kb_id: str, doc_id: str, page_number: int, content: str) -> None:
        """Save the text content of a page to Cloud Storage"""
        file_name = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/page_content_{page_number}.json"
        data = json.dumps({"content": content})

        self.save_bytes(file_name, data, content_type='application/json')

    def load_page_content(self, kb_id: str, doc_id: str, page_number: int) -> Optional[str]:
        """Load the text content of a page from Cloud Storage"""
        file_name = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/page_content_{page_number}.json"
        bucket = self.storage_client.bucket(self.bucket_name)

        try:
            blob = bucket.blob(file_name)
            data = json.loads(blob.download_as_bytes())
            return data
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Cloud Storage file {file_name}: {str(e)}")
            return None
        except Exception as e:
            print(f"Error loading page content from Cloud Storage: {str(e)}")
            return None

    def load_page_content_range(self, kb_id: str, doc_id: str, page_start: int, page_end: int) -> list[str]:
        """Load the text content for a range of pages from Cloud Storage"""
        page_contents = []
        for page_num in range(page_start, page_end + 1):
            content = self.load_page_content(kb_id, doc_id, page_num)
            if content is not None:
                page_contents.append(content)
        return page_contents

    def to_dict(self):
        base_dict = super().to_dict()
        base_dict.update({
            "bucket_name": self.bucket_name
        })
        return base_dict

    def load_data(self, kb_id: str, doc_id: str, data_name: str) -> Optional[dict]:
        """Load JSON data from a file in Cloud Storage"""
        filename = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/{data_name}.json"
        bucket = self.storage_client.bucket(self.bucket_name)

        try:
            blob = bucket.blob(filename)
            return json.loads(blob)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Cloud Storage file {filename}: {str(e)}")
            return None
        except Exception as e:
            print(f"Error loading data from Cloud Storage: {str(e)}")
            return None

    def __create_storage_client(self):
        if env.IN_CLOUD:
            credentials, _ = default()
            auth_request = requests.Request()
            credentials.refresh(auth_request)
            _signing_credentials = compute_engine.IDTokenCredentials(
                auth_request, "", service_account_email=credentials.service_account_email
            )
        else:
            credentials = None
            _signing_credentials = None

        _storage_client = storage.Client(credentials=credentials)
        return _storage_client, _signing_credentials

    def generate_signed_url(self, metadata: dict, method: str = "GET", max_file_size: int = 10000000) -> dict:
        _bucket = metadata.get("bucket")
        _file_path = metadata.get("file_path")

        if not _bucket or not _file_path:
            return {"url": "not available", "headers": None}

        try:
            bucket = self.storage_client.bucket(_bucket)
            blob = bucket.blob(_file_path)
            headers = None

            if method == "PUT":
                headers = {
                    "x-goog-content-length-range": f"0,{max_file_size}",
                    "Content-Type": mime_utils.guess_type(_file_path)[0],
                }

            url = blob.generate_signed_url(
                version="v4",
                credentials=self.signing_credentials,
                expiration=datetime.timedelta(minutes=env.SIGNED_URL_EXPIRATION_TIME),
                method=method,
                headers=headers,
            )
            return {"url": url, "headers": headers}

        except Exception as e:
            print(f"Exception - Generate Signed URL: {str(e)}")
            return {"url": "not available", "headers": None}

    def generate_download_url(self, kb_id: str, doc_id: str, file_name: str) -> dict:
        file_path = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/{file_name}"
        metadata = {"bucket": self.bucket_name, "file_path": file_path}
        upload_url = self.generate_signed_url(metadata)
        return {"path": file_path, "download_url": upload_url}

    def generate_upload_url(self, kb_id: str, doc_id: str, file_name: str, max_file_size: int = 10000000) -> dict:
        file_path = f"{kb_id}/{self.format_doc_id_folder(doc_id)}/{file_name}"
        metadata = {"bucket": self.bucket_name, "file_path": file_path}
        download_url = self.generate_signed_url(metadata, method="PUT", max_file_size=max_file_size)
        return {"path": file_path, "upload_url": download_url}

    def download_to_disk(self, kb_id: str, doc_id: str, file_name: str) -> str:
        doc_id = self.format_doc_id_folder(doc_id)
        file_path = f"{kb_id}/{doc_id}/{file_name}"
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(file_path)

        output_folder = os.path.join(self.base_path, kb_id, doc_id)
        os.makedirs(output_folder, exist_ok=True)

        file_path = os.path.join(self.base_path, file_path)

        blob.download_to_filename(file_path)

        return file_path