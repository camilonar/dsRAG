from typing import Optional

import numpy as np
from bson import Binary
from bson.binary import BinaryVectorDtype

from dsrag.database.vector import VectorDB
from dsrag.database.vector.types import MetadataFilter, VectorSearchResult, MetadataFilters
from integrations.database.mongo import MongoCrud
from integrations.utils.async_utils import sync

def format_metadata_filters(metadata_filters: MetadataFilters) -> dict:
    filters = metadata_filters["filters"]
    operator = metadata_filters["operator"]
    if operator == "and":
        result = {"$and": []}
        ref = result["$and"]
    elif operator == "or":
        result = {"$or": []}
        ref = result["$or"]
    else:
        raise ValueError(f"Unsupported operator: {operator}")

    for _filter in filters:
        ref.append(format_metadata_filter(_filter))

    if not ref:
        return {}
    return result


def format_metadata_filter(metadata_filter: MetadataFilter) -> dict:
    field = "metadata." + metadata_filter["field"]
    operator = metadata_filter["operator"]
    value = metadata_filter["value"]

    operator_mapping = {
        "equals": "$eq",
        "not_equals": "$ne",
        "in": "$in",
        "not_in": "$nin",
        "greater_than": "$gt",
        "less_than": "$lt",
        "greater_than_equals": "$gte",
        "less_than_equals": "$lte",
    }
    formatted_operator = operator_mapping.get(operator)

    if formatted_operator == "$eq":
        formatted_metadata_filter = {field: value}
    else:
        formatted_metadata_filter = {field: {formatted_operator: value}}

    return formatted_metadata_filter


class MongoAtlasDB(VectorDB):
    """
    Class to interact with the MongoDB Atlas Vector API.
    """

    def __init__(self, db_name: str, kb_id: str, uri: str, dimension: int, collection_name: str = None,
                 index_name: str = None, metric: str = "cosine", mandatory_metadata: Optional[dict] = None) -> None:
        self.db_name = db_name
        self.kb_id = kb_id
        self.uri = uri
        self.dimension = dimension
        self.metric = metric
        self.mongo_db = MongoCrud(uri=uri, db_name=self.db_name)
        self.mandatory_metadata = mandatory_metadata if mandatory_metadata else {}

        if collection_name is not None:
            self.collection_name = collection_name
        else:
            # Strip the kb of any spaces
            kb_id = kb_id.replace(" ", "_")
            self.collection_name = f"{kb_id}_vector"

        if not index_name:
            index_name = self.collection_name + "_vector_index"
        self.index_name = index_name

    def format_query(self, query: dict):
        formatted_metadata = {"metadata." + f: v for f, v in self.mandatory_metadata.items()}
        return query | formatted_metadata

    @staticmethod
    def generate_bson_vector(vector:  list[int] | list[float], vector_dtype: BinaryVectorDtype):
        return Binary.from_vector(vector, vector_dtype)

    def add_vectors(self, vectors: list, metadata: list):
        # Convert NumPy arrays to lists
        vectors_as_lists = [vector.tolist() if isinstance(vector, np.ndarray) else vector for vector in vectors]
        try:
            assert len(vectors_as_lists) == len(metadata)
        except AssertionError:
            raise ValueError(
                "Error in add_vectors: the number of vectors and metadata items must be the same."
            )

        # Generate BSON vector from the float32 or int8 embeddings. Assume all vectors are of the same type
        if isinstance(vectors_as_lists[0][0], int):
            dtype = BinaryVectorDtype.INT8
        else:
            dtype = BinaryVectorDtype.FLOAT32
        vectors_as_lists = [self.generate_bson_vector(vector, dtype)
                            for vector in vectors_as_lists]

        # create unique ids for each vector
        ids = [f"{meta['doc_id']}_{meta['chunk_index']}" for meta in metadata]

        # convert to format that Pinecone expects - list of dictionaries including "values", "id", and "metadata"
        vectors_to_upsert = [{"embeddings": vector, "v_id": _id, "metadata": meta} for vector, _id, meta in
                             zip(vectors_as_lists, ids, metadata)]

        # Insert the vectors into the database
        for v in vectors_to_upsert:
            query = self.format_query({'v_id': v["v_id"]})
            projection = {'_id': 1}
            db_item = sync(self.mongo_db.read(self.collection_name, query, projection))

            if db_item:
                sync(self.mongo_db.update(self.collection_name, query, v))
            else:
                sync(self.mongo_db.create(self.collection_name, v))

        indices = sync(self.mongo_db.list_search_indices(self.collection_name))

        # We create the index if it doesn't exist
        for idx in indices:
            if idx['name'] == self.index_name:
                return

        filters = ["metadata." + field for field in metadata[0].keys()]
        self.index_name = sync(self.mongo_db.create_vector_index(self.collection_name, self.dimension,
                                                            path="embeddings", index_name=self.index_name,
                                                            similarity=self.metric, filters=filters))


    def get_num_vectors(self):
        query = self.format_query({})
        return sync(self.mongo_db.count_by_query(self.collection_name, query))

    def remove_document(self, doc_id: str):
        query = self.format_query({'metadata.doc_id': doc_id})
        sync(self.mongo_db.delete(self.collection_name, query))

    def search(self, query_vector, top_k: int = 10, metadata_filter: Optional[MetadataFilter | MetadataFilters] = None) -> list[
        VectorSearchResult]:
        # Convert the query vector to a list if it is a NumPy array
        if isinstance(query_vector, np.ndarray):
            query_vector = query_vector.tolist()
        if isinstance(query_vector[0], list):
            query_vector = query_vector[0] # Unpack the vector

        if metadata_filter:
            if "filters" in metadata_filter:
                formatted_metadata_filter = format_metadata_filters(metadata_filter)
            else:
                formatted_metadata_filter = format_metadata_filter(metadata_filter)
            search_results = sync(self.mongo_db.search_by_embedding(self.collection_name, self.index_name, "embeddings",
                                              embedding=query_vector, top_k=top_k, _filter=formatted_metadata_filter))
        else:
            search_results = sync(self.mongo_db.search_by_embedding(self.collection_name, self.index_name, "embeddings",
                                                                    embedding=query_vector, top_k=top_k))

        results = []
        for match in search_results:
            doc_id = match['metadata']['metadata'].get('doc_id') or match.get('v_id')
            similarity = match['score']

            results.append(
                VectorSearchResult(
                    doc_id=doc_id,
                    vector=None,
                    metadata=match['metadata']['metadata'],
                    similarity=similarity
                )
            )

        results = sorted(results, key=lambda x: x["similarity"], reverse=True)

        return results

    def delete(self):
        # Only delete the MongoDB collection if there is no mandatory_metadata, otherwise only delete the documents
        if not self.mandatory_metadata:
            self.mongo_db.drop(self.collection_name)
        else:
            query = self.format_query({})
            sync(self.mongo_db.bulk_delete(self.collection_name, query))

    def to_dict(self) -> dict[str, str]:
        return {
            **super().to_dict(),
            "db_name": self.db_name,
            "kb_id": self.kb_id,
            "dimension": self.dimension,
            "index_name": self.index_name,
            "metric": self.metric,
            "uri": self.uri,
            "collection_name": self.collection_name,
        }

    def is_async(self) -> bool:
        return True