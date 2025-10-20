from dsrag.embedding import VoyageAIEmbedding
from dsrag.knowledge_base import KnowledgeBase
from dsrag.llm import OpenAIChatAPI
from dsrag.metadata import MetadataStorage
from dsrag.reranker import VoyageReranker
from integrations.database.chunk.mongo_db import MongoDB
from integrations.database.vector.mongo_atlas_db import MongoAtlasDB
from integrations.dsparse.file_parsing.cloud_storage_file_system import CloudStorageFileSystem
from integrations.flex_knowledge_base import FlexKnowledgeBase
from integrations.mongo_metadata import MongoDBMetadataStorage
from integrations.utils import env

main_ms = MongoDBMetadataStorage(db_name=env.DB_NAME, uri=env.MONGODB_URI, collection_name=env.KB_COLLECTION_NAME)

def __create_kb(kb_id: str, metadata_storage: MetadataStorage, mandatory_metadata: dict) -> KnowledgeBase:
    base_name = env.KB_NAME if not kb_id or kb_id == env.KB_NAME else f"{env.KB_NAME}_local"
    vector_db = MongoAtlasDB(db_name=env.DB_NAME, kb_id=kb_id, uri=env.MONGODB_URI, dimension=env.EMBEDDING_MODEL_DIM,
                             collection_name=f"{base_name}_vector")
    chunk_db = MongoDB(db_name=env.DB_NAME, kb_id=kb_id, uri=env.MONGODB_URI, collection_name=f"{base_name}_chunks")
    embedding = VoyageAIEmbedding(model=env.EMBEDDING_MODEL, dimension=env.EMBEDDING_MODEL_DIM,
                                  output_dtype=env.EMBEDDING_MODEL_TYPE)
    reranker = VoyageReranker(model=env.RERANKER_MODEL)
    llm = OpenAIChatAPI(model=env.LLM_MODEL)
    file_system = create_file_system()

    kb = FlexKnowledgeBase(kb_id=kb_id, vector_db=vector_db, chunk_db=chunk_db, embedding_model=embedding,
                       reranker=reranker, file_system=file_system, metadata_storage=metadata_storage,
                       auto_context_model=llm, language=env.KB_LANGUAGE, mandatory_metadata=mandatory_metadata)
    return kb

def create_file_system():
    file_system = CloudStorageFileSystem(base_path="/tmp", bucket_name=env.DB_NAME, in_cloud=env.IN_CLOUD)
    return file_system

def __load_kb(kb_id: str, metadata_storage: MetadataStorage) -> KnowledgeBase:
    kb = FlexKnowledgeBase(kb_id=kb_id, metadata_storage=metadata_storage)
    return kb

def load_kb(kb_id: str) -> KnowledgeBase:
    kb = __load_kb(kb_id, main_ms)
    return kb

def create_kb(kb_id: str, mandatory_metadata: dict) -> KnowledgeBase:
    kb = __create_kb(kb_id, main_ms, mandatory_metadata)
    return kb

def load_or_create(kb_id: str, mandatory_metadata: dict) -> KnowledgeBase:
    if main_ms.kb_exists(kb_id):
        return load_kb(kb_id)
    else:
        return create_kb(kb_id, mandatory_metadata)