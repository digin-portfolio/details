import os
import asyncio
import http.server
import socketserver
import threading
from telegram.ext import Application
from telethon import TelegramClient, events
from config import logger, API_ID, API_HASH, SOURCE_CH_ID, BOT_CHANNEL
from bot_handlers import setup_handlers

class HealthCheckServer(socketserver.TCPServer):
    allow_reuse_address = True

class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
    def log_message(self, format, *args):
        pass  # Keep logs clean

def start_health_check():
    """A simple HTTP server to satisfy Render's port binding requirement."""
    port = int(os.getenv("PORT", "8080"))
    try:
        logger.info(f"Starting health check server on port {port}...")
        with HealthCheckServer(("0.0.0.0", port), HealthCheckHandler) as httpd:
            logger.info(f"Health check server successfully bound to port {port}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Health check server failed to start: {e}")

async def main() -> None:
    # 0. Start Health Check for Render (Free Tier)
    threading.Thread(target=start_health_check, daemon=True).start()

    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN is missing!")
        return

    # 1. Setup PTB Application
    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .build()
    )
    setup_handlers(app)

    # 2. Setup UserBot (Telethon)
    client = None
    if API_ID and API_HASH:
        client = TelegramClient('anime_forwarder', API_ID, API_HASH)
        
        @client.on(events.NewMessage(chats=SOURCE_CH_ID))
        async def forward_media(event):
            if event.message.media:
                try:
                    logger.info(f"Forwarding media from source channel ({SOURCE_CH_ID}) to {BOT_CHANNEL}")
                    await client.forward_messages(BOT_CHANNEL, event.message, drop_author=True)
                except Exception as e:
                    logger.error(f"Forwarding error: {e}")
        
        await client.start()
        logger.info("UserBot started and listening to source channel.")

    # 3. Start PTB polling
    await app.initialize()
    await app.start()
    if app.updater:
        await app.updater.start_polling()
    logger.info("Bot running — Auto-Forwarder + Banner Manager")

    # 4. Keep alive
    try:
        if client:
            await client.run_until_disconnected()
        else:
            while True:
                await asyncio.sleep(3600)
    finally:
        if app.updater:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass