from fastapi import APIRouter

from integrations.utils import env, kb_creation

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge"])

kb = kb_creation.load_kb(env.KB_NAME)

@router.get("/search")
async def search(q: str) -> list[dict]:
    """
    Searches on the Knowledge Base
    """
    search_queries = [q]
    results = kb.query(search_queries)
    return results

@router.post("/documents")
async def add_document(doc_id: str, file_path: str) -> dict:
    """
    Adds a document to the Knowledge Base
    """
    kb.add_document(doc_id=doc_id, file_path=file_path)
    return {"detail": "Document added."}