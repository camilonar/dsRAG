from fastapi import FastAPI

from integrations.routers import knowledge_router

app = FastAPI()

app.include_router(knowledge_router.router)