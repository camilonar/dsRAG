from abc import ABC, abstractmethod


class UrlSigner(ABC):
    """
    Interface that defines operations to sign URLs. This is useful for Cloud
    Storage systems (e.g. Google Cloud Storage, Amazon S3)
    """
    subclasses = {}

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.subclasses[cls.__name__] = cls

    def to_dict(self):
        return {
            "subclass_name": self.__class__.__name__,
        }

    @classmethod
    def from_dict(cls, config) -> "UrlSigner":
        subclass_name = config.pop(
            "subclass_name", None
        )  # Remove subclass_name from config
        subclass = cls.subclasses.get(subclass_name)
        if subclass:
            return subclass(**config)  # Pass the modified config without subclass_name
        else:
            raise ValueError(f"Unknown subclass: {subclass_name}")

    @abstractmethod
    def generate_signed_url(
            self,
            metadata: dict,
            method: str = "GET",
            max_file_size: int = 10000000,
    ) -> dict:
        """
        Generates a signed URL to access a file in Google Cloud Storage.

        :param metadata: File metadata, including 'bucket' and 'file_path'.
        :param method: (optional) Allowed HTTP method for the signed URL (default is 'GET').
        :param max_file_size: Maximum file size allowed (in bytes) with method=PUT (10000000, ~10MB)
        :return: dict with 'url' to access the file, or 'not available' if an error occurs, and 'headers' that must
                be included when method=PUT
        :raises Exception: If an error occurs while generating the signed URL.
        """
        pass

    @abstractmethod
    def generate_download_url(self, kb_id: str, doc_id: str, file_name: str) -> dict:
        pass

    @abstractmethod
    def generate_upload_url(self, kb_id: str, doc_id: str, file_name: str, max_file_size: int = 10000000) -> dict:
        pass