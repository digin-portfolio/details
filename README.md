# 🎬 AnimeFetcher Bot

![AnimeFetcher Banner](C:\Users\hhp\.gemini\antigravity\brain\a502c61d-f27a-4a73-ac7d-cee5d8c7bbf7\anime_fetcher_banner_png_1774105278693.png)

A Telegram bot that posts anime banners (AniList), schedules, watchlist alerts, and related commands.

## 🚀 Features
- **Banner Generation**: Creates anime info banners using the AniList API (e.g. via `/post`).
- **Watchlist Management**: Track your favorite anime and get notifications for new episodes.
- **Port Binding**: Built-in health check server for 24/7 deployment on Render.

## 📜 Rules & Usage
1. **Personal Use**: This bot is intended for personal use and small community management.
2. **Channels**: Only post to channels and groups you manage or have permission to use.
3. **No Spamming**: Avoid using the bot to spam Telegram channels or groups.

## ⚙️ Compatibility
- **Platform**: Python 3.8+
- **Environment**: Local PC (Windows/Linux) or Cloud Platforms (Render, Heroku, etc.).
- **Libraries**: python-telegram-bot (bot), Httpx (API calls), Pillow (banner images).

## ⚖️ Legal Disclaimer
This project is for **educational and personal use only**. We do **not** support or encourage illegal activities, including the distribution of copyrighted material without authorization. The developers are not responsible for any misuse of this tool. Use this bot in accordance with Telegram's Terms of Service and local laws.

---

### How to Run Locally
1. Install dependencies: `pip install -r requirements.txt`
2. Configure `.env` with your `BOT_TOKEN` (and optional `BOT_CHANNEL`, etc.).
3. Run: `python bot.py`
