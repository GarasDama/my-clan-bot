import discord
from discord import app_commands, Embed
from discord.ext import commands

class HelpCog(commands.Cog):
    """
    ボットのヘルプコマンドを管理する機能。
    他のCogに特定の変数を定義することで、動的にヘルプを生成する。
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_all_categories(self) -> dict:
        """ボットにロードされている全てのCogからカテゴリ情報を取得・整理する"""
        categories = {}
        for cog in self.bot.cogs.values():
            if hasattr(cog, "help_category"):
                cat = cog.help_category
                if cat not in categories:
                    categories[cat] = {
                        "description": getattr(cog, "help_description", "説明がありません。"),
                        "cogs": []
                    }
                categories[cat]["cogs"].append(cog)
        return categories

    async def help_category_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """ヘルプカテゴリのオートコンプリート候補を生成する"""
        categories = self.get_all_categories()
        choices = [
            app_commands.Choice(name=f"【{cat}】", value=cat)
            for cat in sorted(list(categories.keys()))
            if current.lower() in cat.lower()
        ]
        return choices[:25]

    @app_commands.command(name="help", description="ボットのコマンドヘルプを表示します。")
    @app_commands.describe(category="詳細を見たいカテゴリを選択してください。")
    @app_commands.autocomplete(category=help_category_autocomplete)
    async def help(self, interaction: discord.Interaction, category: str = None):
        """
        カテゴリ指定なし: カテゴリ一覧を表示
        カテゴリ指定あり: カテゴリ内のコマンド一覧を表示
        """
        all_categories = self.get_all_categories()

        # カテゴリが指定されていない場合、一覧を表示
        if not category:
            embed = Embed(
                title="📜 コマンドヘルプ",
                description="見たいカテゴリを引数で選択（入力時に候補が出ます）してください。",
                color=discord.Color.blurple()
            )
            if not all_categories:
                embed.add_field(name="コマンドなし", value="現在表示できるコマンドはありません。")
            else:
                for cat, data in sorted(all_categories.items()):
                    command_count = 0
                    for cog in data["cogs"]:
                        command_count += len(cog.get_app_commands())

                    embed.add_field(
                        name=f"【{cat}】 ({command_count} コマンド)",
                        value=data["description"],
                        inline=False
                    )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # カテゴリが指定されている場合
        if category not in all_categories:
            return await interaction.response.send_message(f"❌ カテゴリ「{category}」は見つかりませんでした。", ephemeral=True)

        data = all_categories[category]
        embed = Embed(
            title=f"【{category}】のコマンド一覧",
            description=data["description"],
            color=discord.Color.green()
        )

        for cog in data["cogs"]:
            command_helps = getattr(cog, "command_helps", {})
            for cmd in cog.get_app_commands():
                # サブコマンドを持つグループの場合
                if isinstance(cmd, app_commands.Group):
                    for sub_cmd in cmd.commands:
                        qualified_name = sub_cmd.qualified_name
                        desc = command_helps.get(qualified_name, sub_cmd.description or "説明がありません。")
                        embed.add_field(name=f"`/{qualified_name}`", value=desc, inline=False)
                # 通常のコマンドの場合
                elif isinstance(cmd, app_commands.Command):
                    desc = command_helps.get(cmd.name, cmd.description or "説明がありません。")
                    embed.add_field(name=f"`/{cmd.name}`", value=desc, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))