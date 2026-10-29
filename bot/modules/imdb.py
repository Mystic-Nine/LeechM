#!/usr/bin/env python3
import re
import requests
from bot.helper.ext_utils.bot_utils import sync_to_async
from contextlib import suppress
from re import findall, IGNORECASE
from pycountry import countries as conn

from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, regex
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty

from bot import bot, LOGGER, user_data, config_dict
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage
from bot.helper.ext_utils.bot_utils import get_readable_time
from bot.helper.telegram_helper.button_build import ButtonMaker

OMDB_API_KEY = "39b094d0"

IMDB_GENRE_EMOJI = {"Action": "🚀", "Adult": "🔞", "Adventure": "🌋", "Animation": "🎠", "Biography": "📜", "Comedy": "🪗", "Crime": "🔪", "Documentary": "🎞", "Drama": "🎭", "Family": "👨‍👩‍👧‍👦", "Fantasy": "🫧", "Film Noir": "🎯", "Game Show": "🎮", "History": "🏛", "Horror": "🧟", "Musical": "🎻", "Music": "🎸", "Mystery": "🧳", "News": "📰", "Reality-TV": "🖥", "Romance": "🥰", "Sci-Fi": "🌠", "Short": "📝", "Sport": "⛳", "Talk-Show": "👨‍🍳", "Thriller": "🗡", "War": "⚔", "Western": "🪩"}
LIST_ITEMS = 4

def clean_omdb_list(val):
    if not val or val == "N/A":
        return []
    return val.split(", ")

async def imdb_search(_, message):
    if ' ' in message.text:
        k = await sendMessage(message, '<code>Searching IMDB ...</code>')
        title = message.text.split(' ', 1)[1]
        user_id = message.from_user.id
        buttons = ButtonMaker()
        
        if "imdb.com/title/tt" in title.lower():
            match = re.search(r'(tt\d+)', title.lower())
            if match:
                movieid = match.group(1)
                url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={movieid}"
                try:
                    movie = await sync_to_async(lambda u=url: requests.get(u, timeout=20).json())
                    if movie.get("Response") == "True":
                        buttons.ibutton(f"🎬 {movie.get('Title')} ({movie.get('Year')})", f"imdb {user_id} movie {movieid}")
                    else:
                        return await editMessage(k, "<i>No Results Found</i>")
                except Exception as e:
                    LOGGER.error(f"OMDb API Error: {e}")
                    return await editMessage(k, "<i>API Error, Try Again</i>")
            else:
                return await editMessage(k, "<i>Invalid IMDb URL</i>")
        else:
            movies = await sync_to_async(get_poster, title, bulk=True)
            if not movies:
                return await editMessage(k, "<i>No Results Found</i>, Try Again or Use <b>Title ID</b>")
            for movie in movies:
                buttons.ibutton(f"🎬 {movie.get('title')} ({movie.get('year')})", f"imdb {user_id} movie {movie.get('movieID')}")
        
        buttons.ibutton("🚫 Close 🚫", f"imdb {user_id} close")
        await editMessage(k, '<b><i>Here What I found on IMDb.com</i></b>', buttons.build_menu(1))
    else:
        await sendMessage(message, '<i>Send Movie / TV Series Name along with /imdb Command or send IMDB URL</i>')

def get_poster(query, bulk=False, id=False, file=None):
    if not id:
        query = (query.strip()).lower()
        title = query
        year = findall(r'[1-2]\d{3}$', query, IGNORECASE)
        if year:
            year = year[0]
            title = (query.replace(year, "")).strip()
        elif file is not None:
            year = findall(r'[1-2]\d{3}', file, IGNORECASE)
            if year:
                year = year[0]
        else:
            year = None
        
        url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&s={title}"
        if year:
            url += f"&y={year}"
        
        try:
            res = requests.get(url).json()
        except Exception as e:
            LOGGER.error(f"OMDb API Error: {e}")
            return None
        
        if res.get("Response") == "True":
            if bulk:
                movies = []
                for m in res.get("Search", []):
                    movies.append({
                        'title': m.get('Title'),
                        'year': m.get('Year'),
                        'movieID': m.get('imdbID')
                    })
                return movies
            else:
                movieid = res.get("Search")[0].get("imdbID")
        else:
            return None
    else:
        movieid = query

    url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={movieid}&plot=full"
    try:
        movie = requests.get(url).json()
    except Exception as e:
        LOGGER.error(f"OMDb API Error: {e}")
        return None

    if movie.get("Response") == "False":
        return None

    plot = movie.get('Plot', '')
    if plot and plot != "N/A" and len(plot) > 300:
        plot = f"{plot[:300]}..."

    poster = movie.get('Poster', '')
    if poster == "N/A":
        poster = ''

    return {
        'title': movie.get('Title', 'N/A'),
        'trailer': '',
        'votes': movie.get('imdbVotes', 'N/A'),
        "aka": 'N/A',
        "seasons": movie.get("totalSeasons", "N/A"),
        "box_office": movie.get('BoxOffice', 'N/A'),
        'localized_title': movie.get('Title', 'N/A'),
        'kind': movie.get("Type", "N/A"),
        "imdb_id": movie.get("imdbID", ""),
        "cast": list_to_str(clean_omdb_list(movie.get("Actors"))),
        "runtime": movie.get("Runtime", "N/A"),
        "countries": list_to_hash(clean_omdb_list(movie.get("Country")), True),
        "certificates": movie.get("Rated", "N/A"),
        "languages": list_to_hash(clean_omdb_list(movie.get("Language"))),
        "director": list_to_str(clean_omdb_list(movie.get("Director"))),
        "writer": list_to_str(clean_omdb_list(movie.get("Writer"))),
        "producer": 'N/A',
        "composer": 'N/A',
        "cinematographer": 'N/A',
        "music_team": 'N/A',
        "distributors": 'N/A',
        'release_date': movie.get('Released', 'N/A'),
        'year': movie.get('Year', 'N/A'),
        'genres': list_to_hash(clean_omdb_list(movie.get("Genre")), emoji=True),
        'poster': poster,
        'plot': plot if plot != "N/A" else "",
        'rating': str(movie.get("imdbRating", "0")) + " / 10",
        'url': f"https://www.imdb.com/title/{movie.get('imdbID')}",
        'url_cast': f"https://www.imdb.com/title/{movie.get('imdbID')}/fullcredits#cast",
        'url_releaseinfo': f"https://www.imdb.com/title/{movie.get('imdbID')}/releaseinfo",
    }

def list_to_str(k):
    if not k:
        return ""
    elif len(k) == 1:
        return str(k[0])
    elif LIST_ITEMS:
        k = k[:int(LIST_ITEMS)]
        return ' '.join(f'{elem},' for elem in k)[:-1]+' ...'
    else:
        return ' '.join(f'{elem},' for elem in k)[:-1]

def list_to_hash(k, flagg=False, emoji=False):
    listing = ""
    if not k:
        return ""
    elif len(k) == 1:
        if not flagg:
            if emoji:
                return str(IMDB_GENRE_EMOJI.get(k[0], '')+" #"+k[0].replace(" ", "_").replace("-", "_"))
            return str("#"+k[0].replace(" ", "_").replace("-", "_"))
        try:
            conflag = (conn.get(name=k[0])).flag
            return str(f"{conflag} #" + k[0].replace(" ", "_").replace("-", "_"))
        except AttributeError:
            return str("#"+k[0].replace(" ", "_").replace("-", "_"))
    elif LIST_ITEMS:
        k = k[:int(LIST_ITEMS)]
        for elem in k:
            ele = elem.replace(" ", "_").replace("-", "_")
            if flagg:
                with suppress(AttributeError):
                    conflag = (conn.get(name=elem)).flag
                    listing += f'{conflag} '
            if emoji:
                listing += f"{IMDB_GENRE_EMOJI.get(elem, '')} "
            listing += f'#{ele}, '
        return f'{listing[:-2]}'
    else:
        for elem in k:
            ele = elem.replace(" ", "_").replace("-", "_")
            if flagg:
                conflag = (conn.get(name=elem)).flag
                listing += f'{conflag} '
            listing += f'#{ele}, '
        return listing[:-2]

async def imdb_callback(_, query):
    message = query.message
    user_id = query.from_user.id
    data = query.data.split()
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "movie":
        await query.answer()
        imdb = await sync_to_async(get_poster, query=data[3], id=True)
        buttons = []
        if imdb and imdb.get('trailer'):
            if isinstance(imdb['trailer'], list):
                buttons.append([InlineKeyboardButton("▶️ IMDb Trailer ", url=str(imdb['trailer'][-1]))])
                imdb['trailer'] = list_to_str(imdb['trailer'])
            else: buttons.append([InlineKeyboardButton("▶️ IMDb Trailer ", url=str(imdb['trailer']))])
        buttons.append([InlineKeyboardButton("🚫 Close 🚫", callback_data=f"imdb {user_id} close")])
        template = config_dict['IMDB_TEMPLATE']
        if imdb and template != "":
            cap = template.format(
            title = imdb['title'],
            trailer = imdb['trailer'],
            votes = imdb['votes'],
            aka = imdb["aka"],
            seasons = imdb["seasons"],
            box_office = imdb['box_office'],
            localized_title = imdb['localized_title'],
            kind = imdb['kind'],
            imdb_id = imdb["imdb_id"],
            cast = imdb["cast"],
            runtime = imdb["runtime"],
            countries = imdb["countries"],
            certificates = imdb["certificates"],
            languages = imdb["languages"],
            director = imdb["director"],
            writer = imdb["writer"],
            producer = imdb["producer"],
            composer = imdb["composer"],
            cinematographer = imdb["cinematographer"],
            music_team = imdb["music_team"],
            distributors = imdb["distributors"],
            release_date = imdb['release_date'],
            year = imdb['year'],
            genres = imdb['genres'],
            poster = imdb['poster'],
            plot = imdb['plot'],
            rating = imdb['rating'],
            url = imdb['url'],
            url_cast = imdb['url_cast'],
            url_releaseinfo = imdb['url_releaseinfo'],
            **locals()
            )
        else:
            cap = "No Results"
        
        if imdb and imdb.get('poster'):
            try:
                await bot.send_photo(chat_id=query.message.reply_to_message.chat.id,  caption=cap, photo=imdb['poster'], reply_to_message_id=query.message.reply_to_message.id, reply_markup=InlineKeyboardMarkup(buttons))
            except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                poster = imdb.get('poster').replace('.jpg', "._V1_UX360.jpg")
                await sendMessage(message.reply_to_message, cap, InlineKeyboardMarkup(buttons), poster)
        else:
            await sendMessage(message.reply_to_message, cap, InlineKeyboardMarkup(buttons), 'https://telegra.ph/file/5af8d90a479b0d11df298.jpg')
        await message.delete()
    else:
        await query.answer()
        await query.message.delete()
        await query.message.reply_to_message.delete()

bot.add_handler(MessageHandler(imdb_search, filters=command(BotCommands.IMDBCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
bot.add_handler(CallbackQueryHandler(imdb_callback, filters=regex(r'^imdb')))
