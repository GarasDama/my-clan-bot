import discord
from discord import app_commands, ui, ButtonStyle, Embed, Color, Interaction, Member, ChannelType, PermissionOverwrite
from discord.ext import commands
from db_handler import db
import config
import random
import re
from datetime import datetime, timedelta

# --- 定数とヘルパー関数 ---
ROLES = ["gold", "mid", "exp", "jg", "roam"]
ROLES_EMOJI = {"gold":"👑", "mid":"🔮", "exp":"⚔️", "jg":"🗡️", "roam":"🛡️"}

def get_user_profile(user_id: int) -> dict:
    key = f"profile_{user_id}"
    data = db.get(key)
    return data if data else {"role_priority": []}

def set_user_profile(user_id: int, profile_data: dict):
    key = f"profile_{user_id}"
    db.set(key, profile_data)

def user_profile_not_set(user_id: int) -> bool:
    return not get_user_profile(user_id).get("role_priority")

def parse_time_range(time_str: str, default_start="20:00", default_end="24:00"):
    if not time_str: return (default_start, default_end)
    time_str = time_str.strip()
    m = re.match(r"(\d{1,2}):(\d{2})\s*~\s*(\d{1,2}):(\d{2})", time_str)
    if m: return (f"{int(m.group(1)):02}:{m.group(2)}", f"{int(m.group(3)):02}:{m.group(4)}")
    m = re.match(r"(\d{1,2}):(\d{2})\s*まで", time_str)
    if m: return (default_start, f"{int(m.group(1)):02}:{m.group(2)}")
    m = re.match(r"(\d{1,2}):(\d{2})\s*[~から]", time_str)
    if m: return (f"{int(m.group(1)):02}:{m.group(2)}", default_end)
    return (default_start, default_end)

# --- UIクラス定義 ---

class ProfileEditView(ui.View):
    def __init__(self, target_user: Member):
        super().__init__(timeout=300)
        self.target_user = target_user
        profile = get_user_profile(target_user.id)
        self.priority_list: list[str] = profile.get("role_priority", [])
        for role in ROLES:
            button = ui.Button(label=role.upper(), custom_id=f"profile_role_{role}", style=ButtonStyle.secondary)
            button.callback = self.role_button_callback
            self.add_item(button)
        self.update_button_styles()
        confirm_button = ui.Button(label="✅ この順で登録", style=ButtonStyle.green, custom_id="profile_confirm", row=1)
        confirm_button.callback = self.confirm_button_callback
        self.add_item(confirm_button)
        reset_button = ui.Button(label="リセット", style=ButtonStyle.red, custom_id="profile_reset", row=1)
        reset_button.callback = self.reset_button_callback
        self.add_item(reset_button)
    def update_button_styles(self):
        for item in self.children:
            if isinstance(item, ui.Button) and item.custom_id.startswith("profile_role_"):
                role_name = item.custom_id.split("_")[-1]
                item.style = ButtonStyle.primary if role_name in self.priority_list else ButtonStyle.secondary
    async def update_message(self, interaction: Interaction):
        self.update_button_styles()
        formatted_list = "\n".join(f"{i+1}. `{role.upper()}`" for i, role in enumerate(self.priority_list))
        if not formatted_list: formatted_list = "`（上のボタンを押して希望順位を追加してください）`"
        embed = interaction.message.embeds[0]; embed.description = f"**現在の希望順位:**\n{formatted_list}"
        await interaction.response.edit_message(embed=embed, view=self)
    async def role_button_callback(self, interaction: Interaction):
        role_name = interaction.data["custom_id"].split("_")[-1]
        if role_name in self.priority_list: self.priority_list.remove(role_name)
        else:
            if len(self.priority_list) < len(ROLES): self.priority_list.append(role_name)
        await self.update_message(interaction)
    async def confirm_button_callback(self, interaction: Interaction):
        set_user_profile(self.target_user.id, {"role_priority": self.priority_list, "name": self.target_user.display_name})
        formatted_list = "\n".join(f"{i+1}. `{role.upper()}`" for i, role in enumerate(self.priority_list))
        embed = Embed(title="✅ プロフィール更新完了", description=f"以下の希望順位でロールを登録しました。\n\n{formatted_list}", color=Color.green())
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self); self.stop()
    async def reset_button_callback(self, interaction: Interaction):
        self.priority_list.clear(); await self.update_message(interaction)
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id == self.target_user.id: return True
        await interaction.response.send_message("この操作は、コマンドを実行した本人しか行えません。", ephemeral=True); return False

class ProfileSetForUserModal(ui.Modal, title="代理プロフィール設定"):
    roles_input = ui.TextInput(label="希望ロールを上から順番に改行で区切って入力", style=discord.TextStyle.paragraph, placeholder="例:\nmid\njg\ngold...", required=True)
    def __init__(self, target_user: Member):
        super().__init__(); self.target_user = target_user; profile = get_user_profile(self.target_user.id)
        self.roles_input.default = "\n".join(profile.get("role_priority", []))
    async def on_submit(self, interaction: Interaction):
        raw_input = self.roles_input.value.strip().lower()
        priority_list = [role.strip() for role in raw_input.split('\n') if role.strip() in ROLES]
        if not priority_list: return await interaction.response.send_message("❌ 有効なロール名が入力されませんでした。", ephemeral=True)
        set_user_profile(self.target_user.id, {"role_priority": priority_list, "name": self.target_user.display_name})
        formatted_list = "\n".join(f"{i+1}. `{role.upper()}`" for i, role in enumerate(priority_list))
        embed = Embed(title=f"✅ {self.target_user.display_name}さんのプロフィールを更新", description=f"以下の希望順位でロールを登録しました。\n\n{formatted_list}", color=Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class EventView(ui.View):
    def __init__(self, event_id: str):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.attend_button.custom_id = f"event_attend_{self.event_id}"
        self.temp_attend_button.custom_id = f"event_temp_attend_{self.event_id}"
        self.if_free_button.custom_id = f"event_if_free_{self.event_id}"
        self.leave_button.custom_id = f"event_leave_{self.event_id}"
    async def update_embed(self, interaction: Interaction):
        events = db.get("active_events", {})
        event_data = events.get(self.event_id)
        if not event_data or not interaction.message: return
        participants = event_data.get("participants", {})
        limit = event_data.get("limit")
        participant_count = len([p for p in participants.values() if p.get("status") in ["参加", "一時的に参加", "空いていれば参加"]])
        limit_str = f"/{limit}人" if limit else ""
        embed = interaction.message.embeds[0]; embed.clear_fields()
        embed.add_field(name=f"現在の参加状況 ({participant_count}{limit_str})", value="\u200b", inline=False)
        statuses = {"参加": "✅", "一時的に参加": "🕒", "空いていれば参加": "❔"}
        for status, emoji in statuses.items():
            member_list = []
            sorted_participants = sorted([item for item in participants.items() if item[1].get("status") == status], key=lambda item: item[1].get("timestamp", ""))
            for user_id, p_data in sorted_participants:
                roles_str = f"({', '.join(p_data.get('roles', []))})" if p_data.get('roles') else ""
                time_str = f" [{p_data.get('time')}]" if status == "一時的に参加" and p_data.get('time') else ""
                member_list.append(f"- <@{user_id}> {roles_str}{time_str}")
            embed.add_field(name=f"{emoji} {status} ({len(member_list)}人)", value="\n".join(member_list) if member_list else "まだいません", inline=True)
        await interaction.message.edit(embed=embed)
    async def update_participant_data(self, interaction: Interaction, status: str, roles=None, time=None) -> bool:
        events = db.get("active_events", {})
        if self.event_id not in events:
            msg = "このイベントは既に存在しません。";
            if not interaction.response.is_done(): await interaction.response.send_message(msg, ephemeral=True)
            else: await interaction.followup.send(msg, ephemeral=True)
            return False
        participants = events[self.event_id]["participants"]
        user_id_str = str(interaction.user.id)
        if status == "辞退":
            if user_id_str in participants: del participants[user_id_str]
        else:
            if not roles: roles = get_user_profile(interaction.user.id).get("role_priority", [])
            participants[user_id_str] = {"name": interaction.user.display_name, "roles": roles, "status": status, "timestamp": datetime.now().isoformat(), "time": time if status == "一時的に参加" else ""}
        db.set("active_events", events)
        await self.update_embed(interaction)
        return True
    async def _check_profile_and_rsvp(self, interaction: Interaction, status: str):
        if user_profile_not_set(interaction.user.id): return await interaction.response.send_message("❌ まず `/profile set` で希望ロールを登録してください！", ephemeral=True)
        await interaction.response.defer()
        success = await self.update_participant_data(interaction, status)
        if success: await interaction.followup.send(f"「{status}」で受け付けました。", ephemeral=True)
    @ui.button(label="✅ 参加", style=ButtonStyle.green)
    async def attend_button(self, i: Interaction, b: ui.Button): await self._check_profile_and_rsvp(i, "参加")
    @ui.button(label="🕒 一時参加", style=ButtonStyle.primary)
    async def temp_attend_button(self, i: Interaction, b: ui.Button):
        if user_profile_not_set(i.user.id): return await i.response.send_message("❌ まず `/profile set`で希望ロールを登録してください！", ephemeral=True)
        await i.response.send_modal(TempAttendModal(self, i.user))
    @ui.button(label="❔ 空いていれば参加", style=ButtonStyle.primary)
    async def if_free_button(self, i: Interaction, b: ui.Button): await self._check_profile_and_rsvp(i, "空いていれば参加")
    @ui.button(label="❌ 辞退", style=ButtonStyle.red, row=1)
    async def leave_button(self, i: Interaction, b: ui.Button):
        await i.response.defer()
        success = await self.update_participant_data(i, "辞退")
        if success: await i.followup.send("参加を辞退しました。", ephemeral=True)

class TempAttendModal(ui.Modal, title="一時的に参加"):
    roles_input = ui.TextInput(label="希望ロール (任意, 改行区切り)", style=discord.TextStyle.paragraph, placeholder="gold\nmid", required=False)
    time_input = ui.TextInput(label="参加可能な時間帯 (必須)", placeholder="例: 21:30~22:30", required=True)
    def __init__(self, view: EventView, user: Member):
        super().__init__(); self.view = view; self.roles_input.default = "\n".join(get_user_profile(user.id).get("role_priority", []))
    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        roles = [r.strip().lower() for r in self.roles_input.value.split('\n') if r.strip().lower() in ROLES]
        if not roles: roles = get_user_profile(interaction.user.id).get("role_priority", [])
        success = await self.view.update_participant_data(interaction, "一時的に参加", roles=roles, time=self.time_input.value)
        if success: await interaction.followup.send("「一時的に参加」で受け付けました。", ephemeral=True)

class EventCreateModal(ui.Modal, title="イベント作成"):
    summary_input = ui.TextInput(label="イベント概要", placeholder="例: クラン内カスタムマッチ")
    start_time_input = ui.TextInput(label="イベント開始時間", placeholder="例: 21:30から")
    limit_input = ui.TextInput(label="募集人数上限 (任意)", placeholder="例: 10", required=False)
    notes_input = ui.TextInput(label="補足事項 (任意)", style=discord.TextStyle.paragraph, required=False)
    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        limit = self.limit_input.value
        if limit and not limit.isdigit(): return await interaction.followup.send("募集人数は数字で入力してください。", ephemeral=True)
        event_data = { "summary": self.summary_input.value, "start_time": self.start_time_input.value, "notes": self.notes_input.value, "limit": int(limit) if limit else None, "participants": {}, "channel_id": interaction.channel_id, "guild_id": interaction.guild_id }
        embed = Embed(title=f"📅 {event_data['summary']}", color=Color.blue(), description=f"## {event_data['start_time']} 開始\n---")
        limit_str = f"/{event_data['limit']}人" if event_data['limit'] else ""
        embed.add_field(name=f"現在の参加状況 (0{limit_str})", value="下のボタンから意思表明をしてください！", inline=False)
        try:
            msg = await interaction.channel.send(embed=embed)
            event_id = str(msg.id)
            await msg.edit(view=EventView(event_id=event_id))
            events_db_key = "active_events"
            events = db.get(events_db_key, {})
            events[event_id] = event_data
            db.set(events_db_key, events)
            await interaction.followup.send("✅ イベント募集を開始しました。", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ イベント作成中にエラーが発生しました: {e}", ephemeral=True)

class ShuffleResultView(ui.View):
    def __init__(self, shuffle_id: str):
        super().__init__(timeout=None)
        self.shuffle_id = shuffle_id
    @ui.button(label="🟡 控えで参加する", style=ButtonStyle.primary, custom_id="shuffle_join_sub")
    async def join_sub_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        completed_shuffles = db.get("completed_shuffles", {})
        completed_data = completed_shuffles.get(self.shuffle_id)
        if not completed_data: return
        user_id_str = str(interaction.user.id)
        is_participant = any(user_id_str == pid for team in completed_data.get("teams", {}).get("teams", {}).values() for pid in team.values())
        if is_participant or user_id_str in completed_data.get("teams", {}).get("subs", {}):
            return await interaction.followup.send("あなたはすでにこのチーム分けに参加しています。", ephemeral=True)
        sub_role = interaction.guild.get_role(completed_data.get("created_roles", {}).get("sub"))
        if sub_role and isinstance(interaction.user, Member):
            try:
                await interaction.user.add_roles(sub_role, reason="控え参加")
                completed_shuffles[self.shuffle_id].setdefault("teams", {}).setdefault("subs", {})[user_id_str] = {"name": interaction.user.display_name}
                db.set("completed_shuffles", completed_shuffles)
                await interaction.followup.send("控えメンバーとして参加し、ロールを付与しました。", ephemeral=True)
            except discord.Forbidden: await interaction.followup.send("❌ ロール付与の権限がありません。", ephemeral=True)
        else: await interaction.followup.send("控えロールが見つからないか、エラーが発生しました。", ephemeral=True)

class AssignmentResultView(ui.View):
    def __init__(self, assignment_id: str):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id
    @ui.button(label="🙋 不足ロールを埋める", style=ButtonStyle.primary, custom_id="fill_missing_role")
    async def fill_role_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message("どの枠を担当しますか？", view=FillRoleView(self.assignment_id, interaction), ephemeral=True)

class FillRoleView(ui.View):
    def __init__(self, assignment_id: str, original_interaction: Interaction):
        super().__init__(timeout=300)
        self.assignment_id = assignment_id; self.original_interaction = original_interaction; self.selected_slot = None
        assignments = db.get("active_assignments", {}); assignment_data = assignments.get(self.assignment_id)
        options = []
        if assignment_data:
            for role, data in assignment_data["shifts"].items():
                if data is None:
                    label = f"{ROLES_EMOJI.get(role, '❔')} {role.upper()}"
                    value = role; options.append(discord.SelectOption(label=label, value=value))
        select = ui.Select(placeholder="担当したい不足ロールを選択...", options=options)
        select.callback = self.role_select
        if not options: select.placeholder = "現在、不足しているロールはありません。"; select.disabled = True
        self.add_item(select)
        confirm_button = ui.Button(label="確定する", style=ButtonStyle.success); confirm_button.callback = self.confirm
        self.add_item(confirm_button)
    async def role_select(self, interaction: Interaction, select: ui.Select):
        self.selected_slot = select.values[0]
        await interaction.response.send_message(f"`{select.values[0].upper()}` を選択しました。「確定」ボタンを押してください。", ephemeral=True)
    async def confirm(self, interaction: Interaction, button: ui.Button):
        if not self.selected_slot: return await interaction.response.send_message("先にドロップダウンから担当したい枠を選択してください。", ephemeral=True)
        await interaction.response.defer()
        assignments = db.get("active_assignments", {}); assignment_data = assignments.get(self.assignment_id)
        if not assignment_data: return await interaction.followup.send("❌ この割り当ては既に存在しません。", ephemeral=True)
        role_to_fill = self.selected_slot
        if assignment_data["shifts"][role_to_fill] is not None: return await interaction.followup.send("❌ そのロールは既に埋まっています。", ephemeral=True)
        assignment_data["shifts"][role_to_fill] = {"name": interaction.user.display_name, "status": "後から参加"}
        db.set("active_assignments", assignments)
        try:
            original_message = await self.original_interaction.channel.fetch_message(assignment_data["message_id"])
            cog = self.original_interaction.client.get_cog("EventsCog")
            new_embed = cog.format_assignment_embed(assignment_data["shifts"], assignment_data["summary"])
            await original_message.edit(embed=new_embed)
        except Exception as e: print(f"ERROR: シフト表の更新に失敗 - {e}")
        await interaction.followup.send("✅ シフト表にあなたを追加しました！", ephemeral=True)
        self.stop()

# --- Cog本体 ---
class EventsCog(commands.Cog):
    """イベント・プロフィール・チーム分け関連の機能"""
    help_category = "イベント"
    help_description = "イベント募集、プロフィール設定、チーム分けなどを行います。"
    command_helps = { "profile set": "自分の希望ロール（役割）の優先順位を設定します。", "profile set_for_user": "【管理者用】他のメンバーの希望ロール順を代理で登録・更新します。", "event create": "参加者を募集するためのイベントパネルを作成します。", "event assign": "募集を締め切り、チーム分けはせずに役割分担を発表します。", "event shuffle": "募集を締め切り、5v5のチーム分けを自動で実行します。", "event cleanup": "チーム分けで作成された一時的なロールとVCを全て削除します。", "event priority_pick": "役割・チーム分けの際に、特定のメンバーを優先します。" }

    def __init__(self, bot: commands.Bot): self.bot = bot
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        print(f"Cog 'EventsCog' でエラー: {error}"); import traceback; traceback.print_exc()
        if interaction.response.is_done(): await interaction.followup.send("❌ 処理中にエラーが発生しました。", ephemeral=True)
        else: await interaction.response.send_message("❌ 処理中にエラーが発生しました。", ephemeral=True)

    profile = app_commands.Group(name="profile", description="希望ロールなどのプロフィール設定", guild_only=True)
    event = app_commands.Group(name="event", description="イベントの作成や管理", guild_only=True)

    @profile.command(name="set", description="自分の希望ロール順を、ボタン操作で登録・更新します。")
    async def profile_set(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        view = ProfileEditView(target_user=interaction.user)
        profile = get_user_profile(interaction.user.id)
        current_priority = profile.get("role_priority", [])
        formatted_list = "\n".join(f"{i+1}. `{role.upper()}`" for i, role in enumerate(current_priority))
        if not formatted_list: formatted_list = "`（上のボタンを押して希望順位を追加してください）`"
        embed = Embed(title=f"{interaction.user.display_name}の希望ロール設定", description=f"**現在の希望順位:**\n{formatted_list}", color=Color.purple())
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @profile.command(name="set_for_user", description="【管理者用】他のメンバーの希望ロール順を代理で登録・更新します。")
    @app_commands.describe(member="プロフィールを設定するメンバー")
    @app_commands.checks.has_permissions(administrator=True)
    async def profile_set_for_user(self, interaction: Interaction, member: Member):
        await interaction.response.send_modal(ProfileSetForUserModal(target_user=member))

    @event.command(name="create", description="参加者を募集するためのイベントパネルを作成します。")
    @app_commands.checks.has_permissions(manage_events=True)
    async def event_create(self, interaction: Interaction):
        await interaction.response.send_modal(EventCreateModal())

    def _get_active_event(self, interaction: Interaction):
        active_events = db.get("active_events", {})
        channel_events = {sid: sdata for sid, sdata in active_events.items() if sdata.get("channel_id") == interaction.channel_id}
        if not channel_events: return None, None, None
        event_id = max(channel_events.keys(), key=int)
        return event_id, active_events, channel_events[event_id]

    def _solve_assignment(self, participants: dict, priority_picks: dict) -> dict:
        sorted_participants = sorted(participants.items(), key=lambda item: item[1]['timestamp'])
        assigned_users, assignments = set(), {role: None for role in ROLES}
        for role, user_id_str in priority_picks.items():
            if role in ROLES and user_id_str in participants and user_id_str not in assigned_users:
                assignments[role] = participants[user_id_str]; assigned_users.add(user_id_str)
        for user_id, data in sorted_participants:
            if user_id in assigned_users: continue
            for role in data.get("roles", []):
                if role in ROLES and assignments[role] is None:
                    assignments[role] = data; assigned_users.add(user_id); break
        return assignments

    def format_assignment_embed(self, assignment_data: dict, event_summary: str) -> Embed:
        embed = Embed(title=f"【役割分担】{event_summary}", color=Color.green())
        for role, data in assignment_data.items():
            if data:
                icon = {"参加": "✅", "一時的に参加": "🕒", "空いていれば参加": "❔", "後から参加": "🙋"}.get(data["status"], "❔")
                embed.add_field(name=f"{ROLES_EMOJI.get(role, '❔')} {role.upper()}", value=f"{icon} `{data['name']}`", inline=True)
            else: embed.add_field(name=f"{ROLES_EMOJI.get(role, '❔')} {role.upper()}", value="**【不足】**", inline=True)
        return embed

    @event.command(name="assign", description="募集を締め切り、役割分担を発表します。")
    @app_commands.checks.has_permissions(manage_events=True)
    async def event_assign(self, interaction: Interaction):
        await interaction.response.defer()
        event_id, active_events, event_data = self._get_active_event(interaction)
        if not event_id: return await interaction.followup.send("このチャンネルに募集中のイベントはありません。", ephemeral=True)
        participants = {uid: pdata for uid, pdata in event_data.get("participants", {}).items() if pdata.get("status") in ["参加", "一時的に参加", "空いていれば参加"]}
        priority_picks = event_data.get("priority_picks", {})
        assignments = self._solve_assignment(participants, priority_picks)
        embed = self.format_assignment_embed(assignments, event_data['summary'])
        msg = await interaction.channel.send(embed=embed, view=AssignmentResultView(assignment_id=event_id))
        assignments_db_key = "active_assignments"; active_assignments = db.get(assignments_db_key, {})
        active_assignments[event_id] = {"shifts": assignments, "message_id": msg.id, "summary": event_data['summary']}
        db.set(assignments_db_key, active_assignments)
        await interaction.followup.send("✅ 役割分担を発表しました。", ephemeral=True)
        try:
            original_msg = await interaction.channel.fetch_message(int(event_id))
            await original_msg.edit(content=f"~~**【{event_data.get('summary')}】は締め切られました**~~", embed=None, view=None)
        except: pass
        del active_events[event_id]; db.set("active_events", active_events)

    def _solve_strict_5v5(self, players: dict, priority_picks: dict) -> dict | None:
        player_ids = list(players.keys())
        if len(player_ids) < 10: return None
        for _ in range(100):
            assignments, available_roles, available_players = {}, set(ROLES), set(player_ids)
            for role, user_id in priority_picks.items():
                if role in available_roles and user_id in available_players:
                    assignments[("red", role)] = user_id; available_roles.remove(role); available_players.remove(user_id)
            shuffled_players = list(available_players); random.shuffle(shuffled_players)
            slots_to_fill = [(team, role) for team in ["red", "blue"] for role in ROLES if (team, role) not in assignments]
            def solve(p_pool, s_pool):
                if not s_pool: return True
                team, role = s_pool[0]
                candidates = [pid for pid in p_pool if role in get_user_profile(int(pid)).get("role_priority",[])]
                random.shuffle(candidates)
                for candidate in candidates:
                    assignments[(team, role)] = candidate
                    if solve([p for p in p_pool if p != candidate], s_pool[1:]): return True
                    del assignments[(team, role)]
                return False
            if solve(shuffled_players, slots_to_fill):
                team_red = {r: p for t, r in assignments if t == "red" for p in [assignments[(t,r)]]}
                team_blue = {r: p for t, r in assignments if t == "blue" for p in [assignments[(t,r)]]}
                final_players_in_teams = set(team_red.values()) | set(team_blue.values())
                subs = {pid: players[pid] for pid in player_ids if pid not in final_players_in_teams}
                return {"teams": {"red": team_red, "blue": team_blue}, "subs": subs}
        return None

    @event.command(name="shuffle", description="募集を締め切り、5v5のチーム分けを実行します。")
    @app_commands.checks.has_permissions(manage_events=True)
    async def event_shuffle(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        event_id, active_events, event_data = self._get_active_event(interaction)
        if not event_id: return await interaction.followup.send("このチャンネルに募集中のイベントはありません。", ephemeral=True)
        participants = {uid: pdata for uid, pdata in event_data.get("participants", {}).items() if pdata.get("status") == "参加"}
        if len(participants) < 10: return await interaction.followup.send(f"❌ 参加者が10人に満たないため、5v5チーム分けを中止しました。(現在{len(participants)}人)", ephemeral=True)
        priority_picks = event_data.get("priority_picks", {})
        result = self._solve_strict_5v5(participants, priority_picks)
        if not result: return await interaction.followup.send("❌ 参加者のロールの組み合わせでは、バランスの取れた5v5チームを作成できませんでした。", ephemeral=True)
        guild = interaction.guild
        category = guild.get_channel(config.SHUFFLE_VC_CATEGORY_ID)
        if not category or not isinstance(category, discord.CategoryChannel): return await interaction.followup.send("VC作成先のカテゴリが見つかりません。", ephemeral=True)
        try:
            role_red = await guild.create_role(name=f"🔴 赤チーム({event_id[-4:]})", color=Color.red(), reason="チーム分け")
            role_blue = await guild.create_role(name=f"🔵 青チーム({event_id[-4:]})", color=Color.blue(), reason="チーム分け")
            role_sub = await guild.create_role(name=f"🟡 控え({event_id[-4:]})", color=Color.gold(), reason="チーム分け")
            overwrites = {"red": {guild.default_role: PermissionOverwrite(connect=False), role_red: PermissionOverwrite(connect=True)}, "blue": {guild.default_role: PermissionOverwrite(connect=False), role_blue: PermissionOverwrite(connect=True)}}
            vc_red, vc_blue = await category.create_voice_channel(name="🔴 赤チーム VC", overwrites=overwrites["red"]), await category.create_voice_channel(name="🔵 青チーム VC", overwrites=overwrites["blue"])
        except discord.Forbidden: return await interaction.followup.send("❌ ロールまたはVCの作成権限がありません。", ephemeral=True)
        async def assign_roles(team_data, role):
            for pid in team_data.values():
                try: await guild.get_member(int(pid)).add_roles(role)
                except: print(f"Failed to assign role to {pid}")
        await assign_roles(result["teams"]["red"], role_red); await assign_roles(result["teams"]["blue"], role_blue)
        for pid in result["subs"].keys():
            try: await guild.get_member(int(pid)).add_roles(role_sub)
            except: pass
        result_embed = Embed(title=f"【{event_data['summary']}】チーム分け結果発表！", color=Color.green())
        def format_team(team_data): return "\n".join([f"- {ROLES_EMOJI.get(role, '❔')} **{role.upper()}**: <@{pid}>" for role, pid in team_data.items()]) or "N/A"
        result_embed.add_field(name="🔴 赤チーム", value=format_team(result["teams"]["red"]), inline=True)
        result_embed.add_field(name="🔵 青チーム", value=format_team(result["teams"]["blue"]), inline=True)
        result_embed.add_field(name="控えメンバー", value="\n".join([f"- <@{pid}>" for pid in result["subs"].keys()]) if result["subs"] else "なし", inline=False)
        result_embed.add_field(name="専用VC", value=f"- 赤チーム: {vc_red.mention}\n- 青チーム: {vc_blue.mention}", inline=False)
        result_msg = await interaction.channel.send(embed=result_embed)
        completed_shuffles = db.get("completed_shuffles", {}); completed_shuffle_id = str(result_msg.id)
        completed_shuffles[completed_shuffle_id] = {"teams": result, "created_roles": {"red": role_red.id, "blue": role_blue.id, "sub": role_sub.id}, "created_vcs": {"red": vc_red.id, "blue": vc_blue.id}}
        db.set("completed_shuffles", completed_shuffles)
        await result_msg.edit(view=ShuffleResultView(shuffle_id=completed_shuffle_id))
        try:
            original_msg = await interaction.channel.fetch_message(int(event_id))
            await original_msg.edit(content=f"~~**【{event_data.get('summary')}】は締め切られました**~~", embed=None, view=None)
        except: pass
        del active_events[event_id]; db.set("active_events", active_events)
        await interaction.followup.send("✅ チーム分けが完了しました！", ephemeral=True)

    @event.command(name="cleanup", description="Botが作成した一時的なVCとロールを全て削除します。")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def event_cleanup(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        completed_shuffles = db.get("completed_shuffles", {})
        if not completed_shuffles: return await interaction.followup.send("クリーンアップ対象はありません。", ephemeral=True)
        deleted_roles, deleted_vcs, errors = 0, 0, 0
        for shuffle_id in list(completed_shuffles.keys()):
            s_data = completed_shuffles.pop(shuffle_id)
            for role_id in s_data.get("created_roles", {}).values():
                try:
                    role = interaction.guild.get_role(role_id)
                    if role: await role.delete(reason="シャッフルクリーンアップ"); deleted_roles += 1
                except: errors += 1
            for vc_id in s_data.get("created_vcs", {}).values():
                try:
                    vc = interaction.guild.get_channel(vc_id)
                    if vc: await vc.delete(reason="シャッフルクリーンアップ"); deleted_vcs += 1
                except: errors += 1
        db.set("completed_shuffles", completed_shuffles)
        await interaction.followup.send(f"✅ クリーンアップ完了\n- 削除したロール: {deleted_roles}個\n- 削除したVC: {deleted_vcs}個", ephemeral=True)

    @event.command(name="priority_pick", description="このイベントで特定のロールを優先的に担当する人を指定します。")
    @app_commands.checks.has_permissions(manage_events=True)
    @app_commands.describe(role="優先するロール", user="優先するユーザー")
    @app_commands.choices(role=[app_commands.Choice(name=r.upper(), value=r) for r in ROLES])
    async def event_priority_pick(self, interaction: Interaction, role: str, user: Member):
        await interaction.response.defer(ephemeral=True)
        event_id, active_events, event_data = self._get_active_event(interaction)
        if not event_id: return await interaction.followup.send("このチャンネルに募集中のイベントはありません。", ephemeral=True)
        event_data.setdefault("priority_picks", {})[role] = str(user.id)
        db.set("active_events", active_events)
        await interaction.followup.send(f"✅ {user.mention}さんを **{role.upper()}** の優先プレイヤーに設定しました。", ephemeral=True)

# --- セットアップ関数 ---
async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
    active_events = db.get("active_events", {})
    if isinstance(active_events, dict):
        for event_id in active_events.keys(): bot.add_view(EventView(event_id=event_id))
    completed_shuffles = db.get("completed_shuffles", {})
    if isinstance(completed_shuffles, dict):
        for shuffle_id in completed_shuffles.keys(): bot.add_view(ShuffleResultView(shuffle_id=shuffle_id))
    active_assignments = db.get("active_assignments", {})
    if isinstance(active_assignments, dict):
        for assign_id in active_assignments.keys(): bot.add_view(AssignmentResultView(assignment_id=assign_id))