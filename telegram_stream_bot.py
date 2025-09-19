
import asyncio
import logging
import subprocess
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, render_template_string
import threading
import sys
import signal
from concurrent.futures import ThreadPoolExecutor

# Configuration from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
STREAM_INPUT = os.getenv("STREAM_INPUT", "https://d1zq5no55rw5ua.cloudfront.net/136742_hindi_hls_03dea3461951169ta-di_h264/720p.m3u8")
RTMP_OUTPUT = os.getenv("RTMP", "rtmps://dc5-1.rtmp.t.me/s/gg")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# Global variables
ffmpeg_process = None
stream_status = "STOPPED"
bot_application = None
shutdown_event = threading.Event()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Create Flask app with threading enabled
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
            .docker-info {
                background: #e8f4fd;
                padding: 15px;
                border-radius: 8px;
                margin: 15px auto;
                max-width: 500px;
                color: #0066cc;
            }
        </style>
    </head>
    <body>
        <div class="status">APP LIVE</div>
        <div class="docker-info">
            🐳 Running in Docker Container
        </div>
        <div class="stream-info">
            <h3>Stream Status: {{ status }}</h3>
            <p><strong>Input Source:</strong> {{ input_url }}</p>
            <p><strong>Output Destination:</strong> RTMP Stream</p>
            <p><strong>Container Port:</strong> {{ port }}</p>
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
                                input_url=STREAM_INPUT,
                                port=WEB_PORT)

@app.route('/health')
def health():
    """Health check endpoint for Docker"""
    return {"status": "healthy", "stream": stream_status, "bot": "running"}, 200

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
🎬 **Stream Control Bot** (Docker Version)

Available commands:
/stream - Start FFmpeg streaming
/stop - Stop FFmpeg streaming  
/status - Check current stream status
/docker - Show Docker information

🐳 Running in containerized environment
🌐 Web interface: Check the exposed port
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
Web App: LIVE (Port {WEB_PORT})
🐳 Environment: Docker Container
    """
    await update.message.reply_text(status_message)

async def docker_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /docker command"""
    docker_info = f"""
🐳 **Docker Information**
Container: telegram_stream_bot
Web Port: {WEB_PORT}
FFmpeg: Available
Environment: Production

📝 **Configuration**
Bot Token: {"✅ Set" if BOT_TOKEN != "YOUR_BOT_TOKEN_HERE" else "❌ Not configured"}
Stream Input: {"✅ Configured" if STREAM_INPUT else "❌ Missing"}
RTMP Output: {"✅ Configured" if RTMP_OUTPUT else "❌ Missing"}
    """
    await update.message.reply_text(docker_info)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_event.set()
    stop_ffmpeg_stream()
    sys.exit(0)

def run_flask():
    """Run Flask web server in a separate thread"""
    try:
        # Use threaded=True to avoid conflicts with asyncio
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask server error: {e}")

def run_telegram_bot():
    """Run the Telegram bot in its own event loop"""
    async def bot_main():
        global bot_application

        # Validate configuration
        if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            logger.error("Bot token not configured. Please set BOT_TOKEN environment variable.")
            return

        try:
            # Create the Application
            bot_application = Application.builder().token(BOT_TOKEN).build()

            # Add command handlers
            bot_application.add_handler(CommandHandler("start", start_command))
            bot_application.add_handler(CommandHandler("stream", stream_command))
            bot_application.add_handler(CommandHandler("stop", stop_command))
            bot_application.add_handler(CommandHandler("status", status_command))
            bot_application.add_handler(CommandHandler("docker", docker_command))

            logger.info("Starting Telegram bot in Docker container...")
            logger.info(f"Web interface available at http://localhost:{WEB_PORT}")
            logger.info(f"Stream input: {STREAM_INPUT}")

            # Initialize the bot
            await bot_application.initialize()
            await bot_application.start()

            # Start polling
            await bot_application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )

            # Keep running until shutdown
            while not shutdown_event.is_set():
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            # Cleanup
            if bot_application:
                try:
                    await bot_application.updater.stop()
                    await bot_application.stop()
                    await bot_application.shutdown()
                except Exception as e:
                    logger.error(f"Shutdown error: {e}")

    # Create new event loop for the bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(bot_main())
    except Exception as e:
        logger.error(f"Event loop error: {e}")
    finally:
        try:
            # Cancel all remaining tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

            loop.close()
        except Exception as e:
            logger.error(f"Loop cleanup error: {e}")

def main():
    """Main function to orchestrate Flask and Telegram bot"""
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("🚀 Starting Telegram Stream Bot...")

    # Start Flask web server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="FlaskThread")
    flask_thread.start()
    logger.info(f"🌐 Flask web server started on port {WEB_PORT}")

    # Small delay to ensure Flask starts
    import time
    time.sleep(2)

    # Start Telegram bot in a separate thread with its own event loop
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=False, name="TelegramThread")
    bot_thread.start()
    logger.info("🤖 Telegram bot thread started")

    try:
        # Keep main thread alive
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        shutdown_event.set()

    # Wait for bot thread to finish
    bot_thread.join(timeout=10)
    logger.info("Bot shut down complete")

if __name__ == '__main__':
    main()
