# pyre-ignore-all-errors
# type: ignore
import os
import logging
from typing import Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger("anime_bot")

ANILIST_API    = "https://graphql.anilist.co"
BANNER_W, BANNER_H = 1200, 630
WATCHLIST_FILE = "watchlist.json"

BOT_CHANNEL = int(os.getenv("BOT_CHANNEL", "-1003193032701 -1001555967163"))
THUMBNAIL_PATH = os.getenv("THUMBNAIL", r"C:\Users\hhp\ANIMEFETCHER\thumb.jpg")

SCHEDULE_GROUP_ID = int(os.getenv("SCHEDULE_GROUP_ID", "-1001874426493"))
ADMIN_ID = 1059586105


# Quality info for caption
QUALITIES_STR = "480p, 720p, 1080p • x265 HEVC 10bit"
