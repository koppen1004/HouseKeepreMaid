from datetime import datetime

import discord
from discord import ButtonStyle
from discord.ui import Button, View

from send_queue import enqueue_message

confirm_clear = {}


class ShoppingView(View):
    def __init__(self, sheet, create_embed_func):
        super().__init__(timeout=None)
        self.sheet = sheet
        self.create_embed_func = create_embed_func
        self.build()

    def build(self):
        self.clear_items()
        data = self.sheet.get_all_values()

        for i, row in enumerate(data[1:], start=2):
            if len(row) < 4:
                continue

            item = row[2]
            status = row[3]

            button = Button(
                label=item,
                style=ButtonStyle.success if status == "済" else ButtonStyle.secondary
            )

            async def callback(interaction, row=i, item=item):
                try:
                    current = self.sheet.cell(row, 4).value
                    new_status = "未購入" if current == "済" else "済"
                    self.sheet.update_cell(row, 4, new_status)

                    embed = self.create_embed_func(self.sheet)
                    view = ShoppingView(self.sheet, self.create_embed_func)

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


def create_embed(sheet):
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

    embed.add_field(
        name=f"🛍 未購入（{len(not_done)}）",
        value="\n".join(not_done) if not_done else "なし",
        inline=False
    )

    embed.add_field(
        name=f"✅ 購入済み（{len(done)}）",
        value="\n".join(done) if done else "なし",
        inline=False
    )

    return embed


async def handle_shopping_message(bot, message, content, sheet):
    try:
        user_id = message.author.id

        if content in ["リスト削除", "全部削除", "リスト全削除"]:
            confirm_clear[user_id] = True
            await enqueue_message(
                bot,
                message.channel.id,
                content="⚠️ 本当に削除いたしますの？「はい」で実行いたしますわ。"
            )
            return True

        if content == "はい" and confirm_clear.get(user_id):
            sheet.resize(1)
            confirm_clear[user_id] = False
            await enqueue_message(
                bot,
                message.channel.id,
                content="🧹 注文予定は白紙にいたしましたわ。"
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
                    content=f"{item} を追加いたしましたわ。"
                )
            else:
                await enqueue_message(
                    bot,
                    message.channel.id,
                    content="追加する品をお書きくださいませ。"
                )

            return True

        if content in ["リスト", "リスト表示", "買い物リスト", "表示"]:
            data = sheet.get_all_values()

            if len(data) <= 1:
                await enqueue_message(
                    bot,
                    message.channel.id,
                    content="注文予定は何もないようですわね。"
                )
                return True

            embed = create_embed(sheet)
            view = ShoppingView(sheet, create_embed)
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
                        content=f"{item} は注文予定から外しておきますわね。"
                    )
                    return True

            await enqueue_message(
                bot,
                message.channel.id,
                content="そちらは注文予定にはないようですわ。"
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
                        content=f"{item} を注文いたしましたわ。"
                    )
                    return True

            await enqueue_message(
                bot,
                message.channel.id,
                content="そちらは注文予定にはないようですわ。"
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
                        content=f"{item} を注文いたしましたわ。"
                    )
                    return True

            await enqueue_message(
                bot,
                message.channel.id,
                content="そちらは注文予定にはないようですわ。"
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
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。"
            )
        else:
            await enqueue_message(
                bot,
                message.channel.id,
                content="問題が発生しているようですわ。"
            )
        return True

    except Exception as e:
        print(f"[ERROR] handle_shopping_message unexpected: {e}", flush=True)
        try:
            await enqueue_message(
                bot,
                message.channel.id,
                content="問題が発生しているようですわ。"
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
            content=f"商品を追加いたしましたわ：{item}"
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_add HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。"
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。"
            )

    except Exception as e:
        print(f"[ERROR] cmd_add unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。"
        )


async def cmd_list(ctx, sheet):
    try:
        data = sheet.get_all_values()

        if len(data) <= 1:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="何も入っておりません。"
            )
            return

        embed = create_embed(sheet)
        view = ShoppingView(sheet, create_embed)
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
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。"
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。"
            )

    except Exception as e:
        print(f"[ERROR] cmd_list unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。"
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
                    content=f"{item} を注文いたしましたわ。"
                )
                return

        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="そちらは注文予定にはないようですわ。"
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_done HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。"
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。"
            )

    except Exception as e:
        print(f"[ERROR] cmd_done unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。"
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
                    content=f"{item} は注文予定から外しておきますわね。"
                )
                return

        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="そちらは注文予定にはないようですわ。"
        )

    except discord.HTTPException as e:
        status = getattr(e, "status", None)
        print(f"[ERROR] cmd_remove HTTPException: status={status} error={e}", flush=True)

        if status == 429:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="ただいま手が塞がっておりまして…少々時間を開けてからもう一度お願いいたしますわ。"
            )
        else:
            await enqueue_message(
                ctx.bot,
                ctx.channel.id,
                content="問題が発生しているようですわ。"
            )

    except Exception as e:
        print(f"[ERROR] cmd_remove unexpected: {e}", flush=True)
        await enqueue_message(
            ctx.bot,
            ctx.channel.id,
            content="問題が発生しているようですわ。"
        )