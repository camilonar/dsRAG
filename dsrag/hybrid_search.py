from abc import ABC, abstractmethod
from collections.abc import Iterable


class HybridSearch(ABC):
    """Interface for combining results from multiple search strategies."""

    subclasses = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.subclasses[cls.__name__] = cls

    def to_dict(self):
        return {
            "subclass_name": self.__class__.__name__,
        }

    @classmethod
    def from_dict(cls, config):
        config = dict(config or {})
        subclass_name = config.pop("subclass_name", None)
        subclass = cls.subclasses.get(subclass_name)
        if subclass:
            return subclass(**config)
        raise ValueError(f"Unknown subclass: {subclass_name}")

    @abstractmethod
    def hybrid_search(
        self, text_search_results: list, vector_search_results: list
    ) -> list:
        """Combine ranked text and vector search results."""
        pass

    def combine_search_results(
        self, text_search_results: list, vector_search_results: list
    ) -> list:
        """Alias for :meth:`hybrid_search`."""
        return self.hybrid_search(text_search_results, vector_search_results)


class RelativeScoreFusion(HybridSearch):
    """Combine search results using weighted relative-score fusion.

    Scores from each search strategy are min-max normalized independently before
    they are combined. ``alpha`` is the vector-search weight; text search has
    weight ``1 - alpha``.
    """

    def __init__(self, alpha: float = 0.5):
        if not 0 <= alpha <= 1:
            raise ValueError("alpha must be between 0 and 1")
        self.alpha = alpha

    @staticmethod
    def _result_key(result: dict):
        metadata = result.get("metadata") or {}
        doc_id = result.get("doc_id")
        if doc_id is None:
            doc_id = metadata.get("doc_id")
        chunk_index = result.get("chunk_index")
        if chunk_index is None:
            chunk_index = metadata.get("chunk_index")
        return doc_id, chunk_index

    @staticmethod
    def _relative_scores(results: Iterable) -> dict:
        results = list(results)
        if not results:
            return {}

        scores = [float(result.get("similarity", 0.0)) for result in results]
        minimum = min(scores)
        score_range = max(scores) - minimum
        if score_range == 0:
            # A single result, or a list with tied scores, should remain a
            # valid candidate instead of being discarded as irrelevant.
            normalized_scores = [1.0] * len(results)
        else:
            normalized_scores = [
                (score - minimum) / score_range for score in scores
            ]

        return {
            RelativeScoreFusion._result_key(result): normalized_score
            for result, normalized_score in zip(results, normalized_scores)
        }

    def hybrid_search(
        self, text_search_results: list, vector_search_results: list
    ) -> list:
        text_scores = self._relative_scores(text_search_results)
        vector_scores = self._relative_scores(vector_search_results)

        # Keep one result object for each chunk. Vector results are preferred
        # when a chunk occurs in both lists because they carry the canonical
        # vector-search result shape; the metadata is shared by both paths.
        results_by_key = {}
        for result in text_search_results:
            results_by_key[self._result_key(result)] = result
        for result in vector_search_results:
            results_by_key[self._result_key(result)] = result

        fused_results = []
        for key, result in results_by_key.items():
            fused_score = (
                (1 - self.alpha) * text_scores.get(key, 0.0)
                + self.alpha * vector_scores.get(key, 0.0)
            )
            fused_result = dict(result)
            fused_result["similarity"] = fused_score
            fused_results.append(fused_result)

        return sorted(
            fused_results,
            key=lambda result: result["similarity"],
            reverse=True,
        )

    def to_dict(self):
        return {
            **super().to_dict(),
            "alpha": self.alpha,
        }
