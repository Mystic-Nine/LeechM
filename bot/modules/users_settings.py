#!/usr/bin/env python3
from datetime import datetime
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, regex, create
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, path as aiopath, mkdir
from langcodes import Language
from os import path as ospath, getcwd
from PIL import Image
from time import time
from functools import partial
from html import escape
from io import BytesIO
from asyncio import sleep
from cryptography.fernet import Fernet

from bot.helper.ext_utils.lang_utils import LANG_NAMES, LANG_LIST
from bot import OWNER_ID, LOGGER, bot, user_data, config_dict, categories_dict, DATABASE_URL, IS_PREMIUM_USER, MAX_SPLIT_SIZE
from bot.helper.telegram_helper.message_utils import sendMessage, sendCustomMsg, editMessage, deleteMessage, sendFile, chat_info, user_info
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.bot_utils import gd_call, save_jpeg, getdailytasks, update_user_ldata, get_readable_file_size, sync_to_async, new_thread, is_gdrive_link
from bot.helper.mirror_utils.upload_utils.ddlserver.gofile import Gofile
from bot.helper.themes import BotTheme
from bot.modules.autorename import validate_autorename_format
from bot.helper.ext_utils.subtitle_utils import COLOR_OPTIONS, BG_COLOR_OPTIONS, validate_and_escape_subtitle_text

def trun(text, limit=60):
    text = str(text)
    return text[:limit] + "..." if len(text) > limit else text

def parse_metadata_str(string):
    d = {}
    if not string: return d
    pairs = string.split('|')
    for pair in pairs:
        if ':' in pair:
            k, v = pair.split(':', 1)
            d[k.strip()] = v.strip()
    return d

handler_dict = {}
desp_dict = {'rcc': ['RClone is a command-line program to sync files and directories to and from different cloud storage providers like GDrive, OneDrive...', 'Send rclone.conf. \n<b>Timeout:</b> 60 sec'],
            'lprefix': ['Leech Filename Prefix is the Front Part attacted with the Filename of the Leech Files.', 'Send Leech Filename Prefix. Documentation Here : <a href="https://t.me/Rare_Leech_Mirror_Hub/5">Click Me</a> \n<b>Timeout:</b> 60 sec'],
            'lsuffix': ['Leech Filename Suffix is the End Part attached with the Filename of the Leech Files', 'Send Leech Filename Suffix. Documentation Here : <a href="https://t.me/Rare_Leech_Mirror_Hub/5">Click Me</a> \n<b>Timeout:</b> 60 sec'],
            'lremname': ['Leech Filename Remname is combination of Regex(s) used for removing or manipulating Filename of the Leech Files', 'Send Leech Filename Remname. Documentation Here : <a href="https://t.me/Rare_Leech_Mirror_Hub/5">Click Me</a> \n<b>Timeout:</b> 60 sec'],
            'lcaption': ['Leech Caption is the Custom Caption on the Leech Files Uploaded by the bot', 'Send Leech Caption. You can add HTML tags. Documentation Here : <a href="https://t.me/Rare_Leech_Mirror_Hub/5">Click Me</a> \n<b>Timeout:</b> 60 sec'],
            'ldump': ['Leech Files User Dump for Personal Use as a Storage.', 'Send Leech Dump Channel ID\n➲ <b>Format:</b> \ntitle chat_id/@username\ntitle2 chat_id2/@username2. \n\n<b>NOTE:</b>Make Bot Admin in the Channel else it will not accept\n<b>Timeout:</b> 60 sec'],
            'metadata': ['Your channel name that should be used while editing metadata of the file', 'Configure multi metadata properties dynamically using grid manager.'],
            'lattachment': ['Attachment url, it will added in mkv as thumbnail or cover photo, whetever you say.', 'Send Telegraph photo url\n\n<b>Timeout:</b> 60 sec'],
            'mprefix': ['Mirror Filename Prefix is the Front Part attacted with the Filename of the Mirrored/Cloned Files.', 'Send Mirror Filename Prefix. \n<b>Timeout:</b> 60 sec'],
            'msuffix': ['Mirror Filename Suffix is the End Part attached with the Filename of the Mirrored/Cloned Files', 'Send Mirror Filename Suffix. \n<b>Timeout:</b> 60 sec'],
            'mremname': ['Mirror Filename Remname is combination of Regex(s) used for removing or manipulating Filename of the Mirrored/Cloned Files', 'Send Mirror Filename Remname. \n<b>Timeout:</b> 60 sec'],
            'thumb': ['Custom Thumbnail to appear on the Leeched files uploaded by the bot. If Auto Thumbnail is also enabled, this Custom Thumbnail always takes priority - Auto Thumbnail only kicks in when no Custom Thumbnail is set', 'Send a photo to save it as custom thumbnail. \n<b>Alternatively: </b><code>/cmd [photo] -s thumb</code> \n<b>Timeout:</b> 60 sec'],
            'yt_opt': ['YT-DLP Options is the Custom Quality for the extraction of videos from the yt-dlp supported sites.', 'Send YT-DLP Options. Timeout: 60 sec\nFormat: key:value|key:value|key:value.\nExample: format:bv*+mergeall[vcodec=none]|nocheckcertificate:True\nCheck all yt-dlp api options from this <a href="https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184">FILE</a> to convert cli arguments to api options.'],
            'usess': [f'User Session is Telegram Session used to Download Private Contents from Private Channels with no compromise in Privacy, Build with Encryption.\n{"<b>Warning:</b> This Bot is not secured. We recommend asking the group owner to set the Upstream repo to the Official repo. If it is not the official repo, then KPSML-X is not responsible for any issues that may occur in your account." if config_dict["UPSTREAM_REPO"] != "https://github.com/Tamilupdates/KPSML-X" else "Bot is Secure. You can use the session securely."}', 'Send your Session String.\n<b>Timeout:</b> 60 sec'],
            'split_size': ['Leech Splits Size is the size to split the Leeched File before uploading', f'Send Leech split size in any comfortable size, like 2Gb, 500MB or 1.46gB. \n<b>PREMIUM ACTIVE:</b> {IS_PREMIUM_USER}. \n<b>Timeout:</b> 60 sec'],
            'ddl_servers': ['DDL Servers which uploads your File to their Specific Hosting', ''],
            'user_tds': [f'UserTD helps to Upload files via Bot to your Custom Drive Destination via Global SA mail\n\n➲ <b>SA Mail :</b> {"Not Specified" if "USER_TD_SA" not in config_dict else config_dict["USER_TD_SA"]}', 'Send User TD details for Use while Mirror/Clone\n➲ <b>Format:</b>\nname id/link index(optional)\nname2 link2/id2 index(optional)\n\n<b>NOTE:</b>\n<i>1. Drive ID must be valid, then only it will accept\n2. Names can have spaces\n3. All UserTDs are updated on every change\n4. To delete specific UserTD, give Name(s) separated by each line</i>\n\n<b>Timeout:</b> 60 sec'],
            'gofile': ['Gofile is a free file sharing and storage platform. You can store and share your content without any limit.', "Send GoFile's API Key. Get it on https://gofile.io/myProfile, It will not be Accepted if the API Key is Invalid !!\n<b>Timeout:</b> 60 sec"],
            'streamtape': ['Streamtape is free Video Streaming & sharing Hoster', "Send StreamTape's Login and Key\n<b>Format:</b> <code>user_login:pass_key</code>\n<b>Timeout:</b> 60 sec"],
            'autorename_format': ['Auto Rename changes the filename automatically based on a predefined format.', 'Send your Auto Rename Format.\nAvailable Tags: <code>{title}</code>, <code>{season}</code>, <code>{episode}</code>, <code>{quality}</code>, <code>{codec}</code>, <code>{audio}</code>, <code>{sub}</code>, <code>{size}</code>, <code>{language}</code>\nExample: <code>{title} - S{season}E{episode} - {quality} [{size}]</code>\n<b>Timeout:</b> 60 sec'],
            }
fname_dict = {'rcc': 'RClone',
             'lprefix': 'Prefix',
             'lsuffix': 'Suffix',
             'lremname': 'Remname',
             'metadata': 'Metadata',
             'lattachment': 'Attachment',
             'mprefix': 'Prefix',
             'msuffix': 'Suffix',
             'mremname': 'Remname',
             'ldump': 'User Dump',
             'lcaption': 'Caption',
             'thumb': 'Thumbnail',
             'yt_opt': 'YT-DLP Options',
             'usess': 'User Session',
             'split_size': 'Leech Splits',
             'ddl_servers': 'DDL Servers',
             'user_tds': 'User Custom TDs',
             'gofile': 'GoFile',
             'streamtape': 'StreamTape',
             'autorename': 'Auto Rename',
             'autorename_format': 'Auto Rename Format',
             'custom_title': 'Custom Title',
             'lang_pref': 'Audio/Subtitle Order',
             }

async def get_user_settings(from_user, key=None, edit_type=None, edit_mode=None):
    user_id = from_user.id
    name = from_user.mention(style="html")
    buttons = ButtonMaker()
    thumbpath = f"Thumbnails/{user_id}.jpg"
    rclone_path = f'wcl/{user_id}.conf'
    user_dict = user_data.get(user_id, {})
    if key is None:
        buttons.ibutton("Universal Settings", f"userset {user_id} universal")
        buttons.ibutton("Mirror Settings", f"userset {user_id} mirror")
        buttons.ibutton("Leech Settings", f"userset {user_id} leech")
        if user_dict and any(key in user_dict for key in list(fname_dict.keys())):
            buttons.ibutton("Reset Setting", f"userset {user_id} reset_all")
        buttons.ibutton("Close", f"userset {user_id} close")

        text = BotTheme('USER_SETTING', NAME=name, ID=user_id, USERNAME=f'@{from_user.username}', LANG=Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A", DC=from_user.dc_id)
        
        button = buttons.build_menu(1)
    elif key == 'universal':
        ytopt = 'Not Exists' if (val:=user_dict.get('yt_opt', config_dict.get('YT_DLP_OPTIONS', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if ytopt != 'Not Exists' else ''} YT-DLP Options", f"userset {user_id} yt_opt")
        u_sess = 'Exists' if user_dict.get('usess', False) else 'Not Exists'
        buttons.ibutton(f"{'✅️' if u_sess != 'Not Exists' else ''} User Session", f"userset {user_id} usess")
        bot_pm = "Enabled" if user_dict.get('bot_pm', config_dict['BOT_PM']) else "Disabled"
        buttons.ibutton('Disable Bot PM' if bot_pm == 'Enabled' else 'Enable Bot PM', f"userset {user_id} bot_pm")
        if config_dict['BOT_PM']:
            bot_pm = "Force Enabled"
        mediainfo = "Enabled" if user_dict.get('mediainfo', config_dict['SHOW_MEDIAINFO']) else "Disabled"
        buttons.ibutton('Disable MediaInfo' if mediainfo == 'Enabled' else 'Enable MediaInfo', f"userset {user_id} mediainfo")
        if config_dict['SHOW_MEDIAINFO']:
            mediainfo = "Force Enabled"
        save_mode = "Save As Dump" if user_dict.get('save_mode') else "Save As BotPM"
        buttons.ibutton('Save As BotPM' if save_mode == 'Save As Dump' else 'Save As Dump', f"userset {user_id} save_mode")
        dailytl = config_dict['DAILY_TASK_LIMIT'] or "∞"
        dailytas = user_dict.get('dly_tasks')[1] if user_dict and user_dict.get('dly_tasks') and user_id != OWNER_ID and config_dict['DAILY_TASK_LIMIT'] else config_dict['DAILY_TASK_LIMIT'] or "️∞" if user_id != OWNER_ID else "∞"
        if user_dict.get('dly_tasks', False):
            t = str(datetime.now() - user_dict['dly_tasks'][0]).split(':')
            lastused = f"{t[0]}h {t[1]}m {t[2].split('.')[0]}s ago"
        else: lastused = "Bot Not Used yet.."

        _lp = user_dict.get('lang_pref') or {}
        buttons.ibutton(f"{'✅️' if _lp.get('audio') or _lp.get('sub') else ''} Audio & Subtitle", f"userset {user_id} lang_order")

        text = BotTheme('UNIVERSAL', NAME=name, YT=escape(trun(ytopt)), DT=f"{dailytas} / {dailytl}", LAST_USED=lastused, BOT_PM=bot_pm, MEDIAINFO=mediainfo, SAVE_MODE=save_mode, USESS=u_sess)
        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == 'lang_order':
        lp = user_dict.get('lang_pref') or {}
        text = "㊂ <b><u>Audio & Subtitle Order :</u></b>\n\n"
        text += f"➲ <b>Audio first :</b> <i>{LANG_NAMES.get(lp.get('audio'), 'Off')}</i>\n"
        text += f"➲ <b>Subtitle first :</b> <i>{LANG_NAMES.get(lp.get('sub'), 'Off')}</i>\n\n"
        text += ("➲ <b>Description :</b> <i>Choose the language that should be listed FIRST in your leeched videos. "
                 "It works only when the file has 2 or more audio (or subtitle) tracks and one of them is in that language; "
                 "a file with a single track is left untouched. If you also use Intro Sub, the intro subtitle stays first and your "
                 "language follows right after it. Applies to .mkv and .mp4.</i>")
        buttons.ibutton(f"{'✅️' if lp.get('audio') else ''} Audio", f"userset {user_id} lang_audio")
        buttons.ibutton(f"{'✅️' if lp.get('sub') else ''} Subtitle", f"userset {user_id} lang_sub")
        if lp.get('audio') or lp.get('sub'):
            buttons.ibutton('↻ Reset', f"userset {user_id} lang_reset")
        buttons.ibutton("Back", f"userset {user_id} back universal", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key in ('lang_audio', 'lang_sub'):
        kind = 'a' if key == 'lang_audio' else 's'
        cur = (user_dict.get('lang_pref') or {}).get('audio' if kind == 'a' else 'sub')
        text = f"㊂ <b><u>{'Audio' if kind == 'a' else 'Subtitle'} - Language First :</u></b>\n\n"
        text += f"➲ <b>Selected :</b> <i>{LANG_NAMES.get(cur, 'Off')}</i>\n\n"
        text += "<i>Pick the language that should come first. Tap it again or choose Off to keep the original order.</i>"
        buttons.ibutton('Off (keep original order)', f"userset {user_id} setlang {kind} off", "header")
        for code, lname in LANG_LIST:
            buttons.ibutton(f"{'✅ ' if cur == code else ''}{lname}", f"userset {user_id} setlang {kind} {code}")
        buttons.ibutton("Back", f"userset {user_id} back lang_order", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(3)
    elif key == 'mirror':
        buttons.ibutton("RClone", f"userset {user_id} rcc")
        rccmsg = "Exists" if await aiopath.exists(rclone_path) else "Not Exists"
        dailytlup = get_readable_file_size(config_dict['DAILY_MIRROR_LIMIT'] * 1024**3) if config_dict['DAILY_MIRROR_LIMIT'] else "∞"
        dailyup = get_readable_file_size(await getdailytasks(user_id, check_mirror=True)) if config_dict['DAILY_MIRROR_LIMIT'] and user_id != OWNER_ID else "️∞"
        buttons.ibutton("Mirror Prefix", f"userset {user_id} mprefix")
        mprefix = 'Not Exists' if (val:=user_dict.get('mprefix', config_dict.get('MIRROR_FILENAME_PREFIX', ''))) == '' else val

        buttons.ibutton("Mirror Suffix", f"userset {user_id} msuffix")
        msuffix = 'Not Exists' if (val:=user_dict.get('msuffix', config_dict.get('MIRROR_FILENAME_SUFFIX', ''))) == '' else val

        buttons.ibutton("Mirror Remname", f"userset {user_id} mremname")
        mremname = 'Not Exists' if (val:=user_dict.get('mremname', config_dict.get('MIRROR_FILENAME_REMNAME', ''))) == '' else val

        ddl_serv = len(val) if (val := user_dict.get('ddl_servers', False)) else 0
        buttons.ibutton("DDL Servers", f"userset {user_id} ddl_servers")

        tds_mode = "Enabled" if user_dict.get('td_mode', False) else "Disabled"
        if not config_dict['USER_TD_MODE']:
            tds_mode = "Force Disabled"

        user_tds = len(val) if (val := user_dict.get('user_tds', False)) else 0
        buttons.ibutton("User TDs", f"userset {user_id} user_tds")

        text = BotTheme('MIRROR', NAME=name, RCLONE=rccmsg, DDL_SERVER=ddl_serv, DM=f"{dailyup} / {dailytlup}", MREMNAME=escape(trun(mremname)), MPREFIX=escape(trun(mprefix)),
                MSUFFIX=escape(trun(msuffix)), TMODE=tds_mode, USERTD=user_tds)

        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == 'leech':
        if user_dict.get('as_doc', False) or 'as_doc' not in user_dict and config_dict['AS_DOCUMENT']:
            ltype = "DOCUMENT"
            buttons.ibutton("Send As Media", f"userset {user_id} doc")
        else:
            ltype = "MEDIA"
            buttons.ibutton("Send As Document", f"userset {user_id} doc")

        dailytlle = get_readable_file_size(config_dict['DAILY_LEECH_LIMIT'] * 1024**3) if config_dict['DAILY_LEECH_LIMIT'] else "️∞"
        dailyll = get_readable_file_size(await getdailytasks(user_id, check_leech=True)) if config_dict['DAILY_LEECH_LIMIT'] and user_id != OWNER_ID else "∞"

        thumbmsg = "Exists" if await aiopath.exists(thumbpath) else "Not Exists"
        buttons.ibutton(f"{'✅️' if thumbmsg == 'Exists' else ''} Thumbnail", f"userset {user_id} thumb")
        
        split_size = get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)' if user_dict.get('split_size', '') == '' else get_readable_file_size(user_dict['split_size'])
        equal_splits = 'Enabled' if user_dict.get('equal_splits', config_dict.get('EQUAL_SPLITS')) else 'Disabled'
        media_group = 'Enabled' if user_dict.get('media_group', config_dict.get('MEDIA_GROUP')) else 'Disabled'
        buttons.ibutton(f"{'✅️' if user_dict.get('split_size') else ''} Leech Splits", f"userset {user_id} split_size")

        autorename_status = "Enabled" if user_dict.get('autorename', False) else "Disabled"
        buttons.ibutton(f"{'✅️' if autorename_status == 'Enabled' else ''} Auto Rename", f"userset {user_id} autorename")

        lcaption = 'Not Exists' if (val:=user_dict.get('lcaption', config_dict.get('LEECH_FILENAME_CAPTION', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lcaption != 'Not Exists' else ''} Leech Caption", f"userset {user_id} lcaption")

        lprefix = 'Not Exists' if (val:=user_dict.get('lprefix', config_dict.get('LEECH_FILENAME_PREFIX', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lprefix != 'Not Exists' else ''} Leech Prefix", f"userset {user_id} lprefix")

        lsuffix = 'Not Exists' if (val:=user_dict.get('lsuffix', config_dict.get('LEECH_FILENAME_SUFFIX', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lsuffix != 'Not Exists' else ''} Leech Suffix", f"userset {user_id} lsuffix")

        lremname = 'Not Exists' if (val:=user_dict.get('lremname', config_dict.get('LEECH_FILENAME_REMNAME', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lremname != 'Not Exists' else ''} Leech Remname", f"userset {user_id} lremname")

        buttons.ibutton("Leech Dump", f"userset {user_id} ldump")
        ldump = 'Not Exists' if (val:=user_dict.get('ldump', '')) == '' else len(val)

        lattachment = 'Not Exists' if (val:=user_dict.get('lattachment', config_dict.get('ATTACHMENT', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lattachment != 'Not Exists' else ''} Leech Attachment", f"userset {user_id} lattachment")

        metadata = 'Not Exists' if (val:=user_dict.get('metadata', config_dict.get('METADATA', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if metadata != 'Not Exists' else ''} Leech Metadata", f"userset {user_id} metadata")

        intro_subtitle = user_dict.get('intro_subtitle', {})
        has_intro = intro_subtitle.get('text', '') != ''
        intro_enabled = intro_subtitle.get('enabled', True) if has_intro else False
        buttons.ibutton(f"{'✅️' if has_intro and intro_enabled else ''} Intro Sub", f"userset {user_id} intro_subtitle")

        text = BotTheme('LEECH', NAME=name, DL=f"{dailyll} / {dailytlle}",
                LTYPE=ltype, THUMB=thumbmsg, SPLIT_SIZE=split_size,
                EQUAL_SPLIT=equal_splits, MEDIA_GROUP=media_group,
                LCAPTION=escape(trun(lcaption)), LPREFIX=escape(trun(lprefix)),
                LSUFFIX=escape(trun(lsuffix)), LREMNAME=escape(trun(lremname)), 
                LDUMP=ldump, METADATA=escape(trun(metadata)),
                ATTACHMENT=escape(trun(lattachment)))

        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == 'metadata_menu':
        meta_str = user_dict.get('metadata', '')
        meta_dict = parse_metadata_str(meta_str)
        text = "㊂ <b><u>Leech Metadata Configurator :</u></b>\n\n"
        if meta_dict:
            for k, v in meta_dict.items():
                text += f"➲ <b>{k}:</b> <code>{escape(v)}</code>\n"
        else:
            text += "➲ <i>No custom metadata configured yet. Default values will be used.</i>"
        text += "\n<i>Click on any field below to modify its value manually:</i>"
        
        meta_keys = ["Title", "Author", "Artist", "Audio", "Subtitle", "Video", "Encoded By", "Custom Tag", "Comment", "Dubbed By", "Channel", "Website", "Copyright", "Publisher", "Encoder", "Source", "Studio", "Official Site"]
        for index, mkey in enumerate(meta_keys):
            has_val = "✅ " if mkey in meta_dict else "❌ "
            buttons.ibutton(f"{has_val}{mkey}", f"userset {user_id} md_edit {index}")
            
        buttons.ibutton("✨ Set All Metadata", f"userset {user_id} md_set_all", "header")
        buttons.ibutton("↻ Clear All", f"userset {user_id} md_clear_all", "header")
        buttons.ibutton("Back", f"userset {user_id} back leech", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == 'intro_subtitle':
        intro_settings = user_dict.get('intro_subtitle', {})
        intro_text = intro_settings.get('text', '')
        color = intro_settings.get('color', 'white')
        bg_color = intro_settings.get('bg_color', 'none')
        duration = intro_settings.get('duration', 5)
        font_size = intro_settings.get('font_size', 24)
        is_enabled = intro_settings.get('enabled', True)

        text_disp = 'Not Exists' if not intro_text else trun(intro_text, 50)
        text_line = f"➲ <b>Text :</b> <code>{escape(text_disp)}</code>\n"
        status_line = f"➲ <b>Status :</b> <i>{'Enabled' if is_enabled else 'Disabled'}</i>\n" if intro_text else ""
        text = "㊂ <b><u>Intro Subtitle Settings :</u></b>\n\n"
        text += text_line + status_line
        text += f"➲ <b>Color :</b> {COLOR_OPTIONS.get(color, color)}\n"
        text += f"➲ <b>Background :</b> {BG_COLOR_OPTIONS.get(bg_color, bg_color)}\n"
        text += f"➲ <b>Font Size :</b> {font_size}\n"
        text += f"➲ <b>Duration :</b> {duration} seconds\n\n"
        text += "➲ <b>Description :</b> <i>Adds a short, real subtitle track (not burned into the video) showing your own text for the first few seconds of each leeched video - set as the default track, so most players turn it on automatically. Color/Background/Font Size only take visible effect on .mkv files (.mp4 can only carry plain text, a hard limit of the format itself).</i>"

        if intro_text:
            buttons.ibutton('Disable' if is_enabled else 'Enable', f"userset {user_id} intro_toggle", "header")
        buttons.ibutton('Set Text', f"userset {user_id} intro_text")
        buttons.ibutton('Set Color', f"userset {user_id} intro_color")
        buttons.ibutton('Set Background', f"userset {user_id} intro_bgcolor")
        buttons.ibutton('Set Font Size', f"userset {user_id} intro_fontsize")
        buttons.ibutton('Set Duration', f"userset {user_id} intro_duration")
        if intro_text:
            buttons.ibutton('↻ Reset', f"userset {user_id} intro_reset")

        buttons.ibutton("Back", f"userset {user_id} back leech", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == 'autorename':
        auto_status = 'Enabled' if user_dict.get('autorename', False) else 'Disabled'
        format_str = user_dict.get('autorename_format', 'Not Exists')
        custom_title = user_dict.get('custom_title', 'Not Exists')
        
        text = f"㊂ <b><u>Auto Rename Settings :</u></b>\n\n"
        text += f"➲ <b>Status :</b> <i>{auto_status}</i>\n"
        text += f"➲ <b>Current Format :</b> <code>{escape(trun(format_str, 60))}</code>\n"
        text += f"➲ <b>Custom Title :</b> <code>{escape(trun(custom_title, 60))}</code>\n\n"
        text += f"➲ <b>Available Tags :</b> <code>{{title}}</code>, <code>{{season}}</code>, <code>{{episode}}</code>, <code>{{quality}}</code>, <code>{{codec}}</code>, <code>{{audio}}</code>, <code>{{sub}}</code>, <code>{{size}}</code>, <code>{{language}}</code>\n"
        text += f"➲ <b>Format Example :</b> <code>{{title}} - S{{season}}E{{episode}} - {{quality}} [{{size}}]</code>\n\n"
        text += f"➲ <b>Description :</b> <i>Set your Custom Format and Title for Auto Renaming files. Custom Title will override {{title}}.</i>"

        buttons.ibutton("Disable" if auto_status == 'Enabled' else "Enable", f"userset {user_id} toggle_autorename", "header")
        buttons.ibutton("Title", f"userset {user_id} custom_title")
        buttons.ibutton("Format", f"userset {user_id} autorename_format")

        buttons.ibutton("Back", f"userset {user_id} back leech", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == "ddl_servers":
        ddl_serv, serv_list = 0, []
        if (ddl_dict := user_dict.get('ddl_servers', False)):
            for serv, (enabled, _) in ddl_dict.items():
                if enabled:
                    serv_list.append(serv)
                    ddl_serv += 1
        text = f"㊂ <b><u>{fname_dict[key]} Settings :</u></b>\n\n" \
               f"➲ <b>Enabled DDL Server(s) :</b> <i>{ddl_serv}</i>\n\n" \
               f"➲ <b>Description :</b> <i>{desp_dict[key][0]}</i>"
        for btn in ['gofile', 'streamtape']:
            buttons.ibutton(f"{'✅️' if btn in serv_list else ''} {fname_dict[btn]}", f"userset {user_id} {btn}")
        buttons.ibutton("Back", f"userset {user_id} back mirror", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif edit_type:
        text = f"㊂ <b><u>{fname_dict[key]} Settings :</u></b>\n\n"
        if key == 'rcc':
            set_exist = await aiopath.exists(rclone_path)
            text += f"➲ <b>RClone.Conf File :</b> <i>{'' if set_exist else 'Not'} Exists</i>\n\n"
        elif key == 'thumb':
            set_exist = await aiopath.exists(thumbpath)
            text += f"➲ <b>Custom Thumbnail :</b> <i>{'' if set_exist else 'Not'} Exists</i>\n"
            auto_thumb_mode = 'Enabled' if user_dict.get('auto_thumb', False) else 'Disabled'
            text += f"➲ <b>Auto Thumbnail :</b> <i>{auto_thumb_mode}</i>\n\n"
            buttons.ibutton('Disable Auto Thumbnail' if auto_thumb_mode == 'Enabled' else 'Enable Auto Thumbnail', f"userset {user_id} auto_thumb", "header")
        elif key == 'yt_opt':
            set_exist = 'Not Exists' if (val:=user_dict.get('yt_opt', config_dict.get('YT_DLP_OPTIONS', ''))) == '' else val
            text += f"➲ <b>YT-DLP Options :</b> <code>{escape(trun(set_exist, 600))}</code>\n\n"
        elif key == 'usess':
            set_exist = 'Exists' if user_dict.get('usess') else 'Not Exists'
            text += f"➲ <b>{fname_dict[key]} :</b> <code>{set_exist}</code>\n➲ <b>Encryption :</b> {'🔐' if set_exist else '🔓'}\n\n"
        elif key == 'split_size':
            set_exist = get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)' if user_dict.get('split_size', '') == '' else get_readable_file_size(user_dict['split_size'])
            text += f"➲ <b>Leech Split Size :</b> <i>{set_exist}</i>\n\n"
            if user_dict.get('equal_splits', False) or ('equal_splits' not in user_dict and config_dict['EQUAL_SPLITS']):
                buttons.ibutton("Disable Equal Splits", f"userset {user_id} esplits", "header")
            else:
                buttons.ibutton("Enable Equal Splits", f"userset {user_id} esplits", "header")
            if user_dict.get('media_group', False) or ('media_group' not in user_dict and config_dict['MEDIA_GROUP']):
                buttons.ibutton("Disable Media Group", f"userset {user_id} mgroup", "header")
            else:
                buttons.ibutton("Enable Media Group", f"userset {user_id} mgroup", "header")
        elif key in ['lprefix', 'lremname', 'lsuffix', 'lcaption', 'ldump', 'metadata', 'lattachment']:
            set_exist = 'Not Exists' if (val:=user_dict.get(key, config_dict.get(f'LEECH_FILENAME_{key[1:].upper()}', ''))) == '' else val
            if set_exist != 'Not Exists' and key == "ldump":
                dump_items = [f"{index}. <b>{dump}</b> : <code>{ids}</code>" for index, (dump, ids) in enumerate(val.items(), start=1)]
                if len(dump_items) > 10:
                    set_exist = '\n\n' + '\n'.join(dump_items[:10]) + f"\n\n<i>... and {len(dump_items) - 10} more</i>"
                else:
                    set_exist = '\n\n' + '\n'.join(dump_items)
                text += f"➲ <b>Leech Filename {fname_dict[key]} :</b> {set_exist}\n\n"
            else:
                text += f"➲ <b>Leech Filename {fname_dict[key]} :</b> {escape(trun(set_exist, 600))}\n\n"
        elif key in ['autorename_format', 'custom_title']:
            set_exist = 'Not Exists' if (val:=user_dict.get(key, '')) == '' else val
            name_str = "Auto Rename Format" if key == 'autorename_format' else "Custom Title"
            text += f"➲ <b>{name_str} :</b> <code>{escape(trun(set_exist, 600))}</code>\n\n"
            if key == 'autorename_format':
                text += f"➲ <b>Available Tags :</b> <code>{{title}}</code>, <code>{{season}}</code>, <code>{{episode}}</code>, <code>{{quality}}</code>, <code>{{codec}}</code>, <code>{{audio}}</code>, <code>{{sub}}</code>, <code>{{size}}</code>, <code>{{language}}</code>\n"
                text += f"➲ <b>Format Example :</b> <code>{{title}} - S{{season}}E{{episode}} - {{quality}} [{{size}}]</code>\n"
                text += f"➲ <b>Description :</b> <i>{desp_dict['autorename_format'][1]}</i>"
            else:
                text += f"➲ <b>Description :</b> <i>Set a Custom Title to replace {{title}} in your Auto Rename format. E.g., Anime Name or Movie Name.</i>"
        elif key in ['mprefix', 'mremname', 'msuffix']:
            set_exist = 'Not Exists' if (val:=user_dict.get(key, config_dict.get(f'MIRROR_FILENAME_{key[1:].upper()}', ''))) == '' else val
            text += f"➲ <b>Mirror Filename {fname_dict[key]} :</b> {escape(trun(set_exist, 600))}\n\n"
        elif key in ['gofile', 'streamtape']:
            set_exist = 'Exists' if key in (ddl_dict:=user_dict.get('ddl_servers', {})) and ddl_dict[key][1] and ddl_dict[key][1] != '' else 'Not Exists'
            ddl_mode = 'Enabled' if key in (ddl_dict:=user_dict.get('ddl_servers', {})) and ddl_dict[key][0] else 'Disabled'
            text = f"➲ <b>Upload {fname_dict[key]} :</b> {ddl_mode}\n" \
                   f"➲ <b>{fname_dict[key]}'s API Key :</b> {set_exist}\n\n"
            buttons.ibutton('Disable DDL' if ddl_mode == 'Enabled' else 'Enable DDL', f"userset {user_id} s{key}", "header")
        elif key == 'user_tds':
            set_exist = len(val) if (val:=user_dict.get(key, False)) else 'Not Exists'
            tds_mode = "Enabled" if user_dict.get('td_mode', False) else "Disabled"
            buttons.ibutton('Disable UserTDs' if tds_mode == 'Enabled' else 'Enable UserTDs', f"userset {user_id} td_mode", "header")
            if not config_dict['USER_TD_MODE']:
                tds_mode = "Force Disabled"
            text += f"➲ <b>User TD Mode :</b> {tds_mode}\n"
            text += f"➲ <b>{fname_dict[key]} :</b> {set_exist}\n\n"
        else: 
            return
            
        if key not in ['autorename_format', 'custom_title']:
            text += f"➲ <b>Description :</b> <i>{desp_dict[key][0]}</i>"
            
        if not edit_mode:
            buttons.ibutton(f"Change {fname_dict[key]}" if set_exist and set_exist != 'Not Exists' and (set_exist != get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)') else f"Set {fname_dict[key]}", f"userset {user_id} {key} edit")
        else:
            if key not in ['autorename_format', 'custom_title']:
                text += '\n\n' + desp_dict[key][1]
            else:
                text += '\n\n' + "Send your new value. \n<b>Timeout:</b> 60 sec"
            buttons.ibutton("Stop Change", f"userset {user_id} {key}")
            
        if set_exist and set_exist != 'Not Exists' and (set_exist != get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)'):
            if key == 'thumb':
                buttons.ibutton("View Thumbnail", f"userset {user_id} vthumb", "header")
            elif key == 'user_tds':
                buttons.ibutton('Show UserTDs', f"userset {user_id} show_tds", "header")
            buttons.ibutton("↻ Delete", f"userset {user_id} d{key}")
            
        if key in ['autorename_format', 'custom_title']:
            buttons.ibutton("Back", f"userset {user_id} back autorename", "footer")
        else:
            buttons.ibutton("Back", f"userset {user_id} back {edit_type}", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    return text, button


async def update_user_settings(query, key=None, edit_type=None, edit_mode=None, msg=None, sdirect=False):
    msg, button = await get_user_settings(msg.from_user if sdirect else query.from_user, key, edit_type, edit_mode)
    await editMessage(query if sdirect else query.message, msg, button)


async def user_settings(client, message):
    if len(message.command) > 1 and (message.command[1] == '-s' or message.command[1] == '-set'):
        set_arg = message.command[2].strip() if len(message.command) > 2 else None
        msg = await sendMessage(message, '<i>Fetching Settings...</i>', photo='IMAGES')
        if set_arg and (reply_to := message.reply_to_message):
            if message.from_user.id != reply_to.from_user.id:
                return await editMessage(msg, '<i>Reply to Your Own Message for Setting via Args Directly</i>')
            if set_arg in ['lprefix', 'lsuffix', 'lremname', 'lcaption', 'ldump', 'yt_opt', 'metadata', 'lattachment', 'autorename_format', 'custom_title'] and reply_to.text:
                return await set_custom(client, reply_to, msg, set_arg, True)
            elif set_arg == 'thumb' and reply_to.media:
                return await set_thumb(client, reply_to, msg, set_arg, True)
        await editMessage(msg, '''㊂ <b><u>Available Flags :</u></b>
>> Reply to the Value with appropriate arg respectively to set directly without opening USet.

➲ <b>Custom Thumbnail :</b>
    /cmd -s thumb
➲ <b>Leech Filename Prefix :</b>
    /cmd -s lprefix
➲ <b>Leech Filename Suffix :</b>
    /cmd -s lsuffix
➲ <b>Leech Filename Remname :</b>
    /cmd -s lremname
➲ <b>Leech Filename Caption :</b>
    /cmd -s lcaption
➲ <b>Leech Filename Metadata :</b>
    /cmd -s metadata
➲ <b>Leech Filename Attachment :</b>
    /cmd -s lattachment
➲ <b>Auto Rename Format :</b>
    /cmd -s autorename_format
➲ <b>Auto Rename Title :</b>
    /cmd -s custom_title
➲ <b>YT-DLP Options :</b>
    /cmd -s yt_opt
➲ <b>Leech User Dump :</b>
    /cmd -s ldump''')
    else:
        from_user = message.from_user
        handler_dict[from_user.id] = False
        msg, button = await get_user_settings(from_user)
        await sendMessage(message, msg, button, 'IMAGES')


async def set_custom(client, message, pre_event, key, direct=False):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    return_key = 'leech'
    n_key = key
    user_dict = user_data.get(user_id, {})
    if key in ['gofile', 'streamtape']:
        ddl_dict = user_dict.get('ddl_servers', {})
        mode, api = ddl_dict.get(key, [False, ""])
        if key == "gofile" and not await Gofile.is_goapi(value):
            value = ""
        ddl_dict[key] = [mode, value]
        value = ddl_dict
        n_key = 'ddl_servers'
        return_key = 'ddl_servers'
    elif key == 'user_tds':
        user_tds = user_dict.get(key, {})
        for td_item in value.split('\n'):
            if td_item == '':
                continue
            split_ck = td_item.split()
            td_details = td_item.rsplit(maxsplit=(2 if split_ck[-1].startswith('http') and not is_gdrive_link(split_ck[-1]) else 1 if len(split_ck[-1]) > 15 else 0))
            if td_details[0] in list(categories_dict.keys()):
                continue
            for title in list(user_tds.keys()):
                if td_details[0].casefold() == title.casefold():
                    del user_tds[title]
            if len(td_details) > 1:
                if is_gdrive_link(td_details[1].strip()):
                    td_details[1] = GoogleDriveHelper.getIdFromUrl(td_details[1])
                if await sync_to_async(gd_call, 'getFolderData', td_details[1]):
                    user_tds[td_details[0]] = {'drive_id': td_details[1],'index_link': td_details[2].rstrip('/') if len(td_details) > 2 else ''}
        value = user_tds
        return_key = 'mirror'
    elif key == 'ldump':
        ldumps = user_dict.get(key, {})
        for dump_item in value.split('\n'):
            if dump_item == '':
                continue
            dump_info = dump_item.rsplit(maxsplit=(1 if dump_item.split()[-1].startswith(('-100', '@')) else 0))
            if dump_info[0] in list(ldumps.keys()):
                continue
            for title in list(ldumps.keys()):
                if dump_info[0].casefold() == title.casefold():
                    del ldumps[title]
            if len(dump_info) > 1 and (dump_chat := await chat_info(dump_info[1], f'dump set in settings by user {user_id}')):
                ldumps[dump_info[0]] = dump_chat.id
        value = ldumps
    elif key in ['yt_opt', 'usess']:
        if key == 'usess':
            password = Fernet.generate_key()
            try:
                await deleteMessage(await (await sendCustomMsg(message.from_user.id, f"<u><b>Decryption Key:</b></u> \n┃\n┃ <code>{password.decode()}</code>\n┃\n┖ <b>Note:</b> <i>Keep this Key Securely, this is not Stored in Bot and Access Key to use your Session...</i>")).pin(both_sides=True))
                encrypt_sess = Fernet(password).encrypt(value.encode())
                value = encrypt_sess.decode()
            except Exception:
                value = ""
        return_key = 'universal'
    elif key in ['autorename_format', 'custom_title']:
        return_key = 'autorename'
        if key == 'autorename_format' and (invalid_tags := validate_autorename_format(value)):
            # A format with an invalid/typo'd tag (e.g. {qualilty}) is not
            # allowed to save, because it later makes Auto Rename silently
            # fail and the user has no idea why it's not working.
            bad = ", ".join(f"{{{t}}}" for t in sorted(invalid_tags))
            handler_dict[user_id] = False
            await deleteMessage(message)
            err_msg = await sendMessage(
                message,
                f"<b>⚠️ Invalid Tag(s) In Format:</b> <code>{escape(bad)}</code>\n\n"
                f"<b>Available Tags :</b> <code>{{title}}</code>, <code>{{season}}</code>, <code>{{episode}}</code>, "
                f"<code>{{quality}}</code>, <code>{{codec}}</code>, <code>{{audio}}</code>, <code>{{sub}}</code>, "
                f"<code>{{size}}</code>, <code>{{language}}</code>\n\n"
                f"<i>Format was not saved. Please try again.</i>"
            )
            await sleep(6)
            await deleteMessage(err_msg)
            await update_user_settings(pre_event, key, return_key, msg=message, sdirect=direct)
            return

    update_user_ldata(user_id, n_key, value)
    await deleteMessage(message)
    await update_user_settings(pre_event, key, return_key, msg=message, sdirect=direct)
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_metadata_key(client, message, pre_event, mkey):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text.strip() if message.text else ""
    user_dict = user_data.get(user_id, {})
    meta_str = user_dict.get('metadata', '')
    meta_dict = parse_metadata_str(meta_str)
    if value:
        meta_dict[mkey] = value
    else:
        meta_dict.pop(mkey, None)
    new_meta_str = '|'.join([f"{k}:{v}" for k, v in meta_dict.items() if v])
    update_user_ldata(user_id, 'metadata', new_meta_str)
    await deleteMessage(message)
    await update_user_settings(pre_event, 'metadata_menu')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_all_metadata(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text.strip() if message.text else ""
    if value:
        meta_keys = ["Title", "Author", "Artist", "Audio", "Subtitle", "Video", "Encoded By", "Custom Tag", "Comment", "Dubbed By", "Channel", "Website", "Copyright", "Publisher", "Encoder", "Source", "Studio", "Official Site"]
        new_meta_str = '|'.join([f"{k}:{value}" for k in meta_keys])
        update_user_ldata(user_id, 'metadata', new_meta_str)
    else:
        update_user_ldata(user_id, 'metadata', '')
    await deleteMessage(message)
    await update_user_settings(pre_event, 'metadata_menu')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_intro_text(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    success, text, error = validate_and_escape_subtitle_text(message.text or "")
    if not success:
        err_msg = await sendMessage(message, f"⚠️ {error}")
        await deleteMessage(message)
        await sleep(4)
        await deleteMessage(err_msg)
        await update_user_settings(pre_event, 'intro_subtitle')
        return

    intro_settings = user_data.get(user_id, {}).get('intro_subtitle', {})
    intro_settings['text'] = text
    intro_settings.setdefault('color', 'white')
    intro_settings.setdefault('bg_color', 'none')
    intro_settings.setdefault('font_size', 24)
    intro_settings.setdefault('duration', 5)
    intro_settings.setdefault('enabled', True)
    update_user_ldata(user_id, 'intro_subtitle', intro_settings)
    await deleteMessage(message)
    await update_user_settings(pre_event, 'intro_subtitle')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_intro_duration(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = (message.text or "").strip()
    if not value.isdigit() or not (1 <= int(value) <= 30):
        err_msg = await sendMessage(message, "⚠️ Duration must be a number between 1-30 seconds!")
        await deleteMessage(message)
        await sleep(4)
        await deleteMessage(err_msg)
        await update_user_settings(pre_event, 'intro_subtitle')
        return

    intro_settings = user_data.get(user_id, {}).get('intro_subtitle', {})
    intro_settings['duration'] = int(value)
    update_user_ldata(user_id, 'intro_subtitle', intro_settings)
    await deleteMessage(message)
    await update_user_settings(pre_event, 'intro_subtitle')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_intro_fontsize(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = (message.text or "").strip()
    if not value.isdigit() or not (12 <= int(value) <= 72):
        err_msg = await sendMessage(message, "⚠️ Font Size must be a number between 12-72!")
        await deleteMessage(message)
        await sleep(4)
        await deleteMessage(err_msg)
        await update_user_settings(pre_event, 'intro_subtitle')
        return

    intro_settings = user_data.get(user_id, {}).get('intro_subtitle', {})
    intro_settings['font_size'] = int(value)
    update_user_ldata(user_id, 'intro_subtitle', intro_settings)
    await deleteMessage(message)
    await update_user_settings(pre_event, 'intro_subtitle')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_thumb(client, message, pre_event, key, direct=False):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    path = "Thumbnails/"
    if not await aiopath.isdir(path):
        await mkdir(path)
    photo_dir = await message.download()
    des_dir = ospath.join(path, f'{user_id}.jpg')
    await sync_to_async(save_jpeg, photo_dir, des_dir)
    await aioremove(photo_dir)
    update_user_ldata(user_id, 'thumb', des_dir)
    await deleteMessage(message)
    await update_user_settings(pre_event, key, 'leech', msg=message, sdirect=direct)
    if DATABASE_URL:
        await DbManger().update_user_doc(user_id, 'thumb', des_dir)


async def add_rclone(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    path = f'{getcwd()}/wcl/'
    if not await aiopath.isdir(path):
        await mkdir(path)
    des_dir = ospath.join(path, f'{user_id}.conf')
    await message.download(file_name=des_dir)
    update_user_ldata(user_id, 'rclone', f'wcl/{user_id}.conf')
    await deleteMessage(message)
    await update_user_settings(pre_event, 'rcc', 'mirror')
    if DATABASE_URL:
        await DbManger().update_user_doc(user_id, 'rclone', des_dir)


async def leech_split_size(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    sdic = ['b', 'kb', 'mb', 'gb']
    value = message.text.strip()
    slice = -2 if value[-2].lower() in ['k', 'm', 'g'] else -1
    out = value[slice:].strip().lower()
    if out in sdic:
        value = min((float(value[:slice].strip()) * 1024**sdic.index(out)), MAX_SPLIT_SIZE)
    update_user_ldata(user_id, 'split_size', int(round(value)))
    await deleteMessage(message)
    await update_user_settings(pre_event, 'split_size', 'leech')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        if user is None:
            return False
        return bool(user.id == user_id and event.chat.id == query.message.chat.id and mtype)
        
    handler = client.add_handler(MessageHandler(
        pfunc, filters=create(event_filter)), group=-1)
    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
    client.remove_handler(*handler)


@new_thread
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    message = query.message
    data = query.data.split()
    thumb_path = f'Thumbnails/{user_id}.jpg'
    rclone_path = f'wcl/{user_id}.conf'
    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] in ['universal', 'mirror', 'leech']:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "doc":
        update_user_ldata(user_id, 'as_doc', not user_dict.get('as_doc', False))
        await query.answer()
        await update_user_settings(query, 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'vthumb':
        handler_dict[user_id] = False
        await query.answer()
        buttons = ButtonMaker()
        buttons.ibutton('Cʟᴏsᴇ', f'kpsmlx {user_id} close')
        await sendMessage(message, from_user.mention, buttons.build_menu(1), thumb_path)
        await update_user_settings(query, 'thumb', 'leech')
    elif data[2] == 'show_tds':
        handler_dict[user_id] = False
        user_tds = user_dict.get('user_tds', {})
        msg = f'➲ <b><u>User TD(s) Details</u></b>\n\n<b>Total UserTD(s) :</b> {len(user_tds)}\n\n'
        for index_no, (drive_name, drive_dict) in enumerate(user_tds.items(), start=1):
            msg += f'{index_no}: <b>Name:</b> <code>{drive_name}</code>\n'
            msg += f"  <b>Drive ID:</b> <code>{drive_dict['drive_id']}</code>\n"
            msg += f"  <b>Index Link:</b> <code>{ind_url if (ind_url := drive_dict['index_link']) else 'Not Provided'}</code>\n\n"
        try:
            await sendCustomMsg(user_id, msg)
            await query.answer('User TDs Successfully Send in your PM', show_alert=True)
        except Exception:
            await query.answer('Start the Bot in PM (Private) and Try Again', show_alert=True)
        await update_user_settings(query, 'user_tds', 'mirror')
    elif data[2] == "dthumb":
        handler_dict[user_id] = False
        if await aiopath.exists(thumb_path):
            await query.answer()
            await aioremove(thumb_path)
            update_user_ldata(user_id, 'thumb', '')
            await update_user_settings(query, 'thumb', 'leech')
            if DATABASE_URL:
                await DbManger().update_user_doc(user_id, 'thumb')
        else:
            await query.answer("Old Settings", show_alert=True)
            await update_user_settings(query, 'leech')
    elif data[2] == 'thumb':
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'leech', edit_mode)
        if not edit_mode: return
        pfunc = partial(set_thumb, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], 'leech')
        await event_handler(client, query, pfunc, rfunc, True)
    elif data[2] in ['yt_opt', 'usess']:
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'universal', edit_mode)
        if not edit_mode: return
        pfunc = partial(set_custom, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], 'universal')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] in ['dyt_opt', 'dusess']:
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, data[2][1:], '')
        await update_user_settings(query, data[2][1:], 'universal')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'autorename':
        handler_dict[user_id] = False
        await query.answer()
        await update_user_settings(query, 'autorename')
    elif data[2] == 'toggle_autorename':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'autorename', not user_dict.get('autorename', False))
        await update_user_settings(query, 'autorename')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ['bot_pm', 'mediainfo', 'save_mode', 'td_mode']:
        handler_dict[user_id] = False
        if data[2] == 'save_mode' and not user_dict.get(data[2], False) and not user_dict.get('ldump'):
            return await query.answer("Set User Dump first to Change Save Msg Mode !", show_alert=True)
        elif data[2] == 'bot_pm' and (config_dict['BOT_PM'] or config_dict['SAFE_MODE']) or data[2] == 'mediainfo' and config_dict['SHOW_MEDIAINFO'] or data[2] == 'td_mode' and not config_dict['USER_TD_MODE']:
            mode_up = "Disabled" if data[2] == 'td_mode' else "Enabled"
            return await query.answer(f"Force {mode_up}! Can't Alter Settings", show_alert=True)
        if data[2] == 'td_mode' and not user_dict.get('user_tds', False):
            return await query.answer("Set UserTD first to Enable User TD Mode !", show_alert=True)
        await query.answer()
        update_user_ldata(user_id, data[2], not user_dict.get(data[2], False))
        if data[2] in ['td_mode']:
            await update_user_settings(query, 'user_tds', 'mirror')
        else:
            await update_user_settings(query, 'universal')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'split_size':
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'leech', edit_mode)
        if not edit_mode: return
        pfunc = partial(leech_split_size, pre_event=query)
        rfunc = partial(update_user_settings, query, data[2], 'leech')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'dsplit_size':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'split_size', '')
        await update_user_settings(query, 'split_size', 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'esplits':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'equal_splits', not user_dict.get('equal_splits', False))
        await update_user_settings(query, 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'mgroup':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'media_group', not user_dict.get('media_group', False))
        await update_user_settings(query, 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            await DbManger().update_user_data(user_id)
    elif data[2] == 'auto_thumb':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'auto_thumb', not user_dict.get('auto_thumb', False))
        await update_user_settings(query, 'thumb', 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ['sgofile', 'sstreamtape', 'dgofile', 'dstreamtape']:
        handler_dict[user_id] = False
        ddl_dict = user_dict.get('ddl_servers', {})
        key = data[2][1:]
        mode, api = ddl_dict.get(key, [False, ""])
        if data[2][0] == 's':
            if not mode and api == '':
                return await query.answer('Set API to Enable DDL Server', show_alert=True)
            ddl_dict[key] = [not mode, api]
        elif data[2][0] == 'd':
            ddl_dict[key] = [mode, '']
        await query.answer()
        update_user_ldata(user_id, 'ddl_servers', ddl_dict)
        await update_user_settings(query, key, 'ddl_servers')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'rcc':
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'mirror', edit_mode)
        if not edit_mode: return
        pfunc = partial(add_rclone, pre_event=query)
        rfunc = partial(update_user_settings, query, data[2], 'mirror')
        await event_handler(client, query, pfunc, rfunc, document=True)
    elif data[2] == 'drcc':
        handler_dict[user_id] = False
        if await aiopath.exists(rclone_path):
            await query.answer()
            await aioremove(rclone_path)
            update_user_ldata(user_id, 'rclone', '')
            await update_user_settings(query, 'rcc', 'mirror')
            if DATABASE_URL:
                await DbManger().update_user_doc(user_id, 'rclone')
        else:
            await query.answer("Old Settings", show_alert=True)
            await update_user_settings(query)
    elif data[2] in ['ddl_servers', 'user_tds', 'gofile', 'streamtape']:
        handler_dict[user_id] = False
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'mirror' if data[2] in ['ddl_servers', 'user_tds'] else 'ddl_servers', edit_mode)
        if not edit_mode: return
        pfunc = partial(set_custom, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], 'mirror' if data[2] in ['ddl_servers', 'user_tds'] else "ddl_servers")
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'metadata':
        await query.answer()
        await update_user_settings(query, 'metadata_menu')
    elif data[2] == 'md_edit':
        await query.answer()
        idx = int(data[3])
        meta_keys = ["Title", "Author", "Artist", "Audio", "Subtitle", "Video", "Encoded By", "Custom Tag", "Comment", "Dubbed By", "Channel", "Website", "Copyright", "Publisher", "Encoder", "Source", "Studio", "Official Site"]
        mkey = meta_keys[idx]
        text = f"⚙️ <b><u>Set Leech Metadata: {mkey}</u></b>\n\nSend the value you want to assign to <b>{mkey}</b>.\n\n<b>Timeout:</b> 60 sec"
        buttons = ButtonMaker()
        buttons.ibutton("Cancel / Back", f"userset {user_id} metadata")
        await editMessage(message, text, buttons.build_menu(1))
        pfunc = partial(set_metadata_key, pre_event=query, mkey=mkey)
        rfunc = partial(update_user_settings, query, 'metadata_menu')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'md_set_all':
        await query.answer()
        text = "✨ <b><u>Set All Metadata Fields</u></b>\n\nSend a single value to apply to <b>ALL</b> fields at once (e.g., `@Rare_Bots_Hub`).\n\n<b>Timeout:</b> 60 sec"
        buttons = ButtonMaker()
        buttons.ibutton("Cancel / Back", f"userset {user_id} metadata")
        await editMessage(message, text, buttons.build_menu(1))
        pfunc = partial(set_all_metadata, pre_event=query)
        rfunc = partial(update_user_settings, query, 'metadata_menu')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'md_clear_all':
        update_user_ldata(user_id, 'metadata', '')
        await query.answer("Cleared all custom metadata values!", show_alert=True)
        await update_user_settings(query, 'metadata_menu')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'intro_subtitle':
        await query.answer()
        await update_user_settings(query, 'intro_subtitle')
    elif data[2] == 'intro_text':
        await query.answer()
        text = ("⚙️ <b><u>Set Intro Subtitle Text</u></b>\n\n"
                "<i>This text appears at the very start of your leeched videos, as a real subtitle track set as default - most players turn it on automatically.</i>\n\n"
                "<b>Send Intro Text</b>\n<b>Example:</b> <code>Join @MyChannel</code>\n<b>Max Length:</b> 200 characters\n<b>Timeout:</b> 60 sec")
        buttons = ButtonMaker()
        buttons.ibutton("Cancel / Back", f"userset {user_id} intro_subtitle")
        await editMessage(message, text, buttons.build_menu(1))
        pfunc = partial(set_intro_text, pre_event=query)
        rfunc = partial(update_user_settings, query, 'intro_subtitle')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'intro_duration':
        await query.answer()
        text = ("⚙️ <b><u>Set Intro Subtitle Duration</u></b>\n\n"
                "<i>How long (in seconds) the intro subtitle stays visible from the start of the video.</i>\n\n"
                "<b>Send Duration in seconds</b>\n<b>Example:</b> <code>10</code>\n<b>Range:</b> 1-30\n<b>Timeout:</b> 60 sec")
        buttons = ButtonMaker()
        buttons.ibutton("Cancel / Back", f"userset {user_id} intro_subtitle")
        await editMessage(message, text, buttons.build_menu(1))
        pfunc = partial(set_intro_duration, pre_event=query)
        rfunc = partial(update_user_settings, query, 'intro_subtitle')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'intro_fontsize':
        await query.answer()
        text = ("⚙️ <b><u>Set Intro Subtitle Font Size</u></b>\n\n"
                "<i>Only takes visible effect on .mkv files - .mp4 can't carry font-size styling (a hard limit of the format itself).</i>\n\n"
                "<b>Send Font Size</b>\n<b>Example:</b> <code>28</code>\n<b>Range:</b> 12-72\n<b>Timeout:</b> 60 sec")
        buttons = ButtonMaker()
        buttons.ibutton("Cancel / Back", f"userset {user_id} intro_subtitle")
        await editMessage(message, text, buttons.build_menu(1))
        pfunc = partial(set_intro_fontsize, pre_event=query)
        rfunc = partial(update_user_settings, query, 'intro_subtitle')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'intro_color':
        await query.answer()
        buttons = ButtonMaker()
        for color_key, color_name in COLOR_OPTIONS.items():
            buttons.ibutton(color_name, f"userset {user_id} intro_setcolor^{color_key}")
        buttons.ibutton("Back", f"userset {user_id} intro_subtitle", "footer")
        await editMessage(message, "<b>Select Text Color:</b>", buttons.build_menu(2))
    elif data[2].startswith('intro_setcolor'):
        color = data[2].split("^")[1]
        intro_settings = user_dict.get('intro_subtitle', {})
        intro_settings['color'] = color
        update_user_ldata(user_id, 'intro_subtitle', intro_settings)
        await query.answer(f"Color set to {color}!")
        await update_user_settings(query, 'intro_subtitle')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'intro_bgcolor':
        await query.answer()
        buttons = ButtonMaker()
        for color_key, color_name in BG_COLOR_OPTIONS.items():
            buttons.ibutton(color_name, f"userset {user_id} intro_setbgcolor^{color_key}")
        buttons.ibutton("Back", f"userset {user_id} intro_subtitle", "footer")
        await editMessage(message, "<b>Select Background Color:</b>\n<i>Only visible on .mkv files.</i>", buttons.build_menu(2))
    elif data[2].startswith('intro_setbgcolor'):
        bg_color = data[2].split("^")[1]
        intro_settings = user_dict.get('intro_subtitle', {})
        intro_settings['bg_color'] = bg_color
        update_user_ldata(user_id, 'intro_subtitle', intro_settings)
        await query.answer(f"Background set to {bg_color}!")
        await update_user_settings(query, 'intro_subtitle')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'intro_toggle':
        intro_settings = user_dict.get('intro_subtitle', {})
        current = intro_settings.get('enabled', True)
        intro_settings['enabled'] = not current
        update_user_ldata(user_id, 'intro_subtitle', intro_settings)
        await query.answer(f"Intro Subtitle {'enabled' if not current else 'disabled'}!")
        await update_user_settings(query, 'intro_subtitle')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'intro_reset':
        update_user_ldata(user_id, 'intro_subtitle', {})
        await query.answer("Intro Subtitle settings reset!", show_alert=True)
        await update_user_settings(query, 'intro_subtitle')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ['lprefix', 'lsuffix', 'lremname', 'lcaption', 'ldump', 'mprefix', 'msuffix', 'mremname', 'lattachment', 'autorename_format', 'custom_title']:
        handler_dict[user_id] = False
        await query.answer()
        edit_mode = len(data) == 4
        
        if data[2] in ['autorename_format', 'custom_title']:
            return_key = 'autorename'
        elif data[2][0] == 'l':
            return_key = 'leech'
        else:
            return_key = 'mirror'
            
        await update_user_settings(query, data[2], return_key, edit_mode)
        if not edit_mode: return
        pfunc = partial(set_custom, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], return_key)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] in ['dlprefix', 'dlsuffix', 'dlremname', 'dlcaption', 'dldump', 'dmetadata', 'dlattachment', 'dautorename_format', 'dcustom_title']:
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, data[2][1:], {} if data[2] == 'dldump' else '')
        
        if data[2] in ['dautorename_format', 'dcustom_title']:
            if data[2] == 'dautorename_format':
                update_user_ldata(user_id, 'autorename', False)
            await update_user_settings(query, 'autorename')
        else:
            await update_user_settings(query, 'leech')
            
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ['dmprefix', 'dmsuffix', 'dmremname', 'duser_tds']:
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, data[2][1:], {} if data[2] == 'duser_tds' else '')
        if data[2] == 'duser_tds':
            update_user_ldata(user_id, 'td_mode', False)
        await update_user_settings(query, data[2][1:], 'mirror')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ('lang_order', 'lang_audio', 'lang_sub'):
        handler_dict[user_id] = False
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == 'setlang' and len(data) >= 5:
        kind, code = data[3], data[4]
        field = 'audio' if kind == 'a' else 'sub'
        lp = dict(user_dict.get('lang_pref') or {})
        if code == 'off' or lp.get(field) == code:
            lp.pop(field, None)
            await query.answer(f"{field.capitalize()} order: Off")
        elif code in LANG_NAMES:
            lp[field] = code
            await query.answer(f"{LANG_NAMES[code]} will be first in {field}")
        else:
            return await query.answer("Unknown language", show_alert=True)
        update_user_ldata(user_id, 'lang_pref', lp)
        await update_user_settings(query, 'lang_audio' if kind == 'a' else 'lang_sub')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'lang_reset':
        update_user_ldata(user_id, 'lang_pref', {})
        await query.answer("Audio & Subtitle order reset")
        await update_user_settings(query, 'lang_order')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'back':
        handler_dict[user_id] = False
        await query.answer()
        setting = data[3] if len(data) == 4 else None
        await update_user_settings(query, setting)
    elif data[2] == 'reset_all':
        handler_dict[user_id] = False
        await query.answer()
        buttons = ButtonMaker()
        buttons.ibutton('Yes', f"userset {user_id} reset_now y")
        buttons.ibutton('No', f"userset {user_id} reset_now n")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        await editMessage(message, 'Do you want to Reset Settings ?', buttons.build_menu(2))
    elif data[2] == 'reset_now':
        handler_dict[user_id] = False
        if data[3] == 'n':
            return await update_user_settings(query)
        if await aiopath.exists(thumb_path):
            await aioremove(thumb_path)
        if await aiopath.exists(rclone_path):
            await aioremove(rclone_path)
        await query.answer()
        update_user_ldata(user_id, None, None)
        await update_user_settings(query)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            await DbManger().update_user_doc(user_id, 'thumb')
            await DbManger().update_user_doc(user_id, 'rclone')
    elif data[2] == 'user_del':
        user_id = int(data[3])
        await query.answer()
        thumb_path = f'Thumbnails/{user_id}.jpg'
        rclone_path = f'wcl/{user_id}.conf'
        if await aiopath.exists(thumb_path):
            await aioremove(thumb_path)
        if await aiopath.exists(rclone_path):
            await aioremove(rclone_path)
        update_user_ldata(user_id, None, None)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            await DbManger().update_user_doc(user_id, 'thumb')
            await DbManger().update_user_doc(user_id, 'rclone')
        await editMessage(message, f'Data Reset for {user_id}')
    else:
        handler_dict[user_id] = False
        await query.answer()
        await deleteMessage(message.reply_to_message)
        await deleteMessage(message)
        
async def send_users_settings(client, message):
    text = message.text.split(maxsplit=1)
    userid = text[1] if len(text) > 1 else None
    if userid and not userid.isdigit():
        userid = None
    elif (reply_to := message.reply_to_message) and reply_to.from_user and not reply_to.from_user.is_bot:
        userid = reply_to.from_user.id
    if not userid:
        msg = f'<u><b>Total Users / Chats Data Saved :</b> {len(user_data)}</u>'
        buttons = ButtonMaker()
        buttons.ibutton("Close", f"userset {message.from_user.id} close")
        button = buttons.build_menu(1)
        for user, data in user_data.items():
            msg += f'\n\n<code>{user}</code>:'
            if data:
                for key, value in data.items():
                    if key in ['token', 'time', 'ddl_servers', 'usess']:
                        continue
                    msg += f'\n<b>{key}</b>: <code>{escape(str(value))}</code>'
            else:
                msg += "\nUser's Data is Empty!"
        if len(msg.encode()) > 4000:
            with BytesIO(str.encode(msg)) as ofile:
                ofile.name = 'users_settings.txt'
                await sendFile(message, ofile)
        else:
            await sendMessage(message, msg, button)
    elif int(userid) in user_data:
        msg = f'{(await user_info(userid)).mention(style="html")} ( <code>{userid}</code> ):'
        if data := user_data[int(userid)]:
            buttons = ButtonMaker()
            buttons.ibutton("Delete Data", f"userset {message.from_user.id} user_del {userid}")
            buttons.ibutton("Close", f"userset {message.from_user.id} close")
            button = buttons.build_menu(1)
            for key, value in data.items():
                if key in ['token', 'time', 'ddl_servers', 'usess']:
                    continue
                msg += f'\n<b>{key}</b>: <code>{escape(str(value))}</code>'
        else:
            msg += '\nThis User has not Saved anything.'
            button = None
        await sendMessage(message, msg, button)
    else:
        await sendMessage(message, f'{userid} have not saved anything..')

async def set_thumb_cmd(client, message):
    user_id = message.from_user.id
    reply = message.reply_to_message
    
    if not reply or not reply.photo:
        return await sendMessage(message, f"Reply to a photo with /{BotCommands.SetThumbCommand} to set it as your custom thumbnail.")
    
    path = "Thumbnails/"
    if not await aiopath.isdir(path):
        await mkdir(path)
    
    photo_dir = await client.download_media(reply)
    des_dir = ospath.join(path, f'{user_id}.jpg')
    
    await sync_to_async(save_jpeg, photo_dir, des_dir)
    await aioremove(photo_dir)
    
    update_user_ldata(user_id, 'thumb', des_dir)
    
    try:
        await reply.delete()
    except Exception as e:
        LOGGER.error(f"Failed to delete thumbnail photo: {e}")
    
    await sendMessage(message, "✅ Custom Thumbnail saved successfully!")
    
    if DATABASE_URL:
        await DbManger().update_user_doc(user_id, 'thumb', des_dir)


bot.add_handler(MessageHandler(send_users_settings, filters=command(
    BotCommands.UsersCommand) & CustomFilters.sudo))
bot.add_handler(MessageHandler(user_settings, filters=command(
    BotCommands.UserSetCommand) & CustomFilters.authorized_uset))
bot.add_handler(CallbackQueryHandler(edit_user_settings, filters=regex("^userset")))
bot.add_handler(MessageHandler(set_thumb_cmd, filters=command(
    BotCommands.SetThumbCommand) & CustomFilters.authorized_uset))
