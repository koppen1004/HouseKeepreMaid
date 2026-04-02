import discord
from discord.ui import View, Button
from discord import ButtonStyle
from datetime import datetime

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
                current = self.sheet.cell(row, 4).value
                new_status = "未購入" if current == "済" else "済"
                self.sheet.update_cell(row, 4, new_status)

                embed = self.create_embed_func(self.sheet)
                view = ShoppingView(self.sheet, self.create_embed_func)

                await interaction.response.edit_message(embed=embed, view=view)

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


async def handle_shopping_message(message, content, sheet):
    user_id = message.author.id

    # 全削除（確認）
    if content in ["リスト削除", "全部削除", "リスト全削除"]:
        confirm_clear[user_id] = True
        await message.channel.send("⚠️ 本当に削除いたしますの？「はい」で実行いたしますわ。")
        return True

    if content == "はい" and confirm_clear.get(user_id):
        sheet.resize(1)
        confirm_clear[user_id] = False
        await message.channel.send("🧹 注文予定は白紙にいたしましたわ。")
        return True

    # 追加
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
            await message.channel.send(f"{item} を追加いたしましたわ。")
        else:
            await message.channel.send("追加する品をお書きくださいませ。")

        return

    # 表示
    if content in ["リスト", "リスト表示", "買い物リスト", "表示"]:
        data = sheet.get_all_values()
        if len(data) <= 1:
            await message.channel.send("注文予定は何もないようですわね。")
            return True

        embed = create_embed(sheet)
        view = ShoppingView(sheet, create_embed)
        await message.channel.send(embed=embed, view=view)
        return True

    # 削除
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
                await message.channel.send(f"{item} は注文予定から外しておきますわね。")
                return True

        await message.channel.send("そちらは注文予定にはないようですわ。")
        return True

    # 購入済み
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
                await message.channel.send(f"{item} を注文いたしましたわ。")
                return True

        await message.channel.send("そちらは注文予定にはないようですわ。")
        return True

    if content.endswith("購入"):
        item = content[:-2].strip()  # "購入" を削る
        data = sheet.get_all_values()

        for i, row in enumerate(data):
            if i == 0:
                continue
            if len(row) < 4:
                continue
            if row[2] == item:
                sheet.update_cell(i + 1, 4, "済")
                await message.channel.send(f"{item} を注文いたしましたわ。")
                return True

        await message.channel.send("そちらは注文予定にはないようですわ。")
        return True

    return False


async def cmd_add(ctx, sheet, item):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    user = str(ctx.author)

    sheet.append_row([now, user, item, "未購入"])
    await ctx.send(f"商品を追加いたしましたわ：{item}")


async def cmd_list(ctx, sheet):
    data = sheet.get_all_values()

    if len(data) <= 1:
        await ctx.send("何も入っておりません。")
        return

    embed = create_embed(sheet)
    view = ShoppingView(sheet, create_embed)
    await ctx.send(embed=embed, view=view)


async def cmd_done(ctx, sheet, item):
    data = sheet.get_all_values()

    for i, row in enumerate(data):
        if i == 0:
            continue
        if len(row) < 4:
            continue

        if row[2] == item:
            sheet.update_cell(i + 1, 4, "済")
            await ctx.send(f"{item} を注文いたしましたわ。")
            return

    await ctx.send("そちらは注文予定にはないようですわ。")


async def cmd_remove(ctx, sheet, item):
    data = sheet.get_all_values()

    for i, row in enumerate(data):
        if i == 0:
            continue
        if len(row) < 4:
            continue

        if row[2] == item:
            sheet.delete_rows(i + 1)
            await ctx.send(f"{item} は注文予定から外しておきますわね。")
            return

    await ctx.send("そちらは注文予定にはないようですわ。")