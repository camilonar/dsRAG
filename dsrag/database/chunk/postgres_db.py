import json
import time
from typing import Any, Optional

from psycopg2._json import Json

from dsrag.database.chunk.db import ChunkDB
from dsrag.database.chunk.types import ChunkSearchResult, FormattedDocument
from dsrag.database.vector.types import MetadataFilter, MetadataFilters
from integrations.database.postgres import Postgres


class PostgresChunkDB(ChunkDB):
    """PostgreSQL chunk storage with optional native FTS or Lakebase BM25."""

    @classmethod
    def _text_search_config(cls, text_search_type: Optional[str]) -> dict[str, Any]:
        configs = {
            "tsvector": {
                "extension": None,
                "index_method": "gin",
                "index_suffix": "tsvector",
            },
            "bm25": {
                "extension": "lakebase_text",
                "index_method": "lakebase_bm25",
                "index_suffix": "bm25",
            },
        }
        if text_search_type is None:
            return {}
        try:
            return configs[text_search_type]
        except KeyError:
            raise ValueError(
                "TEXT_SEARCH_TYPE must be either None, 'tsvector', or 'bm25'"
            )

    def __init__(self, kb_id: str, username: str, password: str, database: str, host: str="localhost", port: int = 5432,
                 table_name: str = "", mandatory_metadata: dict = None, ssl_mode: str = "require",
                 text_search_type: Optional[str] = "tsvector", text_search_config: str = "english") -> None:
        self.kb_id = kb_id
        self.username = username
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.text_search_type = text_search_type
        self.text_search_config_options = self._text_search_config(text_search_type)
        self.text_search_config = text_search_config
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

        if not table_name:
            # Strip the kb of any spaces
            kb_id = kb_id.replace(" ", "_")
            self.table_name = f"{kb_id}_documents"
        else:
            self.table_name = table_name
        if self.text_search_type:
            self.text_search_index_name = (
                f"{self.table_name}_{self.text_search_config_options['index_suffix']}"
            )
        else:
            self.text_search_index_name = ""
        self.mandatory_metadata = mandatory_metadata if mandatory_metadata else {}

        self.columns = [
            {"name": "doc_id", "type": "TEXT"},
            {"name": "document_title", "type": "TEXT"},
            {"name": "document_summary", "type": "TEXT"},
            {"name": "section_title", "type": "TEXT"},
            {"name": "section_summary", "type": "TEXT"},
            {"name": "chunk_text", "type": "TEXT"},
            {"name": "chunk_index", "type": "INT"},
            {"name": "chunk_length", "type": "INT"},
            {"name": "chunk_page_start", "type": "INT"},
            {"name": "chunk_page_end", "type": "INT"},
            {"name": "is_visual", "type": "BOOLEAN"},
            {"name": "created_on", "type": "TEXT"},
            {"name": "supp_id", "type": "TEXT"},
            {"name": "metadata", "type": "JSONB"},
        ]

        # Create a table for this kb_id if it doesn't exist
        with self.postgres.get_db_connection() as conn:
            from psycopg2 import sql

            cur = conn.cursor()
            cur.execute(f"SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = '{self.table_name}')")
            exists = cur.fetchone()[0]

            if not exists:
                if self.text_search_type == "bm25":
                    cur.execute("CREATE EXTENSION IF NOT EXISTS lakebase_text")

                # Create a table for this kb_id
                column_definitions = []
                for column in self.columns:
                    column_definitions.append(
                        sql.SQL("{} {}").format(
                            sql.Identifier(column["name"]),
                            sql.SQL(column["type"]),
                        )
                    )
                if self.text_search_type is not None:
                    column_definitions.append(
                        sql.SQL(
                            "search_vector TSVECTOR GENERATED ALWAYS AS "
                            "(to_tsvector({}::regconfig, "
                            "coalesce(chunk_text, '') || ' ' || "
                            "coalesce(document_title, '') || ' ' || "
                            "coalesce(section_title, ''))) STORED"
                        ).format(sql.Literal(self.text_search_config))
                    )
                cur.execute(
                    sql.SQL("CREATE TABLE {} ({})").format(
                        sql.Identifier(self.table_name),
                        sql.SQL(", ").join(column_definitions),
                    )
                )
                conn.commit()
            else:
                # Check if we need to add any columns to the table. This happens if the columns have been updated
                cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{self.table_name}'")
                columns = cur.fetchall()
                column_names = [column[0] for column in columns]
                for column in self.columns:
                    if column["name"] not in column_names:
                        # Add the column to the table
                        cur.execute("ALTER TABLE {}_chunks ADD COLUMN {} {}".format(kb_id, column["name"], column["type"]))

            if self.text_search_type == "bm25":
                cur.execute("CREATE EXTENSION IF NOT EXISTS lakebase_text")
            if self.text_search_type:
                self._ensure_text_search_column(cur)
                self._ensure_text_search_index(cur)
                conn.commit()

    def _ensure_text_search_column(self, cur) -> None:
        """Add the generated search vector to an existing chunk table."""
        from psycopg2 import sql

        cur.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "AND column_name = 'search_vector')",
            (self.table_name,),
        )
        if cur.fetchone()[0]:
            return

        cur.execute(
            sql.SQL(
                "ALTER TABLE {} ADD COLUMN search_vector TSVECTOR "
                "GENERATED ALWAYS AS (to_tsvector({}::regconfig, "
                "coalesce(chunk_text, '') || ' ' || "
                "coalesce(document_title, '') || ' ' || "
                "coalesce(section_title, ''))) STORED"
            ).format(
                sql.Identifier(self.table_name),
                sql.Literal(self.text_search_config),
            )
        )

    def _ensure_text_search_index(self, cur) -> bool:
        """Create the selected text index once the table has chunks to index."""
        from psycopg2 import sql

        cur.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = %s)",
            (self.text_search_index_name,),
        )
        if cur.fetchone()[0]:
            return True

        cur.execute(
            sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
                sql.Identifier(self.table_name)
            )
        )
        if not cur.fetchone()[0]:
            return False

        cur.execute(
            sql.SQL("CREATE INDEX {} ON {} USING {} (search_vector)").format(
                sql.Identifier(self.text_search_index_name),
                sql.Identifier(self.table_name),
                sql.SQL(self.text_search_config_options["index_method"]),
            )
        )
        return True

    def format_query(self, query: dict) -> str:
        # This method assumes the resulting dict is going to be used in a 'WHERE metadata @> %s' style query
        return json.dumps(query | self.mandatory_metadata)

    def _format_text_metadata_filter(
        self,
        metadata_filter: Optional[dict[str, Any] | MetadataFilter | MetadataFilters],
    ) -> tuple[str, list[Any]]:
        """Format vector-style metadata filters for a text-search query."""
        if metadata_filter is None:
            return "metadata @> %s::jsonb", [self.format_query({})]

        if "filters" not in metadata_filter and "field" not in metadata_filter:
            return "metadata @> %s::jsonb", [self.format_query(metadata_filter)]

        if "filters" in metadata_filter:
            filters = metadata_filter["filters"]
            operator = metadata_filter["operator"]
            if operator not in ("and", "or"):
                raise ValueError(f"Unsupported metadata filter operator: {operator}")
        else:
            filters = [metadata_filter]
            operator = "and"

        filter_expressions = []
        filter_params: list[Any] = []
        for metadata_item in filters:
            expression, params = self._format_text_metadata_item(metadata_item)
            filter_expressions.append(expression)
            filter_params.extend(params)

        if not filter_expressions:
            return "metadata @> %s::jsonb", [self.format_query({})]

        mandatory_condition = "metadata @> %s::jsonb"
        condition = (
            f"{mandatory_condition} AND ({f' {operator.upper()} '.join(filter_expressions)})"
        )
        return condition, [self.format_query({}), *filter_params]

    @staticmethod
    def _format_text_metadata_item(metadata_item: MetadataFilter) -> tuple[str, list[Any]]:
        field = metadata_item["field"]
        operator = metadata_item["operator"]
        value = metadata_item["value"]
        field_expression = "metadata ->> %s"

        operator_map = {
            "equals": "=",
            "not_equals": "!=",
            "greater_than": ">",
            "less_than": "<",
            "greater_than_equals": ">=",
            "less_than_equals": "<=",
        }
        if operator in operator_map:
            return (
                f"{field_expression} {operator_map[operator]} %s",
                [field, str(value)],
            )
        if operator in ("in", "not_in"):
            values = value if isinstance(value, list) else [value]
            if not values:
                return ("TRUE" if operator == "not_in" else "FALSE"), []
            sql_operator = "IN" if operator == "in" else "NOT IN"
            placeholders = ", ".join(["%s"] * len(values))
            return (
                f"{field_expression} {sql_operator} ({placeholders})",
                [field, *[str(item) for item in values]],
            )
        raise ValueError(f"Unsupported metadata filter operator: {operator}")

    def add_document(self, doc_id: str, chunks: dict[int, dict[str, Any]], supp_id: str = "", metadata: dict = None) -> None:
        if not metadata:
            metadata = {}
        # Add the docs to the sqlite table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            # Create a created on timestamp
            created_on = str(int(time.time()))

            # Get the data from the dictionary
            for chunk_index, chunk in chunks.items():
                chunk_text = chunk.get("chunk_text", "")
                chunk_length = len(chunk_text)

                values_dict = {
                    'doc_id': doc_id,
                    'document_title': chunk.get("document_title", ""),
                    'document_summary': chunk.get("document_summary", ""),
                    'section_title': chunk.get("section_title", ""),
                    'section_summary': chunk.get("section_summary", ""),
                    'chunk_text': chunk.get("chunk_text", ""),
                    'chunk_page_start': chunk.get("chunk_page_start", None),
                    'chunk_page_end': chunk.get("chunk_page_end", None),
                    'is_visual': chunk.get("is_visual", False),
                    'chunk_index': chunk_index,
                    'chunk_length': chunk_length,
                    'created_on': created_on,
                    'supp_id': supp_id,
                    'metadata': Json(metadata)
                }

                # Generate the column names and placeholders
                columns = ', '.join(values_dict.keys())
                placeholders = ', '.join(['%s'] * len(values_dict))

                sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
                cur.execute(sql, tuple(values_dict.values()))

                conn.commit()

    def remove_document(self, doc_id: str) -> None:
        # Remove the docs from the sqlite table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(f"DELETE FROM {self.table_name} WHERE doc_id='{doc_id}' AND metadata @> '{metadata_query}'")
            conn.commit()

    def find_doc_ids_like(self, query: str, limit: int = 20) -> list[str]:
        """Return document IDs containing ``query``, subject to mandatory metadata."""
        with self.postgres.get_db_connection() as conn:
            from psycopg2 import sql

            cur = conn.cursor()
            query_pattern = f"%{query}%"
            where_clause = "doc_id ILIKE %s"
            params = [query_pattern]

            if self.mandatory_metadata:
                where_clause += " AND metadata @> %s"
                params.append(json.dumps(self.format_query({})))

            query_sql = sql.SQL(
                "SELECT DISTINCT doc_id FROM {} "
                "WHERE " + where_clause + " "
                "ORDER BY doc_id LIMIT %s"
            ).format(sql.Identifier(self.table_name))
            cur.execute(query_sql, (*params, limit))
            return [row[0] for row in cur.fetchall()]

    def supports_text_search(self) -> bool:
        """Return whether Lakebase BM25 search was enabled for this table."""
        return self.text_search_type is not None

    def search(
        self,
        query: str,
        top_k: int = 10,
        metadata_filter: Optional[dict[str, Any] | MetadataFilter | MetadataFilters] = None,
    ) -> list[ChunkSearchResult]:
        """Search chunk text, document titles, and section titles."""
        if not self.text_search_type:
            raise NotImplementedError(
                "Enable text search with text_search_type='tsvector' or "
                "text_search_type='bm25' when creating PostgresChunkDB"
            )
        if top_k <= 0 or not query or not query.strip():
            return []

        with self.postgres.get_db_connection() as conn:
            from psycopg2 import sql

            cur = conn.cursor()
            if not self._ensure_text_search_index(cur):
                return []

            metadata_condition, metadata_params = self._format_text_metadata_filter(
                metadata_filter
            )
            if self.text_search_type == "bm25":
                score_sql = (
                    "(search_vector <@> to_bm25query("
                    "to_tsvector({}::regconfig, %s), %s))"
                )
                score_params = (query, self.text_search_index_name)
                order_sql = "ASC"
            else:
                score_sql = (
                    "ts_rank_cd(search_vector, "
                    "websearch_to_tsquery({}::regconfig, %s))"
                )
                score_params = (query,)
                order_sql = "DESC"

            query_statement = sql.SQL(
                "SELECT doc_id, chunk_index, chunk_text, document_title, "
                "section_title, chunk_page_start, chunk_page_end, metadata, "
                + score_sql
                + " AS text_score FROM {} "
                "WHERE search_vector @@ websearch_to_tsquery({}::regconfig, %s) "
                "AND "
                + metadata_condition
                + " ORDER BY text_score "
                + order_sql
                + ", doc_id ASC, chunk_index ASC LIMIT %s"
            ).format(
                sql.Literal(self.text_search_config),
                sql.Identifier(self.table_name),
                sql.Literal(self.text_search_config),
            )
            cur.execute(
                query_statement,
                (*score_params, query, *metadata_params, top_k),
            )
            rows = cur.fetchall()

        results: list[ChunkSearchResult] = []
        for rank, row in enumerate(rows, start=1):
            (
                doc_id,
                chunk_index,
                chunk_text,
                document_title,
                section_title,
                chunk_page_start,
                chunk_page_end,
                metadata,
                text_score,
            ) = row
            results.append(
                ChunkSearchResult(
                    doc_id=doc_id,
                    chunk_index=chunk_index,
                    chunk_text=chunk_text,
                    document_title=document_title,
                    section_title=section_title,
                    chunk_page_start=chunk_page_start,
                    chunk_page_end=chunk_page_end,
                    metadata=metadata or {},
                    score=(
                        float(-text_score)
                        if self.text_search_type == "bm25"
                        else float(text_score)
                    ),
                    rank=rank,
                )
            )
        return results

    def get_document(
        self, doc_id: str, include_content: bool = False
    ) -> Optional[FormattedDocument]:
        # Retrieve the document from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            columns = ["supp_id", "document_title", "document_summary", "created_on", "metadata"]
            if include_content:
                columns += ["chunk_text", "chunk_index"]

            metadata_query = self.format_query({})
            query_statement = (
                f"SELECT {', '.join(columns)} FROM {self.table_name} WHERE doc_id='{doc_id}' AND metadata @> '{metadata_query}'"
            )
            cur.execute(query_statement)
            results = cur.fetchall()

        # If there are no results, return None
        if not results:
            return None

        # Turn the results into an object where the columns are keys
        full_document_string = ""
        if include_content:
            # Concatenate the chunks into a single string
            for result in results:
                # Join each chunk text with a new line character
                full_document_string += result[columns.index("chunk_text")] + "\n"
            # Remove the last new line character
            full_document_string = full_document_string[:-1]

        supp_id = results[0][columns.index("supp_id")]
        title = results[0][columns.index("document_title")]
        summary = results[0][columns.index("document_summary")]
        created_on = results[0][columns.index("created_on")]
        metadata = results[0][columns.index("metadata")]

        # Convert the metadata string back into a dictionary
        if metadata:
            metadata = eval(metadata)

        return FormattedDocument(
            id=doc_id,
            supp_id=supp_id,
            title=title,
            content=full_document_string if include_content else None,
            summary=summary,
            created_on=created_on,
            metadata=metadata
        )

    def get_chunk_text(self, doc_id: str, chunk_index: int) -> Optional[str]:
        # Retrieve the chunk text from the Postgres table
        with self.postgres.get_db_connection() as conn:
            metadata_query = self.format_query({})
            cur = conn.cursor()
            cur.execute(
                f"SELECT chunk_text FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result[0]
        return None
    
    def get_is_visual(self, doc_id: str, chunk_index: int) -> Optional[bool]:
        # Retrieve the is_visual flag from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(
                f"SELECT is_visual FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result[0]
        return None
    
    def get_chunk_page_numbers(self, doc_id: str, chunk_index: int) -> Optional[tuple[int, int]]:
        # Retrieve the chunk page numbers from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(
                f"SELECT chunk_page_start, chunk_page_end FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result
        return None

    def get_document_title(self, doc_id: str, chunk_index: int) -> Optional[str]:
        # Retrieve the document title from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(
                f"SELECT document_title FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result[0]
        return None

    def get_document_summary(self, doc_id: str, chunk_index: int) -> Optional[str]:
        # Retrieve the document summary from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(
                f"SELECT document_summary FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result[0]
        return None

    def get_section_title(self, doc_id: str, chunk_index: int) -> Optional[str]:
        # Retrieve the section title from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(
                f"SELECT section_title FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result[0]
        return None

    def get_section_summary(self, doc_id: str, chunk_index: int) -> Optional[str]:
        # Retrieve the section summary from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(
                f"SELECT section_summary FROM {self.table_name} WHERE doc_id='{doc_id}' AND chunk_index={chunk_index} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchone()
        if result:
            return result[0]
        return None

    def get_segments_in_range(self, doc_id: str, chunk_start: int, chunk_end: int) -> list[dict]:
        # Retrieve ALL the fields from ALL the segments between the given chunk indices
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            columns = ["doc_id", "chunk_page_start", "chunk_page_end", "document_title", "document_summary",
                       "chunk_text"]
            cur.execute(
                f"SELECT {', '.join(columns)} FROM {self.table_name} WHERE doc_id='{doc_id}' AND "
                f"chunk_index BETWEEN {chunk_start} AND {chunk_end} AND metadata @> '{metadata_query}'"
            )
            result = cur.fetchall()
        if result:
            return [{columns[i]: r[i] for i in range(len(columns))} for r in result]
        return []

    def get_segments_in_ranges(self, ranges: list[tuple[str, int, int]]) -> list[list[dict]]:
        """Retrieve multiple chunk ranges with one database query."""
        if not ranges:
            return []

        with self.postgres.get_db_connection() as conn:
            from psycopg2 import sql

            cur = conn.cursor()
            columns = [
                "doc_id", "chunk_page_start", "chunk_page_end",
                "document_title", "document_summary", "chunk_text"
            ]
            values_sql = ", ".join(["(%s, %s, %s, %s)"] * len(ranges))
            query = sql.SQL(
                """
                SELECT requested.range_id, {}
                FROM (VALUES {}) AS requested(range_id, doc_id, chunk_start, chunk_end)
                JOIN {} AS chunks
                  ON chunks.doc_id = requested.doc_id
                 AND chunks.chunk_index BETWEEN requested.chunk_start AND requested.chunk_end
                WHERE chunks.metadata @> %s::jsonb
                ORDER BY requested.range_id, chunks.chunk_index
                """
            ).format(
                sql.SQL(", ".join(f"chunks.{column}" for column in columns)),
                sql.SQL(values_sql),
                sql.Identifier(self.table_name),
            )
            metadata_query = self.format_query({})
            params = tuple(
                value
                for range_id, (doc_id, chunk_start, chunk_end) in enumerate(ranges)
                for value in (range_id, doc_id, chunk_start, chunk_end)
            ) + (metadata_query,)
            cur.execute(query, params)
            result = cur.fetchall()

        grouped_results = [[] for _ in ranges]
        for row in result:
            range_id = row[0]
            grouped_results[range_id].append(
                {columns[i]: row[i + 1] for i in range(len(columns))}
            )
        return grouped_results

    def get_all_doc_ids(self, supp_id: Optional[str] = None) -> list[str]:
        # Retrieve all document IDs from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            query_statement = f"SELECT DISTINCT doc_id FROM {self.table_name} WHERE metadata @> '{metadata_query}'"
            if supp_id:
                query_statement += f" AND supp_id='{supp_id}'"
            cur.execute(query_statement)
            results = cur.fetchall()
        return [result[0] for result in results]

    def doc_id_exists(self, doc_id: str) -> bool:
        # Retrieve all document IDs from the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            query_statement = f"SELECT DISTINCT doc_id FROM {self.table_name} WHERE doc_id='{doc_id}' AND metadata @> '{metadata_query}' LIMIT 1"
            cur.execute(query_statement)
            results = cur.fetchall()
        return True if results else False
    
    def get_document_count(self) -> int:
        # Retrieve the number of documents in the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(f"SELECT COUNT(DISTINCT doc_id) FROM {self.table_name} WHERE metadata @> '{metadata_query}'")
            result = cur.fetchone()
        if result is None:
            return 0
        return result[0]

    def get_total_num_characters(self) -> int:
        # Retrieve the total number of characters in the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            metadata_query = self.format_query({})
            cur.execute(f"SELECT SUM(chunk_length) FROM {self.table_name} WHERE metadata @> '{metadata_query}'")
            result = cur.fetchone()
        if result is None or result[0] is None:
            return 0
        return result[0]

    def delete(self) -> None:
        # Delete the Postgres table
        with self.postgres.get_db_connection() as conn:
            cur = conn.cursor()
            if not self.mandatory_metadata:
                cur.execute(f"DROP TABLE {self.table_name}")
            else:
                from psycopg2 import sql
                condition = self.format_query({})
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {} WHERE metadata @> %s").format(sql.Identifier(self.table_name)),
                    [condition]
                )
            conn.commit()

    def to_dict(self) -> dict[str, str]:
        return {
            **super().to_dict(),
            "kb_id": self.kb_id,
            "username": self.username,
            "password": self.password,
            "database": self.database,
            "host": self.host,
            "port": self.port,
            "table_name": self.table_name,
            "text_search_type": self.text_search_type,
            "text_search_config": self.text_search_config,
        }
