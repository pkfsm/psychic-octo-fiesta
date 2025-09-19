
import asyncio
import logging
import subprocess
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, render_template_string
import threading
import sys

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Replace with your actual bot token
STREAM_INPUT = "https://crichd1.diwij76343.workers.dev/?v=sonyespnind"
RTMP_OUTPUT = os.environ.get("RTMP")

# Global variables
ffmpeg_process = None
stream_status = "STOPPED"

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask web app
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
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                margin-top: 100px;
                background-color: #f0f0f0;
            }
            .status {
                font-size: 48px;
                font-weight: bold;
                color: #2ecc71;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }
            .info {
                font-size: 18px;
                margin-top: 30px;
                color: #666;
            }
            .stream-info {
                background: white;
                padding: 20px;
                border-radius: 10px;
                margin: 20px auto;
                max-width: 600px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
        </style>
    </head>
    <body>
        <div class="status">APP LIVE</div>
        <div class="stream-info">
            <h3>Stream Status: {{ status }}</h3>
            <p><strong>Input Source:</strong> {{ input_url }}</p>
            <p><strong>Output Destination:</strong> RTMP Stream</p>
            <p><strong>Last Updated:</strong> <span id="time"></span></p>
        </div>
        <div class="info">
            Use /stream and /stop commands in Telegram to control the stream
        </div>

        <script>
            document.getElementById('time').textContent = new Date().toLocaleString();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, 
                                status=stream_status, 
                                input_url=STREAM_INPUT)

def start_ffmpeg_stream():
    """Start the FFmpeg streaming process"""
    global ffmpeg_process, stream_status

    if ffmpeg_process is not None and ffmpeg_process.poll() is None:
        logger.info("Stream is already running")
        return False

    try:
        ffmpeg_process = subprocess.Popen([
            "ffmpeg", "-re", "-i", STREAM_INPUT,
            "-c:v", "libx264", "-preset", "veryfast", 
            "-b:v", "2000k", "-maxrate", "2500k", "-bufsize", "3000k",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-f", "flv", RTMP_OUTPUT
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        stream_status = "STREAMING"
        logger.info("FFmpeg stream started successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to start FFmpeg stream: {e}")
        stream_status = "ERROR"
        return False

def stop_ffmpeg_stream():
    """Stop the FFmpeg streaming process"""
    global ffmpeg_process, stream_status

    if ffmpeg_process is None or ffmpeg_process.poll() is not None:
        logger.info("No active stream to stop")
        return False

    try:
        ffmpeg_process.terminate()
        ffmpeg_process.wait(timeout=5)
        ffmpeg_process = None
        stream_status = "STOPPED"
        logger.info("FFmpeg stream stopped successfully")
        return True

    except subprocess.TimeoutExpired:
        ffmpeg_process.kill()
        ffmpeg_process = None
        stream_status = "STOPPED"
        logger.info("FFmpeg stream force killed")
        return True
    except Exception as e:
        logger.error(f"Failed to stop FFmpeg stream: {e}")
        return False

async def stream_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /stream command"""
    chat_id = update.effective_chat.id

    if start_ffmpeg_stream():
        await context.bot.send_message(chat_id=chat_id, text="STREAM STARTED")
        logger.info(f"Stream started by user {update.effective_user.username}")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Failed to start stream or stream already running")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /stop command"""
    chat_id = update.effective_chat.id

    if stop_ffmpeg_stream():
        await context.bot.send_message(chat_id=chat_id, text="STOP STREAM")
        logger.info(f"Stream stopped by user {update.effective_user.username}")
    else:
        await context.bot.send_message(chat_id=chat_id, text="No active stream to stop")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    welcome_message = """
🎬 **Stream Control Bot**

Available commands:
/stream - Start FFmpeg streaming
/stop - Stop FFmpeg streaming
/status - Check current stream status

The web interface is running at the same address showing "APP LIVE"
    """
    await update.message.reply_text(welcome_message)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /status command"""
    global stream_status, ffmpeg_process

    # Check if process is still running
    if ffmpeg_process is not None and ffmpeg_process.poll() is not None:
        stream_status = "STOPPED"
        ffmpeg_process = None

    status_message = f"""
📊 **Current Status**
Stream: {stream_status}
Input: {STREAM_INPUT[:50]}...
Output: RTMP Stream
Web App: LIVE
    """
    await update.message.reply_text(status_message)

def run_flask():
    """Run Flask web server in a separate thread"""
    app.run(host='0.0.0.0', port=8080, debug=False)

async def main():
    """Main function to run the bot"""
    # Start Flask web server in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stream", stream_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))

    # Start the bot
    logger.info("Starting Telegram bot...")
    logger.info("Web interface available at http://localhost:8080")

    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        # Clean up any running streams
        if ffmpeg_process is not None:
            stop_ffmpeg_stream()
