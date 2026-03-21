import os
import time
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
        pass

def start_health_check():
    port = int(os.getenv("PORT", "8080"))
    try:
        logger.info(f"Starting health check server on port {port}...")
        with HealthCheckServer(("0.0.0.0", port), HealthCheckHandler) as httpd:
            logger.info(f"Health check server successfully bound to port {port}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Health check server failed to start: {e}")

async def main() -> None:
    print(r"""
    
    ░█████╗░███╗░░██╗██╗███╗░░░███╗███████╗  ███████╗███████╗████████╗░█████╗░██╗░░██╗███████╗██████╗░
    ██╔══██╗████╗░██║██║████╗░████║██╔════╝  ██╔════╝██╔════╝╚══██╔══╝██╔══██╗██║░░██║██╔════╝██╔══██╗
    ███████║██╔██╗██║██║██╔████╔██║█████╗░░  █████╗░░█████╗░░░░░██║░░░██║░░╚═╝███████║█████╗░░██████╔╝
    ██╔══██║██║╚████║██║██║╚██╔╝██║██╔══╝░░  ██╔══╝░░██╔══╝░░░░░██║░░░██║░░██╗██╔══██║██╔══╝░░██╔══██╗
    ██║░░██║██║░╚███║██║██║░╚═╝░██║███████╗  ██║░░░░░███████╗░░░██║░░░╚█████╔╝██║░░██║███████╗██║░░██║
    ╚═╝░░╚═╝╚═╝░░╚══╝╚═╝╚═╝░░░░░╚═╝╚══════╝  ╚═╝░░░░░╚══════╝░░░╚═╝░░░░╚════╝░╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝
    
    Version 2.0 | Automated Forwarder & Banner Maker
    -------------------------------------------------
    """)

    threading.Thread(target=start_health_check, daemon=True).start()

    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN is missing!")
        return

    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .build()
    )
    setup_handlers(app)

    client = None
    if API_ID and API_HASH:
        import re
        import base64
        import httpx
        from anilist_api import fetch_anilist, SEARCH_QUERY, DETAIL_QUERY, build_caption
        from banner_maker import generate_banner

        SESSION_NAME = 'anime_forwarder'
        session_string = os.getenv("SESSION_STRING", "")
        if session_string:
            session_path = f"{SESSION_NAME}.session"
            if not os.path.exists(session_path):
                logger.info("Restoring session from SESSION_STRING env variable...")
                with open(session_path, 'wb') as f:
                    f.write(base64.b64decode(session_string))
                logger.info("Session file restored successfully.")

        last_posted_banners: dict = {}
        banner_in_progress: set = set()

        # ── Album / media-group state ─────────────────────────────────────────
        # grouped_id → {"messages": [...], "task": asyncio.Task | None}
        pending_albums: dict = {}
        ALBUM_WAIT = 1.5  # seconds to wait before flushing an album

        client = TelegramClient('anime_forwarder', API_ID, API_HASH)

        def _extract_title_ep(text: str, filename: str):
            title_query, ep_num = "", ""
            if filename:
                ep_match = re.search(r"(?:S\d+\s+)?(\d+)", filename, re.I)
                if ep_match:
                    ep_num = ep_match.group(1).lstrip('0') or '1'
                title_match = re.search(r"\d+\s*-\s*([^\[\.]+)", filename)
                if title_match:
                    title_query = title_match.group(1).strip()
            if not title_query and text:
                title_query = text.split('\n')[0].split('|')[0].strip()
                if not ep_num:
                    ep_match = re.search(r"Episode[:\s]*(\d+)", text, re.I)
                    if ep_match:
                        ep_num = ep_match.group(1)
            return title_query, ep_num

        async def _send_banner(title_query: str, ep_num: str):
            """Fetch AniList info and post a banner photo. One banner per (anime, episode)."""
            if not title_query:
                return

            logger.info(f"Analyzing for banner: '{title_query}' Ep: '{ep_num}'")
            search_data = await fetch_anilist(SEARCH_QUERY, {"search": title_query})
            results = search_data.get("data", {}).get("Page", {}).get("media", [])
            if not results:
                return

            media     = results[0]
            anime_id  = str(media["id"])
            ep_key    = ep_num or "1"
            cache_key = (anime_id, ep_key)

            now = time.time()
            already_sent = (
                cache_key in last_posted_banners
                and (now - last_posted_banners[cache_key]) < 300
            )
            if already_sent or cache_key in banner_in_progress:
                reason = "in-progress" if cache_key in banner_in_progress else "already sent"
                logger.info(f"Skipping banner ({reason}): {title_query} Ep {ep_key}")
                return

            banner_in_progress.add(cache_key)
            try:
                full_data  = await fetch_anilist(DETAIL_QUERY, {"id": int(anime_id)})
                full_media = full_data["data"]["Media"]
                caption    = build_caption(full_media, ep_key)
                cover_url  = (
                    (full_media.get("coverImage") or {}).get("extraLarge")
                    or (full_media.get("coverImage") or {}).get("large")
                )
                if cover_url:
                    async with httpx.AsyncClient(timeout=20) as c:
                        cover_bytes = (await c.get(cover_url)).content
                    banner_bytes = generate_banner(full_media, cover_bytes)
                    await client.send_file(
                        BOT_CHANNEL,
                        banner_bytes,
                        caption=caption,
                        parse_mode='markdown',
                        force_document=False,  # send as photo, not document
                        attributes=[],
                    )
                    last_posted_banners[cache_key] = time.time()
                    logger.info(f"Banner sent for '{title_query}' Ep {ep_key}")
            finally:
                banner_in_progress.discard(cache_key)

        async def _flush_album(grouped_id: int):
            """Wait for ALBUM_WAIT seconds, then forward all collected album messages."""
            await asyncio.sleep(ALBUM_WAIT)
            album = pending_albums.pop(grouped_id, None)
            if not album:
                return
            messages = sorted(album["messages"], key=lambda m: m.id)
            logger.info(f"Flushing album {grouped_id}: {len(messages)} file(s)")
            try:
                await client.forward_messages(BOT_CHANNEL, messages, drop_author=True)
                logger.info(f"Album {grouped_id} forwarded ({len(messages)} files).")
            except Exception as e:
                logger.error(f"Album forward error: {e}")

        @client.on(events.NewMessage(chats=SOURCE_CH_ID))
        async def forward_media(event):
            if not event.message.media:
                return

            try:
                text       = event.message.text or ""
                filename   = event.message.file.name if event.message.file else ""
                grouped_id = event.message.grouped_id  # None for standalone files

                logger.info(
                    f"New media | grouped_id={grouped_id} "
                    f"file='{filename}' text='{text[:30]}...'"
                )

                title_query, ep_num = _extract_title_ep(text, filename)

                # ── ALBUM (multiple files sent together) ──────────────────────
                if grouped_id is not None:
                    if grouped_id not in pending_albums:
                        # First message of this album → send banner once
                        pending_albums[grouped_id] = {"messages": [], "task": None}
                        await _send_banner(title_query, ep_num)

                    pending_albums[grouped_id]["messages"].append(event.message)

                    # Cancel previous timer and restart it (wait for remaining files)
                    existing = pending_albums[grouped_id].get("task")
                    if existing and not existing.done():
                        existing.cancel()
                    pending_albums[grouped_id]["task"] = asyncio.create_task(
                        _flush_album(grouped_id)
                    )

                # ── SINGLE FILE ───────────────────────────────────────────────
                else:
                    await _send_banner(title_query, ep_num)
                    logger.info(f"Forwarding single file to {BOT_CHANNEL}")
                    await client.forward_messages(
                        BOT_CHANNEL, event.message, drop_author=True
                    )

            except Exception as e:
                logger.error(f"Forwarding/Banner error: {e}")

        await client.connect()
        if not await client.is_user_authorized():
            logger.error("UserBot is NOT authorized! Set SESSION_STRING env variable on Render.")
            client = None
        else:
            logger.info("UserBot authorized and listening to source channel.")

    await app.initialize()
    await app.start()
    if app.updater:
        await app.updater.start_polling()
    logger.info("Bot running — Auto-Forwarder + Banner Manager")

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
