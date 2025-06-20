import discord
from discord import app_commands, ui, ButtonStyle, ChannelType, Embed, Color, Interaction, Member
from discord.ext import commands, tasks
from db_handler import db
import config
from datetime import datetime, timezone, timedelta
import asyncio

# --- UIコンポーネントクラス ---

class RoleSelectionView(discord.ui.View):
    """新メンバーに「体験」「助っ人」を選択させるためのView"""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="体験として加入", style=ButtonStyle.success, custom_id="persistent_trial_join"))
        self.add_item(discord.ui.Button(label="助っ人として参加", style=ButtonStyle.secondary, custom_id="persistent_helper_join"))

class EvaluationDecisionView(discord.ui.View):
    """体験メンバーの合否を決定するためのView"""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="合格", style=ButtonStyle.success, custom_id="persistent_trial_pass"))
        self.add_item(discord.ui.Button(label="不合格", style=ButtonStyle.danger, custom_id="persistent_trial_fail"))
        self.add_item(discord.ui.Button(label="保留", style=ButtonStyle.secondary, custom_id="persistent_trial_hold"))

class ClanJoinView(discord.ui.View):
    """合格通知の際に、クランメンバーロールを付与するためのView"""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="クランメンバーになる", style=ButtonStyle.primary, custom_id="persistent_clan_join")
    async def join_clan_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        role = interaction.guild.get_role(config.CLAN_MEMBER_ROLE_ID)
        if not role:
            return await interaction.followup.send("⚠ 「クランメンバー」ロールが見つかりません。", ephemeral=True)

        if role in member.roles:
            return await interaction.followup.send("✅ あなたはすでにクランメンバーです。", ephemeral=True)

        try:
            await member.add_roles(role)
            await interaction.followup.send("✅ あなたはクランメンバーになりました！", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ ロールの付与に失敗しました。権限を確認してください。", ephemeral=True)


# --- メインのCogクラス ---
class ManagementCog(commands.Cog):
    """体験メンバーの管理や、選考関連のコマンドを扱う機能"""
    help_category = "選考管理"
    help_description = "新メンバーの受付、体験フローの管理、合否連絡などを行います。"
    command_helps = {
        "management entry_panel": "（管理者用）新メンバー受付用のパネルを送信します。",
        "management result": "（管理者用）ユーザーの選考結果（合否）を登録・通知します。",
        "management template": "（管理者用）通知に使うメッセージのテンプレートを管理します。",
        "lazy join": "「lazy life」ロールを自分に付与します。",
        "lazy toggle": "（管理者用）lazy joinコマンドの有効/無効を切り替えます。",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(RoleSelectionView())
        self.bot.add_view(EvaluationDecisionView())
        self.bot.add_view(ClanJoinView())
        self.trial_reminder_task.start()

    def cog_unload(self):
        self.trial_reminder_task.cancel()

    def get_guild_data(self, guild_id: int) -> dict:
        """このCogで使うギルドごとのデータを取得・初期化する"""
        key = f"management_{guild_id}"
        defaults = {"results": {}, "templates": {"合格": [], "不合格": []}, "selected_templates": {"合格": 0, "不合格": 0}, "is_lazy_join_enabled": True}
        guild_data = db.get(key, {})
        for k, v in defaults.items():
            guild_data.setdefault(k, v)
        return guild_data

    def save_guild_data(self, guild_id: int, data: dict):
        """このCogで使うギルドごとのデータを保存する"""
        key = f"management_{guild_id}"
        db.set(key, data)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """永続Viewのボタン処理を一括で行うリスナー"""
        custom_id = interaction.data.get("custom_id")
        if not custom_id: return

        if custom_id == "persistent_trial_join":
            await self.handle_trial_join(interaction)
        elif custom_id == "persistent_helper_join":
            await self.handle_helper_join(interaction)
        elif custom_id in ["persistent_trial_pass", "persistent_trial_fail", "persistent_trial_hold"]:
            await self.handle_trial_result(interaction)

    # cogs/management.py の ManagementCog クラス内

    async def handle_trial_join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = interaction.user
        trial_role = interaction.guild.get_role(config.TRIAL_ROLE_ID)
        trial_key = f"trial_{member.id}"

        # ★★★ 修正点1: チェックを最初に行う ★★★
        # DBに記録があるか、または既にロールを持っているかを確認
        if db.get(trial_key) is not None or (trial_role and trial_role in member.roles):
            return await interaction.followup.send("あなたは既に体験フローに参加中です。", ephemeral=True)

        # --- ここから先は、新規参加者として処理 ---

        # ★★★ 修正点2: エラーハンドリングを強化 ★★★
        try:
            # ロール付与処理
            non_trial_role = interaction.guild.get_role(config.NON_TRIAL_ROLE_ID)
            if not trial_role:
                return await interaction.followup.send("⚠ `TRIAL_ROLE_ID`が正しく設定されていません。", ephemeral=True)

            await member.add_roles(trial_role, reason="体験加入")
            if non_trial_role and non_trial_role in member.roles:
                await member.remove_roles(non_trial_role, reason="体験加入への切り替え")

            # DB記録処理
            db.set(trial_key, {
                "name": member.display_name,
                "join_timestamp": datetime.now(timezone.utc).isoformat(),
                "notified_day_1": False,
                "notified_day_3": False
            })

            # 本人への通知
            welcome_message = (
                "✅ **体験メンバーとしてサーバーへようこそ！**\n\n"
                "あなたのための選考用スレッドが、管理者チャンネルに作成されました。\n"
                "今後の流れについては、管理者からの連絡をお待ちください。\n\n"
                "もしよろしければ、自己紹介チャンネルで簡単な自己紹介をお願いします！"
            )
            await interaction.followup.send(welcome_message, ephemeral=True)

            # バックグラウンドでスレッド作成
            asyncio.create_task(self.create_evaluation_thread(member, interaction.guild))

        except discord.Forbidden:
            await interaction.followup.send("❌ ロール付与の権限がありません。ボットのロール階層を確認してください。", ephemeral=True)
        except Exception as e:
            print(f"ERROR: handle_trial_joinで予期せぬエラー: {e}")
            await interaction.followup.send("予期せぬエラーが発生しました。管理者に連絡してください。", ephemeral=True)

    async def handle_helper_join(self, interaction: discord.Interaction):
        """「助っ人として参加」ボタンの処理"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = interaction.user
        helper_role = interaction.guild.get_role(config.NON_TRIAL_ROLE_ID)
        trial_role = interaction.guild.get_role(config.TRIAL_ROLE_ID)
        if not helper_role: return await interaction.followup.send("⚠ `NON_TRIAL_ROLE_ID`が正しく設定されていません。", ephemeral=True)

        try:
            await member.add_roles(helper_role)
            if trial_role and trial_role in member.roles: await member.remove_roles(trial_role)
            await interaction.followup.send("「助っ人」としてサーバーへようこそ！", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ ロール付与の権限がありません。", ephemeral=True)

    async def create_evaluation_thread(self, member: discord.Member, guild: discord.Guild):
        """裏側で評価用スレッドを作成する"""
        eval_channel = guild.get_channel(config.EVALUATION_CHANNEL_ID)
        if not isinstance(eval_channel, discord.TextChannel): return

        staff_role = guild.get_role(config.STAFF_ROLE_ID)
        try:
            thread = await eval_channel.create_thread(name=f"【体験】{member.display_name}さんの選考", type=ChannelType.private_thread)
            await thread.send(content=f"{staff_role.mention if staff_role else ''} {member.display_name}さんの体験加入が開始されました。", view=EvaluationDecisionView())
        except Exception as e:
            print(f"ERROR: 評価スレッドの作成に失敗 - {e}")

    async def handle_trial_result(self, interaction: discord.Interaction):
        """合否ボタンの処理"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not isinstance(interaction.channel, discord.Thread): return

        member_name = interaction.channel.name.replace("【体験】", "").replace("さんの選考", "")
        member = discord.utils.get(interaction.guild.members, display_name=member_name)
        if not member: return await interaction.followup.send(f"対象ユーザー「{member_name}」が見つかりません。", ephemeral=True)

        result_map = {"persistent_trial_pass": "合格", "persistent_trial_fail": "不合格"}
        result = result_map.get(interaction.data["custom_id"])
        if not result: return await interaction.followup.send("この選考を「保留」としてマークしました。", ephemeral=True)

        trial_role = interaction.guild.get_role(config.TRIAL_ROLE_ID)
        full_role = interaction.guild.get_role(config.CLAN_MEMBER_ROLE_ID)
        post_trial_role = config.POST_TRIAL_ROLE_ID and interaction.guild.get_role(config.POST_TRIAL_ROLE_ID)

        db.delete(f"trial_{member.id}")

        try:
            if trial_role and trial_role in member.roles: await member.remove_roles(trial_role)

            if result == "合格":
                if full_role: await member.add_roles(full_role)
                result_channel = interaction.guild.get_channel(config.RESULT_CHANNEL_ID)
                if isinstance(result_channel, discord.TextChannel):
                    res_thread = await result_channel.create_thread(name=f"🎉{member.display_name}さん、ようこそ！")
                    await res_thread.send(f"{member.mention} さん、体験お疲れ様でした！\n\n**【選考結果：合格】**\n\n本日より、正式にクランメンバーとなりました！", view=ClanJoinView())
                await interaction.followup.send("「合格」処理を実行しました。", ephemeral=True)
            else: # 不合格
                if post_trial_role: await member.add_roles(post_trial_role)
                await member.send("体験選考にご参加いただきありがとうございました。\n誠に残念ながら、今回はご期待に沿えない結果となりました。")
                await interaction.followup.send("「不合格」処理を実行し、「体験後」ロールを付与しました。", ephemeral=True)

            await interaction.channel.edit(archived=True, locked=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 処理中にエラーが発生: {e}", ephemeral=True)

    # --- コマンドグループの定義 ---
    management = app_commands.Group(name="management", description="メンバー管理関連のコマンド", guild_only=True)
    result_group = app_commands.Group(name="result", description="選考結果の管理", parent=management)
    template_group = app_commands.Group(name="template", description="通知テンプレートの管理", parent=management)
    lazy_group = app_commands.Group(name="lazy", description="lazy life関連のコマンド", guild_only=True)

    @management.command(name="entry_panel", description="（管理者用）新メンバー受付用のパネルを送信します。")
    @app_commands.checks.has_permissions(administrator=True)
    async def entry_panel(self, interaction: discord.Interaction):
        embed = Embed(title="クランへの加入", description="ようこそ！当サーバーへの加入方法を選択してください。", color=Color.blue())
        embed.add_field(name="体験として加入", value="まずはお試しで活動に参加し、クランの雰囲気などを知りたい方はこちらを選択してください。", inline=False)
        embed.add_field(name="助っ人として参加", value="本加入はせず、イベント等に助っ人として参加したい方はこちらを選択してください。", inline=False)
        await interaction.channel.send(embed=embed, view=RoleSelectionView())
        await interaction.response.send_message("受付パネルを送信しました。", ephemeral=True)

    @result_group.command(name="add", description="ユーザーに選考結果を登録します。")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(result=[app_commands.Choice(name="合格", value="合格"), app_commands.Choice(name="不合格", value="不合格")])
    async def result_add(self, interaction: Interaction, user: Member, result: str):
        guild_data = self.get_guild_data(interaction.guild_id)
        guild_data["results"][str(user.id)] = result
        self.save_guild_data(interaction.guild_id, guild_data)
        await interaction.response.send_message(f"✅ {user.display_name}さんの結果を「{result}」に設定しました。", ephemeral=True)

    @result_group.command(name="list", description="現在の選考結果を一覧表示します。")
    @app_commands.checks.has_permissions(administrator=True)
    async def result_list(self, interaction: Interaction):
        guild_data = self.get_guild_data(interaction.guild_id)
        results = guild_data["results"]
        if not results: return await interaction.response.send_message("📭 現在登録されている結果はありません。", ephemeral=True)
        message = "🗂 **登録済みの選考結果一覧**\n"
        for user_id, result in results.items():
            member = interaction.guild.get_member(int(user_id))
            display_name = member.display_name if member else f"ID: {user_id}"
            message += f"- {display_name}：**{result}**\n"
        await interaction.response.send_message(content=message, ephemeral=True)

    @result_group.command(name="send", description="登録された選考結果を本人に一括で通知します。")
    @app_commands.checks.has_permissions(administrator=True)
    async def result_send(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_data = self.get_guild_data(interaction.guild_id)
        results = guild_data["results"]
        if not results: return await interaction.followup.send("📭 送信する結果が登録されていません。", ephemeral=True)

        channel = interaction.guild.get_channel(config.RESULT_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel): return await interaction.followup.send("⚠ 結果発表用チャンネルが見つかりません。")

        success, fail = 0, 0
        for user_id, result in list(results.items()):
            member = interaction.guild.get_member(int(user_id))
            if not member:
                fail += 1; continue
            try:
                thread = await channel.create_thread(name=f"{member.display_name}さんの選考結果", type=ChannelType.private_thread)
                await thread.add_user(member)
                index = guild_data["selected_templates"].get(result)
                templates = guild_data["templates"].get(result, [])
                if index is None or not (0 <= index < len(templates)):
                    await thread.send(f"{member.mention}さん、こんにちは。\n現在、{result}の通知メッセージが設定されていません。")
                else:
                    message = templates[index].replace("{mention}", member.mention)
                    view = ClanJoinView() if result == "合格" else None
                    await thread.send(content=message, view=view)
                success += 1
            except discord.Forbidden:
                fail += 1

        await interaction.followup.send(f"✅ 全ての選考結果の送信処理が完了しました。\n成功: {success}件, 失敗: {fail}件")
        guild_data["results"].clear()
        self.save_guild_data(interaction.guild_id, guild_data)

    @template_group.command(name="add", description="通知用のメッセージテンプレートを追加します。")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(result_type=[app_commands.Choice(name="合格", value="合格"), app_commands.Choice(name="不合格", value="不合格")])
    async def template_add(self, interaction: Interaction, result_type: str, message: str):
        guild_data = self.get_guild_data(interaction.guild_id)
        guild_data["templates"][result_type].append(message)
        self.save_guild_data(interaction.guild_id, guild_data)
        index = len(guild_data['templates'][result_type]) - 1
        await interaction.response.send_message(f"✅ テンプレートを【{result_type}】に追加しました。(番号: {index})", ephemeral=True)

    @template_group.command(name="list", description="登録されているメッセージテンプレートを一覧表示します。")
    @app_commands.checks.has_permissions(administrator=True)
    async def template_list(self, interaction: Interaction):
        guild_data = self.get_guild_data(interaction.guild_id)
        embed = Embed(title="登録済みテンプレート一覧", color=Color.green())
        for result_type, template_list in guild_data["templates"].items():
            value = "\n".join(f"`{i}`: {template}" for i, template in enumerate(template_list)) if template_list else "登録されていません。"
            embed.add_field(name=f"【{result_type}】", value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @template_group.command(name="set", description="通知に使用するテンプレートの番号を選択します。")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(result_type=[app_commands.Choice(name="合格", value="合格"), app_commands.Choice(name="不合格", value="不合格")])
    async def template_set(self, interaction: Interaction, result_type: str, index: int):
        guild_data = self.get_guild_data(interaction.guild_id)
        if not (0 <= index < len(guild_data["templates"][result_type])):
            return await interaction.response.send_message("❌ 指定されたテンプレートが見つかりません。", ephemeral=True)
        guild_data["selected_templates"][result_type] = index
        self.save_guild_data(interaction.guild_id, guild_data)
        await interaction.response.send_message(f"✅ {result_type}のテンプレートを [{index}] に設定しました。", ephemeral=True)

    @template_group.command(name="delete", description="指定した番号のメッセージテンプレートを削除します。")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(result_type=[app_commands.Choice(name="合格", value="合格"), app_commands.Choice(name="不合格", value="不合格")])
    async def template_delete(self, interaction: Interaction, result_type: str, index: int):
        guild_data = self.get_guild_data(interaction.guild_id)
        templates = guild_data["templates"][result_type]
        if not (0 <= index < len(templates)):
            return await interaction.response.send_message(f"❌ 番号 `{index}` のテンプレートは見つかりません。", ephemeral=True)
        templates.pop(index)
        self.save_guild_data(interaction.guild_id, guild_data)
        await interaction.response.send_message(f"✅ 【{result_type}】 のテンプレート `{index}` を削除しました。", ephemeral=True)

    @lazy_group.command(name="join", description="lazy lifeロールを自分に付与します")
    async def lazy_join(self, interaction: Interaction):
        guild_data = self.get_guild_data(interaction.guild_id)
        if not guild_data.get("is_lazy_join_enabled", True):
            return await interaction.response.send_message("❌ このコマンドは現在、管理者によって無効化されています。", ephemeral=True)
        role = interaction.guild.get_role(config.LAZY_LIFE_ROLE_ID)
        if not role: return await interaction.response.send_message("❌ 'lazy life' ロールが見つかりません。", ephemeral=True)
        if role in interaction.user.roles: return await interaction.response.send_message("あなたはすでに 'lazy life' ロールを持っています。", ephemeral=True)
        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("✅ 'lazy life' ロールを付与しました！", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ ロール付与の権限がありません。", ephemeral=True)

    @lazy_group.command(name="toggle", description="（管理者用）lazy joinコマンドの有効/無効を切り替えます")
    @app_commands.checks.has_permissions(administrator=True)
    async def lazy_toggle(self, interaction: Interaction, enabled: bool):
        guild_data = self.get_guild_data(interaction.guild_id)
        guild_data["is_lazy_join_enabled"] = enabled
        self.save_guild_data(interaction.guild_id, guild_data)
        status = "有効" if enabled else "無効"
        await interaction.response.send_message(f"✅ `/lazy join` コマンドを **{status}** に設定しました。", ephemeral=True)

    @tasks.loop(hours=12.0)
    async def trial_reminder_task(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        all_data = db.all()
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild or not config.REPORT_CHANNEL_ID: return
        report_channel = guild.get_channel(config.REPORT_CHANNEL_ID)
        if not report_channel: return
        for key, data in all_data.items():
            if key.startswith("trial_") and isinstance(data, dict):
                join_dt = datetime.fromisoformat(data.get("join_timestamp", now.isoformat()))
                days_passed = (now - join_dt).days
                member_id = int(key.split('_')[1])
                if days_passed >= 1 and not data.get("notified_day_1"):
                    await report_channel.send(f"【🔔 体験1日経過】<@{member_id}> さんが参加してから1日が経過しました。")
                    data["notified_day_1"] = True; db.set(key, data)
                if days_passed >= 3 and not data.get("notified_day_3"):
                    await report_channel.send(f"【📝 体験3日経過】<@{member_id}> さんが参加してから3日が経過しました。")
                    data["notified_day_3"] = True; db.set(key, data)

async def setup(bot: commands.Bot):
    await bot.add_cog(ManagementCog(bot))