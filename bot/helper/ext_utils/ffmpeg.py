from os import path as os_path
import logging
from re import sub as re_sub
from aioshutil import move
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from bot import LOGGER, bot_cache
from bot.helper.ext_utils.fs_utils import clean_target
from bot.helper.ext_utils.bot_utils import cmd_exec
from bot.helper.ext_utils.lang_utils import stream_lang
import json
from bot.helper.ext_utils.subtitle_utils import create_subtitle_file

LOGGER = logging.getLogger(__name__)

########-------- Metadata -------------#########
TEXT_SUBS = {'ass', 'ssa', 'subrip', 'srt', 'webvtt', 'mov_text', 'text'}


async def probe_streams(path):
    """ffprobe -show_streams as a list of dicts (None when it fails)."""
    try:
        out, _, code = await cmd_exec(['ffprobe', '-hide_banner', '-loglevel', 'error', '-print_format', 'json', '-show_streams', path])
        if code != 0:
            return None
        return json.loads(out or '{}').get('streams') or None
    except Exception:
        return None


def _is_default(s):
    return bool((s.get('disposition') or {}).get('default'))


def layout(streams, pref, has_intro, mp4):
    """Output stream plan.
    - audio / subtitle tracks of the wanted language move to the front (only with >= 2 tracks of that kind,
      only when the language exists and not every track already is that language);
    - a new intro subtitle (has_intro) always stays first, the wanted language follows it;
    - for .mp4 streams the container cannot hold (bitmap subs, fonts, data) are dropped and text subs
      become mov_text.
    Returns dict(order, changed, flags)."""
    pref = pref or {}
    vids = [s for s in streams if s.get('codec_type') == 'video']
    auds = [s for s in streams if s.get('codec_type') == 'audio']
    subs = [s for s in streams if s.get('codec_type') == 'subtitle']
    rest = [s for s in streams if s.get('codec_type') not in ('video', 'audio', 'subtitle')]

    def front(items, want):
        if not want or len(items) < 2:
            return items, False
        hit = [s for s in items if stream_lang(s) == want]
        if not hit or len(hit) == len(items):
            return items, False
        return hit + [s for s in items if s not in hit], True

    new_auds, a_req = front(auds, pref.get('audio'))
    new_subs, s_req = front(subs, pref.get('sub'))
    ids = lambda lst: [s['index'] for s in lst]
    s_had_default = any(_is_default(s) for s in subs)
    a_flags_bad = a_req and [_is_default(s) for s in new_auds] != [True] + [False] * (len(new_auds) - 1)
    if has_intro:
        s_flags_bad = s_req and s_had_default
    else:
        s_flags_bad = s_req and s_had_default and [_is_default(s) for s in new_subs] != [True] + [False] * (len(new_subs) - 1)
    changed = ids(new_auds) != ids(auds) or ids(new_subs) != ids(subs) or bool(a_flags_bad) or bool(s_flags_bad)

    if mp4:
        new_subs = [s for s in new_subs if s.get('codec_name') in TEXT_SUBS]
        rest = []

    flags = []
    s_off = 1 if has_intro else 0
    if mp4:
        for k, s in enumerate(new_subs):
            if s.get('codec_name') != 'mov_text':
                flags += [f'-c:s:{k + s_off}', 'mov_text']
    if a_req:
        flags += ['-disposition:a:0', 'default'] + [x for i in range(1, len(new_auds)) for x in (f'-disposition:a:{i}', '0')]
    if s_req and s_had_default:
        if has_intro:
            flags += [x for i in range(len(new_subs)) for x in (f'-disposition:s:{i + 1}', '0')]
        elif new_subs:
            flags += ['-disposition:s:0', 'default'] + [x for i in range(1, len(new_subs)) for x in (f'-disposition:s:{i}', '0')]
    return {'order': vids + new_auds + new_subs + rest, 'changed': changed, 'flags': flags}


async def edit_metadata(listener, base_dir: str, media_file: str, outfile: str, metadata: str = '', intro_settings: dict = None, lang_pref: dict = None):
    file_name = os_path.basename(media_file)
    basename = os_path.splitext(file_name)[0]
    basenameX = re_sub(r'www\S+', '', basename)
    basenameX = re_sub(r'(^\s*-\s*|(\s*-\s*){2,})', '', basenameX)

    file_ext = os_path.splitext(file_name)[-1].lower()
    if file_ext not in ('.mkv', '.mp4'):
        return

    # Intro Subtitle: a short softsub (a real, selectable subtitle track,
    # not burned into the video) showing the user's own text for the first
    # few seconds, set as the default track. Built as a second FFmpeg input
    # mapped in *before* the main file's own streams, so it always lands at
    # subtitle index s:0 - that's what makes "-disposition:s:0 default"
    # below reliably target the new subtitle rather than any subtitle
    # track the source file might already have.
    intro_sub_file, intro_sub_fmt = None, None
    if intro_settings and intro_settings.get('text') and intro_settings.get('enabled', True):
        intro_sub_file, intro_sub_fmt = create_subtitle_file(intro_settings, media_file, file_ext)

    # Audio/Subtitle language order (user setting). Only touches files that have 2+ tracks of a kind.
    want_lang = bool(lang_pref and (lang_pref.get('audio') or lang_pref.get('sub')))
    lang_only = want_lang and not metadata and not intro_sub_file
    lay = None
    if want_lang:
        streams = await probe_streams(media_file)
        if streams:
            lay = layout(streams, lang_pref, bool(intro_sub_file), file_ext == '.mp4')
        if lang_only and not (lay and lay['changed']):
            if intro_sub_file:
                await clean_target(intro_sub_file)
            return    # one audio/subtitle track, or already in the wanted order: leave the file alone

    # Multi-metadata parsing engine
    meta_args = []
    meta_dict = {}
    if metadata and ':' in metadata:
        pairs = metadata.split('|')
        for pair in pairs:
            if ':' in pair:
                k, v = pair.split(':', 1)
                meta_dict[k.strip().lower()] = v.strip()

    if lang_only:
        pass    # language order only: do not touch titles / tags
    elif meta_dict:
        # Title logic handling
        title_val = meta_dict.get('title', '')
        if title_val:
            if basename.strip().lower().startswith("www"):
                title_metadata = f"{title_val} - {basenameX}"
            elif basename.strip().lower().startswith("@"):
                title_metadata = f"{basenameX}"
            else:
                title_metadata = title_val
        else:
            title_metadata = basenameX

        meta_args.extend(['-metadata', f'title={title_metadata}'])

        # Data mapping dictionary
        mapping = {
            'author': 'author',
            'artist': 'artist',
            'comment': 'comment',
            'copyright': 'copyright',
            'publisher': 'publisher',
            'encoder': 'encoder',
            'studio': 'studio',
            'audio': 'audio',
            'subtitle': 'subtitle',
            'video': 'video',
            'encoded by': 'encoded_by',
            'custom tag': 'custom_tag',
            'dubbed by': 'dubbed_by',
            'channel': 'channel',
            'website': 'website',
            'source': 'source',
            'official site': 'official_site'
        }

        for user_key, ff_key in mapping.items():
            if val := meta_dict.get(user_key):
                meta_args.extend(['-metadata', f'{ff_key}={val}'])

        # Per-stream title injection
        fallback_stream_title = meta_dict.get('title') or meta_dict.get('channel') or meta_dict.get('author') or ""
        if fallback_stream_title:
            meta_args.extend([
                '-metadata:s:v', f'title={meta_dict.get("video", fallback_stream_title)}',
                '-metadata:s:a', f'title={meta_dict.get("audio", fallback_stream_title)}',
                '-metadata:s:s', f'title={meta_dict.get("subtitle", fallback_stream_title)}'
            ])
    else:
        # Backward compatibility for the old single-string format
        if metadata:
            if basename.strip().lower().startswith("www"):
                title_metadata = f"{metadata} - {basenameX}"
            elif basename.strip().lower().startswith("@"):
                title_metadata = f"{basenameX}"
            else:
                title_metadata = metadata
        else:
            title_metadata = basenameX

        meta_args.extend([
            '-metadata', f'title={title_metadata}',
            '-metadata:s:v', f'title={metadata or title_metadata}',
            '-metadata:s:a', f'title={metadata or title_metadata}',
            '-metadata:s:s', f'title={metadata or title_metadata}'
        ])

    def build_cmd(plan):
        cmd = [bot_cache['pkgs'][2], '-hide_banner', '-loglevel', 'error', '-nostdin']
        if intro_sub_file:
            cmd.extend(['-i', intro_sub_file])   # input 0: the new intro subtitle
        cmd.extend(['-i', media_file])           # input 0 (no intro sub) or input 1
        mi = 1 if intro_sub_file else 0
        if plan:
            # explicit stream list (language order and/or mp4-safe); intro subtitle stays first
            if intro_sub_file:
                cmd.extend(['-map', '0:0'])
            for st in plan['order']:
                cmd.extend(['-map', f"{mi}:{st['index']}"])
        elif intro_sub_file:
            # Map the new subtitle FIRST, before the main file's own streams -
            # this is what guarantees it lands at subtitle index s:0 (see the
            # comment above), regardless of whether the source already has its
            # own subtitle track(s).
            cmd.extend(['-map', '0:0', '-map', '1'])
        else:
            cmd.extend(['-map', '0'])
        cmd.extend(meta_args)
        cmd.extend(['-c', 'copy'])
        if intro_sub_file:
            # This targets ONLY the new subtitle stream (s:0, guaranteed by the
            # map order above) - any subtitle track(s) the source file already
            # had keep their original codec via the blanket -c copy, instead of
            # also being forced through this conversion.
            if intro_sub_fmt == 'ass':
                # MKV carries ASS as-is; no conversion needed.
                cmd.extend(['-c:s:0', 'copy'])
            else:
                # MP4 can't hold a raw "subrip" stream - convert to mov_text.
                cmd.extend(['-c:s:0', 'mov_text'])
            cmd.extend(['-disposition:s:0', 'default'])
        if plan:
            cmd.extend(plan['flags'])
        cmd.append(outfile)
        return cmd

    async def run(plan):
        listener.suproc = await create_subprocess_exec(*build_cmd(plan), stderr=PIPE)
        _, err = await listener.suproc.communicate()
        return listener.suproc.returncode, (err or b'').decode(errors='ignore')

    code, err = await run(lay)
    if code != 0 and file_ext == '.mp4' and listener.suproc != 'cancelled' and code != -9 \
            and ('not currently supported in container' in err or 'Could not find tag' in err):
        # MP4 cannot hold ASS/PGS subtitles, fonts or data streams: drop/convert them and retry once
        streams = await probe_streams(media_file)
        if streams:
            await clean_target(outfile)
            code, err = await run(layout(streams, lang_pref if want_lang else {}, bool(intro_sub_file), True))

    if code == 0:
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        await clean_target(outfile)
        LOGGER.error('%s. Changing metadata failed, Path %s', err[-700:], media_file)
    if intro_sub_file:
        await clean_target(intro_sub_file)


########-------- Attachment -------------#########
async def edit_attachment(listener, base_dir: str, media_file: str, outfile: str, attachment: str = ''):
    file_name = os_path.basename(media_file)

    file_ext = os_path.splitext(file_name)[-1].lower()
    if file_ext != '.mkv':
        return

    omg = "photo"  
    attachment_ext = attachment.split(".")[-1].lower()   
    mime_type = "application/octet-stream"
    if attachment_ext in ["jpg", "jpeg"]:
        mime_type = "image/jpeg"
    elif attachment_ext == "png":
        mime_type = "image/png"
        
    cmd = [
        bot_cache['pkgs'][2], '-hide_banner', '-loglevel', 'error', '-progress', 'pipe:1',
        '-i', media_file,
        '-attach', attachment,
        '-metadata:s:t', f'mimetype={mime_type}',
        '-metadata:s:t', f'filename={omg}.{attachment_ext}',
        '-disposition:t', 'default',
        '-c', 'copy', 
        '-map', '0', 
        '-map', '0:t?', 
        outfile
    ]  
    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()
    if code == 0:
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        await clean_target(outfile)
        LOGGER.error('%s. Changing failed, Path %s', (await listener.suproc.stderr.read()).decode(), media_file)
