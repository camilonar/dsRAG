from abc import ABC, abstractmethod


class DocLibrary(ABC):
    """
    Defines operations to access the basic data of a library of documents
    """
    @abstractmethod
    def find_doc_ids_like(self, query: str, limit: int = 20) -> list[str]:
        """
        Finds the doc_ids that match the criteria. Implementations are expected
        to implement the equivalent of a LIKE '%query%' query

        :param query: the query string
        :param limit: the maximum number of results (default: 20)
        :return: a list of unique doc_id that match the query
        """