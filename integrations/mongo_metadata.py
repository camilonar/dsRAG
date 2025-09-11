from dsrag.metadata import MetadataStorage
from integrations.database.mongo import MongoCrud
from integrations.utils.async_utils import sync


class MongoDBMetadataStorage(MetadataStorage):

    def __init__(self, db_name: str, uri: str, collection_name: str) -> None:
        super().__init__()
        self.db_name = db_name
        self.uri = uri
        self.mongo_db = MongoCrud(uri=uri, db_name=self.db_name.replace(" ", "_"))
        self.collection_name = collection_name

    def kb_exists(self, kb_id: str) -> bool:
        query = {'kb_id': kb_id}
        projection = {'kb_id': 1}
        item = sync(self.mongo_db.read(self.collection_name, query, projection))
        return bool(item)

    def load(self, kb_id: str) -> dict:
        query = {'kb_id': kb_id}
        response = sync(self.mongo_db.read(self.collection_name, query))

        if response:
            return response.get('metadata', {})
        else:
            return {}

    def save(self, full_data: dict, kb_id: str) -> None:
        data = {'kb_id': kb_id, 'metadata': full_data}

        if self.kb_exists(kb_id):
            query = {'kb_id': kb_id}
            sync(self.mongo_db.update(self.collection_name, query, data))
        else:
            sync(self.mongo_db.create(self.collection_name, data))

    def delete(self, kb_id: str) -> None:
        query = {'kb_id': kb_id}
        sync(self.mongo_db.delete(self.collection_name, query))
