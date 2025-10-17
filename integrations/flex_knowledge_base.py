from typing import Optional
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
