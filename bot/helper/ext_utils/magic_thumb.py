"""Magic (instant) Thumbnail.

After a video was uploaded with the permanent thumbnail, the copy that is delivered
to the user / dump chats is re-sent through the Bot API with `cover=<image>`:
  * no download / upload of the video (it is sent by file_id),
  * only a small image is uploaded,
  * the cover is temporary, the permanent thumbnail always stays on the file.
Optional: any failure returns None and the caller falls back to plain copy_message.
Works the same with pyrofork and wzgram (plain HTTP to the Bot API).
"""
import json
from asyncio import sleep
from os import environ, path as ospath, remove
from types import SimpleNamespace

from aiohttp import ClientSession, ClientTimeout, FormData
from PIL import Image

from bot import bot, BOT_TOKEN, LOGGER
from bot.helper.ext_utils.bot_utils import sync_to_async

BOT_API = environ.get('TELEGRAM_BOT_API_URL', 'https://api.telegram.org').rstrip('/')
_session = None


class MagicMsg:
    """Tiny stand-in for the pyrogram Message returned by copy_message."""

    def __init__(self, chat_id, message_id):
        self.chat = SimpleNamespace(id=chat_id)
        self.id = message_id
        self.text = None

    async def edit_reply_markup(self, reply_markup=None):
        return await bot.edit_message_reply_markup(self.chat.id, self.id, reply_markup)


def _make_cover(path):
    out = f"{path}.cover.jpg"
    with Image.open(path) as img:
        img = img.convert('RGB')
        img.thumbnail((1280, 1280))
        img.save(out, 'JPEG', quality=90)
    return out


async def prepare_cover(path):
    """HD-ish temp JPEG (max 1280px) for the cover. Returns path or None."""
    try:
        if path and ospath.isfile(path):
            return await sync_to_async(_make_cover, path)
    except Exception as e:
        LOGGER.warning(f"Magic Thumbnail: cover prepare failed: {e}")
    return None


def cleanup_cover(path):
    try:
        if path and path.endswith('.cover.jpg') and ospath.isfile(path):
            remove(path)
    except Exception:
        pass


def _entities_json(entities):
    out = []
    for e in entities or []:
        t = getattr(getattr(e, 'type', None), 'name', None)
        if not t or t == 'UNKNOWN':
            continue
        d = {'type': t.lower(), 'offset': e.offset, 'length': e.length}
        if getattr(e, 'url', None):
            d['url'] = e.url
        if getattr(e, 'language', None):
            d['language'] = e.language
        if getattr(e, 'custom_emoji_id', None):
            d['custom_emoji_id'] = str(e.custom_emoji_id)
        out.append(d)
    return json.dumps(out) if out else None


def markup_json(markup):
    if not markup or not getattr(markup, 'inline_keyboard', None):
        return None
    rows = []
    for row in markup.inline_keyboard:
        r = []
        for b in row:
            d = {'text': b.text}
            if getattr(b, 'url', None):
                d['url'] = b.url
            elif getattr(b, 'callback_data', None) is not None:
                cd = b.callback_data
                d['callback_data'] = cd.decode() if isinstance(cd, bytes) else cd
            else:
                continue
            r.append(d)
        if r:
            rows.append(r)
    return json.dumps({'inline_keyboard': rows}) if rows else None


async def magic_copy(chat_id, src_msg, cover_path, reply_to=None, reply_markup=None):
    """Send src_msg's video to chat_id with a temporary cover. Returns MagicMsg or None."""
    global _session
    try:
        video = getattr(src_msg, 'video', None)
        if not (BOT_TOKEN and video and cover_path and ospath.isfile(cover_path)):
            return None
        if _session is None or _session.closed:
            _session = ClientSession(timeout=ClientTimeout(total=90))
        for attempt in range(2):
            form = FormData()
            form.add_field('chat_id', str(chat_id))
            form.add_field('video', video.file_id)
            form.add_field('supports_streaming', 'true')
            form.add_field('disable_notification', 'true')
            if getattr(video, 'duration', None):
                form.add_field('duration', str(video.duration))
            if getattr(video, 'width', None):
                form.add_field('width', str(video.width))
                form.add_field('height', str(video.height))
            if src_msg.caption:
                form.add_field('caption', src_msg.caption)
                if ents := _entities_json(src_msg.caption_entities):
                    form.add_field('caption_entities', ents)
            if reply_to:
                form.add_field('reply_parameters', json.dumps({'message_id': int(reply_to), 'allow_sending_without_reply': True}))
            if mk := markup_json(reply_markup):
                form.add_field('reply_markup', mk)
            with open(cover_path, 'rb') as fh:
                form.add_field('cover', fh.read(), filename='cover.jpg', content_type='image/jpeg')
            async with _session.post(f"{BOT_API}/bot{BOT_TOKEN}/sendVideo", data=form) as resp:
                data = await resp.json(content_type=None)
            if data.get('ok'):
                return MagicMsg(chat_id, data['result']['message_id'])
            wait = (data.get('parameters') or {}).get('retry_after')
            if wait and wait <= 5 and attempt == 0:
                await sleep(wait + 1)
                continue
            LOGGER.warning(f"Magic Thumbnail failed, using normal copy: {data.get('description')}")
            return None
    except Exception as e:
        LOGGER.warning(f"Magic Thumbnail error, using normal copy: {e!r}")
    return None
