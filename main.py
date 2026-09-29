from fastapi import FastAPI

from integrations.web.routers import knowledge_router

import logging
import sys

# Set up a detailed formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(filename)s:%(lineno)d'
)

# Create a handler for console output
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# Configure the dsrag logger
logger = logging.getLogger("dsrag")
logger.setLevel(logging.DEBUG)

# Clear existing handlers and add our handler
if logger.hasHandlers():
    logger.handlers.clear()
logger.addHandler(console_handler)

app = FastAPI()

app.include_router(knowledge_router.router)