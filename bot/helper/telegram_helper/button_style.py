"""Colored inline buttons (Telegram Bot API 9.4+: primary=blue, success=green, danger=red).

Instead of touching hundreds of call sites, InlineKeyboardButton.__init__ is wrapped once:
a button without an explicit `style` gets one from its label / callback data
(Close/Cancel/Delete -> red, Save/Done/Enable -> green, Next/Back/Preview -> blue).
Pass style=ButtonStyle.X yourself to override. Old Telegram clients just show normal buttons.
Switch off with env BUTTON_COLORS=false. Does nothing when the Telegram library has no `style`.
"""
import re
from functools import wraps
from inspect import signature
from logging import getLogger
from os import environ

LOGGER = getLogger(__name__)
_STATE = {'on': environ.get('BUTTON_COLORS', 'true').lower() not in ('0', 'false', 'no')}

_SMALL = str.maketrans({'ᴀ': 'a', 'ʙ': 'b', 'ᴄ': 'c', 'ᴅ': 'd', 'ᴇ': 'e', 'ꜰ': 'f', 'ɢ': 'g', 'ʜ': 'h', 'ɪ': 'i',
                        'ᴊ': 'j', 'ᴋ': 'k', 'ʟ': 'l', 'ᴍ': 'm', 'ɴ': 'n', 'ᴏ': 'o', 'ᴘ': 'p', 'ǫ': 'q', 'ʀ': 'r',
                        'ꜱ': 's', 'ᴛ': 't', 'ᴜ': 'u', 'ᴠ': 'v', 'ᴡ': 'w', 'ʏ': 'y', 'ᴢ': 'z'})
DANGER = {'close', 'cancel', 'delete', 'remove', 'reset', 'stop', 'disable', 'clear', 'abort', 'exit', 'clean', 'no', 'false', 'kill'}
SUCCESS = {'done', 'save', 'confirm', 'yes', 'enable', 'apply', 'accept', 'ok', 'start', 'true', 'activate', 'install', 'continue'}
PRIMARY = {'next', 'previous', 'prev', 'pre', 'back', 'preview', 'refresh', 'view', 'page', 'mediainfo', 'screenshots'}
_ARROWS = ('<<', '>>', '«', '»', '⌫')


def classify(text, data=None):
    """-> 'danger' | 'success' | 'primary' | None"""
    try:
        norm = str(text or '').lower().translate(_SMALL)
        words = set(re.findall(r'[a-z]+', norm))
        tail = str(data or '').lower().replace('_', ' ').split()[-1:]   # e.g. "stats 123 close"
        words |= set(tail)
        if words & DANGER:
            return 'danger'
        if words & SUCCESS:
            return 'success'
        if words & PRIMARY or any(a in norm for a in _ARROWS):
            return 'primary'
    except Exception:
        pass
    return None


def install():
    """Wrap InlineKeyboardButton once. Returns True when active."""
    if not _STATE['on']:
        return False
    try:
        from pyrogram.types import InlineKeyboardButton as B
        from pyrogram.enums import ButtonStyle
        if 'style' not in signature(B.__init__).parameters:
            LOGGER.info("button colors: this Telegram library has no `style` support")
            return False
        styles = {'danger': ButtonStyle.DANGER, 'success': ButtonStyle.SUCCESS, 'primary': ButtonStyle.PRIMARY}
        orig = B.__init__
        if getattr(orig, '_colored', False):
            return True

        @wraps(orig)
        def __init__(self, *a, **kw):
            if _STATE['on'] and kw.get('style') is None:
                name = classify(kw.get('text', a[0] if a else ''), kw.get('callback_data'))
                if name:
                    kw['style'] = styles[name]
            orig(self, *a, **kw)

        __init__._colored = True
        B.__init__ = __init__
        return True
    except Exception as e:
        LOGGER.warning(f"button colors disabled: {e!r}")
        return False


def disable():
    _STATE['on'] = False


async def selftest(client):
    """Serialize one colored button like a real send; if the library can't, turn colors off."""
    if not _STATE['on']:
        return
    try:
        from inspect import isawaitable
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        res = InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='x')]]).write(client)
        if isawaitable(res):
            await res
    except Exception as e:
        _STATE['on'] = False
        LOGGER.warning(f"button colors turned off (library cannot send styled buttons): {e!r}")
