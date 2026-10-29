"""Audio / subtitle language helpers (used by the 'Audio & Subtitle' user setting)."""
from re import split as _split

# code -> (display name, accepted tags). Codes are the 3-letter tags ffmpeg/mkvmerge normally write.
LANGS = {
    'eng': ('English', {'en', 'eng', 'english'}),
    'hin': ('Hindi', {'hi', 'hin', 'hindi'}),
    'tam': ('Tamil', {'ta', 'tam', 'tamil'}),
    'tel': ('Telugu', {'te', 'tel', 'telugu'}),
    'mal': ('Malayalam', {'ml', 'mal', 'malayalam'}),
    'kan': ('Kannada', {'kn', 'kan', 'kannada'}),
    'ben': ('Bengali', {'bn', 'ben', 'bengali', 'bangla'}),
    'mar': ('Marathi', {'mr', 'mar', 'marathi'}),
    'pan': ('Punjabi', {'pa', 'pan', 'punjabi'}),
    'guj': ('Gujarati', {'gu', 'guj', 'gujarati'}),
    'urd': ('Urdu', {'ur', 'urd', 'urdu'}),
    'jpn': ('Japanese', {'ja', 'jpn', 'japanese'}),
    'kor': ('Korean', {'ko', 'kor', 'korean'}),
    'chi': ('Chinese', {'zh', 'zho', 'chi', 'chinese', 'mandarin', 'cmn', 'yue', 'cantonese'}),
    'spa': ('Spanish', {'es', 'spa', 'spanish'}),
    'fre': ('French', {'fr', 'fra', 'fre', 'french'}),
    'ger': ('German', {'de', 'deu', 'ger', 'german'}),
    'ita': ('Italian', {'it', 'ita', 'italian'}),
    'por': ('Portuguese', {'pt', 'por', 'portuguese'}),
    'rus': ('Russian', {'ru', 'rus', 'russian'}),
    'ara': ('Arabic', {'ar', 'ara', 'arabic'}),
    'tur': ('Turkish', {'tr', 'tur', 'turkish'}),
    'tha': ('Thai', {'th', 'tha', 'thai'}),
    'ind': ('Indonesian', {'id', 'ind', 'indonesian'}),
    'vie': ('Vietnamese', {'vi', 'vie', 'vietnamese'}),
    'nep': ('Nepali', {'ne', 'nep', 'nepali'}),
}
LANG_NAMES = {code: v[0] for code, v in LANGS.items()}
LANG_LIST = [(code, v[0]) for code, v in LANGS.items()]
_ALIAS = {a: code for code, v in LANGS.items() for a in v[1]}


def norm_lang(tag):
    """'en-US' / 'ENG' / 'English' -> 'eng'; unknown tags come back lower-cased."""
    t = str(tag or '').strip().lower()
    if not t:
        return ''
    if t in _ALIAS:
        return _ALIAS[t]
    head = _split(r'[-_ ]', t)[0]
    return _ALIAS.get(head, t)


def stream_lang(stream):
    """Language code of an ffprobe stream dict ('' when unknown). Falls back to the track title
    ('English [Forced]', 'Hindi DD5.1') when the language tag is missing or 'und'."""
    tags = stream.get('tags') or {}
    lang = norm_lang(tags.get('language') or tags.get('LANGUAGE'))
    if lang and lang not in ('und', 'unk', 'mis', 'zxx'):
        return lang
    title = str(tags.get('title') or tags.get('TITLE') or '').lower()
    for word in _split(r'[^a-z]+', title):
        if len(word) >= 4 and word in _ALIAS:
            return _ALIAS[word]
    return ''
