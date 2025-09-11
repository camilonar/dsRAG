import datetime
import time
from typing import Any, Optional

from dsrag.database.chunk import ChunkDB, FormattedDocument
from integrations.database.mongo import MongoCrud
from integrations.utils.async_utils import sync


class MongoDB(ChunkDB):

    def __init__(self, db_name: str, kb_id: str, uri: str, collection_name: str = None) -> None:
        self.db_name = db_name
        self.kb_id = kb_id
        self.uri = uri
        self.mongo_db = MongoCrud(uri=uri, db_name=self.db_name)
        if collection_name is not None:
            self.collection_name = collection_name
        else:
            # Strip the kb of any spaces
            kb_id = kb_id.replace(" ", "_")
            self.collection_name = f"{kb_id}_chunks"

        """
        - **Partition Key (`doc_id`):** String
        - **Sort Key (`chunk_index`):** Number
        - **Additional Attributes:**
        - `supp_id` (String)
        - `document_title` (String)
        - `document_summary` (String)
        - `section_title` (String)
        - `section_summary` (String)
        - `chunk_text` (String)
        - `chunk_length` (Number)
        - `chunk_page_start` (Number)
        - `chunk_page_end` (Number)
        - `is_visual` (Boolean)
        - `created_on` (String) or (Number) depending on your timestamp format
        - `metadata` (String) or (Map)
        """

    def add_document(self, doc_id: str, chunks: dict[int, dict[str, Any]], supp_id: str = "",
                     metadata: dict = {}) -> None:
        # Create a 'created_on' timestamp
        created_on = int(time.time())

        for chunk_index, chunk in chunks.items():
            try:
                # Initialize the item with mandatory attributes
                item = {
                    'doc_id': doc_id,
                    'chunk_index': float(str(chunk_index)),
                    'created_on': float(str(created_on))
                }

                if supp_id:
                    item['supp_id'] = supp_id

                if metadata:
                    item['metadata'] = metadata  # Assuming metadata is a dict

                # Process 'chunk_text'
                chunk_text = chunk.get('chunk_text')
                if chunk_text and chunk_text.strip() != '':
                    item['chunk_text'] = chunk_text
                    item['chunk_length'] = len(chunk_text)

                # Process other string attributes, avoiding empty strings
                for attr in ['document_title', 'document_summary', 'section_title', 'section_summary']:
                    value = chunk.get(attr)
                    if value and value.strip() != '':
                        item[attr] = value

                # Process numerical attributes 'chunk_page_start', 'chunk_page_end'
                for attr in ['chunk_page_start', 'chunk_page_end']:
                    value = chunk.get(attr)
                    if value is not None:
                        item[attr] = value

                # Process boolean attributes
                if 'is_visual' in chunk:
                    is_visual = chunk['is_visual']
                    if isinstance(is_visual, bool):
                        item['is_visual'] = is_visual
                    else:
                        item['is_visual'] = bool(is_visual)

                # Remove attributes with None values or empty strings
                item = {k: v for k, v in item.items() if v not in [None, '', []]}

                # Write the item to MongoDB (if the item exists then update the existing register)
                query = {'doc_id': doc_id, 'chunk_index': float(str(chunk_index))}
                projection = {'_id': 1}
                db_item = sync(self.mongo_db.read(self.collection_name, query, projection))

                if db_item:
                    item.pop('created_on')
                    sync(self.mongo_db.update(self.collection_name, query, item))
                else:
                    sync(self.mongo_db.create(self.collection_name, item))

            except Exception as e:
                print(f"Error processing chunk_index {chunk_index}: {e}")
                # Handle exceptions as needed (e.g., log, skip, or raise)


    def remove_document(self, doc_id: str) -> None:
        query = {'doc_id': doc_id}
        sync(self.mongo_db.bulk_delete(self.collection_name, query))

    def get_document(self, doc_id: str, include_content: bool = False) -> Optional[FormattedDocument]:
        # Define the attributes to retrieve
        projection = {'supp_id': 1, 'document_title': 1, 'document_summary': 1, 'created_on': 1, 'metadata': 1}
        if include_content:
            projection |= {'chunk_text': 1, 'chunk_index': 1}

        try:
            # Query the table for all items with the given doc_id
            query = {'doc_id': doc_id}
            items = sync(self.mongo_db.list_by_query(self.collection_name, query, projection=projection))

            # If no items found, return None
            if not items:
                return None

            # Initialize variables
            full_document_string = ""
            chunks = []

            # Process common fields
            first_item = items[0]
            supp_id = first_item.get('supp_id')
            title = first_item.get('document_title')
            summary = first_item.get('document_summary')
            created_on = first_item.get('created_on')
            created_on = int(created_on)
            metadata = first_item.get('metadata')

            # If metadata is stored as a string, convert it back to a dictionary
            if metadata and isinstance(metadata, str):
                metadata = eval(metadata)  # Be cautious with eval; consider safer alternatives

            # Process items
            for item in items:
                # Collect chunks if include_content is True
                if include_content:
                    chunk_text = item.get('chunk_text', '')
                    chunk_index = item.get('chunk_index')
                    chunk_index = int(chunk_index)
                    chunks.append((chunk_index, chunk_text))

            # Concatenate chunks
            if include_content and chunks:
                # Sort the chunks based on chunk_index
                chunks.sort(key=lambda x: x[0])
                # Join chunk_texts with newline character
                full_document_string = '\n'.join(chunk_text for _, chunk_text in chunks)

            return FormattedDocument(
                id=doc_id,
                supp_id=supp_id,
                title=title,
                content=full_document_string if include_content else None,
                summary=summary,
                created_on=datetime.datetime.fromtimestamp(created_on, datetime.UTC),
                metadata=metadata,
                chunk_count=len(items)
            )

        except Exception as e:
            print(f"Error retrieving document '{doc_id}': {e}")
            # Handle exceptions as needed
            return None

    def get_chunk_text(self, doc_id: str, chunk_index: int) -> Optional[str]:
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'chunk_text': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            return item.get('chunk_text')
        else:
            return None

    def get_is_visual(self, doc_id: str, chunk_index: int) -> Optional[bool]:
        # Get the 'is_visual' attribute for the given doc_id and chunk_index
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'is_visual': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            return item.get('is_visual')
        else:
            return None

    def get_chunk_page_numbers(self, doc_id: str, chunk_index: int) -> tuple[Optional[int], Optional[int]]:
        # Get the chunk page start and end
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'chunk_page_start': 1, 'chunk_page_end': 1, '_id': 0}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            # Convert the Decimal values to integers
            page_start = int(item.get('chunk_page_start', 0))
            page_end = int(item.get('chunk_page_end', 0))
            return page_start, page_end
        else:
            return None, None

    def get_document_title(self, doc_id: str, chunk_index: int) -> Optional[str]:
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'document_title': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            return item.get('document_title')
        else:
            return None

    def get_document_summary(self, doc_id: str, chunk_index: int) -> Optional[str]:
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'document_summary': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            return item.get('document_summary')
        else:
            return None

    def get_section_title(self, doc_id: str, chunk_index: int) -> Optional[str]:
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'section_title': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            return item.get('section_title')
        else:
            return None

    def get_section_summary(self, doc_id: str, chunk_index: int) -> Optional[str]:
        query = {'doc_id': doc_id, 'chunk_index': chunk_index}
        projection = {'section_summary': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))

        if item:
            return item.get('section_summary')
        else:
            return None

    def get_all_doc_ids(self, supp_id: Optional[str] = None) -> list[str]:
        query = {'supp_id': supp_id}
        projection = {'doc_id': 1}

        try:
            items = sync(self.mongo_db.list_by_query(self.collection_name, query, projection))
            doc_ids = {item['doc_id'] for item in items}
            return list(doc_ids)
        except Exception as e:
            print(f"Error retrieving doc_ids: {e}")
            # Optionally, re-raise the exception or handle it accordingly
            raise

    def get_document_count(self) -> int:
        count = sync(self.mongo_db.count_by_query(self.collection_name, {}))
        return count

    def get_total_num_characters(self) -> int:
        pipeline = [
            {'$group': {
                '_id': None,
                'total': {
                    '$sum': "chunk_length"
                }
            }}
        ]
        response = sync(self.mongo_db.aggregate(self.collection_name, pipeline))

        if response:
            return response[0].get('total', 0)
        else:
            return 0

    def delete(self) -> None:
        # Delete the MongoDB collection
        self.mongo_db.drop(self.collection_name)

    def to_dict(self) -> dict[str, str]:
        return {
            **super().to_dict(),
            "db_name": self.db_name,
            "kb_id": self.kb_id,
            "uri": self.uri,
            "collection_name": self.collection_name,
        }