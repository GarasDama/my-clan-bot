import os
import asyncio
import discord
from discord.ext import commands
import config
from aiohttp import web

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        print("📦 Cogを読み込んでいます...")
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('_'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f'✅ Loaded: {filename}')
                except Exception as e:
                    print(f'❌ Failed to load {filename}: {type(e).__name__}: {e}')
        try:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"📡 {len(synced)}個のコマンドをギルド({config.GUILD_ID})に同期しました。")
        except Exception as e:
            print(f"❌ コマンド同期に失敗: {e}")

    async def on_ready(self):
        print("----------------------------------------")
        print(f"✅ {self.user} としてログインしました！")
        print("----------------------------------------")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is alive!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = os.getenv("PORT", 8080)
    site = web.TCPSite(runner, '0.0.0.0', port)
    print(f"🌐 Web server is running on port {port}.")
    await site.start()
    await asyncio.Future()

async def main():
    bot = MyBot()
    await asyncio.gather(bot.start(config.BOT_TOKEN), start_web_server())

if __name__ == '__main__':
    if not os.path.exists('./cogs'):
        os.makedirs('./cogs')
    try:
        asyncio.run(main())
    except config.ConfigError as e:
        print(f"FATAL: 設定エラー: {e}")
    except KeyboardInterrupt:
        print("🛑 Bot is shutting down.")
