async def handle_reminder_message(message, content):
    if content in ["テスト", "確認", "リマインダー確認"]:
        await message.channel.send("こちらはリマインダー用チャンネルですわ。")
        return True

    return False