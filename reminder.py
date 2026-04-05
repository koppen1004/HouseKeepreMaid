import re
import asyncio
import discord
from discord.ext import tasks
from datetime import datetime, timedelta

from send_queue import enqueue_message

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
    m = re.search(r"\s+(\d+)分おき$", text)
    if m:
        repeat_minutes = int(m.group(1))
        text = re.sub(r"\s+\d+分おき$", "", text).strip()
        return text, repeat_minutes
    return text, 60


def parse_reminder_input(content: str):
    content = content.strip()
    content, repeat_minutes = parse_repeat_minutes(content)
    now = now_jst()

    m = re.match(r"^(\d+)分後\s+(.+)$", content)
    if m:
        minutes = int(m.group(1))
        text = m.group(2).strip()
        remind_at = now + timedelta(minutes=minutes)
        return remind_at, text, repeat_minutes

    m = re.match(r"^今日\s+(\d{1,2}):(\d{2})\s+(.+)$", content)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        text = m.group(3).strip()

        remind_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if remind_at <= now:
            return None, None, None
        return remind_at, text, repeat_minutes

    m = re.match(r"^明日\s+(\d{1,2}):(\d{2})\s+(.+)$", content)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        text = m.group(3).strip()

        tomorrow = now + timedelta(days=1)
        remind_at = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return remind_at, text, repeat_minutes

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
    try:
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

        await enqueue_message(
            message.client,
            message.channel.id,
            embed=embed,
            metadata={"feature": "reminder", "action": "create", "reminder_id": rid},
        )
        return True

    except Exception as e:
        print(f"[ERROR] create_reminder: {e}", flush=True)
        await enqueue_message(
            message.client,
            message.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "reminder", "action": "create_error"},
        )
        return True


async def handle_list(message, sheet):
    try:
        records = await get_records_async(sheet)

        filtered = [
            r for r in records
            if str(r.get("channel_id")) == str(message.channel.id)
        ]

        embed = build_reminder_embed(filtered)
        await enqueue_message(
            message.client,
            message.channel.id,
            embed=embed,
            metadata={"feature": "reminder", "action": "list"},
        )
        return True

    except Exception as e:
        print(f"[ERROR] handle_list: {e}", flush=True)
        await enqueue_message(
            message.client,
            message.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "reminder", "action": "list_error"},
        )
        return True


async def handle_complete(message, content, sheet):
    try:
        m = re.match(r"^完了\s+(\d+)$", content)
        if not m:
            return False

        target_id = m.group(1)
        records = await get_records_async(sheet)

        for i, r in enumerate(records, start=2):
            if str(r.get("id")) == target_id and str(r.get("channel_id")) == str(message.channel.id):
                await update_cell_async(sheet, i, 9, "done")
                await enqueue_message(
                    message.client,
                    message.channel.id,
                    content=f"✅ リマインダー {target_id} 、完了ですわ。",
                    metadata={"feature": "reminder", "action": "complete", "reminder_id": target_id},
                )
                return True

        await enqueue_message(
            message.client,
            message.channel.id,
            content="そのIDのリマインダーは見つかりませんわ。",
            metadata={"feature": "reminder", "action": "complete_not_found", "reminder_id": target_id},
        )
        return True

    except Exception as e:
        print(f"[ERROR] handle_complete: {e}", flush=True)
        await enqueue_message(
            message.client,
            message.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "reminder", "action": "complete_error"},
        )
        return True


async def handle_delete(message, content, sheet):
    try:
        m = re.match(r"^削除\s+(\d+)$", content)
        if not m:
            return False

        target_id = m.group(1)
        records = await get_records_async(sheet)

        for i, r in enumerate(records, start=2):
            if str(r.get("id")) == target_id and str(r.get("channel_id")) == str(message.channel.id):
                await delete_row_async(sheet, i)
                await enqueue_message(
                    message.client,
                    message.channel.id,
                    content=f"🗑 リマインダー {target_id} を削除いたしましたわ。",
                    metadata={"feature": "reminder", "action": "delete", "reminder_id": target_id},
                )
                return True

        await enqueue_message(
            message.client,
            message.channel.id,
            content="そのIDのリマインダーは見つかりませんわ。",
            metadata={"feature": "reminder", "action": "delete_not_found", "reminder_id": target_id},
        )
        return True

    except Exception as e:
        print(f"[ERROR] handle_delete: {e}", flush=True)
        await enqueue_message(
            message.client,
            message.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "reminder", "action": "delete_error"},
        )
        return True


async def handle_reminder_message(message, content, sheet):
    print(f"HANDLE_REMINDER_MESSAGE: {content}", flush=True)

    try:
        if content in ["テスト", "確認", "リマインダー確認"]:
            await enqueue_message(
                message.client,
                message.channel.id,
                content="こちらはリマインダー用チャンネルですわ。",
                metadata={"feature": "reminder", "action": "channel_check"},
            )
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
            await enqueue_message(
                message.client,
                message.channel.id,
                content=(
                    "使い方例:\n"
                    "・10分後 薬を飲む\n"
                    "・今日 21:00 お風呂 30分おき\n"
                    "・明日 07:30 ゴミ出し 15分おき\n"
                    "・2026-04-05 19:00 会議\n"
                    "・一覧\n"
                    "・完了 1\n"
                    "・削除 1"
                ),
                metadata={"feature": "reminder", "action": "help"},
            )
            return True

        return False

    except Exception as e:
        print(f"[ERROR] handle_reminder_message: {e}", flush=True)
        await enqueue_message(
            message.client,
            message.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "reminder", "action": "handle_message_error"},
        )
        return True


# =========================
# バックグラウンド監視
# =========================
def start_reminder_loop(bot, sheet):
    global reminder_loop

    if reminder_loop is not None and reminder_loop.is_running():
        return

    @tasks.loop(seconds=30)
    async def _loop():
        try:
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

                    embed = discord.Embed(
                        title="⏰ リマインダーですわ",
                        description=text,
                        color=0xFFCC00
                    )
                    embed.add_field(name="ID", value=str(r["id"]), inline=True)
                    embed.add_field(name="停止方法", value=f"`完了 {r['id']}`", inline=True)
                    embed.set_footer(text=f"{repeat_minutes}分ごとに再通知中")

                    delay = (user_id % 5) * 2

                    await enqueue_message(
                        bot,
                        channel_id,
                        content=f"<@{user_id}>",
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(
                            users=True,
                            roles=False,
                            everyone=False,
                        ),
                        delay_before_send=delay,
                        metadata={
                            "feature": "reminder",
                            "action": "notify",
                            "reminder_id": r["id"],
                            "user_id": user_id,
                        },
                    )

                    new_next = now + timedelta(minutes=repeat_minutes)
                    await update_cell_async(sheet, i, 7, fmt_dt(new_next))
                    await update_cell_async(sheet, i, 11, fmt_dt(now))

                except Exception as row_error:
                    print(f"[Reminder Loop Error] row={i}: {row_error}", flush=True)

        except Exception as loop_error:
            print(f"[Reminder Loop Fatal] {loop_error}", flush=True)

    @_loop.before_loop
    async def before_loop():
        await bot.wait_until_ready()

    reminder_loop = _loop
    reminder_loop.start()