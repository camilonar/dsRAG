import os

IN_CLOUD = bool(os.getenv("IN_CLOUD", False))
SIGNED_URL_EXPIRATION_TIME = int(os.getenv("SIGNED_URL_EXPIRATION_TIME", 200))

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME")
KB_COLLECTION_NAME = os.getenv("KB_COLLECTION_NAME", "knowledge_bases")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "voyage-law-2")
EMBEDDING_MODEL_DIM = int(os.getenv("EMBEDDING_MODEL_DIM", 1024))
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "rerank-2.5-lite")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

KB_LANGUAGE = os.getenv("KB_LANGUAGE", "es")
KB_NAME = os.getenv("KB_NAME")