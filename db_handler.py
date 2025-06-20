import os
import pymongo
import config

IS_REPLIT = 'REPL_ID' in os.environ

class DatabaseHandler:
    def get(self, key, default=None): raise NotImplementedError
    def set(self, key, value): raise NotImplementedError
    def delete(self, key): raise NotImplementedError
    def all(self): raise NotImplementedError
    def prefix(self, p_str: str = ""): raise NotImplementedError

if IS_REPLIT:
    print("INFO: Replit環境を検出。Replit DBを使用します。")
    from replit import db as replit_db

    class ReplitDBHandler(DatabaseHandler):
        def get(self, key, default=None): return replit_db.get(key, default)
        def set(self, key, value): replit_db[str(key)] = value
        def delete(self, key):
            key_str = str(key)
            if key_str in replit_db: del replit_db[key_str]; return True
            return False
        def all(self): return {key: replit_db[key] for key in replit_db.keys()}
        def prefix(self, p_str: str = ""): return tuple(key for key in replit_db.keys() if key.startswith(p_str))

    db = ReplitDBHandler()
else:
    print("INFO: Replit以外の環境を検出。MongoDBを使用します。")
    class MongoDBHandler(DatabaseHandler):
        def __init__(self):
            try:
                self.client = pymongo.MongoClient(config.MONGO_URI)
                self.db = self.client.get_database("ClanBotDB")
                self.collection = self.db.get_collection("data")
                print("✅ MongoDBに正常に接続しました。")
            except Exception as e:
                print(f"❌ MongoDBへの接続に失敗しました: {e}"); self.client = None
        def get(self, key, default=None):
            if not self.client: return default
            document = self.collection.find_one({"_id": str(key)})
            return document if document else default
        def set(self, key, value):
            if not self.client: return
            # _idは変更不可なので、valueから除外
            if '_id' in value: del value['_id']
            self.collection.update_one({"_id": str(key)}, {"$set": value}, upsert=True)
        def delete(self, key):
            if not self.client: return False
            result = self.collection.delete_one({"_id": str(key)})
            return result.deleted_count > 0
        def all(self) -> dict:
            if not self.client: return {}
            return {doc["_id"]: doc for doc in self.collection.find({})}
        def prefix(self, p_str: str = "") -> tuple:
            if not self.client: return tuple()
            return tuple(doc["_id"] for doc in self.collection.find({"_id": {"$regex": f"^{p_str}"}}))

    db = MongoDBHandler()