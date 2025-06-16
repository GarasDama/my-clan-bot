import pymongo
import config

class MongoHandler:
    def __init__(self):
        try:
            self.client = pymongo.MongoClient(config.MONGO_URI)
            self.db = self.client.get_database("ClanBotDB")
            self.collection = self.db.get_collection("clan_data") # コレクション名をより具体的に
            print("✅ MongoDBに正常に接続しました。")
        except Exception as e:
            print(f"❌ MongoDBへの接続に失敗しました: {e}")
            self.client = None

    def get(self, key, default=None):
        if not self.client: return default
        # MongoDBでは各データはドキュメント。_idで検索。
        document = self.collection.find_one({"_id": str(key)})
        return document if document else default

    def set(self, key, value):
        if not self.client: return
        # _id以外のデータをvalueとして保存
        self.collection.update_one(
            {"_id": str(key)},
            {"$set": value},
            upsert=True
        )

    def delete(self, key):
        if not self.client: return False
        result = self.collection.delete_one({"_id": str(key)})
        return result.deleted_count > 0

    # ★★★★★ 新しく追加した機能 ★★★★★
    def all(self) -> dict:
        """データベースの全データを辞書として取得する"""
        if not self.client: return {}
        all_docs = self.collection.find({})
        # MongoDBの_idをキーとする辞書に変換
        return {doc["_id"]: doc for doc in all_docs}

db = MongoHandler()
