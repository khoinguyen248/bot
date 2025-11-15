import discord
from discord.ext import commands, tasks
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
from dotenv import load_dotenv
import traceback

load_dotenv()

# ------------ CONFIG -------------- #
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_RAW = os.getenv("BIRTHDAY_CHANNEL_ID")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

print("DISCORD_TOKEN is set:", bool(DISCORD_TOKEN))
print("BIRTHDAY_CHANNEL_ID raw:", CHANNEL_ID_RAW)
print("GOOGLE_SHEET_ID:", SHEET_ID)

if CHANNEL_ID_RAW is None:
    raise RuntimeError("BIRTHDAY_CHANNEL_ID is not set in .env")
try:
    CHANNEL_ID = int(CHANNEL_ID_RAW)
except ValueError:
    raise RuntimeError("BIRTHDAY_CHANNEL_ID in .env must be a number (Discord channel ID)")

# ------------ GOOGLE SHEETS -------------- #
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    print("✅ Google Sheets: authorized successfully")
except Exception as e:
    print("❌ Error authorizing Google Sheets:", e)
    traceback.print_exc()
    client = None  # để tránh crash ngay lúc import


def get_birthdays():
    """Đọc toàn bộ dữ liệu từ sheet, có log lỗi chi tiết."""
    if client is None:
        print("⚠ get_birthdays: client is None (Google auth failed)")
        return []

    try:
        sheet = client.open_by_key(SHEET_ID).sheet1
        data = sheet.get_all_records()
        print(f"✅ Loaded {len(data)} rows from Google Sheet")
        return data
    except Exception as e:
        print("❌ Error reading Google Sheet:", e)
        traceback.print_exc()
        return []


# ------------ DISCORD BOT -------------- #
intents = discord.Intents.default()
intents.message_content = True  # rất quan trọng để đọc command

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user} (ID: {bot.user.id})")
    # Kiểm tra channel ngay khi bot online
    channel = bot.get_channel(CHANNEL_ID)
    print("get_channel(CHANNEL_ID) on_ready ->", channel)

    if channel is None:
        print("⚠ WARNING: Bot không tìm thấy channel với ID này.")
        print("  - Kiểm tra lại BIRTHDAY_CHANNEL_ID trong .env")
        print("  - Bot có đang ở đúng server có channel đó không?")
        print("  - Bot có quyền xem kênh đó không?")
    else:
        try:
            await channel.send("✅ Bot đã online và sẵn sàng chúc sinh nhật!")
        except Exception as e:
            print("❌ Không gửi được tin nhắn test vào channel:", e)
            traceback.print_exc()

    # Bắt đầu task check sinh nhật
    birthday_check.start()


@tasks.loop(hours=24)
async def birthday_check():
    """Task chạy mỗi 24h để kiểm tra sinh nhật."""
    print("---- Running birthday_check task ----")
    today = datetime.now().strftime("%m-%d")
    print("Today =", today)

    try:
        data = get_birthdays()
        channel = bot.get_channel(CHANNEL_ID)
        print("Channel resolved in birthday_check ->", channel)

        if channel is None:
            print("❌ ERROR: channel is None trong birthday_check. Không thể gửi tin nhắn.")
            return

        if not data:
            await channel.send("⚠ Không đọc được dữ liệu sinh nhật từ Google Sheet.")
            return

        found = False

        for idx, row in enumerate(data, start=2):  # start=2 vì row 1 là header
            print(f"Row {idx}:", row)

            # Check key tồn tại
            if "birthday" not in row or "discord_id" not in row or "name" not in row:
                print(f"⚠ Row {idx} thiếu key cần thiết (name/birthday/discord_id)")
                continue

            birthday_str = str(row["birthday"]).strip()
            discord_id = str(row["discord_id"]).strip()
            name = str(row["name"]).strip()

            if not birthday_str:
                print(f"⚠ Row {idx}: birthday rỗng")
                continue

            try:
                bday = datetime.strptime(birthday_str, "%Y-%m-%d").strftime("%m-%d")
            except Exception as e:
                print(f"❌ Row {idx}: lỗi parse birthday '{birthday_str}':", e)
                continue

            if bday == today:
                found = True
                if discord_id.isdigit():
                    mention = f"<@{discord_id}>"
                else:
                    mention = name  # fallback nếu ID sai

                msg = (
                    f"🎉 **Sinh nhật vui vẻ {mention}!** 🎂🥳\n"
                    "Chúc bạn tuổi mới thật nhiều sức khỏe, niềm vui và thành công!"
                )
                print(f"Sending birthday message for row {idx}:", msg)
                await channel.send(msg)

        if not found:
            print("Không có sinh nhật nào hôm nay (theo dữ liệu trong sheet).")

    except Exception as e:
        print("❌ Exception trong birthday_check:")
        traceback.print_exc()


@birthday_check.before_loop
async def before_birthday_check():
    print("⏳ Chờ bot sẵn sàng trước khi chạy birthday_check...")
    await bot.wait_until_ready()
    print("✅ Bot đã sẵn sàng, chuẩn bị chạy birthday_check.")


@bot.command()
async def checktoday(ctx):
    """Command: !checktoday để xem hôm nay có ai sinh nhật không."""
    print("Command !checktoday by", ctx.author)
    today = datetime.now().strftime("%m-%d")
    data = get_birthdays()

    bdays = []

    for idx, row in enumerate(data, start=2):
        if "birthday" not in row or "name" not in row:
            continue

        birthday_str = str(row["birthday"]).strip()
        name = str(row["name"]).strip()

        try:
            bday = datetime.strptime(birthday_str, "%Y-%m-%d").strftime("%m-%d")
        except Exception:
            continue

        if bday == today:
            bdays.append(name)

    if bdays:
        await ctx.send("🎂 Hôm nay sinh nhật của: " + ", ".join(bdays))
    else:
        await ctx.send("Hôm nay không có ai sinh nhật (theo dữ liệu trong sheet).")


@bot.command()
async def checkchannel(ctx):
    """Command debug: !checkchannel để xem CHANNEL_ID map ra kênh nào."""
    ch = bot.get_channel(CHANNEL_ID)
    await ctx.send(f"CHANNEL_ID={CHANNEL_ID} -> {ch}")


bot.run(DISCORD_TOKEN)
