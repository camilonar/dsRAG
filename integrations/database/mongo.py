from typing import Any, Dict, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne, UpdateMany
from pymongo.operations import SearchIndexModel


class MongoCrud:
    """
    Generic CRUD operations for MongoDB.
    """

    _instance = None

    def __new__(cls, uri: str, db_name: str):
        """
        Implements the Singleton pattern to ensure only one instance of MongoCrud exists at a time.

        :param uri: conection URI to MongoDB.
        :param db_name: database name.
        """
        if cls._instance is None:
            cls._instance = super(MongoCrud, cls).__new__(cls)
            cls._instance.client = AsyncIOMotorClient(uri)
            cls._instance._db = cls._instance.client[db_name]
        return cls._instance

    def update_document_fields(self, document: Any) -> dict:
        """
        Converts ObjectId fields to text strings.

        :param document: document that might contain ObjectId attributes.
        :return: document with ObjectId converted into str.
        """
        if not isinstance(document, dict):
            return document

        for k, v in document.items():
            if isinstance(v, ObjectId):
                document[k] = str(v)
            elif isinstance(v, list):
                document[k] = self.update_document_fields_list(v)
            elif isinstance(v, dict):
                document[k] = self.update_document_fields(v)

        return document

    def update_document_fields_list(self, documents: list[Any]) -> list[dict]:
        """
        Applies 'update_document_fields' to a list of documents.

        :param documents: List of MongoDB documents.
        :return: List of documents with ObjectId converted to strings.
        """
        return [self.update_document_fields(doc) for doc in documents]

    async def create(self, collection: str, document: Dict[str, Any]) -> str:
        """
        Creates a new document in a collection.

        :param collection: Name of the collection.
        :param document: Document data.
        :return: ID of the created document.
        :raises Exception: If an error occurs during creation.
        """
        try:
            result = await self._db[collection].insert_one(document)
            return str(result.inserted_id)
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def update(
        self,
        collection: str,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs,
    ) -> bool:
        """
        Updates a document in a collection.

        :param collection: Name of the collection.
        :param query: Filters to identify the document.
        :param update_data: Data to update.
        :param kwargs: Use additional arguments to perform updates other than '$set'.
        For example, sending: inc={'version': 1} applies the "$inc: {'version': 1}" operator.
        :return: True if at least one document was updated.
        :raises Exception: If an error occurs during the update.
        """
        try:
            operators = {"$" + k: v for k, v in kwargs.items()}
            result = await self._db[collection].update_one(
                query, {"$set": update_data} | operators
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def bulk_update(
        self, collection: str, updates: list[Dict], one_per_update: bool = True
    ) -> Dict[str, int]:
        """
        Performs a bulk update of documents.

        :param collection: Name of the collection.
        :param updates: List of dictionaries with queries and data to update.
        :param one_per_update: Indicates whether only one element per query should be updated.
        :return: Operation summary, including successful and failed updates.
        :raises Exception: If an error occurs during the bulk operation.
        """
        try:
            if one_per_update:
                bulk_updates = [
                    UpdateOne(update["query"], {"$set": update["update"]})
                    for update in updates
                ]
            else:
                bulk_updates = [
                    UpdateMany(update["query"], {"$set": update["update"]})
                    for update in updates
                ]

            result = await self._db[collection].bulk_write(bulk_updates)

            failed_updates = 0
            if result.bulk_api_result.get("writeErrors"):
                failed_updates = len(result.bulk_api_result["writeErrors"])

            return {
                "total_updated": result.modified_count,
                "total_failed": failed_updates,
            }

        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def read(
        self, collection: str, query: Dict[str, Any], projection: Dict[str, int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Reads a specific document from a collection.

        :param collection: Name of the collection.
        :param query: Filters to identify the document.
        :param projection: Indicates the fields to project (by default, all fields are projected).
        :return: Found document or None if it doesn’t exist.
        :raises Exception: If an error occurs during the read operation.
        """
        try:
            if projection:
                document = await self._db[collection].find_one(query, projection=projection)
            else:
                document = await self._db[collection].find_one(query)
            if document:
                document = self.update_document_fields(document)
            return document
        except Exception as e:
            print(f"Database - {str(e)}")

    async def delete(self, collection: str, query: Dict[str, Any]) -> bool:
        """
        Deletes a document from a collection.

        :param collection: Name of the collection.
        :param query: Filters to identify the document.
        :return: True if at least one document was deleted.
        :raises Exception: If an error occurs during the deletion.
        """
        try:
            result = await self._db[collection].delete_one(query)
            return result.deleted_count > 0
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def bulk_delete(self, collection: str, query: Dict[str, Any]) -> bool:
        """
        Deletes all documents from a collection that match a search.

        :param collection: Name of the collection.
        :param query: Filters to identify the documents.
        :return: True if at least one document was deleted.
        :raises Exception: If an error occurs during the deletion.
        """
        try:
            result = await self._db[collection].delete_many(query)
            return result.deleted_count > 0
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def list_collection(self, collection: str) -> list[dict]:
        """
        Lists all documents in a collection.

        :param collection: Name of the collection.
        :return: List of documents in the collection.
        :raises Exception: If an error occurs during the query.
        """
        try:
            documents = await self._db[collection].find().to_list(length=None)
            documents = self.update_document_fields_list(documents)
            return documents
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def list_by_query(
        self, collection: str, query: Dict[str, Any], projection: Dict[str, int] = None
    ) -> list[dict]:
        """
        Lists documents from a collection with filters and projection.

        :param collection: Name of the collection.
        :param query: Search filters.
        :param projection: Indicates the fields to project (by default, all fields are projected).
        :return: List of documents that meet the criteria.
        :raises Exception: If an error occurs during the query.
        """
        try:
            if projection:
                cursor = self._db[collection].find( query, projection)
            else:
                cursor = self._db[collection].find(query)

            documents = await cursor.to_list(length=None)
            documents = self.update_document_fields_list(documents)
            return documents
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def count_by_query(
        self, collection: str, query: Dict[str, Any]
    ) -> int:
        """
        Counts the number of items in a collection with filters.

        :param collection: Name of the collection.
        :param query: Search filters.
        :return: Count.
        :raises Exception: If an error occurs during the query.
        """
        try:
            return await self._db[collection].count_documents(query)
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def drop(self, collection: str):
        """
        Drops a collection.

        :param collection: the name of the collection.
        """
        try:
            await self._db[collection].drop()
        except Exception as e:
            print(f"Database - {str(e)}")
            raise e

    async def aggregate(self, collection: str, pipeline: list[dict]) -> list:
        docs = []
        async for doc in self._db[collection].aggregate(pipeline):
            docs.append(doc)
        return docs

    async def list_collection_names(self) -> list[str]:
        return await self._db.list_collection_names()

    async def list_search_indices(self, collection: str) -> list[dict]:
        indices = []
        async for idx in self._db[collection].list_search_indexes():
            indices.append(idx)
        return indices

    async def create_vector_index(self, collection_name: str, dimension: int, path: str = "embeddings",
                            index_name: str = None, similarity: str = "cosine", filters: list[str] = []) -> Optional[str]:
        # Define the vector search index
        if not index_name:
            index_name = collection_name + "_vector_index"

        vector_index_definition = {
            "fields": [
                {
                    "type": "vector",
                    "path": path,  # Field containing your vector embeddings
                    "numDimensions": dimension,  # Example: dimensionality of your embeddings
                    "similarity": similarity  # Example: cosine similarity
                }
            ]
        }

        for _filter in filters:
            vector_index_definition["fields"].append(
                {
                    "type": "filter",
                    "path": _filter
                }
            )

        # Create a SearchIndexModel object
        search_index_model = SearchIndexModel(
            name=index_name,
            definition=vector_index_definition,
            type="vectorSearch"
        )

        try:
            # Create the vector search index
            index_name = await self._db[collection_name].create_search_index(search_index_model)
            print(f"Vector search index '{index_name}' is being built.")
            return index_name
        except Exception as e:
            print(f"Error creating vector search index: {e}")
            return None

    async def search_by_embedding(
        self,
        collection: str,
        index: str,
        path: str,
        embedding: list[float],
        top_k: int = 5,
        num_candidates: int = 100,
        _filter: dict = {},
    ) -> list[Dict[str, Any]]:
        """
        Perform a semantic search using embeddings with MongoDB Atlas Vector Search.

        :param collection: Name of the collection.
        :param index: Name of the search index.
        :param path: Field where the embeddings are stored.
        :param embedding: Query embedding (list of floats).
        :param top_k: Number of closest results to return.
        :param num_candidates: Number of candidate documents to evaluate in the initial search phase.
        :param _filter: Contains filters and limits the search space.
        :return: List of most similar documents based on the embedding.
        """
        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": index,
                        "path": path,
                        "queryVector": embedding,
                        "numCandidates": num_candidates,
                        "limit": top_k,
                        "filter": _filter,
                    }
                },
                {
                    "$project": {
                        "score": {"$meta": "vectorSearchScore"},
                        "metadata": "$$ROOT",
                    }
                },
            ]

            cursor = self._db[collection].aggregate(pipeline)
            documents = await cursor.to_list(length=top_k)
            updated_documents = self.update_document_fields_list(
                [doc["metadata"] for doc in documents[:top_k]]
            )
            final_results = [
                {"metadata": doc, "score": documents[i]["score"]}
                for i, doc in enumerate(updated_documents)
            ]
            return final_results

        except Exception as e:
            print(f"Error on search by embedding: {str(e)}")
            return []