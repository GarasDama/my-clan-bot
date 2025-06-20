import discord
from discord import app_commands
from discord.ext import commands, tasks
from db_handler import db
from datetime import datetime, timezone, timedelta

def format_seconds(seconds: int) -> str:
    """秒を、人間が読みやすい「X時間Y分」や「Y分」の形式に変換する"""
    if seconds < 60:
        return f"{seconds}秒"
    minutes = seconds // 60
    hours = minutes // 60
    minutes = minutes % 60
    if hours > 0:
        return f"{hours}時間{minutes}分"
    else:
        return f"{minutes}分"

class ActivityCog(commands.Cog):
    """サーバー内の活動（チャット、VC参加）を記録し、ランキング化する機能"""
    help_category = "活動記録"
    help_description = "サーバー内のチャット・VC活動履歴やランキングを記録・表示します。"
    command_helps = {
        "ranking": "サーバー内の活動ランキングを表示します（チャット回数/VC滞在時間・総合/月間/週間）",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # ボイスチャンネルのセッションを一時的に保存する辞書 { user_id: join_time }
        self.vc_sessions = {}
        # 1時間ごとにリセット処理をチェックするタスクを開始
        self.check_and_reset_activity.start()

    def cog_unload(self):
        # Cogがアンロードされるときにタスクを安全に停止する
        self.check_and_reset_activity.cancel()

    def get_activity_db(self, user_id: str) -> dict:
        """ユーザーの活動記録データをDBから取得または初期化する"""
        key = f"activity_{user_id}"
        default_data = {
            "name": "",
            "message_count": {"total": 0, "monthly": 0, "weekly": 0},
            "vc_seconds": {"total": 0, "monthly": 0, "weekly": 0}
        }
        # .get()はコピーを返さないため、デフォルト値の場合はコピーを作成して返す
        data = db.get(key)
        if data is None:
            return default_data
        # 念のため、不足しているキーをデフォルト値で埋める
        for k, v in default_data.items():
            if k not in data:
                data[k] = v
        return data

    @commands.Cog.listener()
    async def on_ready(self):
        """ボット起動時に、すでにVCに入っている人を記録する"""
        print("アクティビティCog: on_ready - VCセッションを初期化します。")
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        self.vc_sessions[member.id] = datetime.now()
        print(f"現在 {len(self.vc_sessions)} 人がVCに参加中です。")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """メッセージが投稿されるたびに呼ばれ、チャット数をカウントする"""
        if not message.guild or message.author.bot:
            return

        user_id = str(message.author.id)
        user_activity = self.get_activity_db(user_id)

        user_activity["name"] = message.author.display_name
        user_activity["message_count"]["total"] += 1
        user_activity["message_count"]["monthly"] += 1
        user_activity["message_count"]["weekly"] += 1

        db.set(f"activity_{user_id}", user_activity)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ボイスチャンネルの状態が変化したときに呼ばれ、滞在時間を記録する"""
        if member.bot:
            return

        user_id = member.id

        # VCに参加した時
        if before.channel is None and after.channel is not None:
            self.vc_sessions[user_id] = datetime.now()

        # VCから退出した時
        elif before.channel is not None and after.channel is None:
            if user_id in self.vc_sessions:
                join_time = self.vc_sessions.pop(user_id)
                duration_seconds = int((datetime.now() - join_time).total_seconds())

                user_activity = self.get_activity_db(str(user_id))
                user_activity["name"] = member.display_name
                user_activity["vc_seconds"]["total"] += duration_seconds
                user_activity["vc_seconds"]["monthly"] += duration_seconds
                user_activity["vc_seconds"]["weekly"] += duration_seconds

                db.set(f"activity_{str(user_id)}", user_activity)

    @app_commands.command(name="ranking", description="サーバー内の活動ランキングを表示します。")
    @app_commands.describe(
        type="ランキングの種類を選択してください。",
        period="集計期間を選択してください。"
    )
    @app_commands.choices(
        type=[
            discord.app_commands.Choice(name="💬 チャット回数", value="message_count"),
            discord.app_commands.Choice(name="🎤 VC滞在時間", value="vc_seconds"),
        ],
        period=[
            discord.app_commands.Choice(name="👑 総合", value="total"),
            discord.app_commands.Choice(name="🌙 月間", value="monthly"),
            discord.app_commands.Choice(name="📅 週間", value="weekly"),
        ]
    )
    async def ranking(self, interaction: discord.Interaction, type: discord.app_commands.Choice[str], period: discord.app_commands.Choice[str]):
        await interaction.response.defer()

        all_data = db.all()
        all_users_data = []
        for key, user_data in all_data.items():
            if key.startswith("activity_"):
                if user_data and user_data.get("name"):
                    score = user_data.get(type.value, {}).get(period.value, 0)
                    if score > 0:
                        all_users_data.append({"name": user_data["name"], "score": score})

        sorted_users = sorted(all_users_data, key=lambda x: x["score"], reverse=True)

        embed = discord.Embed(
            title=f"🏆 {period.name} {type.name} ランキング",
            description="サーバー内での活動ランキングです。",
            color=discord.Color.gold()
        )

        rank_text = ""
        for i, user in enumerate(sorted_users[:10]):
            rank = i + 1
            name = user["name"]
            score = user["score"]

            score_display = format_seconds(score) if type.value == "vc_seconds" else f"{score} 回"

            if rank == 1: rank_text += f"🥇 **{rank}位:** {name} - **{score_display}**\n"
            elif rank == 2: rank_text += f"🥈 **{rank}位:** {name} - **{score_display}**\n"
            elif rank == 3: rank_text += f"🥉 **{rank}位:** {name} - **{score_display}**\n"
            else: rank_text += f"**{rank}位:** {name} - {score_display}\n"

        if not rank_text:
            rank_text = "まだ誰もランクインしていません。"

        embed.add_field(name="Top 10", value=rank_text)
        await interaction.followup.send(embed=embed)

    @tasks.loop(hours=1.0)
    async def check_and_reset_activity(self):
        """週間・月間の活動記録をリセットする必要があるかチェックする"""
        now = datetime.now(timezone(timedelta(hours=+9), 'JST'))
        tracker_key = "_internal_tracker"
        tracker = db.get(tracker_key, {"weekly": "", "monthly": ""})

        current_week = now.strftime("%Y-%U")
        current_month = now.strftime("%Y-%m")

        # --- 週間リセットのチェック ---
        if tracker.get("weekly") != current_week:
            print(f"新しい週 ({current_week}) を検出しました。週間活動記録をリセットします。")
            all_data = db.all()
            for key, user_data in all_data.items():
                if key.startswith("activity_"):
                    user_data["message_count"]["weekly"] = 0
                    user_data["vc_seconds"]["weekly"] = 0
                    db.set(key, user_data)
            tracker["weekly"] = current_week
            db.set(tracker_key, tracker)
            print("週間活動記録のリセットが完了しました。")

        # --- 月間リセットのチェック ---
        if tracker.get("monthly") != current_month:
            print(f"新しい月 ({current_month}) を検出しました。月間活動記録をリセットします。")
            all_data = db.all()
            for key, user_data in all_data.items():
                 if key.startswith("activity_"):
                    user_data["message_count"]["monthly"] = 0
                    user_data["vc_seconds"]["monthly"] = 0
                    db.set(key, user_data)
            tracker["monthly"] = current_month
            db.set(tracker_key, tracker)
            print("月間活動記録のリセットが完了しました。")

    @check_and_reset_activity.before_loop
    async def before_check_and_reset(self):
        # ボットが完全に起動するまで待つ
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityCog(bot))