import os
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
from reminder import handle_reminder_message


# ===== Google Sheets設定 =====
import os
import json

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

sheet = client_gs.open("Shopping_List").sheet1


# ===== Discord Bot設定 =====
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_shopping_channel(channel_id):
    return channel_id == SHOPPING_CHANNEL_ID


def is_reminder_channel(channel_id):
    return channel_id == REMINDER_CHANNEL_ID


# ===== コマンド =====
@bot.command()
async def add(ctx, *, item):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_add(ctx, sheet, item)


@bot.command()
async def list(ctx):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_list(ctx, sheet)


@bot.command()
async def done(ctx, *, item):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_done(ctx, sheet, item)


@bot.command()
async def remove(ctx, *, item):
    if not is_shopping_channel(ctx.channel.id):
        await ctx.send("こちらのコマンドは買い物リスト用チャンネルでお使いくださいませ。")
        return

    await cmd_remove(ctx, sheet, item)


# ===== 自然文処理 =====
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    channel_id = message.channel.id

    if is_shopping_channel(channel_id):
        handled = await handle_shopping_message(message, content, sheet)
        if handled:
            return

    elif is_reminder_channel(channel_id):
        handled = await handle_reminder_message(message, content)
        if handled:
            return

    await bot.process_commands(message)


# ===== 起動 =====
bot.run(os.environ["DISCORD_TOKEN"])