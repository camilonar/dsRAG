import time
from typing import Optional, Sequence
import json
import numpy as np

from dsrag.database.vector.db import VectorDB
from dsrag.database.vector.types import VectorSearchResult, MetadataFilter, ChunkMetadata, Vector, MetadataFilters
from dsrag.utils.imports import LazyLoader
from integrations.database.doc_library import DocLibrary
from integrations.database.postgres import Postgres

# Lazy load PostgreSQL dependencies
psycopg2 = LazyLoader("psycopg2", "psycopg2-binary")
pgvector = LazyLoader("pgvector")

# We'll import register_vector when needed to avoid immediate import

def format_metadata_filters(metadata_filters: MetadataFilters) -> str:
    filters = metadata_filters["filters"]
    operator = metadata_filters["operator"]

    formatted_filters = [format_metadata_filter(_filter) for _filter in filters]
    if not formatted_filters:
        return "TRUE"

    if operator == "and":
        result = " AND ".join(formatted_filters)
    elif operator == "or":
        result = " OR ".join(formatted_filters)
    else:
        raise ValueError(f"Unsupported operator: {operator}")

    return result

def format_metadata_filter(metadata_filter: MetadataFilter) -> str:
    """
    Format the metadata filter to be used in the PostgresSQL query method.

    Args:
        metadata_filter (dict): The metadata filter.

    Returns:
        str: The formatted metadata filter.
    """
    field = metadata_filter['field']
    operator = metadata_filter['operator']
    value = metadata_filter['value']

    # Map the operator to SQL syntax
    operator_map = {
        'equals': '=',
        'not_equals': '!=',
        'in': 'IN',
        'not_in': 'NOT IN',
        'greater_than': '>',
        'less_than': '<',
        'greater_than_equals': '>=',
        'less_than_equals': '<=',
    }

    # Ensure the operator is valid
    if operator not in operator_map:
        raise ValueError(f"Unsupported operator: {operator}")

    sql_operator = operator_map[operator]

    # Handle different types of values
    if isinstance(value, list):
        # Convert list to a tuple for SQL IN expressions
        value_placeholder = f"({', '.join(['%s'] * len(value))})"
    else:
        # Single value placeholder
        value_placeholder = "%s"

    # Construct the SQL filter expression
    if operator in ['in', 'not_in']:
        filter_expression = f"metadata->>'{field}' {sql_operator} {value_placeholder}"
    else:
        filter_expression = f"metadata->>'{field}' {sql_operator} {value_placeholder}"

    return filter_expression


class PostgresVectorDB(VectorDB, DocLibrary):
    MAX_IDLE_TIME = 450

    @classmethod
    def _embedding_config(cls, embedding_type: str):
        configs = {
            "vector": {
                "extension": "vector",
                "column_type": "vector",
                "quantize_sql": "%s",
                "index_method": "hnsw",
                "operator_class": "vector_cosine_ops",
                "index_options": "WITH (m = 16, ef_construction = 64)",
            },
            "rabitq8": {
                "extension": "lakebase_vector CASCADE",
                "column_type": "rabitq8",
                "quantize_sql": "quantize_to_rabitq8(%s::vector)",
                "index_method": "lakebase_ann",
                "operator_class": "rabitq8_cosine_ops",
                "index_options": "",
            },
        }
        try:
            return configs[embedding_type]
        except KeyError:
            raise ValueError("EMBEDDING_TYPE must be either 'vector' or 'rabitq8'")

    def __init__(self, kb_id: str, username: str, password: str, database: str, host: str = "localhost", port: int = 5432,
                 vector_dimension: int = 768, table_name: str = "", embedding_type = "rabitq8",
                 mandatory_metadata: Optional[dict] = None, ssl_mode: str = "require"):
        self.kb_id = kb_id
        if not table_name:
            # Strip the kb of any spaces
            kb_id = kb_id.replace(" ", "_")
            self.table_name = f'{kb_id}_vectors'
        else:
            self.table_name = table_name

        self.index_name = f'{self.table_name}_embedding_index'
        self.username = username
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.vector_dimension = vector_dimension
        self.mandatory_metadata = mandatory_metadata if mandatory_metadata else {}
        self.embedding_type = embedding_type
        self.embedding_config = self._embedding_config(self.embedding_type)
        self.last_connection = time.time()
        connection_params = {
            "dbname": database,
            "user": username,
            "password": password,
            "host": host,
            "port": port,
            "sslmode": ssl_mode
        }
        self.postgres = Postgres(connection_params)

        # Create the extension if it doesn't exist
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"CREATE EXTENSION IF NOT EXISTS {self.embedding_config['extension']}")
            conn.commit()

            # Import register_vector only when needed
            from pgvector.psycopg2 import register_vector
            register_vector(conn)

            from psycopg2 import sql

            cur.execute(
                sql.SQL(
                    "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = {})")
                .format(sql.Literal(self.table_name))
            )
            exists = cur.fetchone()[0]
            if not exists:
                print("exists", exists)

            # Create the table for this kb id if it doesn't exist
            if not exists:
                cur.execute(
                    sql.SQL(
                        "CREATE TABLE {} (id TEXT, kb_id TEXT, metadata JSONB, "
                        "embedding {}(%s), PRIMARY KEY(id, kb_id))"
                    ).format(
                        sql.Identifier(self.table_name),
                        sql.SQL(self.embedding_config["column_type"]),
                    ),
                    [vector_dimension]
                )
                conn.commit()

                # Create the index
                cur.execute(
                    sql.SQL(
                        """
                        CREATE INDEX {} ON {} USING {}(embedding {}) {}
                        """)
                    .format(
                        sql.Identifier(self.index_name),
                        sql.Identifier(self.table_name),
                        sql.SQL(self.embedding_config["index_method"]),
                        sql.SQL(self.embedding_config["operator_class"]),
                        sql.SQL(self.embedding_config["index_options"])
                    )
                )
                conn.commit()

    def format_query(self, query: dict):
        # This method assumes the resulting dict is going to be used in a 'WHERE metadata @> %s' style query
        return query | self.mandatory_metadata

    def get_num_vectors(self):
        with self.postgres.get_db_connection() as conn:
            from psycopg2 import sql

            cur = conn.cursor()
            condition = self.format_query({})
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {} WHERE metadata @> %s").format(sql.Identifier(self.table_name)),
                [json.dumps(condition)])
            count = cur.fetchone()[0]
        return count

    def add_vectors(self, vectors: Sequence[Vector], metadata: Sequence[ChunkMetadata]):

        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()

            vectors = np.array(vectors)
            # Create the ids from the doc_id and chunk_index
            ids = [
                f"{content['doc_id']}_{content['chunk_index']}" for content in metadata]

            from psycopg2 import sql
            if self.mandatory_metadata:
                data_to_insert = [(_id, kb_id, json.dumps(content), embedding)
                                  for _id, kb_id, content, embedding in zip(ids, [self.kb_id for _ in range(len(ids))],
                                                                    metadata, vectors)]
            else:
                data_to_insert = [(_id, kb_id, json.dumps(content), embedding)
                                  for _id, kb_id, content, embedding in zip(ids, ["" for _ in range(len(ids))],
                                                                            metadata, vectors)]

            insert_sql = sql.SQL(
                "INSERT INTO {} (id, kb_id, metadata, embedding) "
                "VALUES (%s, %s, %s, " + self.embedding_config["quantize_sql"] + ")"
            ).format(
                sql.Identifier(self.table_name)).as_string(cur)

            cur.executemany(insert_sql, data_to_insert)
            conn.commit()

    def remove_document(self, doc_id):

        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()

            # Delete all vectors with the given doc_id
            condition = self.format_query({"doc_id": doc_id})

            from psycopg2 import sql
            cur.execute(
                sql.SQL(
                    "DELETE FROM {} WHERE metadata @> %s").format(sql.Identifier(self.table_name)),
                [json.dumps(condition)]
            )

            conn.commit()

    def search(self, query_vector: list, top_k: int = 10, metadata_filter: Optional[MetadataFilter | MetadataFilters] = None):
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()

            query_vector = np.array(query_vector)

            from psycopg2 import sql
            if metadata_filter:
                if "filters" in metadata_filter:
                    filter_expression = format_metadata_filters(metadata_filter)
                    filter_value = []
                    for f in metadata_filter["filters"]:
                        if isinstance(f["value"], list):
                            filter_value.extend(f["value"])
                        else:
                            filter_value.append(f["value"])
                else:
                    filter_expression = format_metadata_filter(metadata_filter)
                    filter_value = metadata_filter['value']

                if isinstance(filter_value, list):
                    filter_params = tuple(filter_value)
                else:
                    filter_params = (filter_value,)

                if (
                    ("filters" in metadata_filter and any(
                        f["field"] == "doc_id" for f in metadata_filter["filters"]
                    ))
                    or (
                        "filters" not in metadata_filter
                        and metadata_filter["field"] == "doc_id"
                    )
                ):
                    # Filtering doc_ids before calculating vector distances will usually be
                    # substantially faster for large tables (make sure to create an index).
                    query = sql.SQL(
                        """
                        WITH filtered AS MATERIALIZED (
                            SELECT metadata, embedding
                            FROM {}
                            WHERE {}
                        )
                        SELECT metadata, embedding, (embedding <=> """
                        + self.embedding_config["quantize_sql"]
                        + """ ) AS cosine_distance
                        FROM filtered
                        ORDER BY cosine_distance ASC
                        LIMIT %s
                        """
                    ).format(
                        sql.Identifier(self.table_name),
                        sql.SQL(filter_expression)
                    )
                    params = (*filter_params, query_vector, top_k)
                else:
                    query = sql.SQL(
                        """
                        SELECT metadata, embedding, (embedding <=> """
                        + self.embedding_config["quantize_sql"]
                        + """ ) AS cosine_distance
                        FROM {}
                        WHERE {}
                        ORDER BY cosine_distance ASC
                        LIMIT %s
                        """
                    ).format(
                        sql.Identifier(self.table_name),
                        sql.SQL(filter_expression)
                    )
                    params = (query_vector, *filter_params, top_k)

                cur.execute(query, params)
            else:
                query = sql.SQL(
                    """
                    SELECT metadata, (embedding <=> """
                    + self.embedding_config["quantize_sql"]
                    + """ ) AS cosine_distance
                    FROM {}
                    ORDER BY cosine_distance ASC
                    LIMIT %s
                    """
                ).format(sql.Identifier(self.table_name))
                cur.execute(query, (query_vector, top_k))

            results = cur.fetchall()
            formatted_results: list[VectorSearchResult] = []
            for row in results:
                metadata, embedding, cosine_distance = row

                formatted_results.append(
                    VectorSearchResult(
                        doc_id=metadata["doc_id"],
                        vector=None,
                        metadata=metadata,
                        similarity=1 - cosine_distance,
                    )
                )

        return formatted_results

    def delete(self):
        # Delete the table
        with self.postgres.get_db_connection() as conn:

            from psycopg2 import sql
            cur = conn.cursor()
            if not self.mandatory_metadata:
                cur.execute(sql.SQL("DROP TABLE {}").format(
                    sql.Identifier(self.table_name)))
            else:
                condition = self.format_query({})
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {} WHERE metadata @> %s").format(sql.Identifier(self.table_name)),
                    [json.dumps(condition)]
                )
            conn.commit()

    def find_doc_ids_like(self, query: str, limit: int = 20) -> list[str]:
        with self.postgres.get_db_connection() as conn:
            from psycopg2 import sql
            cur = conn.cursor()
            query = f"%{query}%"
            if not self.mandatory_metadata:
                query_sql = sql.SQL("""SELECT DISTINCT(metadata ->> 'doc_id') as doc_id
                                    FROM {}
                                    WHERE (metadata ->> 'doc_id') ILIKE %s
                                    ORDER BY doc_id
                                    LIMIT %s""").format(sql.Identifier(self.table_name))
                cur.execute(query_sql, (query, limit))
            else:
                query_sql = sql.SQL("""SELECT DISTINCT(metadata ->> 'doc_id') as doc_id
                                    FROM {}
                                    WHERE (metadata ->> 'doc_id') ILIKE %s
                                    AND metadata @> %s
                                    ORDER BY doc_id
                                    LIMIT %s""").format(sql.Identifier(self.table_name))
                condition = self.format_query({})
                cur.execute(query_sql, (query, json.dumps(condition), 20))
            results = cur.fetchall()
            doc_ids = [r[0] for r in results]
            return doc_ids

    def to_dict(self):
        return {
            **super().to_dict(),
            "kb_id": self.kb_id,
            "username": self.username,
            "password": self.password,
            "database": self.database,
            "host": self.host,
            "port": self.port,
            "embedding_type": self.embedding_type,
            "vector_dimension": self.vector_dimension,
            "table_name": self.table_name
        }
