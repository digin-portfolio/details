import os
import datetime
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from config import logger, BOT_CHANNEL, THUMBNAIL_PATH, SCHEDULE_GROUP_ID, ADMIN_ID
from anilist_api import (
    fetch_anilist, SEARCH_QUERY, DETAIL_QUERY, AIRING_QUERY, SCHEDULE_QUERY, build_caption
)
from banner_maker import generate_banner
from data_manager import (
    load_watchlist, save_watchlist, load_alerts, save_alerts, 
    add_alert, remove_alert, get_user_alerts, update_notified_ep
)

SEARCH, SELECT, CONFIRM_EP, UPLOAD = range(4)
WATCH_SEARCH, WATCH_SELECT = range(4, 6)
ALERT_SEARCH, ALERT_SELECT, ALERT_CONFIRM_EP = range(6, 9)

async def check_new_episodes(context: ContextTypes.DEFAULT_TYPE) -> None:
    channel = BOT_CHANNEL
    if not channel:
        return

    watchlist = load_watchlist()
    user_alerts = load_alerts()
    if not watchlist and not user_alerts:
        return

    # Merge IDs from watchlist and all user alerts
    all_alert_ids = set()
    for aids_dict in user_alerts.values():
        all_alert_ids.update([int(k) for k in aids_dict.keys()])
    
    ids = list(set([int(k) for k in watchlist.keys()]) | all_alert_ids)
    if not ids:
        return

    try:
        data      = await fetch_anilist(AIRING_QUERY, {"ids": ids})
        schedules = data["data"]["Page"]["airingSchedules"]
    except Exception as e:
        logger.error(f"Airing check failed: {type(e).__name__}: {e}")
        return

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    for sched in schedules:
        if sched.get("airingAt", 0) > now:
            continue
        media    = sched["media"]
        anime_id = str(media["id"])
        ep_num   = sched["episode"]
        if ep_num <= watchlist.get(anime_id, 0):
            continue

        try:
            # 1. Handle Watchlist (Channel Auto-Post)
            if anime_id in watchlist and ep_num > watchlist.get(anime_id, 0):
                logger.info(f"Auto-posting banner for ep {ep_num} of {media['title']['romaji']}")
                caption   = build_caption(media, str(ep_num))
                cover_url = ((media.get("coverImage") or {}).get("extraLarge")
                             or (media.get("coverImage") or {}).get("large"))
                if cover_url:
                    async with httpx.AsyncClient(timeout=20) as c:
                        img_resp = await c.get(cover_url)
                        cover_bytes = img_resp.content
                    banner_bytes = generate_banner(media, cover_bytes)
                    await context.bot.send_photo(
                        chat_id=channel,
                        photo=banner_bytes,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await context.bot.send_message(chat_id=channel, text=caption, parse_mode=ParseMode.MARKDOWN)
                
                watchlist[anime_id] = ep_num
                save_watchlist(watchlist)

            # 2. Handle User Alerts (Private DMs)
            # We use a separate tracking for alerts to avoid missing them if job fails half-way
            # For simplicity, we'll just check if current ep aired in last 10 mins or so
            # But safer is to track last notified ep per user.
            # Let's just notify all users who have this anime_id and haven't been notified for this ep.
            title_en = media["title"].get("english") or media["title"].get("romaji")
            alert_msg = (
                f"🔔 *Airing Notification*\n\n"
                f"Hey! *{title_en}* Episode *{ep_num}* just aired!\n"
                f"Wait for some hour to upload files and Go check your channel for the file."
            )
            
            for user_id, aids_dict in user_alerts.items():
                if anime_id in aids_dict:
                    last_notif = aids_dict[anime_id]
                    if ep_num > last_notif:
                        try:
                            await context.bot.send_message(chat_id=user_id, text=alert_msg, parse_mode=ParseMode.MARKDOWN)
                            # Update local dict so we don't resend in same run or next run
                            aids_dict[anime_id] = ep_num
                            logger.info(f"Sent alert for {title_en} Ep {ep_num} to user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to send DM to {user_id}: {e}")

        except Exception as e:
            logger.error(f"Auto-post/Alert error: {e}")
            
    # Save final alert state once after all notifications
    save_alerts(user_alerts)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    
    admin_help = (
        "<b>📮 Admin Commands:</b>\n"
        "• <code>/post</code> — search and post banner + metadata\n"
        "• <code>/watch</code> — track anime for auto-posting banners\n"
        "• <code>/watchlist</code> — show tracked anime\n"
        "• <code>/unwatch</code> — remove tracking\n"
        "• <code>/post_schedule</code> — send schedule to group\n\n"
    ) if is_admin else ""

    await update.message.reply_text(
        "👋 <b>Anime Station Bot</b>\n\n"
        f"{admin_help}"
        "<b>📣 Your Alerts:</b>\n"
        "• <code>/alert</code> — get private DM when an anime airs\n"
        "• <code>/unalert</code> — remove your alerts\n\n"
        "<b>📅 Schedule:</b>\n"
        "• <code>/schedule</code> — see today's airing schedule\n\n"
        "• <code>/cancel</code> — stop current search",
        parse_mode=ParseMode.HTML,
    )

async def post_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("🔍 Enter the *anime name* to search:",
                                    parse_mode=ParseMode.MARKDOWN)
    return SEARCH

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("⏳ Searching AniList…")
    try:
        data    = await fetch_anilist(SEARCH_QUERY, {"search": update.message.text.strip()})
        results = data["data"]["Page"]["media"]
    except Exception as e:
        await msg.edit_text(f"❌ {e}")
        return ConversationHandler.END

    if not results:
        await msg.edit_text("😕 No results.")
        return SEARCH

    context.user_data["search_results"] = results
    keyboard = []
    for i, m in enumerate(results):
        title = m["title"].get("english") or m["title"].get("romaji") or "?"
        year  = m.get("seasonYear") or ""
        fmt   = (m.get("format") or "").replace("_", " ")
        keyboard.append([InlineKeyboardButton(f"{title} ({year}) [{fmt}]",
                                              callback_data=f"post_{i}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="post_cancel")])
    await msg.edit_text("📋 *Select the anime:*", parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT

async def select_anime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "post_cancel":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    idx   = int(query.data.split("_")[1])
    media = context.user_data["search_results"][idx]
    try:
        data  = await fetch_anilist(DETAIL_QUERY, {"id": media["id"]})
        media = data["data"]["Media"]
    except Exception:
        pass

    context.user_data["selected_media"] = media
    await query.edit_message_text(
        "Enter *episode number* (e.g. `01`) or type `skip`:",
        parse_mode=ParseMode.MARKDOWN)
    return CONFIRM_EP

async def confirm_and_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text    = update.message.text.strip()
    episode = None if text.lower() == "skip" else text
    media   = context.user_data["selected_media"]
    channel = BOT_CHANNEL
    msg     = await update.message.reply_text("🚀 Starting…")
    try:
        caption   = build_caption(media, episode)
        cover_url = ((media.get("coverImage") or {}).get("extraLarge")
                     or (media.get("coverImage") or {}).get("large"))
        if cover_url:
            await msg.edit_text("🎨 Generating banner…")
            async with httpx.AsyncClient(timeout=20) as c:
                img_resp = await c.get(cover_url)
                cover_bytes = img_resp.content
            banner_bytes = generate_banner(media, cover_bytes)
            await context.bot.send_photo(
                chat_id=channel,
                photo=banner_bytes,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await context.bot.send_message(chat_id=channel, text=caption, parse_mode=ParseMode.MARKDOWN)
        await msg.edit_text("✅ Banner posted!\n\n"
                            "📂 *Now send the anime files* (MKV/MP4).\n"
                            "I will forward them to the channel with the correct name.",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ Finish", callback_data="post_finish")]
                            ]))
        context.user_data["episode"] = episode
        return UPLOAD
    except Exception as e:
        logger.error(f"Post error: {type(e).__name__}: {e}")
        await msg.edit_text(f"❌ Error: {type(e).__name__}\n{e}")
        return ConversationHandler.END

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc   = update.message.document
    media = context.user_data.get("selected_media")
    ep    = context.user_data.get("episode")
    
    if not doc or not doc.file_name.lower().endswith((".mkv", ".mp4", ".m4v")):
        await update.message.reply_text("⚠️ Please send me the *MKV or MP4 video file* as a document.")
        return UPLOAD

    # Extract quality from filename if present
    quality = ""
    for q in ["480p", "720p", "1080p", "360p", "2160p", "4k"]:
        if q in doc.file_name.lower():
            quality = f" [{q}]"
            break
            
    title = media["title"].get("english") or media["title"].get("romaji")
    # Clean title for filename-safe
    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    new_name = f"S1 {ep or '01'} - {safe_title}{quality}.mkv"
    
    thumb = THUMBNAIL_PATH if os.path.exists(THUMBNAIL_PATH) else None
    
    
    try:
        await context.bot.send_document(
            chat_id=BOT_CHANNEL,
            document=doc.file_id,
            filename=new_name,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Manual upload error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")

    return UPLOAD

async def finish_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.delete_message()
    context.user_data.clear()
    return ConversationHandler.END

async def watch_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("🔍 Enter anime name to track:",
                                    parse_mode=ParseMode.MARKDOWN)
    return WATCH_SEARCH

async def watch_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("⏳ Searching…")
    try:
        data    = await fetch_anilist(SEARCH_QUERY, {"search": update.message.text.strip()})
        results = data["data"]["Page"]["media"]
    except Exception as e:
        await msg.edit_text(f"❌ {e}")
        return ConversationHandler.END

    if not results:
        await msg.edit_text("😕 No results.")
        return WATCH_SEARCH

    context.user_data["watch_results"] = results
    keyboard = []
    for i, m in enumerate(results):
        title = m["title"].get("english") or m["title"].get("romaji") or "?"
        year  = m.get("seasonYear") or ""
        fmt   = (m.get("format") or "").replace("_", " ")
        keyboard.append([InlineKeyboardButton(f"{title} ({year}) [{fmt}]",
                                              callback_data=f"watch_{i}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="watch_cancel")])
    await msg.edit_text("📋 *Select anime to track:*", parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup(keyboard))
    return WATCH_SELECT

async def watch_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "watch_cancel":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    idx      = int(query.data.split("_")[1])
    media    = context.user_data["watch_results"][idx]
    anime_id = str(media["id"])
    title    = media["title"].get("english") or media["title"].get("romaji") or "?"

    watchlist = load_watchlist()
    if anime_id in watchlist:
        await query.edit_message_text(f"ℹ️ *{title}* already tracked.",
                                      parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    watchlist[anime_id] = 0
    save_watchlist(watchlist)
    await query.edit_message_text(
        f"✅ Now tracking *{title}*\n\n"
        f"Bot will auto-post the banner and metadata when each episode airs.",
        parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def show_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return
    watchlist = load_watchlist()
    if not watchlist:
        await update.message.reply_text("📭 Empty. Use /watch to add anime.")
        return
    ids = [int(k) for k in watchlist.keys()]
    try:
        q = "query ($ids: [Int]) { Page { media(id_in: $ids, type: ANIME) { id title { english romaji } } } }"
        data   = await fetch_anilist(q, {"ids": ids})
        titles = {str(m["id"]): m["title"].get("english") or m["title"].get("romaji")
                  for m in data["data"]["Page"]["media"]}
    except Exception:
        titles = {}
    lines = ["📋 *Tracked Anime:*\n"]
    for anime_id, last_ep in watchlist.items():
        name = titles.get(anime_id, f"ID {anime_id}")
        lines.append(f"• {name} — last ep: `{last_ep or 'none'}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return
    watchlist = load_watchlist()
    if not watchlist:
        await update.message.reply_text("📭 Already empty.")
        return
    ids = [int(k) for k in watchlist.keys()]
    try:
        q = "query ($ids: [Int]) { Page { media(id_in: $ids, type: ANIME) { id title { english romaji } } } }"
        data   = await fetch_anilist(q, {"ids": ids})
        titles = {str(m["id"]): m["title"].get("english") or m["title"].get("romaji")
                  for m in data["data"]["Page"]["media"]}
    except Exception:
        titles = {}
    keyboard = [[InlineKeyboardButton(f"❌ {titles.get(str(aid), str(aid))}", callback_data=f"uw_{aid}")]
                for aid in watchlist]
    keyboard.append([InlineKeyboardButton("Close", callback_data="uw_close")])
    await update.message.reply_text("Select to remove:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def unwatch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "uw_close":
        await query.delete_message()
        return
    anime_id  = query.data.split("_", 1)[1]
    watchlist = load_watchlist()
    watchlist.pop(anime_id, None)
    save_watchlist(watchlist)
    await query.edit_message_text("✅ Removed.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def get_schedule_text() -> str:
    now    = datetime.datetime.now(datetime.timezone.utc)
    start  = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    end    = start + 86400 # 24 hours
    
    try:
        data = await fetch_anilist(SCHEDULE_QUERY, {"weekStart": start, "weekEnd": end})
        schedules = (data.get("data") or {}).get("Page", {}).get("airingSchedules", [])
        
        if not schedules:
            return "📅 No anime airing today."

        schedules.sort(key=lambda x: x["airingAt"])
        date_str = now.strftime("%A, %d %B %Y")
        text = f"📅 *Anime Airing Schedule*\n🗓 *{date_str}*\n{'-'*25}\n\n"
        
        for s in schedules:
            dt = datetime.datetime.fromtimestamp(s["airingAt"], datetime.timezone.utc)
            time_str = dt.strftime("%I:%M %p")
            media    = s["media"]
            title    = media["title"].get("english") or media["title"].get("romaji") or "Unknown"
            ep       = s["episode"]
            fmt      = (media.get("format") or "").upper()
            icon     = "📺" if fmt == "TV" else "🎥" if "MOVIE" in fmt else "📽"
            text += f"`{time_str}` — *Ep {ep}* — {icon} {title}\n"
        return text
    except Exception as e:
        logger.error(f"Schedule build error: {e}")
        return f"❌ Error fetching schedule: {e}"

async def handle_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await get_schedule_text()
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def post_schedule_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return
    text = await get_schedule_text()
    await context.bot.send_message(chat_id=SCHEDULE_GROUP_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(f"✅ Schedule posted to group: `{SCHEDULE_GROUP_ID}`", parse_mode=ParseMode.MARKDOWN)

async def auto_post_schedule(context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await get_schedule_text()
    if "No anime airing" not in text and "Error" not in text:
        await context.bot.send_message(chat_id=SCHEDULE_GROUP_ID, text=text, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Auto-posted daily schedule to {SCHEDULE_GROUP_ID}")

def get_post_conv_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("post", post_start)],
        states={
            SEARCH:     [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)],
            SELECT:     [CallbackQueryHandler(select_anime, pattern="^post_")],
            CONFIRM_EP: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_and_post)],
            UPLOAD:     [
                MessageHandler(filters.Document.ALL, handle_file_upload),
                CallbackQueryHandler(finish_upload, pattern="^post_finish")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

async def alert_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🔍 Enter anime name to get *private alerts*:",
                                    parse_mode=ParseMode.MARKDOWN)
    return ALERT_SEARCH

async def alert_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("⏳ Searching…")
    try:
        data    = await fetch_anilist(SEARCH_QUERY, {"search": update.message.text.strip()})
        results = data["data"]["Page"]["media"]
    except Exception as e:
        await msg.edit_text(f"❌ {e}")
        return ConversationHandler.END

    if not results:
        await msg.edit_text("😕 No results.")
        return ALERT_SEARCH

    context.user_data["alert_results"] = results
    keyboard = []
    for i, m in enumerate(results):
        title = m["title"].get("english") or m["title"].get("romaji") or "?"
        year  = m.get("seasonYear") or ""
        fmt   = (m.get("format") or "").replace("_", " ")
        keyboard.append([InlineKeyboardButton(f"{title} ({year}) [{fmt}]",
                                              callback_data=f"alert_{i}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="alert_cancel")])
    await msg.edit_text("📋 *Select anime for alerts:*", parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup(keyboard))
    return ALERT_SELECT

async def alert_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "alert_cancel":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    idx   = int(query.data.split("_")[1])
    media = context.user_data["alert_results"][idx]
    context.user_data["alert_media"] = media
    
    await query.edit_message_text(
        f"📋 Selected: *{media['title'].get('english') or media['title'].get('romaji')}*\n\n"
        f"Enter the **last episode you watched** (e.g. `12`).\n"
        f"I will alert you for *future* episodes.",
        parse_mode=ParseMode.MARKDOWN)
    return ALERT_CONFIRM_EP

async def alert_confirm_ep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ep_text = update.message.text.strip()
    try:
        last_ep = int(ep_text)
    except ValueError:
        await update.message.reply_text("❓ Please enter a **number** (e.g. `12`):")
        return ALERT_CONFIRM_EP
        
    media    = context.user_data["alert_media"]
    anime_id = int(media["id"])
    title    = media["title"].get("english") or media["title"].get("romaji") or "?"
    user_id  = update.effective_user.id

    if add_alert(user_id, anime_id, last_ep):
        await update.message.reply_text(
            f"✅ Alert set for *{title}* (starting after ep {last_ep})!\n\n"
            f"I will DM you when the next episode airs.",
            parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Error setting alert.")
    
    context.user_data.clear()
    return ConversationHandler.END

async def unalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id    = update.effective_user.id
    user_aids  = get_user_alerts(user_id) # Now returns a dict
    if not user_aids:
        await update.message.reply_text("📭 You have no active alerts.")
        return
    
    aids = [int(k) for k in user_aids.keys()]
    try:
        q = "query ($ids: [Int]) { Page { media(id_in: $ids, type: ANIME) { id title { english romaji } } } }"
        data   = await fetch_anilist(q, {"ids": aids})
        titles = {m["id"]: m["title"].get("english") or m["title"].get("romaji")
                  for m in data["data"]["Page"]["media"]}
    except Exception:
        titles = {}
        
    keyboard = [[InlineKeyboardButton(f"❌ {titles.get(aid, str(aid))}", callback_data=f"ua_{aid}")]
                for aid in aids]
    keyboard.append([InlineKeyboardButton("Close", callback_data="ua_close")])
    await update.message.reply_text("Select an alert to remove:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def unalert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "ua_close":
        await query.delete_message()
        return
        
    anime_id = int(query.data.split("_", 1)[1])
    user_id  = update.effective_user.id
    if remove_alert(user_id, anime_id):
        await query.edit_message_text("✅ Alert removed.")
    else:
        await query.edit_message_text("❌ Error removing alert.")

def get_alert_conv_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("alert", alert_start)],
        states={
            ALERT_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, alert_search)],
            ALERT_SELECT: [CallbackQueryHandler(alert_select, pattern="^alert_")],
            ALERT_CONFIRM_EP: [MessageHandler(filters.TEXT & ~filters.COMMAND, alert_confirm_ep)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

def get_watch_conv_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("watch", watch_start)],
        states={
            WATCH_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_search)],
            WATCH_SELECT: [CallbackQueryHandler(watch_select, pattern="^watch_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

def setup_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("schedule", handle_schedule))
    app.add_handler(CommandHandler("post_schedule", post_schedule_manual))
    app.add_handler(get_post_conv_handler())
    app.add_handler(get_watch_conv_handler())
    app.add_handler(get_alert_conv_handler())
    app.add_handler(CommandHandler("watchlist", show_watchlist))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CallbackQueryHandler(unwatch_callback, pattern="^uw_"))
    app.add_handler(CommandHandler("unalert", unalert))
    app.add_handler(CallbackQueryHandler(unalert_callback, pattern="^ua_"))
    
    # Jobs
    app.job_queue.run_repeating(check_new_episodes, interval=300, first=30)
    # Daily schedule at 00:05 UTC
    app.job_queue.run_daily(auto_post_schedule, time=datetime.time(hour=0, minute=5, tzinfo=datetime.timezone.utc))
