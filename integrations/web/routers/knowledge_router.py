import os
from typing import Optional

from fastapi import APIRouter, Body
from fastapi.params import Query, Depends

from dsrag.database.vector.types import MetadataFilter, MetadataFilters
from dsrag.knowledge_base import KnowledgeBase
from integrations.utils import env, kb_creation
from integrations.web.dto.knowledge_validator import AddDocumentModel, SearchDocumentModel

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge"])

main_kb = kb_creation.load_or_create(env.KB_NAME, {})
cache_kb = {} # Small cache to store Knowledge bases that have been recently used
file_system = kb_creation.create_file_system()

@router.get("/search")
async def search(query: SearchDocumentModel = Depends()) -> list[dict]:
    """
    Searches on the Knowledge Base

    :param query: the query parameters
    """
    search_queries = [query.q]
    kb = _create_or_retrieve_kb(query.kb_id)
    mfilters = MetadataFilters(filters=[], operator="and")
    eq_filters = query.model_dump(include={"year", "court", "p_type"}, exclude_defaults=True, exclude_none=True)
    for k, v in eq_filters.items():
        mfilters["filters"].append(MetadataFilter(field=k, operator="equals", value=str(v)))

    in_filters = query.model_dump(include={"doc_ids"}, exclude_defaults=True, exclude_none=True)
    for k, v in in_filters.items():
        mfilters["filters"].append(MetadataFilter(field=k[:-1], operator="in", value=v))
    results = kb.query(search_queries, return_mode="simplified_text", metadata_filter=mfilters)

    return results

@router.post("/docs")
async def add_document(doc_id: str, kb_id: Optional[str] = None, is_local: bool = False, data: AddDocumentModel = Body(...)) -> dict:
    """
    Adds a document to the Knowledge Base

    :param doc_id: the ID of the document
    :param kb_id: The ID of the knowledge base where the document is going to be added. If no kb_id is provided then the
     default KB will be used
    :param data: additional data of the document
    :param is_local: indicates if the file is already on the local system, which means that the downloading step
    can be skipped
    """
    kb_name = kb_id if kb_id else env.KB_NAME
    if not is_local:
        file_path = file_system.download_to_disk(kb_name, doc_id, doc_id)
    else:
        file_path = f"{kb_name}/{doc_id}/{doc_id}"

    kb = _create_or_retrieve_kb(kb_name)
    kb.add_document(doc_id=doc_id, file_path=file_path, metadata=data.metadata)

    if os.path.exists(file_path):
       os.remove(file_path)

    return {"detail": "Document added."}

@router.get("/docs/upload")
async def upload_document(doc_id: str, kb_id: Optional[str] = None) -> dict:
    """
    Generates a signed URL to upload a document
    """
    kb_name = kb_id if kb_id else env.KB_NAME
    return file_system.generate_upload_url(kb_name, doc_id, doc_id)

@router.get("/docs/download")
async def download_document(doc_id: str, kb_id: Optional[str] = None) -> dict:
    """
    Generates a signed URL to download an existing document
    """
    kb_name = kb_id if kb_id else env.KB_NAME
    return file_system.generate_download_url(kb_name, doc_id, doc_id)

@router.get("/docs/id")
async def find_doc_ids(doc_id: str = Query(..., min_length=3), kb_id: Optional[str] = None) -> list[str]:
    """
    Finds the available document IDs
    """
    kb = _create_or_retrieve_kb(kb_id)
    doc_ids = kb.vector_db.find_doc_ids_like(doc_id, limit=20)
    return doc_ids

def _create_or_retrieve_kb(kb_id: Optional[str] = None) -> KnowledgeBase:
    if not kb_id:
        return main_kb
    else:
        if kb_id in cache_kb:
            return cache_kb[kb_id]
        new_kb = kb_creation.load_or_create(kb_id, mandatory_metadata={"kb_id": kb_id})
        cache_kb[kb_id] = new_kb
        if len(cache_kb) > env.MAX_KB_CACHE:
            cache_kb.pop(next(iter(cache_kb)))
        return new_kb
