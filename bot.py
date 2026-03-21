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
    # 0. Show ASCII Art
    print(r"""
    
    ░█████╗░███╗░░██╗██╗███╗░░░███╗███████╗  ███████╗███████╗████████╗░█████╗░██╗░░██╗███████╗██████╗░
    ██╔══██╗████╗░██║██║████╗░████║██╔════╝  ██╔════╝██╔════╝╚══██╔══╝██╔══██╗██║░░██║██╔════╝██╔══██╗
    ███████║██╔██╗██║██║██╔████╔██║█████╗░░  █████╗░░█████╗░░░░░██║░░░██║░░╚═╝███████║█████╗░░██████╔╝
    ██╔══██║██║╚████║██║██║╚██╔╝██║██╔══╝░░  ██╔══╝░░██╔══╝░░░░░██║░░░██║░░██╗██╔══██║██╔══╝░░██╔══██╗
    ██║░░██║██║░╚███║██║██║░╚═╝░██║███████╗  ██║░░░░░███████╗░░░██║░░░╚█████╔╝██║░░██║███████╗██║░░██║
    ╚═╝░░╚═╝╚═╝░░╚══╝╚═╝╚═╝░░░░░╚═╝╚══════╝  ╚═╝░░░░░╚══════╝░░░╚═╝░░░░╚════╝░╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝
    
    Version 2.0 | Automated Forwarder & Banner Maker
    -------------------------------------------------
    """)

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
        import re
        import base64
        import httpx
        from anilist_api import fetch_anilist, SEARCH_QUERY, DETAIL_QUERY, build_caption
        from banner_maker import generate_banner

        # Support SESSION_STRING env variable (for Render/cloud deployment)
        SESSION_NAME = 'anime_forwarder'
        session_string = os.getenv("SESSION_STRING", "")
        if session_string:
            session_path = f"{SESSION_NAME}.session"
            if not os.path.exists(session_path):
                logger.info("Restoring session from SESSION_STRING env variable...")
                with open(session_path, 'wb') as f:
                    f.write(base64.b64decode(session_string))
                logger.info("Session file restored successfully.")

        # Cache to prevent duplicate banners (Key: (anime_id, episode), Value: timestamp)
        # Using a simple dict for now
        last_posted_banners = {}

        client = TelegramClient('anime_forwarder', API_ID, API_HASH)
        
        @client.on(events.NewMessage(chats=SOURCE_CH_ID))
        async def forward_media(event):
            if not event.message.media:
                return

            try:
                # 1. Extract Info
                text = event.message.text or ""
                filename = event.message.file.name if event.message.file else ""
                
                logger.info(f"New media detected! Text: '{text[:30]}...', File: '{filename}'")
                
                # Simple extraction logic: prioritize text before '|' or first line
                # Then look for episode numbers
                title_query = ""
                ep_num = ""

                # Try to get episode from filename (e.g., S1 01 - Name)
                if filename:
                    ep_match = re.search(r"(?:S\d+\s+)?(\d+)", filename, re.I)
                    if ep_match:
                        ep_num = ep_match.group(1).lstrip('0') or '1'
                    
                    # Try to extract title between episode and quality
                    title_match = re.search(r"\d+\s*-\s*([^\[\.]+)", filename)
                    if title_match:
                        title_query = title_match.group(1).strip()

                if not title_query and text:
                    title_query = text.split('\n')[0].split('|')[0].strip()
                    if not ep_num:
                        ep_match = re.search(r"Episode[:\s]*(\d+)", text, re.I)
                        if ep_match:
                            ep_num = ep_match.group(1)

                # 2. Automated Banner Logic
                if title_query:
                    logger.info(f"Analyzing for banner: '{title_query}' Ep: '{ep_num}'")
                    
                    # Search AniList
                    search_data = await fetch_anilist(SEARCH_QUERY, {"search": title_query})
                    results = search_data.get("data", {}).get("Page", {}).get("media", [])
                    
                    if results:
                        media = results[0]
                        anime_id = str(media["id"])
                        ep_key = ep_num or "1"
                        cache_key = (anime_id, ep_key)

                        # Check if we posted this recently (within 5 minutes)
                        import time
                        now = time.time()
                        if cache_key not in last_posted_banners or (now - last_posted_banners[cache_key] > 300):
                            logger.info(f"Generating automated banner for {title_query} Ep {ep_key}")
                            
                            # Get full details
                            full_data = await fetch_anilist(DETAIL_QUERY, {"id": int(anime_id)})
                            full_media = full_data["data"]["Media"]
                            
                            caption = build_caption(full_media, ep_key)
                            cover_url = (full_media.get("coverImage") or {}).get("extraLarge") or (full_media.get("coverImage") or {}).get("large")
                            
                            if cover_url:
                                async with httpx.AsyncClient(timeout=20) as c:
                                    img_resp = await c.get(cover_url)
                                    cover_bytes = img_resp.content
                                banner_bytes = generate_banner(full_media, cover_bytes)
                                
                                # Use Telethon to send the banner (file)
                                await client.send_file(
                                    BOT_CHANNEL, 
                                    banner_bytes, 
                                    caption=caption, 
                                    parse_mode='markdown'
                                )
                                last_posted_banners[cache_key] = now
                
                # 3. Finally forward the file
                logger.info(f"Forwarding media to {BOT_CHANNEL}")
                await client.forward_messages(BOT_CHANNEL, event.message, drop_author=True)

            except Exception as e:
                logger.error(f"Forwarding/Banner error: {e}")
        
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("UserBot is NOT authorized! Set SESSION_STRING env variable on Render.")
            logger.error("Run the bot locally first to generate a session, then encode it.")
            client = None  # Disable userbot, still allow PTB bot to run
        else:
            logger.info("UserBot authorized and listening to source channel.")


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