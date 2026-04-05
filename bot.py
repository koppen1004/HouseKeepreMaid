import os
import json
import asyncio
import discord
from discord.ext import commands
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

# ===== Google Sheets設定 =====
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

# 既存の買い物リストは sheet1 をそのまま使う
shopping_sheet = spreadsheet.sheet1

# リマインダー用ワークシートを作成 / 取得
reminder_sheet = setup_reminder_sheet(spreadsheet)

# ===== Discord Bot設定 =====
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def is_shopping_channel(channel_id):
    return channel_id == SHOPPING_CHANNEL_ID


def is_reminder_channel(channel_id):
    return channel_id == REMINDER_CHANNEL_ID


# ===== ヘルプ系 =====
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


# ===== テキストコマンド =====
@bot.command()
async def add(ctx, *, item):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_add(ctx, shopping_sheet, item)


@bot.command()
async def list(ctx):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_list(ctx, shopping_sheet)


@bot.command()
async def done(ctx, *, item):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_done(ctx, shopping_sheet, item)


@bot.command()
async def remove(ctx, *, item):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_remove(ctx, shopping_sheet, item)


# ===== スラッシュコマンド =====
@tree.command(name="help", description="コマンドの使い方を表示します")
async def help_command(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    embed = get_help_embed(channel_id)
    await interaction.response.send_message(embed=embed)


# ===== イベント =====
@bot.event
async def on_ready():
    await tree.sync()
    print(f"ログイン完了: {bot.user}")
    print("スラッシュコマンド同期完了")

    # リマインダー監視ループ開始
    start_reminder_loop(bot, reminder_sheet)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    channel_id = message.channel.id

    print(f"ON_MESSAGE: channel={channel_id} content={content}", flush=True)

    if is_shopping_channel(channel_id):
        handled = await handle_shopping_message(message, content, shopping_sheet)
        if handled:
            return

    elif is_reminder_channel(channel_id):
        print("REMINDER CHANNEL MATCHED", flush=True)

        handled = await handle_reminder_message(message, content, reminder_sheet)

        print(f"REMINDER HANDLED: {handled}", flush=True)

        if handled:
            return

    await bot.process_commands(message)


# ===== 起動 =====
from flask import Flask
from threading import Thread
import time

app = Flask('')


@app.route('/')
def home():
    return "Bot is running"


def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))


def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()


def run_bot():
    retry_count = 0

    while True:
        try:
            print("Starting bot...", flush=True)
            bot.run(os.environ["DISCORD_TOKEN"])

        except discord.HTTPException as e:
            status = getattr(e, "status", None)

            print(f"[ERROR] Discord HTTPException: status={status}", flush=True)
            print(str(e), flush=True)

            if status == 429:
                wait_time = 120
                print(f"[RATE LIMIT] Sleeping {wait_time}s...", flush=True)
                time.sleep(wait_time)
            else:
                wait_time = 30
                print(f"[HTTP ERROR] Sleeping {wait_time}s...", flush=True)
                time.sleep(wait_time)

        except Exception as e:
            print(f"[FATAL ERROR] {e}", flush=True)
            time.sleep(30)

        retry_count += 1
        print(f"[RETRY] count={retry_count}", flush=True)


keep_alive()
run_bot()