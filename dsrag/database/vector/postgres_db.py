from typing import Optional, Sequence
import json
import numpy as np

from dsrag.database.vector.db import VectorDB
from dsrag.database.vector.types import VectorSearchResult, MetadataFilter, ChunkMetadata, Vector, MetadataFilters
from dsrag.utils.imports import LazyLoader

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


class PostgresVectorDB(VectorDB):
    def __init__(self, kb_id: str, username: str, password: str, database: str, host: str = "localhost", port: int = 5432,
                 vector_dimension: int = 768, table_name: str = "", mandatory_metadata: Optional[dict] = {}):
        self.kb_id = kb_id
        if not table_name:
            # Strip the kb of any spaces
            kb_id = kb_id.replace(" ", "_")
            self.table_name = f'{kb_id}_vectors'
        else:
            self.table_name = table_name

        self.index_name = f'{table_name}_embedding_index'
        self.username = username
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.vector_dimension = vector_dimension
        self.mandatory_metadata = mandatory_metadata

        # Create the extension if it doesn't exist
        conn = psycopg2.connect(
            dbname=database,
            user=username,
            password=password,
            host=host,
            port=port
        )
        cur = conn.cursor()
        cur.execute('CREATE EXTENSION IF NOT EXISTS vector')
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
            creation_sql = "CREATE TABLE {} (id TEXT, kb_id TEXT, metadata JSONB, embedding vector(%s)," \
                "PRIMARY KEY(id, kb_id))"

            cur.execute(
                sql.SQL(creation_sql)
                .format(sql.Identifier(self.table_name)),
                [vector_dimension]
            )
            conn.commit()

            # Create the index
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX {} ON {} USING hnsw(embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                    """)
                .format(
                    sql.Identifier(self.index_name),
                    sql.Identifier(self.table_name)
                )
            )
            conn.commit()

        conn.close()

    def format_query(self, query: dict):
        # This method assumes the resulting dict is going to be used in a 'WHERE metadata @> %s' style query
        return query | self.mandatory_metadata

    def get_num_vectors(self):
        conn = psycopg2.connect(
            dbname=self.database,
            user=self.username,
            password=self.password,
            host=self.host,
            port=self.port
        )

        try:
            from psycopg2 import sql

            cur = conn.cursor()
            condition = self.format_query({})
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {} WHERE metadata @> %s").FORMAT(sql.Identifier(self.table_name)),
                [json.dumps(condition)])
            count = cur.fetchone()[0]
        finally:
            conn.close()
        return count

    def add_vectors(self, vectors: Sequence[Vector], metadata: Sequence[ChunkMetadata]):

        conn = psycopg2.connect(
            dbname=self.database,
            user=self.username,
            password=self.password,
            host=self.host,
            port=self.port
        )
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

        insert_sql = sql.SQL("INSERT INTO {} (id, kb_id, metadata, embedding) VALUES (%s, %s, %s, %s)").format(
            sql.Identifier(self.table_name)).as_string(cur)

        cur.executemany(insert_sql, data_to_insert)
        conn.commit()
        conn.close()

    def remove_document(self, doc_id):

        conn = psycopg2.connect(
            dbname=self.database,
            user=self.username,
            password=self.password,
            host=self.host,
            port=self.port
        )
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
        conn.close()

    def search(self, query_vector: list, top_k: int = 10, metadata_filter: Optional[MetadataFilter | MetadataFilters] = None):

        conn = psycopg2.connect(
            dbname=self.database,
            user=self.username,
            password=self.password,
            host=self.host,
            port=self.port
        )
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

            query = sql.SQL("""
                SELECT metadata, embedding, 1 - (embedding <=> %s) AS cosine_similarity
                FROM {} 
                WHERE {} 
                ORDER BY cosine_similarity DESC 
                LIMIT %s
            """).format(
                sql.Identifier(self.table_name),
                sql.SQL(filter_expression)
            )

            if isinstance(filter_value, list):
                params = (query_vector, *filter_value, top_k)
            else:
                params = (query_vector, filter_value, top_k)

            cur.execute(query, params)
        else:
            query = sql.SQL("""
                SELECT metadata, embedding, 1 - (embedding <=> %s) AS cosine_similarity
                FROM {}
                ORDER BY cosine_similarity DESC
                LIMIT %s
            """).format(sql.Identifier(self.table_name))
            cur.execute(query, (query_vector, top_k))

        results = cur.fetchall()
        formatted_results: list[VectorSearchResult] = []
        for row in results:
            metadata, embedding, cosine_similarity = row

            formatted_results.append(
                VectorSearchResult(
                    doc_id=metadata["doc_id"],
                    vector=embedding,
                    metadata=metadata,
                    similarity=cosine_similarity,
                )
            )

        conn.close()

        return formatted_results

    def delete(self):
        # Delete the table
        conn = psycopg2.connect(
            dbname=self.database,
            user=self.username,
            password=self.password,
            host=self.host,
            port=self.port
        )

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
        conn.close()

    def to_dict(self):
        return {
            **super().to_dict(),
            "kb_id": self.kb_id,
            "username": self.username,
            "password": self.password,
            "database": self.database,
            "host": self.host,
            "port": self.port,
            "vector_dimension": self.vector_dimension,
            "table_name": self.table_name
        }
