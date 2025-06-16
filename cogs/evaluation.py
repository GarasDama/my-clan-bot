import discord
from discord import app_commands
from discord.ext import commands
import db_handler as db
import config
from datetime import datetime, timezone, timedelta
import pprint

# ===============================================
# ★★★ UIクラス定義セクション ★★★
# ===============================================

# --- 評価時のコメント入力用モーダル ---
class CommentModal(discord.ui.Modal, title="評価コメントの入力"):
    comment = discord.ui.TextInput(label="評価コメント", style=discord.TextStyle.paragraph, placeholder="具体的な行動や良かった点などを記述してください。", required=True, max_length=500)
    def __init__(self, target_user: discord.Member, points: int):
        super().__init__()
        self.target_user = target_user
        self.points = points

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target_user_id = str(self.target_user.id)
        
        # データベースからデータを取得、なければ新しいデータ構造で初期化
        default_data = {
            "name": self.target_user.display_name,
            "public_reputation": {"points": 0},
            "internal_rating": {"points": 0, "history": [], "admin_log": []}
        }
        user_data = db.get(target_user_id, default_data)

        # ポイントを計算
        user_data["internal_rating"]["points"] += self.points
        if self.points > 0:
            user_data["public_reputation"]["points"] += 1
        elif self.points < 0:
            user_data["public_reputation"]["points"] -= 1
        
        # 履歴を作成
        jst = timezone(timedelta(hours=+9), 'JST')
        new_history = {
            "by_id": interaction.user.id,
            "by_name": interaction.user.display_name,
            "points": self.points,
            "comment": self.comment.value,
            "timestamp": datetime.now(jst).isoformat()
        }
        user_data["internal_rating"]["history"].insert(0, new_history)
        user_data["internal_rating"]["history"] = user_data["internal_rating"]["history"][:20]
        
        # データベースに保存
        db.set(target_user_id, user_data)
        
        await interaction.followup.send(f"{self.target_user.mention} さんを **{self.points:+}点** で評価し、記録しました。", ephemeral=True)
        
        # ロール更新処理を呼び出す
        if interaction.guild:
            cog = interaction.client.get_cog("EvaluationCog")
            if cog:
                await cog.update_user_title_role(self.target_user, interaction.guild)


# --- 右クリック評価用のUI ---
class EvaluationView(discord.ui.View):
    def __init__(self, target_user: discord.Member):
        super().__init__(timeout=300)
        self.target_user = target_user
        self.selected_points = None
    
    @discord.ui.select(placeholder="評価点数を選択してください...", options=[ discord.SelectOption(label="👍👍👍 (+5) 伝説的な貢献", value="5"), discord.SelectOption(label="👍👍 (+3) 素晴らしい", value="3"), discord.SelectOption(label="👍 (+1) 良い", value="1"), discord.SelectOption(label="😐 (0) 普通", value="0"), discord.SelectOption(label="👎 (-1) 課題あり", value="-1"), discord.SelectOption(label="👎👎 (-3) 要改善", value="-3"), discord.SelectOption(label="👎👎👎 (-5) 警告", value="-5"), ])
    async def select_points(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_points = int(select.values[0])
        await interaction.response.edit_message(content=f"点数 **{self.selected_points:+}** を選択しました。")
    
    @discord.ui.button(label="コメント入力", style=discord.ButtonStyle.primary)
    async def open_comment_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected_points is None: 
            return await interaction.response.send_message("先に評価点数を選択してください。", ephemeral=True)
        await interaction.response.send_modal(CommentModal(target_user=self.target_user, points=self.selected_points))

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="評価をキャンセルしました。", view=None)

# --- 管理者パネル用のポイント操作モーダル ---
class PointSetModal(discord.ui.Modal):
    internal_points = discord.ui.TextInput(label="内部評価ポイント (任意)", placeholder="例: 100", style=discord.TextStyle.short, required=False)
    public_points = discord.ui.TextInput(label="公開評判ポイント (任意)", placeholder="例: 10", style=discord.TextStyle.short, required=False)
    reason = discord.ui.TextInput(label="操作の理由 (必須)", style=discord.TextStyle.paragraph, required=True)
    
    def __init__(self, target_user: discord.Member, mode: str, panel_view: discord.ui.View):
        super().__init__(title=f"ポイント{ '上書き(SET)' if mode == 'set' else '加算(ADD)' }", timeout=None)
        self.target_user = target_user
        self.mode = mode
        self.panel_view = panel_view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target_user_id = str(self.target_user.id)
        user_data = db.get(target_user_id)
        
        if self.internal_points.value:
            try:
                val = int(self.internal_points.value)
                if self.mode == 'set': user_data["internal_rating"]["points"] = val
                else: user_data["internal_rating"]["points"] += val
            except ValueError: return await interaction.followup.send("内部評価ポイントは整数で入力してください。", ephemeral=True)
        
        if self.public_points.value:
            try:
                val = int(self.public_points.value)
                if self.mode == 'set': user_data["public_reputation"]["points"] = val
                else: user_data["public_reputation"]["points"] += val
            except ValueError: return await interaction.followup.send("公開評判ポイントは整数で入力してください。", ephemeral=True)
        
        jst = timezone(timedelta(hours=+9), 'JST')
        admin_log_entry = { "by": interaction.user.display_name, "action": f"manual_{self.mode}", "reason": self.reason.value, "timestamp": datetime.now(jst).isoformat() }
        user_data.setdefault("internal_rating", {}).setdefault("admin_log", []).insert(0, admin_log_entry)

        db.set(target_user_id, user_data)
        
        await interaction.followup.send(f"**{self.target_user.display_name}** さんのポイントを操作しました。", ephemeral=True)
        
        # ロール更新とパネル表示の更新
        if interaction.guild:
            cog = interaction.client.get_cog("EvaluationCog")
            if cog:
                await cog.update_user_title_role(self.target_user, interaction.guild)
        
        await self.panel_view.update_display(self.target_user)

# --- 管理者パネル本体のUI ---
class AdminPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.message = None
        self.selected_user_id = None
        self._update_player_select()

    def _update_player_select(self):
        all_player_data = db.all()
        options = []
        for key, data in all_player_data.items():
            if key.startswith("_"): continue
            if isinstance(data, dict) and "evaluation" in key:
                label = data.get("name", key)
                options.append(discord.SelectOption(label=label, value=key.split('_')[-1]))
        if not options: options.append(discord.SelectOption(label="データがありません", value="no_data"))
        player_select = discord.ui.Select(placeholder="▼ 確認・操作したいプレイヤーを選択", options=options, row=0)
        player_select.callback = self.on_player_select
        if len(self.children) > 0 and isinstance(self.children[0], discord.ui.Select): self.children[0] = player_select
        else: self.add_item(player_select)

    async def update_display(self, user: discord.Member):
        target_user_id = str(user.id)
        user_data = db.get(f"evaluation_{target_user_id}", {"public_reputation":{"points":0}, "internal_rating":{"points":0,"history":[]}})
        cog = self.bot.get_cog("EvaluationCog")
        rank, _ , _ = cog.get_reputation_details(user_data.get('public_reputation', {}).get('points', 0))
        
        embed = discord.Embed(title=f"👤 {user.display_name} さんのステータス", color=discord.Color.blue())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="公開評判", value=f"**{user_data.get('public_reputation', {}).get('points', 0)} pt** (ランク: {rank})", inline=False)
        embed.add_field(name="内部評価", value=f"**{user_data.get('internal_rating', {}).get('points', 0)} pt**", inline=False)
        history_text = ""
        for h in user_data.get('internal_rating', {}).get('history', [])[:3]: history_text += f"- `{h['points']:+}pt` by {h['by_name']}: {h['comment'][:30]}\n"
        if not history_text: history_text = "まだありません"
        embed.add_field(name="最近の評価履歴", value=history_text, inline=False)
        if self.message: await self.message.edit(content=None, embed=embed, view=self)

    async def on_player_select(self, interaction: discord.Interaction):
        if not interaction.data["values"]: return
        selected_value = interaction.data["values"][0]
        if selected_value == "no_data": return await interaction.response.defer()
        self.selected_user_id = selected_value
        member = interaction.guild.get_member(int(self.selected_user_id))
        if not member: return await interaction.response.send_message("メンバーが見つかりませんでした。", ephemeral=True)
        await interaction.response.defer()
        await self.update_display(member)

    @discord.ui.button(label="ポイント上書き(SET)", style=discord.ButtonStyle.danger, row=1)
    async def point_set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_user_id: return await interaction.response.send_message("先にプレイヤーを選択してください。", ephemeral=True)
        member = interaction.guild.get_member(int(self.selected_user_id))
        await interaction.response.send_modal(PointSetModal(target_user=member, mode='set', panel_view=self))
    
    @discord.ui.button(label="ポイント加算(ADD)", style=discord.ButtonStyle.primary, row=1)
    async def point_add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_user_id: return await interaction.response.send_message("先にプレイヤーを選択してください。", ephemeral=True)
        member = interaction.guild.get_member(int(self.selected_user_id))
        await interaction.response.send_modal(PointSetModal(target_user=member, mode='add', panel_view=self))

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.secondary, row=2)
    async def close_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="パネルを閉じました。", view=None, embed=None)

# ===============================================
# ★★★ コマンド定義セクション ★★★
# ===============================================

# --- 右クリックメニュー（ContextMenu）の定義 ---
@app_commands.context_menu(name="このプレイヤーを評価")
@app_commands.checks.has_permissions(administrator=True)
async def evaluate_user(interaction: discord.Interaction, user: discord.Member):
    if user.bot: return await interaction.response.send_message("Botは評価できません。", ephemeral=True)
    if user.id == interaction.user.id: return await interaction.response.send_message("自分自身は評価できません。", ephemeral=True)
    view = EvaluationView(target_user=user)
    await interaction.response.send_message(f"**{user.display_name}** さんを評価します。", view=view, ephemeral=True)

@evaluate_user.error
async def on_evaluate_user_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions): await interaction.response.send_message("このコマンドを実行するには管理者権限が必要です。", ephemeral=True)
    else: print(f"ContextMenu 'evaluate_user' でエラー: {error}"); await interaction.response.send_message("予期せぬエラーが発生しました。", ephemeral=True)

# --- スラッシュコマンド等を管理するCog本体 ---
class EvaluationCog(commands.Cog):
    help_category = "評価システム"
    help_description = "プレイヤーの評価・称号システムです。"
    command_helps = {
        "admin_panel": "評価データを閲覧・操作する管理者用パネルを開きます。",
        "rating": "（管理者用）指定ユーザーの詳細な評価履歴を確認します。",
        "reputation": "自分や他人の公開評判（ランクと紹介文）を確認します。",
        "title_setting": "（管理者用）称号獲得に必要なポイントや連携ロールを設定します。",
    }
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_reputation_details(self, points: int):
        # 称号データをDBからロード。なければデフォルト値を使う。
        titles_data = db.get("titles_config", {
            "Hopeful": {"point": 10, "role_id": None}, "Ace": {"point": 30, "role_id": None},
            "Veteran": {"point": 60, "role_id": None}, "Hero": {"point": 100, "role_id": None},
            "Legend": {"point": 200, "role_id": None}
        })
        # ポイントでソート
        sorted_titles = sorted(titles_data.items(), key=lambda item: item[1]['point'])

        user_title = None
        for name, data in reversed(sorted_titles):
            if points >= data['point']:
                user_title = name
                break
        
        if user_title == "Legend": rank, flavor, color = "S (伝説的)", "クランの誰もが認めるエース。その存在は皆の希望となっている。", discord.Color.gold()
        elif user_title == "Hero": rank, flavor, color = "A (英雄的)", "クランの信頼できる主力メンバー。安定した活躍を見せている。", discord.Color.orange()
        elif user_title == "Veteran": rank, flavor, color = "B (優秀)", "多くの場面で頼りになる、クランに不可欠な存在。", discord.Color.blue()
        elif user_title == "Ace": rank, flavor, color = "C (有望)", "着実に力をつけている、期待のメンバー。", discord.Color.green()
        elif user_title == "Hopeful": rank, flavor, color = "D (駆け出し)", "クランの一員としての活動を始めたばかり。", discord.Color.light_grey()
        else: rank, flavor, color = "E (見習い)", "これからの活動に期待がかかる。", discord.Color.dark_grey()
            
        return rank, flavor, color

    async def update_user_title_role(self, member: discord.Member, guild: discord.Guild):
        # ... (ロール更新ロジックをここに実装) ...
        pass

    @app_commands.command(name="admin_panel", description="管理者用のコントロールパネルを開きます。")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = AdminPanelView(self.bot)
        await interaction.followup.send("▼ 確認・操作したいプレイヤーを選択してください", view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="rating", description="指定したユーザーの内部評価と詳細な履歴を確認します。")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="評価を確認したいユーザー")
    async def rating(self, interaction: discord.Interaction, user: discord.Member):
        target_user_id = str(user.id)
        user_data = db.get(f"evaluation_{target_user_id}")
        if not user_data: return await interaction.response.send_message(f"{user.mention} さんの評価データはまだありません。", ephemeral=True)
        # ... (ratingコマンドのEmbed作成ロジック) ...

    @app_commands.command(name="reputation", description="自分や他のメンバーの公開評判を確認します。")
    @app_commands.describe(user="評判を確認したいユーザー（指定がなければ自分）")
    async def reputation(self, interaction: discord.Interaction, user: discord.Member = None):
        if user is None: user = interaction.user
        target_user_id = str(user.id)
        user_data = db.get(f"evaluation_{target_user_id}")
        if not user_data: return await interaction.response.send_message(f"{user.mention} さんの評判データはまだありません。", ephemeral=True)
        points = user_data.get("public_reputation", {}).get("points", 0)
        rank, flavor_text, color = self.get_reputation_details(points)
        embed = discord.Embed(title=f"👤 {user.display_name} さんの評判", description=f"**評判ランク: {rank}**", color=color)
        embed.add_field(name="紹介", value=flavor_text)
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="title_setting", description="称号獲得に必要なポイントや連携ロールを設定します。")
    @app_commands.checks.has_permissions(administrator=True)
    # ... (title_settingコマンドの実装) ...

# セットアップ関数
async def setup(bot: commands.Bot):
    await bot.add_cog(EvaluationCog(bot))
    bot.tree.add_command(evaluate_user)
