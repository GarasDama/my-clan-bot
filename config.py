import os
from dotenv import load_dotenv
from typing import Optional

# .envファイルを最初に一度だけ読み込む
load_dotenv()

# Replitで実行中かどうかを判定
IS_REPLIT = 'REPL_ID' in os.environ

class ConfigError(Exception):
    """設定関連のエラーを示すカスタム例外"""
    pass

def get_env_var(name: str, required: bool = True, cast_to=str, default=None) -> Optional[any]:
    """
    環境変数を安全に取得し、指定された型に変換する。
    必須の変数がない場合や、型変換に失敗した場合はエラーを発生させる。
    """
    value = os.getenv(name)

    if value is None:
        if required:
            raise ConfigError(f"必須の環境変数 '{name}' が定義されていません。")
        return default

    try:
        # 空文字の場合はデフォルト値を返す
        if value == '':
            return default
        return cast_to(value)
    except (ValueError, TypeError):
        raise ConfigError(f"環境変数 '{name}' の値 '{value}' を {cast_to.__name__} に正しく変換できません。")

# --- Bot設定 ---
BOT_TOKEN = get_env_var("BOT_TOKEN")
GUILD_ID = get_env_var("GUILD_ID", cast_to=int)
MONGO_URI = get_env_var("MONGO_URI", required=not IS_REPLIT) # Replit以外で必須

# --- チャンネルID ---
ROLE_SELECT_CHANNEL_ID = get_env_var("ROLE_SELECT_CHANNEL_ID", required=False, cast_to=int)
RESULT_CHANNEL_ID = get_env_var("RESULT_CHANNEL_ID", required=False, cast_to=int)
MAIN_CHANNEL_ID = get_env_var("MAIN_CHANNEL_ID", required=False, cast_to=int)
TRIAL_CHANNEL_ID = get_env_var("TRIAL_CHANNEL_ID", required=False, cast_to=int)
EVALUATION_CHANNEL_ID = get_env_var("EVALUATION_CHANNEL_ID", required=False, cast_to=int)
REPORT_CHANNEL_ID = get_env_var("REPORT_CHANNEL_ID", required=False, cast_to=int)

# --- ロールID ---
LAZY_LIFE_ROLE_ID = get_env_var("LAZY_LIFE_ROLE_ID", required=False, cast_to=int)
CLAN_MEMBER_ROLE_ID = get_env_var("CLAN_MEMBER_ROLE_ID", required=False, cast_to=int)
TRIAL_ROLE_ID = get_env_var("TRIAL_ROLE_ID", required=False, cast_to=int)
NON_TRIAL_ROLE_ID = get_env_var("NON_TRIAL_ROLE_ID", required=False, cast_to=int)
STAFF_ROLE_ID = get_env_var("STAFF_ROLE_ID", required=False, cast_to=int)
POST_TRIAL_ROLE_ID = get_env_var("POST_TRIAL_ROLE_ID", required=False, cast_to=int) 

# --- VCカテゴリID ---
SHUFFLE_VC_CATEGORY_ID = get_env_var("SHUFFLE_VC_CATEGORY_ID", required=False, cast_to=int)
