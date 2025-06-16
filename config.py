import os
from dotenv import load_dotenv

load_dotenv()

class ConfigError(Exception):
    pass

def get_env_var(name: str):
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"必須の環境変数 '{name}' が定義されていません。")
    return value

BOT_TOKEN = get_env_var("BOT_TOKEN")
GUILD_ID = int(get_env_var("GUILD_ID"))
MONGO_URI = get_env_var("MONGO_URI")
