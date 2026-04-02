import re
import asyncio
import discord
from discord.ext import tasks
from datetime import datetime, timedelta

JST = timedelta(hours=9)

HEADERS = [
    "id",
    "channel_id",
    "user_id",
    "user_name",
    "text",
    "remind_at",
    "next_notify_at",
    "repeat_minutes",
    "status",
    "created_at",
    "last_notified_at",
]

reminder_loop = None


# =========================
# シート準備
# =========================
def setup_reminder_sheet(spreadsheet):
    try:
        ws = spreadsheet.worksheet("Reminders")
    except Exception:
        ws = spreadsheet.add_worksheet(title="Reminders", rows=1000, cols=20)
        ws.append_row(HEADERS)

    values = ws.get_all_values()
    if not values:
        ws.append_row(HEADERS)
    elif values[0] != HEADERS:
        ws.clear()
        ws.append_row(HEADERS)

    return ws


# =========================
# 時刻関連
# =========================
def now_jst():
    return datetime.utcnow() + JST


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


# =========================
# 解析
# =========================
def parse_repeat_minutes(text: str):
    """
    末尾の '30分おき' を抜き出す
    """
    m = re.search(r"\s+(\d+)分おき$", text)
    if m:
        repeat_minutes = int(m.group(1))
        text = re.sub(r"\s+\d+分おき$", "", text).strip()
        return text, repeat_minutes
    return text, 60  # デフォルト60分おき


def parse_reminder_input(content: str):
    """
    対応形式:
      1) 10分後 薬を飲む
      2) 今日 21:00 お風呂
      3) 明日 07:30 ゴミ出し 15分おき
      4) 2026-04-05 19:00 会議
    """
    content = content.strip()
    content, repeat_minutes = parse_repeat_minutes(content)
    now = now_jst()

    # 1) 10分後 XXX
    m = re.match(r"^(\d+)分後\s+(.+)$", content)
    if m:
        minutes = int(m.group(1))
        text = m.group(2).strip()
        remind_at = now + timedelta(minutes=minutes)
        return remind_at, text, repeat_minutes

    # 2) 今日 HH:MM XXX
    m = re.match(r"^今日\s+(\d{1,2}):(\d{2})\s+(.+)$", content)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        text = m.group(3).strip()

        remind_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if remind_at <= now:
            return None, None, None  # 今日の時刻が過ぎていたら無効
        return remind_at, text, repeat_minutes

    # 3) 明日 HH:MM XXX
    m = re.match(r"^明日\s+(\d{1,2}):(\d{2})\s+(.+)$", content)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        text = m.group(3).strip()

        tomorrow = now + timedelta(days=1)
        remind_at = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return remind_at, text, repeat_minutes

    # 4) YYYY-MM-DD HH:MM XXX
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s+(.+)$", content)
    if m:
        date_str = m.group(1)
        hour = int(m.group(2))
        minute = int(m.group(3))
        text = m.group(4).strip()

        remind_at = datetime.strptime(f"{date_str} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
        if remind_at <= now:
            return None, None, None
        return remind_at, text, repeat_minutes

    return None, None, None


# =========================
# シート操作
# =========================
def _get_all_records(sheet):
    return sheet.get_all_records()


def _append_row(sheet, row):
    sheet.append_row(row)


def _update_cell(sheet, row, col, value):
    sheet.update_cell(row, col, value)


def _delete_row(sheet, row):
    sheet.delete_rows(row)


async def get_records_async(sheet):
    return await asyncio.to_thread(_get_all_records, sheet)


async def append_row_async(sheet, row):
    await asyncio.to_thread(_append_row, sheet, row)


async def update_cell_async(sheet, row, col, value):
    await asyncio.to_thread(_update_cell, sheet, row, col, value)


async def delete_row_async(sheet, row):
    await asyncio.to_thread(_delete_row, sheet, row)


async def get_next_id(sheet):
    records = await get_records_async(sheet)
    max_id = 0
    for r in records:
        try:
            rid = int(r.get("id", 0))
            if rid > max_id:
                max_id = rid
        except Exception:
            pass
    return max_id + 1


# =========================
# 表示系
# =========================
def build_reminder_embed(records):
    embed = discord.Embed(
        title="⏰ リマインダー一覧",
        color=0xFFCC00
    )

    active_lines = []
    done_lines = []

    for r in records:
        rid = r.get("id")
        text = r.get("text", "")
        remind_at = r.get("remind_at", "")
        repeat_minutes = r.get("repeat_minutes", "")
        status = r.get("status", "")

        line = f"**{rid}**. {text}\n└ 初回: {remind_at} / 再通知: {repeat_minutes}分おき"

        if status == "active":
            active_lines.append(line)
        else:
            done_lines.append(line)

    embed.add_field(
        name=f"稼働中（{len(active_lines)}）",
        value="\n\n".join(active_lines) if active_lines else "なし",
        inline=False
    )

    embed.add_field(
        name=f"完了・停止（{len(done_lines)}）",
        value="\n\n".join(done_lines[:10]) if done_lines else "なし",
        inline=False
    )

    return embed


# =========================
# メッセージ処理
# =========================
async def create_reminder(message, content, sheet):
    remind_at, text, repeat_minutes = parse_reminder_input(content)

    if not remind_at or not text:
        return False

    rid = await get_next_id(sheet)
    now = now_jst()

    row = [
        rid,
        str(message.channel.id),
        str(message.author.id),
        str(message.author),
        text,
        fmt_dt(remind_at),
        fmt_dt(remind_at),
        str(repeat_minutes),
        "active",
        fmt_dt(now),
        "",
    ]

    await append_row_async(sheet, row)

    embed = discord.Embed(
        title="⏰ リマインダーを登録しましたわ",
        color=0xFFCC00
    )
    embed.add_field(name="ID", value=str(rid), inline=True)
    embed.add_field(name="内容", value=text, inline=False)
    embed.add_field(name="初回通知", value=fmt_dt(remind_at), inline=False)
    embed.add_field(name="再通知", value=f"{repeat_minutes}分おき", inline=False)

    await message.channel.send(embed=embed)
    return True


async def handle_list(message, sheet):
    values = await asyncio.to_thread(sheet.get_all_values)
    print("=== RAW VALUES ===", flush=True)
    for row in values:
        print(row, flush=True)

    records = await get_records_async(sheet)
    channel_id = str(message.channel.id)

    print("=== ALL RECORDS ===", flush=True)
    for r in records:
        print(r, flush=True)

    print("CURRENT CHANNEL ID:", channel_id, flush=True)

    filtered = [r for r in records if r.get("channel_id") == channel_id]

    print("=== FILTERED RECORDS ===", flush=True)
    for r in filtered:
        print(r, flush=True)

    embed = build_reminder_embed(filtered)
    await message.channel.send(embed=embed)
    return True


async def handle_complete(message, content, sheet):
    m = re.match(r"^完了\s+(\d+)$", content)
    if not m:
        return False

    target_id = m.group(1)
    records = await get_records_async(sheet)

    for i, r in enumerate(records, start=2):
        if str(r.get("id")) == target_id and str(r.get("channel_id")) == str(message.channel.id):
            await update_cell_async(sheet, i, 9, "done")  # status
            await message.channel.send(f"✅ リマインダー {target_id} 、完了ですわ。")
            return True

    await message.channel.send("そのIDのリマインダーは見つかりませんわ。")
    return True


async def handle_delete(message, content, sheet):
    m = re.match(r"^削除\s+(\d+)$", content)
    if not m:
        return False

    target_id = m.group(1)
    records = await get_records_async(sheet)

    for i, r in enumerate(records, start=2):
        if str(r.get("id")) == target_id and str(r.get("channel_id")) == str(message.channel.id):
            await delete_row_async(sheet, i)
            await message.channel.send(f"🗑 リマインダー {target_id} を削除いたしましたわ。")
            return True

    await message.channel.send("そのIDのリマインダーは見つかりませんわ。")
    return True


async def handle_reminder_message(message, content, sheet):
    print(f"HNADLE_REMINDER_MESSAGE:{content}",flush=True)

    if content in ["テスト", "確認", "リマインダー確認"]:
        await message.channel.send("こちらはリマインダー用チャンネルですわ。")
        return True

    if content in ["一覧", "リスト", "リマインダー一覧"]:
        return await handle_list(message, sheet)

    if await handle_complete(message, content, sheet):
        return True

    if await handle_delete(message, content, sheet):
        return True

    if await create_reminder(message, content, sheet):
        return True

    if content in ["help", "/help", "ヘルプ"]:
        await message.channel.send(
            "使い方例:\n"
            "・10分後 薬を飲む\n"
            "・今日 21:00 お風呂 30分おき\n"
            "・明日 07:30 ゴミ出し 15分おき\n"
            "・2026-04-05 19:00 会議\n"
            "・一覧\n"
            "・完了 1\n"
            "・削除 1"
        )
        return True

    return False


# =========================
# バックグラウンド監視
# =========================
def start_reminder_loop(bot, sheet):
    global reminder_loop

    if reminder_loop is not None and reminder_loop.is_running():
        return

    @tasks.loop(seconds=30)
    async def _loop():
        now = now_jst()
        records = await get_records_async(sheet)

        for i, r in enumerate(records, start=2):
            try:
                if r.get("status") != "active":
                    continue

                next_notify_at_str = r.get("next_notify_at")
                if not next_notify_at_str:
                    continue

                next_notify_at = parse_dt(next_notify_at_str)
                if next_notify_at > now:
                    continue

                channel_id = int(r["channel_id"])
                user_id = int(r["user_id"])
                text = r["text"]
                repeat_minutes = int(r.get("repeat_minutes", 60))

                channel = bot.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await bot.fetch_channel(channel_id)
                    except Exception:
                        continue

                embed = discord.Embed(
                    title="⏰ リマインダーですわ",
                    description=text,
                    color=0xFFCC00
                )
                embed.add_field(name="ID", value=str(r["id"]), inline=True)
                embed.add_field(name="停止方法", value=f"`完了 {r['id']}`", inline=True)
                embed.set_footer(text=f"{repeat_minutes}分ごとに再通知中")

                await channel.send(content=f"<@{user_id}>", embed=embed)

                new_next = now + timedelta(minutes=repeat_minutes)
                await update_cell_async(sheet, i, 7, fmt_dt(new_next))   # next_notify_at
                await update_cell_async(sheet, i, 11, fmt_dt(now))       # last_notified_at

            except Exception as e:
                print(f"[Reminder Loop Error] row={i}: {e}")

    @ _loop.before_loop
    async def before_loop():
        await bot.wait_until_ready()

    reminder_loop = _loop
    reminder_loop.start()