import httpx
import datetime
import typing
from config import logger, ANILIST_API

SEARCH_QUERY = """
query ($search: String) {
  Page(perPage: 5) {
    media(search: $search, type: ANIME) {
      id
      title { romaji english native }
      season seasonYear format episodes duration
      genres
      coverImage { extraLarge large }
      studios(isMain: true) { nodes { name } }
    }
  }
}
"""

DETAIL_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english native }
    season seasonYear format episodes duration
    genres
    coverImage { extraLarge large }
    studios(isMain: true) { nodes { name } }
    nextAiringEpisode { airingAt episode }
    startDate { year month day }
  }
}
"""

AIRING_QUERY = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    airingSchedules(mediaId_in: $ids, notYetAired: false, sort: TIME_DESC) {
      id airingAt episode
      media {
        id
        title { romaji english }
        episodes duration genres
        coverImage { extraLarge large }
        studios(isMain: true) { nodes { name } }
        season seasonYear format
        startDate { year month day }
        nextAiringEpisode { airingAt episode }
      }
    }
  }
}
"""

SCHEDULE_QUERY = """
query ($weekStart: Int, $weekEnd: Int) {
  Page(page: 1) {
    pageInfo {
      hasNextPage
    }
    airingSchedules(airingAt_greater: $weekStart, airingAt_lesser: $weekEnd, sort: [TIME]) {
      airingAt
      episode
      media {
        id
        title {
          english
          romaji
        }
        format
        genres
      }
    }
  }
}
"""

async def fetch_anilist(query: str, variables: dict) -> typing.Dict[str, typing.Any]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(ANILIST_API,
                                     json={"query": query, "variables": variables})
            if resp.status_code != 200:
                logger.error(f"AniList Error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"AniList API error: {type(e).__name__}: {e}")
        raise
    return {}

def season_tag(media: dict) -> str:
    season = (media.get("season") or "").capitalize()
    year   = media.get("seasonYear") or ""
    fmt    = (media.get("format") or "").replace("_", " ")
    parts  = []
    if season and year:
        parts.append(f"{season} {year}")
    if fmt:
        parts.append(fmt)
    return " • ".join(parts) if parts else "Unknown"

def get_studio(media: dict) -> str:
    try:
        return media["studios"]["nodes"][0]["name"]
    except Exception:
        return ""

def make_acronym(title: str) -> str:
    FILLERS = {"a","an","the","of","in","on","at","to","and","or","for","with",
               "by","from","as","is","i","my","no","wa","ga","wo","ni","de","na","mo"}
    words = title.split()
    initials, first_word = [], ""
    for w in words:
        clean = "".join(c for c in w if c.isalnum())
        if not clean:
            continue
        if not first_word:
            first_word = clean
        if clean.lower() not in FILLERS:
            initials.append(clean[0].upper())
    acronym = "".join(initials)
    if 2 <= len(acronym) <= 5:
        return acronym
    if len(acronym) > 5:
        return str(acronym)[0:5] # pyre-ignore
    camel = "".join("".join(c for c in w if c.isalnum()) for w in words[0:2]) # pyre-ignore
    return camel if camel else first_word

def make_hashtags(media: dict) -> str:
    title_en   = media["title"].get("english") or media["title"].get("romaji") or ""
    genres     = media.get("genres") or []
    acronym    = make_acronym(title_en)
    genre_tags = [g.replace(" ", "") for g in genres[0:4]] # pyre-ignore
    return "  ".join([f"#{acronym}", "#Anime"] + [f"#{g}" for g in genre_tags])

def format_air_date(media: dict, episode=None) -> str:
    nae = media.get("nextAiringEpisode")
    if nae and nae.get("airingAt"):
        dt     = datetime.datetime.fromtimestamp(nae["airingAt"], datetime.timezone.utc)
        ep_num = nae.get("episode", "?")
        return f"📅 *Ep {ep_num} Airs:* `{dt.strftime('%d %b %Y, %H:%M UTC')}`"
    sd = media.get("startDate") or {}
    y, m, d = sd.get("year"), sd.get("month"), sd.get("day")
    if y and m and d:
        dt    = datetime.date(y, m, d)
        label = f"Ep {episode}" if episode else "Started"
        return f"📅 *{label}:* `{dt.strftime('%d %b %Y')}`"
    return ""

def build_caption(media: dict, episode=None) -> str:
    title_en   = media["title"].get("english") or media["title"].get("romaji") or "Unknown"
    title_rom  = media["title"].get("romaji") or ""
    genres     = media.get("genres") or []
    duration   = media.get("duration")
    episodes   = media.get("episodes")
    studio     = get_studio(media)
    genre_tags = "  ".join(f"`{g}`" for g in genres[0:5]) # pyre-ignore

    ep_ln  = f"📺 *Episode:* `{episode}`\n"          if episode  else ""
    dur_ln = f"⏱ *Duration:* `{duration} min/Ep`\n" if duration else ""
    tot_ln = f"🎞 *Total Episodes:* `{episodes}`\n"  if episodes else ""
    stu_ln = f"🏢 *Studio:* `{studio}`\n"            if studio   else ""
    air    = format_air_date(media, episode)
    air_ln = f"{air}\n"                              if air      else ""
    tags   = make_hashtags(media)

    return (
        f"🗓 *{season_tag(media)}*\n\n"
        f"🎬 _{title_en} | {title_rom}_\n\n"
        f"{'─'*30}\n"
        f"{ep_ln}"
        f"🎙 *Audio:* `Japanese [English Sub]`\n"
        f"{dur_ln}{tot_ln}{stu_ln}"
        f"📺 *Quality:* `480p, 720p, 1080p` • `x265 HEVC 10bit`\n"
        f"{air_ln}\n{tags}"
    )
