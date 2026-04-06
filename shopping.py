from datetime import datetime

import discord
from discord import ButtonStyle
from discord.ui import Button, View

from send_queue import enqueue_message

confirm_clear = {}

MAX_VIEW_ITEMS = 25


class ShoppingView(View):
    def __init__(self, sheet, create_embed_func, max_items: int = MAX_VIEW_ITEMS):
        super().__init__(timeout=None)
        self.sheet = sheet
        self.create_embed_func = create_embed_func
        self.max_items = max_items
        self.build()

    def build(self):
        self.clear_items()
        data = self.sheet.get_all_values()

        added = 0

        for i, row in enumerate(data[1:], start=2):
            if len(row) < 4:
                continue

            if added >= self.max_items:
                break

            item = row[2]
            status = row[3]

            button = Button(
                label=item[:80],
                style=ButtonStyle.success if status == "済" else ButtonStyle.secondary
            )

            async def callback(interaction, row=i, item=item):
                try:
                    current = self.sheet.cell(row, 4).value
                    new_status = "未購入" if current == "済" else "済"
                    self.sheet.update_cell(row, 4, new_status)

                    embed = self.create_embed_func(self.sheet, self.max_items)
                    view = ShoppingView(self.sheet, self.create_embed_func, self.max_items)

                    await interaction.response.edit_message(embed=embed, view=view)

                except discord.HTTPException as e:
                    status = getattr(e, "status", None)
                    print(f"[ERROR] shopping button callback HTTPException: status={status} error={e}", flush=True)

                    try:
                        if status == 429:
                            if interaction.response.is_done():
                                await interaction.followup.send(
                                    "ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                                    ephemeral=True
                                )
                            else:
                                await interaction.response.send_message(
                                    "ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                                    ephemeral=True
                                )
                        else:
                            if interaction.response.is_done():
                                await interaction.followup.send(
                                    "問題が発生しているようですわ。",
                                    ephemeral=True
                                )
                            else:
                                await interaction.response.send_message(
                                    "問題が発生しているようですわ。",
                                    ephemeral=True
                                )
                    except Exception as notify_error:
                        print(f"[ERROR] shopping button callback notify failed: {notify_error}", flush=True)

                except Exception as e:
                    print(f"[ERROR] shopping button callback unexpected: {e}", flush=True)
                    try:
                        if interaction.response.is_done():
                            await interaction.followup.send(
                                "問題が発生しているようですわ。",
                                ephemeral=True
                            )
                        else:
                            await interaction.response.send_message(
                                "問題が発生しているようですわ。",
                                ephemeral=True
                            )
                    except Exception as notify_error:
                        print(f"[ERROR] shopping button callback fallback failed: {notify_error}", flush=True)

            button.callback = callback
            self.add_item(button)
            added += 1


def create_embed(sheet, max_items: int = MAX_VIEW_ITEMS):
    data = sheet.get_all_values()

    embed = discord.Embed(
        title="🛒 買い物リスト",
        color=0x00FFCC
    )

    not_done = []
    done = []

    for row in data[1:]:
        if len(row) < 4:
            continue

        item = row[2]
        status = row[3]

        if status == "済":
            done.append(f"✅ {item}")
        else:
            not_done.append(f"❌ {item}")

    not_done_display = not_done[:max_items]
    done_display = done[:max_items]

    embed.add_field(
        name=f"🛍 未購入（{len(not_done)}）",
        value="\n".join(not_done_display) if not_done_display else "なし",
        inline=False
    )

    embed.add_field(
        name=f"✅ 購入済み（{len(done)}）",
        value="\n".join(done_display) if done_display else "なし",
        inline=False
    )

    total_items = len(not_done) + len(done)
    if total_items > max_items:
        embed.set_footer(text=f"表示負荷軽減のため先頭 {max_items} 件まで表示しておりますわ。")

    return embed


async def handle_shopping_message(bot, message, content, sheet):
    try:
        user_id = message.author.id

        if content in ["リスト削除", "全部削除", "リスト全削除"]:
            confirm_clear[user_id] = True
            await enqueue_message(
                bot,
                message.channel.id,
                content="⚠️ 本当に削除いたしますの？「はい」で実行いたしますわ。",
                metadata={"feature": "shopping", "action": "confirm_clear"},
            )
            return True

        if content == "はい" and confirm_clear.get(user_id):
            sheet.resize(1)
            confirm_clear[user_id] = False
            await enqueue_message(
                bot,
                message.channel.id,
                content="🧹 注文予定は白紙にいたしましたわ。",
                metadata={"feature": "shopping", "action": "clear_all"},
            )
            return True

        suffixes = ["を追加", "追加", "追加して", "入れて"]

        if any(content.endswith(s) for s in suffixes):
            item = content

            for s in suffixes:
                if item.endswith(s):
                    item = item[:-len(s)]
                    break

            item = item.strip()

            if item:
                sheet.append_row([
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    str(message.author),
                    item,
                    "未購入"
                ])
                await enqueue_message(
                    bot,
                    message.channel.id,
                    content=f"{item} を追加いたしましたわ。",
                    metadata={"feature": "shopping", "action": "add_item", "item": item},
                )
            else:
                await enqueue_message(
                    bot,
                    message.channel.id,
                    content="追加する品をお書きくださいませ。",
                    metadata={"feature": "shopping", "action": "add_item_empty"},
                )

            return True

        if content in ["リスト", "リスト表示", "買い物リスト", "表示"]:
            data = sheet.get_all_values()

            if len(data) <= 1:
                await enqueue_message(
                    bot,
                    message.channel.id,
                    content="注文予定は何もないようですわね。",
                    metadata={"feature": "shopping", "action": "show_list_empty"},
                )
                return True

            embed = create_embed(sheet, MAX_VIEW_ITEMS)
            view = ShoppingView(sheet, create_embed, MAX_VIEW_ITEMS)
            await enqueue_message(
                bot,
                message.channel.id,
                embed=embed,
                view=view,
                metadata={"feature": "shopping", "action": "show_list"},
            )
            return True

        if content.endswith("を削除"):
            item = content.replace("を削除", "").replace("削除", "").strip()
            data = sheet.get_all_values()

            for i, row in enumerate(data):
                if i == 0:
                    continue
                if len(row) < 4:
                    continue
                if row[2] == item:
                    sheet.delete_rows(i + 1)
                    await enqueue_message(
                        bot,
                        message.channel.id,
                        content=f"{item} は注文予定から外しておきますわね。",
                        metadata={"feature": "shopping", "action": "remove_item", "item": item},
                    )
                    return True

            await enqueue_message(
                bot,
                message.channel.id,
                content="そちらは注文予定にはないようですわ。",
                metadata={"feature": "shopping", "action": "remove_item_not_found", "item": item},
            )
            return True

        if content.endswith("を購入済み"):
            item = content.replace("を購入済み", "").replace("購入", "").strip()
            data = sheet.get_all_values()

            for i, row in enumerate(data):
                if i == 0:
                    continue
                if len(row) < 4:
                    continue
                if row[2] == item:
                    sheet.update_cell(i + 1, 4, "済")
                    await enqueue_message(
                        bot,
                        message.channel.id,
                        content=f"{item} を注文いたしましたわ。",
                        metadata={"feature": "shopping", "action": "mark_done", "item": item},
                    )
                    return True

            await enqueue_message(
                bot,
                message.channel.id,
                content="そちらは注文予定にはないようですわ。",
                metadata={"feature": "shopping", "action": "mark_done_not_found", "item": item},
            )
            return True

        if content.endswith("購入"):
            item = content[:-2].strip()
            data = sheet.get_all_values()

            for i, row in enumerate(data):
                if i == 0:
                    continue
                if len(row) < 4:
                    continue
                if row[2] == item:
                    sheet.update_cell(i + 1, 4, "済")
                    await enqueue_message(
                        bot,
                        message.channel.id,
                        content=f"{item} を注文いたしましたわ。",
                        metadata={"feature": "shopping", "action": "mark_done_short", "item": item},
                    )
                    return True

            await enqueue_message(
                bot,
                message.channel.id,
                content="そちらは注文予定にはないようですわ。",
                metadata={"feature": "shopping", "action": "mark_done_short_not_found", "item": item},
            )
            return True

        return False

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] handle_shopping_message HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                bot,
                message.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                metadata={"feature": "shopping", "action": "http_429"},
            )
        else:
            await enqueue_message(
                bot,
                message.channel.id,
                content="問題が発生しているようですわ。",
                metadata={"feature": "shopping", "action": "http_error", "status": status},
            )
        return True

    except Exception as e:
        print(f"[ERROR] handle_shopping_message unexpected: {e}", flush=True)
        try:
            await enqueue_message(
                bot,
                message.channel.id,
                content="問題が発生しているようですわ。",
                metadata={"feature": "shopping", "action": "unexpected_error"},
            )
        except Exception as enqueue_error:
            print(f"[ERROR] handle_shopping_message enqueue failed: {enqueue_error}", flush=True)
        return True


async def cmd_add(ctx, sheet, item):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        user = str(ctx.author)

        sheet.append_row([now, user, item, "未購入"])
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content=f"商品を追加いたしましたわ：{item}",
            metadata={"feature": "shopping", "action": "cmd_add", "item": item},
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_add HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                metadata={"feature": "shopping", "action": "cmd_add_429"},
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。",
                metadata={"feature": "shopping", "action": "cmd_add_http_error", "status": status},
            )

    except Exception as e:
        print(f"[ERROR] cmd_add unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "shopping", "action": "cmd_add_unexpected_error"},
        )


async def cmd_list(ctx, sheet):
    try:
        data = sheet.get_all_values()

        if len(data) <= 1:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="何も入っておりません。",
                metadata={"feature": "shopping", "action": "cmd_list_empty"},
            )
            return

        embed = create_embed(sheet, MAX_VIEW_ITEMS)
        view = ShoppingView(sheet, create_embed, MAX_VIEW_ITEMS)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            embed=embed,
            view=view,
            metadata={"feature": "shopping", "action": "cmd_list"},
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_list HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                metadata={"feature": "shopping", "action": "cmd_list_429"},
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。",
                metadata={"feature": "shopping", "action": "cmd_list_http_error", "status": status},
            )

    except Exception as e:
        print(f"[ERROR] cmd_list unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "shopping", "action": "cmd_list_unexpected_error"},
        )


async def cmd_done(ctx, sheet, item):
    try:
        data = sheet.get_all_values()

        for i, row in enumerate(data):
            if i == 0:
                continue
            if len(row) < 4:
                continue

            if row[2] == item:
                sheet.update_cell(i + 1, 4, "済")
                await enqueue_message(
                    ctx.bot,
                    ctx.channel.id,
                    content=f"{item} を注文いたしましたわ。",
                    metadata={"feature": "shopping", "action": "cmd_done", "item": item},
                )
                return

        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="そちらは注文予定にはないようですわ。",
            metadata={"feature": "shopping", "action": "cmd_done_not_found", "item": item},
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_done HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                metadata={"feature": "shopping", "action": "cmd_done_429"},
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。",
                metadata={"feature": "shopping", "action": "cmd_done_http_error", "status": status},
            )

    except Exception as e:
        print(f"[ERROR] cmd_done unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "shopping", "action": "cmd_done_unexpected_error"},
        )


async def cmd_remove(ctx, sheet, item):
    try:
        data = sheet.get_all_values()

        for i, row in enumerate(data):
            if i == 0:
                continue
            if len(row) < 4:
                continue

            if row[2] == item:
                sheet.delete_rows(i + 1)
                await enqueue_message(
                    ctx.bot,
                    ctx.channel.id,
                    content=f"{item} は注文予定から外しておきますわね。",
                    metadata={"feature": "shopping", "action": "cmd_remove", "item": item},
                )
                return

        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="そちらは注文予定にはないようですわ。",
            metadata={"feature": "shopping", "action": "cmd_remove_not_found", "item": item},
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_remove HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。",
                metadata={"feature": "shopping", "action": "cmd_remove_429"},
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。",
                metadata={"feature": "shopping", "action": "cmd_remove_http_error", "status": status},
            )

    except Exception as e:
        print(f"[ERROR] cmd_remove unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。",
            metadata={"feature": "shopping", "action": "cmd_remove_unexpected_error"},
        )