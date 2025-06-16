import pymongo
import config

class MongoHandler:
    def __init__(self):
        try:
            self.client = pymongo.MongoClient(config.MONGO_URI)
            self.db = self.client.get_database("ClanBotDB") # データベース名
            self.collection = self.db.get_collection("data_collection") # テーブルのようなもの
            print("✅ MongoDBに正常に接続しました。")
        except Exception as e:
            print(f"❌ MongoDBへの接続に失敗しました: {e}")
            self.client = None

    def get(self, key, default=None):
        if not self.client: return default
        document = self.collection.find_one({"_id": str(key)})
        return document.get("value") if document else default

    def set(self, key, value):
        if not self.client: return
        self.collection.update_one(
            {"_id": str(key)},
            {"$set": {"value": value}},
            upsert=True # キーがなければ新規作成
        )

    def delete(self, key):
        if not self.client: return False
        result = self.collection.delete_one({"_id": str(key)})
        return result.deleted_count > 0

    def prefix(self, p_str: str = ""):
        if not self.client: return tuple()
        # MongoDBではキーのプレフィックス検索は非効率なため、
        # 必要になったら別の方法を検討しますが、今回は基本的なキー一覧を返します。
        # 今回の最小構成では使わないので、空のタプルを返します。
        return tuple()

db = MongoHandler()
