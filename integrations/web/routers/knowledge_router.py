import os

from fastapi import APIRouter, Body

from integrations.utils import env, kb_creation
from integrations.web.dto.knowledge_validator import AddDocumentModel

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge"])

kb = kb_creation.load_kb(env.KB_NAME)
file_system = kb_creation.create_file_system()

@router.get("/search")
async def search(q: str) -> list[dict]:
    """
    Searches on the Knowledge Base
    """
    search_queries = [q]
    results = kb.query(search_queries)
    return results

@router.post("/docs")
async def add_document(doc_id: str, is_local: bool = False, data: AddDocumentModel = Body(...)) -> dict:
    """
    Adds a document to the Knowledge Base

    :param doc_id: the ID of the document
    :param data: additional data of the document
    :param is_local: indicates if the file is already on the local system, which means that the downloading step
    can be skipped
    """
    if not is_local:
        file_path = file_system.download_to_disk(env.KB_NAME, doc_id, doc_id)
    else:
        file_path = f"{env.KB_NAME}/{doc_id}/{doc_id}"

    kb.add_document(doc_id=doc_id, file_path=file_path, metadata=data.metadata)

    if os.path.exists(file_path):
       os.remove(file_path)

    return {"detail": "Document added."}

@router.get("/docs/upload")
async def upload_document(doc_id: str) -> dict:
    """
    Generates a signed URL to upload a document
    """
    return file_system.generate_upload_url(env.KB_NAME, doc_id, doc_id)

@router.get("/docs/download")
async def download_document(doc_id: str) -> dict:
    """
    Generates a signed URL to download an existing document
    """
    return file_system.generate_download_url(env.KB_NAME, doc_id, doc_id)