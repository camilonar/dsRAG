import os

import dotenv

dotenv.load_dotenv()

IN_CLOUD = bool(os.getenv("IN_CLOUD", False))
SIGNED_URL_EXPIRATION_TIME = int(os.getenv("SIGNED_URL_EXPIRATION_TIME", 200))

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME")
KB_COLLECTION_NAME = os.getenv("KB_COLLECTION_NAME", "knowledge_bases")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "voyage-3.5-lite")
EMBEDDING_MODEL_DIM = int(os.getenv("EMBEDDING_MODEL_DIM", 1024))
EMBEDDING_MODEL_TYPE = os.getenv("EMBEDDING_MODEL_TYPE", "int8")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "rerank-2.5-lite")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5-nano")

KB_LANGUAGE = os.getenv("KB_LANGUAGE", "es")
KB_NAME = os.getenv("KB_NAME")
BUCKET_NAME = os.getenv("BUCKET_NAME")