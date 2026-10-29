#!/usr/bin/env python3
from contextlib import suppress
from aiohttp import ClientSession
from urllib.parse import quote as q
from pycountry import countries as conn

from pyrogram.filters import command, regex
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.errors import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty

from bot import LOGGER, bot, config_dict, user_data
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker

# TMDB API Key is configured via /bsetting -> Config Variables -> TMDB_API_KEY

LIST_ITEMS = 4
IMDB_GENRE_EMOJI = {"Action": "🚀", "Adult": "🔞", "Adventure": "🌋", "Animation": "🎠", "Biography": "📜", "Comedy": "🪗", "Crime": "🔪", "Documentary": "🎞", "Drama": "🎭", "Family": "👨‍👩‍👧‍👦", "Fantasy": "🫧", "Film Noir": "🎯", "Game Show": "🎮", "History": "🏛", "Horror": "🧟", "Musical": "🎻", "Music": "🎸", "Mystery": "🧳", "News": "📰", "Reality-TV": "🖥", "Romance": "🥰", "Sci-Fi": "🌠", "Short": "📝", "Sport": "⛳", "Talk-Show": "👨‍🍳", "Thriller": "🗡", "War": "⚔", "Western": "🪩"}

async def mydramalist_search(_, message):
    if ' ' in message.text:
        if not config_dict.get('TMDB_API_KEY'):
            return await sendMessage(message, "<b>⚠️ TMDB API Key is not configured.</b>")
        temp = await sendMessage(message, '<i>Searching TMDB ...</i>')
        title = message.text.split(' ', 1)[1]
        user_id = message.from_user.id
        buttons = ButtonMaker()
        
        url = f"https://api.themoviedb.org/3/search/multi?api_key={config_dict['TMDB_API_KEY']}&query={q(title)}"
        
        async with ClientSession() as sess:
            async with sess.get(url) as resp:
                if resp.status != 200:
                    return await editMessage(temp, "<i>API Error! Please check your TMDB API Key.</i>")
                res = await resp.json()
        
        results = res.get('results', [])
        results = [r for r in results if r.get('media_type') in ['tv', 'movie']]

        if not results:
            return await editMessage(temp, "<i>No Results Found</i>, Try Again")
            
        for drama in results[:10]:
            media_type = drama.get('media_type', 'tv')
            d_id = drama.get('id')
            d_title = drama.get('name') or drama.get('title', 'Unknown')
            d_year = (drama.get('first_air_date') or drama.get('release_date') or 'N/A')[:4]
            buttons.ibutton(f"🎬 {d_title} ({d_year})", f"mdl {user_id} drama {media_type}_{d_id}")
            
        buttons.ibutton("🚫 Close 🚫", f"mdl {user_id} close")
        await editMessage(temp, '<b><i>Dramas found :</i></b>', buttons.build_menu(1))
    else:
        await sendMessage(message, f'<i>Send Movie / TV Series Name along with /{BotCommands.MyDramaListCommand} Command</i>')


async def extract_MDL(slug):
    media_type, tmdb_id = slug.split('_')
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={config_dict['TMDB_API_KEY']}&append_to_response=credits"
    
    async with ClientSession() as sess:
        async with sess.get(url) as resp:
            data = await resp.json()
            
    plot = data.get('overview', '')
    if plot and len(plot) > 300:
        plot = f"{plot[:300]}..."
        
    cast_data = []
    for c in data.get('credits', {}).get('cast', [])[:LIST_ITEMS]:
        cast_data.append({'name': c.get('name'), 'link': f"https://www.themoviedb.org/person/{c.get('id')}"})
        
    networks = [n.get('name') for n in data.get('networks', [])]
    
    duration = "N/A"
    if media_type == 'tv' and data.get('episode_run_time'):
        duration = f"{data['episode_run_time'][0]} min"
    elif media_type == 'movie' and data.get('runtime'):
        duration = f"{data['runtime']} min"
        
    poster_path = data.get('poster_path')
    poster_url = f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else ""

    countries = [c.get('name') for c in data.get('production_countries', [])]

    directors = [c.get('name') for c in data.get('created_by', [])]
    if media_type == 'movie':
        directors = [c.get('name') for c in data.get('credits', {}).get('crew', []) if c.get('job') == 'Director']

    return {
        'title': data.get('name') or data.get('title', 'N/A'),
        'score': str(data.get('vote_average', 'N/A')),
        "aka": data.get('original_name') or data.get('original_title', 'N/A'),
        'episodes': str(data.get('number_of_episodes', 'N/A')),
        'type': data.get('type', 'Movie' if media_type == 'movie' else 'TV Series'),
        "cast": list_to_str(cast_data, cast=True),
        "country": list_to_hash(countries, True),
        'aired_date': data.get('first_air_date') or data.get('release_date', 'N/A'),
        'aired_on': 'N/A',
        'org_network': list_to_str(networks),
        'duration': duration,
        'watchers': str(data.get('popularity', 'N/A')),
        'ranked': 'N/A',
        'popularity': str(data.get('popularity', 'N/A')),
        'related_content': 'N/A',
        'native_title': data.get('original_name') or data.get('original_title', 'N/A'),
        'director': list_to_str(directors),
        'screenwriter': 'N/A',
        'genres': list_to_hash([g.get('name') for g in data.get('genres', [])], emoji=True),
        'tags': 'N/A',
        'poster': poster_url,
        'synopsis': plot,
        'rating': str(data.get('vote_average', '0'))[:3] + " / 10",
        'content_rating': 'N/A',
        'url': f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
    }


def list_to_str(k, cast=False):
    if not k or k == "N/A":
        return "N/A"
    if not isinstance(k, list):
        return str(k)
    
    limit_k = k[:int(LIST_ITEMS)] if LIST_ITEMS else k
    
    if cast and all(isinstance(elem, dict) for elem in limit_k):
        return ', '.join(f'''<a href="{elem.get('link')}">{elem.get('name')}</a>''' for elem in limit_k)
    return ', '.join(str(elem) for elem in limit_k)


def list_to_hash(k, flagg=False, emoji=False):
    if not k or k == "N/A":
        return "N/A"
    if not isinstance(k, list):
        k = [k]
        
    limit_k = k[:int(LIST_ITEMS)] if LIST_ITEMS else k
    
    result = []
    for elem in limit_k:
        ele = str(elem).replace(" ", "_").replace("-", "_")
        prefix = ""
        if flagg:
            with suppress(AttributeError):
                conflag = (conn.get(name=elem)).flag
                prefix += f'{conflag} '
        if emoji:
            prefix += f"{IMDB_GENRE_EMOJI.get(elem, '')} "
        result.append(f'{prefix}#{ele}')
        
    return ", ".join(result)


async def mdl_callback(_, query):
    message = query.message
    user_id = query.from_user.id
    data = query.data.split()
    
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "drama":
        await query.answer()
        mdl = await extract_MDL(data[3])
        buttons = ButtonMaker()
        buttons.ibutton("🚫 Close 🚫", f"mdl {user_id} close")
        
        template = config_dict.get('MDL_TEMPLATE', '')
        if mdl and template != "":
            cap = template.format(**mdl)
        else:
            cap = "<i>No Data Received</i>"
            
        if mdl.get('poster'):
            try: 
                await message.reply_to_message.reply_photo(mdl["poster"], caption=cap, reply_markup=buttons.build_menu(1))
            except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                await sendMessage(message.reply_to_message, cap, buttons.build_menu(1), mdl["poster"])
        else:
            await sendMessage(message.reply_to_message, cap, buttons.build_menu(1), 'https://te.legra.ph/file/5af8d90a479b0d11df298.jpg')
        await message.delete()
    else:
        await query.answer()
        await message.delete()
        await message.reply_to_message.delete()

bot.add_handler(MessageHandler(mydramalist_search, filters=command(BotCommands.MyDramaListCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
bot.add_handler(CallbackQueryHandler(mdl_callback, filters=regex(r'^mdl')))
