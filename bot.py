import re
import os
import requests
import yt_dlp
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ChatMember
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEB_PLAYER_URL = os.environ.get("WEB_PLAYER_URL", "https://your-player.vercel.app")
FORCE_CHANNEL = os.environ.get("FORCE_CHANNEL", "SteveXearning")

# ─────────────────────────────────────────────
# FORCE JOIN
# ─────────────────────────────────────────────

async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(f"@{FORCE_CHANNEL}", user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False


async def force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL}")],
        [InlineKeyboardButton("✅ I Joined", callback_data="check_join")],
    ]
    await update.message.reply_text(
        "⚠️ *Access Restricted!*\n\n"
        "You must join our channel to use this bot.\n\n"
        "1️⃣ Click *Join Channel* below\n"
        "2️⃣ Then click *I Joined* ✅",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_valid_url(text):
    return bool(re.match(r'https?://[^\s]+', text.strip()))


def is_terabox_url(url):
    return any(x in url for x in [
        '1024tera.com', 'terabox.com', 'teraboxapp.com', 'freeterabox.com'
    ])


def is_supported_url(url):
    return any(x in url for x in [
        'instagram.com', 'youtube.com', 'youtu.be',
        'tiktok.com', 'twitter.com', 'x.com', 'facebook.com'
    ])


def get_terabox_stream(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.1024tera.com/',
    }
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
    html = resp.text

    title_match = re.search(r'"server_filename"\s*:\s*"([^"]+)"', html)
    title = title_match.group(1) if title_match else 'Terabox Video'

    thumb_match = re.search(r'"thumbs"\s*:\s*\{[^}]*"url3"\s*:\s*"([^"]+)"', html)
    if not thumb_match:
        thumb_match = re.search(r'"thumbs"\s*:\s*\{[^}]*"url1"\s*:\s*"([^"]+)"', html)
    thumbnail = thumb_match.group(1).replace('\\u0026', '&') if thumb_match else ''

    match = re.search(r'"dlink"\s*:\s*"(https?://[^"]+)"', html)
    if match:
        return match.group(1).replace('\\u0026', '&'), title, thumbnail

    surl = url.split('surl=')[-1].split('&')[0]
    api = f"https://www.1024tera.com/api/shorturlinfo?shorturl={surl}"
    r2 = requests.get(api, headers=headers, timeout=15)
    data = r2.json()
    item = data.get('list', [{}])[0]
    dlink = item.get('dlink', '')
    if not thumbnail:
        thumbs = item.get('thumbs', {})
        thumbnail = thumbs.get('url3') or thumbs.get('url1', '')
    if dlink:
        return dlink, item.get('server_filename', title), thumbnail

    raise ValueError("Could not extract Terabox stream.")


def build_player_url(stream_url, title, thumb='', quality=''):
    u = (
        f"{WEB_PLAYER_URL}?"
        f"src={urllib.parse.quote(stream_url, safe='')}"
        f"&title={urllib.parse.quote(title, safe='')}"
        f"&thumb={urllib.parse.quote(thumb, safe='')}"
    )
    if quality:
        u += f"&quality={urllib.parse.quote(quality, safe='')}"
    return u

# ─────────────────────────────────────────────
# DOWNLOAD & SEND — with audio fix ✅
# ─────────────────────────────────────────────

async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    msg = await update.message.reply_text("⬇️ Downloading...")

    ydl_opts = {
        'quiet': True,
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        # ✅ This format properly merges video + audio using ffmpeg
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

    os.makedirs('downloads', exist_ok=True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if not filepath.endswith('.mp4'):
                filepath = filepath.rsplit('.', 1)[0] + '.mp4'

            title = info.get('title', 'Video')[:50]

            # Instagram image post
            if info.get('ext') in ['jpg', 'jpeg', 'png', 'webp']:
                await msg.delete()
                await update.message.reply_photo(
                    photo=open(filepath, 'rb'),
                    caption=f"📸 *{title}*\n\nvia @{context.bot.username}",
                    parse_mode="Markdown"
                )
            else:
                file_size = os.path.getsize(filepath)
                if file_size > 49 * 1024 * 1024:
                    os.remove(filepath)
                    await msg.edit_text(
                        "❌ Video is too large (over 50MB).\n"
                        "Try a shorter video."
                    )
                    return

                await msg.edit_text("📤 Uploading...")
                await update.message.reply_video(
                    video=open(filepath, 'rb'),
                    caption=f"🎬 *{title}*\n\nvia @{context.bot.username}",
                    parse_mode="Markdown",
                    supports_streaming=True,
                )
                await msg.delete()

        if os.path.exists(filepath):
            os.remove(filepath)

    except Exception as e:
        clean_error = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
        await msg.edit_text(
            f"❌ *Failed to download.*\n\n"
            f"Make sure the video is public.\n\n"
            f"`{clean_error[:150]}`",
            parse_mode="Markdown"
        )
        for f in os.listdir('downloads'):
            try:
                os.remove(os.path.join('downloads', f))
            except:
                pass

# ─────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update.effective_user.id, context):
        await force_join_message(update, context)
        return
    await update.message.reply_text(
        "🎬 *Welcome to Video Saver Bot!*\n\n"
        "Send me a link and I'll send you the media directly:\n\n"
        "✅ Instagram — videos & photos\n"
        "✅ YouTube\n"
        "✅ TikTok\n"
        "✅ Twitter / X\n"
        "✅ Facebook\n"
        "✅ Terabox — stream inside Telegram\n\n"
        "Just paste a link below 👇",
        parse_mode="Markdown"
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update.effective_user.id, context):
        await force_join_message(update, context)
        return

    url = update.message.text.strip()

    if not is_valid_url(url):
        await update.message.reply_text("❌ Please send a valid video URL.")
        return

    try:
        # ── TERABOX ──
        if is_terabox_url(url):
            msg = await update.message.reply_text("🔍 Fetching Terabox info...")
            stream_url, title, thumbnail = get_terabox_stream(url)
            player_url = build_player_url(stream_url, title, thumbnail)

            keyboard = [[
                InlineKeyboardButton("👉 CLICK HERE", web_app=WebAppInfo(url=player_url))
            ]]
            caption = (
                f"*How To Watch Video, Click here*\n\n"
                f"📦 | Here's your stream link :\n"
                f"👉 [CLICK HERE]({player_url}) |\n\n"
                f"🚫 | If you are not getting video below. Then "
                f"try opening the link manually using the link provided above.(real)"
            )
            await msg.delete()
            if thumbnail:
                await update.message.reply_photo(
                    photo=thumbnail,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        # ── INSTAGRAM / YOUTUBE / TIKTOK / TWITTER ──
        elif is_supported_url(url):
            await download_and_send(update, context, url)

        else:
            await update.message.reply_text(
                "❌ Unsupported link.\n\n"
                "Supported: Instagram, YouTube, TikTok, Twitter, Facebook, Terabox"
            )

    except Exception as e:
        clean_error = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
        await update.message.reply_text(
            f"❌ *Error:* `{clean_error[:150]}`",
            parse_mode="Markdown"
        )


async def handle_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await is_member(update.effective_user.id, context):
        await query.edit_message_text(
            "✅ *Welcome!* You're now verified.\n\n"
            "Send me any video link to get started 🎬",
            parse_mode="Markdown"
        )
    else:
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL}")],
            [InlineKeyboardButton("✅ I Joined", callback_data="check_join")],
        ]
        await query.edit_message_text(
            "❌ *You haven't joined yet!*\n\n"
            "Please join the channel first, then tap *I Joined*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(handle_check_join, pattern="^check_join$"))
    print("🤖 Bot is running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
if __name__ == "__main__":
    main()
