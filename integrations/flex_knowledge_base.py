from typing import Optional

from dsrag.auto_context import get_segment_header
from dsrag.knowledge_base import KnowledgeBase
from dsrag.database.vector import VectorDB
from dsrag.database.vector.types import MetadataFilter, MetadataFilters
from dsrag.database.chunk import ChunkDB
from dsrag.embedding import Embedding
from dsrag.reranker import Reranker
from dsrag.llm import LLM
from dsrag.dsparse.file_parsing.file_system import FileSystem
from dsrag.metadata import MetadataStorage


class FlexKnowledgeBase(KnowledgeBase):
    def __init__(
            self,
            kb_id: str,
            title: str = "",
            supp_id: str = "",
            description: str = "",
            language: str = "en",
            storage_directory: str = "~/dsRAG",
            embedding_model: Optional[Embedding] = None,
            reranker: Optional[Reranker] = None,
            auto_context_model: Optional[LLM] = None,
            vector_db: Optional[VectorDB] = None,
            chunk_db: Optional[ChunkDB] = None,
            file_system: Optional[FileSystem] = None,
            exists_ok: bool = True,
            save_metadata_to_disk: bool = True,
            metadata_storage: Optional[MetadataStorage] = None,
            mandatory_metadata: dict = {}
    ):
        """Initialize a KnowledgeBase instance.

        Args:
            kb_id (str): Unique identifier for the knowledge base.
            title (str, optional): Title of the knowledge base. Defaults to "".
            supp_id (str, optional): Supplementary identifier. Defaults to "".
            description (str, optional): Description of the knowledge base. Defaults to "".
            language (str, optional): Language code for the knowledge base. Defaults to "en".
            storage_directory (str, optional): Base directory for storing files. Defaults to "~/dsRAG".
            embedding_model (Optional[Embedding], optional): Model for generating embeddings.
                Defaults to OpenAIEmbedding.
            reranker (Optional[Reranker], optional): Model for reranking results.
                Defaults to CohereReranker.
            auto_context_model (Optional[LLM], optional): LLM for generating context.
                Defaults to OpenAIChatAPI.
            vector_db (Optional[VectorDB], optional): Vector database for storing embeddings.
                Defaults to BasicVectorDB.
            chunk_db (Optional[ChunkDB], optional): Database for storing text chunks.
                Defaults to BasicChunkDB.
            file_system (Optional[FileSystem], optional): File system for storing images.
                Defaults to LocalFileSystem.
            exists_ok (bool, optional): Whether to load existing KB if it exists. Defaults to True.
            save_metadata_to_disk (bool, optional): Whether to persist metadata. Defaults to True.
            metadata_storage (Optional[MetadataStorage], optional): Storage for KB metadata.
                Defaults to LocalMetadataStorage.
            mandatory_metadata (dict, optional): metadata that must always be included in insertions and
                in searches. This can be used when multiple Knowledge Bases have access to the same collection/table
                but only can query over a subset of data based on its metadata.

        Raises:
            ValueError: If KB exists and exists_ok is False.
        """
        self.kb_metadata = {
            "mandatory_metadata": mandatory_metadata
        }
        super().__init__(kb_id, title, supp_id, description, language, storage_directory, embedding_model,
            reranker, auto_context_model, vector_db, chunk_db, file_system, exists_ok, save_metadata_to_disk,
            metadata_storage)
        self.vector_db.mandatory_metadata = self.kb_metadata["mandatory_metadata"]
        self.chunk_db.mandatory_metadata = self.kb_metadata["mandatory_metadata"]

    def add_document(
            self,
            doc_id: str,
            text: str = "",
            file_path: str = "",
            document_title: str = "",
            auto_context_config: dict = {},
            file_parsing_config: dict = {},
            semantic_sectioning_config: dict = {},
            chunking_config: dict = {},
            chunk_size: int = None,
            min_length_for_chunking: int = None,
            supp_id: str = "",
            metadata: dict = {},
    ):
        # Fuse mandatory metadata with metadata
        metadata |= self.kb_metadata["mandatory_metadata"]

        super().add_document(doc_id, text, file_path, document_title, auto_context_config, file_parsing_config,
            semantic_sectioning_config, chunking_config, chunk_size, min_length_for_chunking, supp_id,
            metadata)

    def _search(self, query: str, top_k: int,
                metadata_filter: Optional[MetadataFilter | MetadataFilters] = None) -> list:
        query_vector = self._get_embeddings([query], input_type="query")[0]

        filters = MetadataFilters(filters=[], operator="and")

        m_metadata = self.kb_metadata["mandatory_metadata"]
        for k, v in m_metadata.items():
            filters["filters"].append(MetadataFilter(field=k, operator="equals", value=v))

        if metadata_filter:
            if "filters" in metadata_filter:
                filters["filters"].extend(metadata_filter["filters"])
            else:
                filters["filters"].append(metadata_filter)
        search_results = self.vector_db.search(query_vector, top_k, filters)
        if len(search_results) == 0:
            return []
        search_results = self.reranker.rerank_search_results(query, search_results)
        return search_results

    def _get_segments_content(self, relevant_segment_info: list[dict], return_mode: str):
        for segment_info in relevant_segment_info:
            doc_id, chunk_start, chunk_end = segment_info["doc_id"], segment_info["chunk_start"], segment_info["chunk_end"]
            return_mode = self._get_return_mode(doc_id, chunk_start, chunk_end, return_mode)
            if return_mode in ("text", "simplified_text"):
                segments_details = self.chunk_db.get_segments_in_range(doc_id, chunk_start, chunk_end)
                start_page_number, end_page_number = (segments_details[0]["chunk_page_start"],
                                                      segments_details[-1]["chunk_page_end"])
                segment_header = get_segment_header(segments_details[0].get("document_title", ""),
                                                    segments_details[0].get("document_summary", "")).strip()
                segment_text = "".join(details.get("chunk_text", "") for details in segments_details).strip()
                segment_info["segment_page_start"] = start_page_number
                segment_info["segment_page_end"] = end_page_number
                if return_mode == "simplified_text":
                    segment_info["header"] = segment_header.strip()
                    segment_info["content"] = segment_text.strip()
                else:
                    segment_info["content"] = f"{segment_header.strip()}\n\n" + segment_text

                if self.backward_compatible:
                    # Deprecated keys, but needed for backwards compatibility
                    segment_info["chunk_page_start"] = start_page_number
                    segment_info["chunk_page_end"] = end_page_number

                    # Backwards compatibility, where previously the content was stored in the "text" key
                    if type(segment_info["content"]) == str:
                        segment_info["text"] = segment_info["content"]
                    else:
                        segment_info["text"] = ""
            else:
                # get the page numbers that the segment starts and ends on
                start_page_number, end_page_number = self._get_segment_page_numbers(doc_id, chunk_start, chunk_end)
                page_image_paths = self.file_system.get_files(kb_id=self.kb_id, doc_id=doc_id,
                                                              page_start=start_page_number, page_end=end_page_number)
                # If there are no page images, fallback to using text mode
                if page_image_paths == []:
                    page_image_paths = self._get_segment_content_from_database(doc_id, chunk_start, chunk_end,
                                                                               return_mode="text")
                return page_image_paths

    def _get_return_mode(self, doc_id: str, chunk_start: int, chunk_end: int, return_mode: str):
        if return_mode == "dynamic":
            # loop through the chunks in the segment to see if any of them are visual
            segment_is_visual = False
            for chunk_index in range(chunk_start, chunk_end):
                is_visual = self._get_is_visual(doc_id, chunk_index)
                if is_visual:
                    return "page_images"

            return "text"

        return return_mode