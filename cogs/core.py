import discord
from discord.ext import commands
from discord import app_commands

class CoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="ボットの応答速度をテストします。")
    async def ping(self, interaction: discord.Interaction):
        latency = self.bot.latency * 1000
        await interaction.response.send_message(f"🏓 Pong! \n応答速度: {latency:.2f}ms")

async def setup(bot: commands.Bot):
    await bot.add_cog(CoreCog(bot))
