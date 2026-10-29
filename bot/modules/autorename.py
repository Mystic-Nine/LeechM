#!/usr/bin/env python3
import re
import os
from requests import post as rpost
from urllib.parse import quote_plus
from bot import user_data, LOGGER, bot, DATABASE_URL, config_dict
from pyrogram.handlers import MessageHandler
from pyrogram.filters import command
from bot.helper.telegram_helper.message_utils import sendMessage
from bot.helper.ext_utils.bot_utils import update_user_ldata, sync_to_async
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.modules.anilist import ANIME_GRAPHQL_QUERY
from bot.modules.poster import fetch_json
from html import escape

def trun(text, limit=60):
    text = str(text)
    return text[:limit] + "..." if len(text) > limit else text

# The only tags allowed in an Auto Rename format string
VALID_AUTORENAME_TAGS = {'title', 'season', 'episode',
                          'quality', 'codec', 'audio', 'sub', 'size', 'language'}

# Shared with get_autorename() below and with get_clean_title() (used by
# Auto Thumbnail) - strips season/episode/quality/codec/audio/sub noise
# words out of a filename, leaving (roughly) just the title.
NOISE_PATTERN = r'(S\d{1,2}|E\d{1,3}|Ep\s*\d{1,3}|Episode\s*\d{1,3}|480p|720p|1080p|1440p|2160p|4K|x264|x265|HEVC|AV1|H264|H265|10bit|10Bit|AVC|BluRay|WEB-DL|WEBRip|HDRip|HDTV|Dual[\s\-]?Audio|Multi[\s\-]?Audio|Hindi|English|Tamil|Telugu|Malayalam|Kannada|Bengali|ESub|HC-ENG|MSub|Multi[\s\-]?Sub|Subbed|Audio)'

def get_clean_title(filename):
    """
    Strip a filename down to (roughly) just its title, the same way
    get_autorename() does for the {title} tag - brackets/parens and
    season/episode/quality/codec/audio/sub noise words removed. Used by
    Auto Thumbnail to know what to search AniList/TMDB for.
    """
    name = os.path.splitext(filename)[0]
    clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', name)
    clean_title = re.sub(NOISE_PATTERN, '', clean_title, flags=re.IGNORECASE)
    return re.sub(r'(\s|-|\.)+', ' ', clean_title).strip()

def validate_autorename_format(format_str):
    """
    Returns any {tag} used in the user's format that isn't supported (e.g. a
    typo like {qualilty}). An unsupported tag makes get_autorename() raise a
    KeyError and silently fall back to the original filename, which just
    looks like "Auto Rename isn't working" to the user with no clue why.
    So the format should be validated before it's saved.
    """
    used_tags = set(re.findall(r'\{([a-zA-Z_]+)\}', format_str))
    return used_tags - VALID_AUTORENAME_TAGS

_TITLE_CACHE = {}


async def resolve_auto_title(search_name):
    # PERF: a season leech has dozens of files with the same cleaned name -> do the
    # AniList/TMDB lookup once, not once per file (each call can take seconds).
    key = (search_name or '').strip().lower()
    if key in _TITLE_CACHE:
        return _TITLE_CACHE[key]
    res = await _resolve_auto_title(search_name)
    if res:
        if len(_TITLE_CACHE) > 300:
            _TITLE_CACHE.clear()
        _TITLE_CACHE[key] = res
    return res


async def _resolve_auto_title(search_name):
    """
    Used when the format uses {title} but the user has no Custom Title set.
    Searches AniList for an anime match using the cleaned filename
    (search_name) first. If found, returns its English/Romaji title. If it's
    not an anime (no match), falls back to a TMDB Movie/TV/Drama search
    (requires TMDB_API_KEY, configurable via /bsetting). Returns None if
    neither finds a match, in which case the caller falls back to the
    cleaned filename as the title.
    """
    if not search_name or not search_name.strip():
        return None
    search_name = search_name.strip()

    # 1) AniList anime search. This is a blocking call, so it's run via
    #    sync_to_async in a thread to avoid blocking the event loop.
    try:
        anires = await sync_to_async(
            rpost, 'https://graphql.anilist.co',
            json={'query': ANIME_GRAPHQL_QUERY, 'variables': {'search': search_name}},
            timeout=10
        )
        media = anires.json().get('data', {}).get('Media')
        if media:
            title = media.get('title', {}) or {}
            if (t := title.get('english') or title.get('romaji')):
                return t
    except Exception as e:
        LOGGER.error(f"Auto Rename: AniList title lookup failed for '{search_name}': {e}")

    # 2) TMDB multi search (Movie / TV / Drama) - reached when it's not anime
    if config_dict.get('TMDB_API_KEY'):
        try:
            safe_query = quote_plus(search_name)
            url = f"https://api.themoviedb.org/3/search/multi?api_key={config_dict['TMDB_API_KEY']}&query={safe_query}"
            result = await fetch_json(url)
            if result and result.get('results'):
                valid = [r for r in result['results'] if r.get('media_type') in ('movie', 'tv')]
                if valid and (t := valid[0].get('title') or valid[0].get('name')):
                    return t
        except Exception as e:
            LOGGER.error(f"Auto Rename: TMDB title lookup failed for '{search_name}': {e}")

    return None

async def get_title_for_thumbnail(filename, caption=""):
    """
    Resolve a title to search for Auto Thumbnail - the same pipeline Auto
    Rename uses for {title}: prefer a "Title: ..." line in the caption if
    present, otherwise clean the filename, then try AniList (anime) and
    fall back to TMDB (movie/TV/drama). Returns None if nothing is found,
    in which case the caller should just skip fetching a thumbnail.
    """
    caption_title = None
    if caption and (m := re.search(r'(?:^|\n)\s*Title\s*[:\-]+\s*(.+)', caption, re.IGNORECASE)):
        caption_title = m.group(1).strip()

    clean_title = caption_title if caption_title else get_clean_title(filename)
    if not clean_title:
        return None
    return await resolve_auto_title(clean_title) or clean_title

async def get_autorename(filename, user_id, size="", media_quality="", lang="", subs="", caption="", skip=False):
    """
    Advanced Auto Rename Logic: Cleans the filename and applies user format.
    Available Tags: {title}, {season}, {episode}, {quality}, {codec}, {audio}, {sub}, {size}, {language}

    - `caption`   : original Telegram caption of the file. Used as a fallback source to find
                    Season/Episode when the filename itself doesn't contain them.
    - `skip`      : if True, Auto Rename is bypassed completely and the original filename is
                    returned as-is. Used when the user has explicitly renamed the file via a
                    manual rename command/flag (e.g. "/l -n filename.mkv") so that command
                    should win over Auto Rename.
    """
    user_dict = user_data.get(user_id, {})

    # A manual rename command (-n / -name) always wins over Auto Rename
    if skip:
        return filename

    # If the user has Auto Rename disabled, return the original filename
    if not user_dict.get('autorename', False):
        return filename

    # Default format set
    format_str = user_dict.get('autorename_format', '{title} - S{season}E{episode} - {quality} {codec} {audio} {sub}')
    if not format_str:
        format_str = '{title} - S{season}E{episode} - {quality}'

    name, ext = os.path.splitext(filename)

    # Check whether the user put an explicit extension (.mkv, .mp4 etc.) at
    # the very end of the format. If so, that wins; otherwise the original
    # file's extension is kept.
    has_custom_ext = bool(re.search(r'\.[A-Za-z0-9]{2,5}$', format_str.strip()))

    # Backup source to look for Season/Episode/Quality/Title etc. when
    # they're not found in the filename itself. Many long anime/movie names
    # push the useful bits (season, episode, quality) toward the end of the
    # filename where Telegram may visually truncate it, and some uploaders
    # put this info only in the caption, in many different styles
    # (e.g. "Episode :- 11", "Episode: 11", "Ep- 11", "S02E07").
    caption_text = caption or ""

    def _extract(patterns, *texts):
        """Try each regex pattern against each text in order (filename
        first, then caption) and return the first capture group matched."""
        for text in texts:
            if not text:
                continue
            for pat in patterns:
                if m := re.search(pat, text, re.IGNORECASE):
                    return m.group(1)
        return None

    # Word form ("Season 01", "Episode :- 11", "Ep- 11") tried first, then
    # the compact filename form ("S02", "E07") as a fallback.
    season = _extract(
        [r'(?:Season)\.?\s*[:\-]*\s*(\d{1,2})', r'S(\d{1,2})(?!\d)'],
        name, caption_text)
    season = season.zfill(2) if season else ""

    episode = _extract(
        [r'(?:Episode|Ep)\.?\s*[:\-]*\s*(\d{1,3})', r'E(\d{1,3})(?!\d)'],
        name, caption_text)
    if not episode:
        # Some uploaders just put the episode number at the very start of
        # the filename with no S/E/Episode marker at all, e.g.
        # "01 Shikimori's Not Just a Cutie Dual 480p.mkv" (single-season
        # anime, season not mentioned anywhere). Only trust this when the
        # number is zero-padded (01, 02, ... 09) since a real title
        # essentially never starts with a leading zero - this keeps titles
        # that just happen to start with a plain number (e.g. "86 Eighty
        # Six", "91 Days") from being misread as an episode number.
        if m := re.match(r"^(0\d{1,2})(?!\d)[\s._-]", name.strip()):
            episode = m.group(1)
    episode = episode.zfill(2) if episode else ""

    if not season and episode:
        # No season marker found anywhere, but an episode number was found -
        # almost always means a single-season show that just didn't bother
        # tagging the season. Default to Season 01 instead of leaving
        # {season} blank.
        season = "01"

    quality = _extract([r'(480p|720p|1080p|1440p|2160p|4K)'], name, caption_text) or media_quality

    codec = _extract([r'(x264|x265|HEVC|AV1|H264|H265|10bit|10Bit|AVC)'], name, caption_text) or ""

    audio = _extract(
        [r'(Dual[\s\-]?Audio|Multi[\s\-]?Audio|Hindi|English|Tamil|Telugu|Malayalam|Kannada|Bengali)'],
        name, caption_text)
    audio = audio.title() if audio else lang

    sub = _extract([r'(ESub|HC-ENG|MSub|Multi[\s\-]?Sub|Subbed)'], name, caption_text) or subs

    # A structured caption often has its own explicit "Title - ..." /
    # "Title: ..." line, which tends to be cleaner and more reliable than
    # whatever can be scraped out of the filename - use it when present.
    caption_title = None
    if caption_text and (m := re.search(r'(?:^|\n)\s*Title\s*[:\-]+\s*(.+)', caption_text, re.IGNORECASE)):
        caption_title = m.group(1).strip()

    # Clean the original filename (strip brackets/parentheses and noise words)
    clean_title = caption_title if caption_title else re.sub(r'\[.*?\]|\(.*?\)', '', name)
    clean_title = re.sub(NOISE_PATTERN, '', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'(\s|-|\.)+', ' ', clean_title).strip() 

    # Check the user's Custom Title. If there isn't one and the format uses
    # {title}, try to resolve a proper title via AniList/TMDB
    # (resolve_auto_title). If that fails too, fall back to the cleaned
    # filename as the title.
    custom_title = user_dict.get('custom_title', '')
    if custom_title:
        final_title = custom_title
    elif '{title}' in format_str:
        final_title = await resolve_auto_title(clean_title) or clean_title
    else:
        final_title = clean_title

    try:
        # Build the new name from the user's format
        new_name = format_str.format(
            title=final_title,
            season=season,
            episode=episode,
            quality=quality,
            codec=codec,
            audio=audio,
            sub=sub,
            size=size,
            language=audio
        )
        
        # If the file has no season or episode, remove the leftover empty 'SE'
        if not season and not episode:
            new_name = new_name.replace('SE', '').replace('S E', '')
        elif not season and episode:
            new_name = new_name.replace('SE', 'E')
        elif season and not episode:
            # Without an episode, a dangling 'E' would be left after the season
            # (e.g. a file with "...S2..." but no episode would end up as
            # "S02E.mp4"). This only removes the empty 'E' right after the
            # season, not any other 'E' character in the title.
            new_name = re.sub(rf'S{re.escape(season)}E(?!\d)', f'S{season}', new_name)
            
        # Clean up extra spaces, dashes or dots left behind (safeguard)
        new_name = re.sub(r'\s+', ' ', new_name)
        new_name = re.sub(r'-\s*-', '-', new_name)
        new_name = re.sub(r'\.\s*\.', '.', new_name)
        new_name = new_name.strip(' -.')
        
        # If the new name somehow ends up empty, fall back to the title
        if not new_name:
            new_name = final_title

        # Extension handling: if the user gave an explicit extension in the
        # format, that's kept; otherwise the original file's extension is used.
        final_name = new_name if has_custom_ext else f"{new_name}{ext}"

        LOGGER.debug(f"Auto Renamed: {filename} -> {final_name}")
        return final_name
    
    except KeyError as e:
        LOGGER.error(f"Auto Rename KeyError: Missing tag {e} in user format.")
        return filename
    except Exception as e:
        LOGGER.error(f"Auto Rename Error: {e}")
        return filename

# ==========================================
# /autorename Command Logic
# ==========================================

async def autorename_cmd(client, message):
    user_id = message.from_user.id

    if len(message.command) > 1:
        new_format = message.text.split(maxsplit=1)[1]
        if invalid_tags := validate_autorename_format(new_format):
            bad = ", ".join(f"{{{t}}}" for t in sorted(invalid_tags))
            await sendMessage(
                message,
                f"<b>⚠️ Invalid Tag(s) In Format:</b> <code>{escape(bad)}</code>\n\n"
                f"<b>Available Tags :</b> <code>{{title}}</code>, <code>{{season}}</code>, <code>{{episode}}</code>, "
                f"<code>{{quality}}</code>, <code>{{codec}}</code>, <code>{{audio}}</code>, <code>{{sub}}</code>, "
                f"<code>{{size}}</code>, <code>{{language}}</code>\n\n"
                f"<i>Format was not saved. Please fix the tag and try again.</i>"
            )
            return
        update_user_ldata(user_id, 'autorename_format', new_format)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
        await sendMessage(message, f"<b>Auto Rename Format Updated To:</b>\n<code>{escape(new_format)}</code>")
        return

    user_dict = user_data.get(user_id, {})
    buttons = ButtonMaker()

    auto_status = 'Enabled' if user_dict.get('autorename', False) else 'Disabled'
    format_str = user_dict.get('autorename_format', 'Not Exists')
    custom_title = user_dict.get('custom_title', 'Not Exists')
    
    text = f"㊂ <b><u>Auto Rename Settings :</u></b>\n\n"
    text += f"➲ <b>Status :</b> <i>{auto_status}</i>\n"
    text += f"➲ <b>Current Format :</b> <code>{escape(trun(format_str, 60))}</code>\n"
    text += f"➲ <b>Custom Title :</b> <code>{escape(trun(custom_title, 60))}</code>\n\n"
    text += f"➲ <b>Available Tags :</b> <code>{{title}}</code>, <code>{{season}}</code>, <code>{{episode}}</code>, <code>{{quality}}</code>, <code>{{codec}}</code>, <code>{{audio}}</code>, <code>{{sub}}</code>, <code>{{size}}</code>, <code>{{language}}</code>\n"
    text += f"➲ <b>Format Example :</b> <code>{{title}} S{{season}}E{{episode}} [{{quality}}] Hindi.mkv</code>\n\n"
    text += f"➲ <b>Description :</b> <i>Set your Custom Format and Title for Auto Renaming files. Custom Title will override {{title}}. Add an extension (.mkv/.mp4) at the end of the format to force it, otherwise the original file's extension is kept. Season/Episode are auto-detected from the filename, and from the file caption if missing in the name. A manual rename command (e.g. \"-n filename.mkv\") always overrides Auto Rename.</i>"

    buttons.ibutton("Disable" if auto_status == 'Enabled' else "Enable", f"userset {user_id} toggle_autorename", "header")
    buttons.ibutton("Title", f"userset {user_id} custom_title")
    buttons.ibutton("Format", f"userset {user_id} autorename_format")

    buttons.ibutton("Back", f"userset {user_id} back leech", "footer")
    buttons.ibutton("Close", f"userset {user_id} close", "footer")
    
    button = buttons.build_menu(2)
    await sendMessage(message, text, button)

# Command Handler
bot.add_handler(MessageHandler(autorename_cmd, filters=command(BotCommands.AutoRenameCommand) & CustomFilters.authorized_uset))
