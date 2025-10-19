import os
from typing import Optional

from fastapi import APIRouter, Body

from dsrag.knowledge_base import KnowledgeBase
from integrations.utils import env, kb_creation
from integrations.web.dto.knowledge_validator import AddDocumentModel

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge"])

main_kb = kb_creation.load_or_create(env.KB_NAME, {})
file_system = kb_creation.create_file_system()

@router.get("/search")
async def search(q: str, kb_id: Optional[str] = None) -> list[dict]:
    """
    Searches on the Knowledge Base

    :param q: the query string
    :param kb_id: The ID of the knowledge base that is going to be searched. If no kb_id is provided then the default
    KB is used
    """
    search_queries = [q]
    kb = _create_or_retrieve_kb(kb_id)
    results = kb.query(search_queries)

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
    if not is_local:
        file_path = file_system.download_to_disk(env.KB_NAME, doc_id, doc_id)
    else:
        file_path = f"{env.KB_NAME}/{doc_id}/{doc_id}"

    kb = _create_or_retrieve_kb(kb_id)
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

def _create_or_retrieve_kb(kb_id: Optional[str] = None) -> KnowledgeBase:
    if not kb_id:
        return main_kb
    else:
        return kb_creation.load_or_create(kb_id, mandatory_metadata={"kb_id": kb_id})