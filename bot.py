import os
import json
import logging
import discord
from discord.ext import commands
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask
from threading import Thread

from config import SHOPPING_CHANNEL_ID, REMINDER_CHANNEL_ID
from shopping import (
    handle_shopping_message,
    cmd_add,
    cmd_list,
    cmd_done,
    cmd_remove,
)
from reminder import (
    setup_reminder_sheet,
    start_reminder_loop,
    handle_reminder_message,
)
from send_queue import MessageSenderQueue

logging.basicConfig(level=logging.INFO)


scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    scope
)

client_gs = gspread.authorize(creds)
spreadsheet = client_gs.open("Shopping_List")

shopping_sheet = spreadsheet.sheet1
reminder_sheet = setup_reminder_sheet(spreadsheet)


app = Flask("")


@app.route("/")
def home():
    return "Bot is running"


def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))


def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()


def create_shopping_help_embed():
    embed = discord.Embed(
        title="🛒 買い物リスト ヘルプ",
        description="こちらでは買い物リスト機能をご利用いただけますわ。",
        color=0x00FFCC
    )

    embed.add_field(
        name="📦 追加",
        value="牛乳を追加 / 牛乳追加 / 牛乳入れて",
        inline=False
    )

    embed.add_field(
        name="🗑 削除",
        value="ココアを削除",
        inline=False
    )

    embed.add_field(
        name="✅ 購入済み",
        value="ココアを購入済み / ココア購入",
        inline=False
    )

    embed.add_field(
        name="📋 表示",
        value="リスト / リスト表示",
        inline=False
    )

    embed.add_field(
        name="⚠️ その他",
        value="全部削除 / リスト削除",
        inline=False
    )

    return embed


def create_reminder_help_embed():
    embed = discord.Embed(
        title="⏰ リマインダー ヘルプ",
        description="こちらではリマインダー機能をご利用いただけますわ。",
        color=0xFFCC00
    )

    embed.add_field(
        name="📝 登録例",
        value=(
            "10分後 薬を飲む\n"
            "今日 21:00 お風呂 30分おき\n"
            "明日 07:30 ゴミ出し 15分おき\n"
            "2026-04-05 19:00 会議"
        ),
        inline=False
    )

    embed.add_field(
        name="📋 一覧",
        value="一覧 / リスト / リマインダー一覧",
        inline=False
    )

    embed.add_field(
        name="✅ 完了",
        value="完了 1",
        inline=False
    )

    embed.add_field(
        name="🗑 削除",
        value="削除 1",
        inline=False
    )

    return embed


def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    tree = bot.tree
    bot.send_queue = None
    bot.reminder_loop_started = False

    def is_shopping_channel(channel_id):
        return channel_id == SHOPPING_CHANNEL_ID

    def is_reminder_channel(channel_id):
        return channel_id == REMINDER_CHANNEL_ID

    async def safe_interaction_send(interaction: discord.Interaction, **kwargs):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(**kwargs)
            else:
                await interaction.followup.send(**kwargs)
        except discord.HTTPException as e:
            status = getattr(e, "status", None)
            print(f"[ERROR] safe_interaction_send failed: status={status} error={e}", flush=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        content="問題が発生しているようですわ。",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        content="問題が発生しているようですわ。",
                        ephemeral=True
                    )
            except Exception as retry_error:
                print(f"[ERROR] safe_interaction_send fallback failed: {retry_error}", flush=True)

    def get_help_embed(channel_id):
        if is_shopping_channel(channel_id):
            return create_shopping_help_embed()

        if is_reminder_channel(channel_id):
            return create_reminder_help_embed()

        return discord.Embed(
            title="ヘルプ",
            description="このチャンネルでは機能が設定されておりませんわ。",
            color=0x999999
        )

    @bot.command()
    async def add(ctx, *, item):
        try:
            if not is_shopping_channel(ctx.channel.id):
                await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
                return

            await cmd_add(ctx, shopping_sheet, item)

        except Exception as e:
            print(f"[ERROR] add command failed: {e}", flush=True)
            await ctx.send("処理中にエラーが発生しましたわ。")

    @bot.command()
    async def list(ctx):
        try:
            if not is_shopping_channel(ctx.channel.id):
                await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
                return

            await cmd_list(ctx, shopping_sheet)

        except Exception as e:
            print(f"[ERROR] list command failed: {e}", flush=True)
            await ctx.send("処理中にエラーが発生しましたわ。")

    @bot.command()
    async def done(ctx, *, item):
        try:
            if not is_shopping_channel(ctx.channel.id):
                await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
                return

            await cmd_done(ctx, shopping_sheet, item)

        except Exception as e:
            print(f"[ERROR] done command failed: {e}", flush=True)
            await ctx.send("処理中にエラーが発生しましたわ。")

    @bot.command()
    async def remove(ctx, *, item):
        try:
            if not is_shopping_channel(ctx.channel.id):
                await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
                return

            await cmd_remove(ctx, shopping_sheet, item)

        except Exception as e:
            print(f"[ERROR] remove command failed: {e}", flush=True)
            await ctx.send("処理中にエラーが発生しましたわ。")

    @bot.command()
    async def queue_status(ctx):
        try:
            if not hasattr(bot, "send_queue") or bot.send_queue is None:
                await ctx.send("送信キューは未初期化ですわ。")
                return

            await ctx.send(f"現在の送信キュー件数は {bot.send_queue.qsize()} 件ですわ。")

        except Exception as e:
            print(f"[ERROR] queue_status failed: {e}", flush=True)
            await ctx.send("処理中にエラーが発生しましたわ。")

    @tree.command(name="help", description="コマンドの使い方を表示します")
    async def help_command(interaction: discord.Interaction):
        try:
            channel_id = interaction.channel.id
            embed = get_help_embed(channel_id)
            await safe_interaction_send(interaction, embed=embed)

        except Exception as e:
            print(f"[ERROR] help command failed: {e}", flush=True)
            await safe_interaction_send(
                interaction,
                content="ヘルプ表示中にエラーが発生しましたわ。",
                ephemeral=True
            )

    @bot.event
    async def on_ready():
        try:
            await tree.sync()
            print(f"ログイン完了: {bot.user}", flush=True)
            print("スラッシュコマンド同期完了", flush=True)

            if bot.send_queue is None:
                bot.send_queue = MessageSenderQueue(bot, base_interval=2.0)
                await bot.send_queue.start()
                print("送信キューワーカー起動完了", flush=True)

            if not bot.reminder_loop_started:
                start_reminder_loop(bot, reminder_sheet)
                bot.reminder_loop_started = True
                print("リマインダーループ起動完了", flush=True)

        except Exception as e:
            print(f"[ERROR] on_ready failed: {e}", flush=True)

    @bot.event
    async def on_message(message):
        try:
            if message.author.bot:
                return

            content = message.content.strip()
            channel_id = message.channel.id

            print(f"ON_MESSAGE: channel={channel_id} content={content}", flush=True)

            if is_shopping_channel(channel_id):
                handled = await handle_shopping_message(bot, message, content, shopping_sheet)
                if handled:
                    return

            elif is_reminder_channel(channel_id):
                print("REMINDER CHANNEL MATCHED", flush=True)

                handled = await handle_reminder_message(bot, message, content, reminder_sheet)
                print(f"REMINDER HANDLED: {handled}", flush=True)

                if handled:
                    return

            await bot.process_commands(message)

        except discord.HTTPException as e:
            print(f"[ERROR] on_message HTTPException: {e}", flush=True)

        except Exception as e:
            print(f"[ERROR] on_message unexpected error: {e}", flush=True)

    return bot


if __name__ == "__main__":
    keep_alive()
    bot = create_bot()
    bot.run(os.environ["DISCORD_TOKEN"])