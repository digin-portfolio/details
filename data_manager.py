import json
import os
from config import logger

WATCHLIST_FILE = "watchlist.json"
ALERT_FILE = "alerts.json"

# --- Watchlist Management (Channel) ---

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return {}
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading watchlist: {e}")
        return {}

def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving watchlist: {e}")

# --- Alert Management (Personal) ---

def load_alerts():
    if not os.path.exists(ALERT_FILE):
        return {}
    try:
        with open(ALERT_FILE, "r") as f:
            data = json.load(f)
            # Migration: convert [id1, id2] to {"id1": 0, "id2": 0}
            migrated = False
            for user_id, content in data.items():
                if isinstance(content, list):
                    data[user_id] = {str(aid): 0 for aid in content}
                    migrated = True
            if migrated:
                save_alerts(data)
            return data
    except Exception as e:
        logger.error(f"Error loading alerts: {e}")
        return {}

def save_alerts(alerts):
    try:
        with open(ALERT_FILE, "w") as f:
            json.dump(alerts, f, indent=4)
        logger.info(f"Successfully saved {len(alerts)} user alert profiles.")
    except Exception as e:
        logger.error(f"Error saving alerts: {e}")

def add_alert(user_id: str, anime_id: int, last_ep: int = 0):
    alerts = load_alerts()
    user_id_str, anime_id_str = str(user_id), str(anime_id)
    if user_id_str not in alerts:
        alerts[user_id_str] = {}
    
    alerts[user_id_str][anime_id_str] = last_ep
    save_alerts(alerts)
    return True

def remove_alert(user_id: str, anime_id: int):
    alerts = load_alerts()
    user_id_str, anime_id_str = str(user_id), str(anime_id)
    if user_id_str in alerts and anime_id_str in alerts[user_id_str]:
        del alerts[user_id_str][anime_id_str]
        if not alerts[user_id_str]:
            del alerts[user_id_str]
        save_alerts(alerts)
        return True
    return False

def get_user_alerts(user_id: str) -> dict:
    alerts = load_alerts()
    return alerts.get(str(user_id), {})

def update_notified_ep(user_id: str, anime_id: int, ep: int):
    alerts = load_alerts()
    u_str, a_str = str(user_id), str(anime_id)
    if u_str in alerts and a_str in alerts[u_str]:
        alerts[u_str][a_str] = ep
        save_alerts(alerts)
