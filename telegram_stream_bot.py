import asyncio
import logging
import subprocess
import os
import re
from urllib.parse import urlparse
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, render_template_string
import threading
import sys
import signal

# =========================
# Configuration
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
STREAM_INPUT = os.getenv("STREAM_INPUT", "https://crichd1.diwij76343.workers.dev/?v=sonyespnind")
RTMP_OUTPUT = os.getenv("RTMP", "")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# =========================
# Globals
# =========================
ffmpeg_process = None
stream_status = "STOPPED"
current_input_url = STREAM_INPUT
shutdown_event = threading.Event()

# =========================
# Logging
# =========================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# =========================
# URL extraction helpers
# =========================
URL_REGEX = re.compile(r"(https?://[^\s)\]]+)")

def extract_stream_url(update: Update) -> str | None:
    """
    Extract a URL from the /stream command text or entities (raw URL or [text](url)).
    """
    msg = update.effective_message
    if not msg:
        return None

    # Prefer entities
    try:
        if msg.entities:
            for ent in msg.entities:
                etype = getattr(ent, 'type', None)
                if etype == 'text_link' and getattr(ent, 'url', None):
                    return ent.url
                if etype == 'url' and msg.text:
                    try:
                        return msg.text[ent.offset: ent.offset + ent.length]
                    except Exception:
                        pass
    except Exception:
        pass

    # Fallback: parse text after /stream
    text = (msg.text or '').strip()
    if text.startswith('/stream'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            cand = parts[1].strip()
            # Handle [label](url)
            if cand.startswith('[') and cand.endswith(')') and '](' in cand:
                try:
                    cand = cand.split('](', 1)[1].rstrip(')')
                except Exception:
                    pass
            cand = cand.strip('[]()')
            m = URL_REGEX.search(cand)
            if m:
                return m.group(1)

    return None

def is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ('http', 'https') and bool(p.netloc)
    except Exception:
        return False

# =========================
# Flask app
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stream Bot Status</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body { font-family: Arial, sans-serif; text-align: center; margin-top: 80px; background-color: #f7f7f7; }
            .status { font-size: 48px; font-weight: bold; color: #2ecc71; }
            .panel { background: white; padding: 20px; border-radius: 10px; margin: 20px auto; max-width: 740px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
            .k { color:#666 }
            code { background:#f0f0f0; padding:2px 6px; border-radius:4px }
        </style>
    </head>
    <body>
        <div class="status">APP LIVE</div>
        <div class="panel">
            <h3>Stream Status: {{ status }}</h3>
            <p><span class="k">Input Source:</span> <code>{{ input_url }}</code></p>
            <p><span class="k">Output:</span> RTMP</p>
            <p><span class="k">Port:</span> {{ port }}</p>
            <p><span class="k">Updated:</span> <span id="time"></span></p>
        </div>
        <script>document.getElementById('time').textContent = new Date().toLocaleString();</script>
    </body>
    </html>
    """
    return render_template_string(html_template, status=stream_status, input_url=current_input_url, port=WEB_PORT)

@app.route('/health')
def health():
    return {"status": "healthy", "stream": stream_status, "input": current_input_url}, 200

# =========================
# FFmpeg control
# =========================
def start_ffmpeg_stream(input_url: str | None = None):
    global ffmpeg_process, stream_status, current_input_url

    if ffmpeg_process is not None and ffmpeg_process.poll() is None:
        logger.info("Stream is already running")
        return False

    current_input_url = input_url or STREAM_INPUT

    try:
        ffmpeg_process = subprocess.Popen([
            "ffmpeg", "-re", "-i", current_input_url,
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", "2000k", "-maxrate", "2500k", "-bufsize", "3000k",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-f", "flv", RTMP_OUTPUT
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        stream_status = "STREAMING"
        logger.info("FFmpeg stream started: %s", current_input_url)
        return True
    except Exception as e:
        logger.error("Failed to start FFmpeg stream: %s", e)
        stream_status = "ERROR"
        return False

def stop_ffmpeg_stream():
    global ffmpeg_process, stream_status

    if ffmpeg_process is None or ffmpeg_process.poll() is not None:
        logger.info("No active stream to stop")
        return False

    try:
        ffmpeg_process.terminate()
        ffmpeg_process.wait(timeout=5)
        ffmpeg_process = None
        stream_status = "STOPPED"
        logger.info("FFmpeg stream stopped")
        return True
    except subprocess.TimeoutExpired:
        ffmpeg_process.kill()
        ffmpeg_process = None
        stream_status = "STOPPED"
        logger.info("FFmpeg stream force killed")
        return True
    except Exception as e:
        logger.error("Failed to stop FFmpeg stream: %s", e)
        return False

# =========================
# Telegram handlers
# =========================
async def stream_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stream [<url>] -> start stream using provided URL or default."""
    chat_id = update.effective_chat.id

    url = extract_stream_url(update)
    if url and not is_valid_url(url):
        await context.bot.send_message(chat_id=chat_id, text="Invalid URL. Please provide a valid http(s) link.")
        return

    if url:
        # Restart with new input
        if ffmpeg_process is not None and ffmpeg_process.poll() is None:
            stop_ffmpeg_stream()
        if start_ffmpeg_stream(url):
            await context.bot.send_message(chat_id=chat_id, text=f"STREAM STARTED\nSource: {url}")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Failed to start stream with the provided URL.")
        return

    # No URL provided -> use default
    if start_ffmpeg_stream():
        await context.bot.send_message(chat_id=chat_id, text="STREAM STARTED")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Failed to start stream or stream already running")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if stop_ffmpeg_stream():
        await context.bot.send_message(chat_id=chat_id, text="STOP STREAM")
    else:
        await context.bot.send_message(chat_id=chat_id, text="No active stream to stop")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Stream Control Bot\n\n"
        "/stream - Start default stream or /stream <url> to use a link\n"
        "/stop - Stop FFmpeg streaming\n"
        "/status - Show status\n"
    )
    await update.message.reply_text(msg)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stream_status, ffmpeg_process

    if ffmpeg_process is not None and ffmpeg_process.poll() is not None:
        stream_status = "STOPPED"

    msg = (
        f"Status: {stream_status}\n"
        f"Input: {current_input_url}\n"
        f"Web: LIVE (Port {WEB_PORT})\n"
    )
    await update.message.reply_text(msg)

# =========================
# Runners (Flask + Bot in separate threads/event loops)
# =========================
def signal_handler(signum, frame):
    logger.info("Signal %s received, shutting down...", signum)
    shutdown_event.set()
    stop_ffmpeg_stream()

def run_flask():
    try:
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True, use_reloader=False)
    except Exception as e:
        logger.error("Flask error: %s", e)

def run_bot():
    async def bot_main():
        if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            logger.error("BOT_TOKEN not set")
            return

        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("stream", stream_command))
        application.add_handler(CommandHandler("stop", stop_command))
        application.add_handler(CommandHandler("status", status_command))

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        try:
            while not shutdown_event.is_set():
                await asyncio.sleep(1)
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot_main())
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()

def main():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Starting web server and bot...")

    flask_thread = threading.Thread(target=run_flask, name="FlaskThread", daemon=True)
    flask_thread.start()

    bot_thread = threading.Thread(target=run_bot, name="BotThread", daemon=False)
    bot_thread.start()

    try:
        while not shutdown_event.is_set():
            # keep main thread alive
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_event.set()

    bot_thread.join(timeout=10)

if __name__ == '__main__':
    main()
