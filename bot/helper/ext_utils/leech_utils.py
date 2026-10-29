from hashlib import md5
from html import escape
from time import strftime, gmtime, time
from re import IGNORECASE, sub as re_sub, search as re_search
from shlex import split as ssplit
from natsort import natsorted
from os import path as ospath
from aiofiles.os import remove as aioremove, path as aiopath, mkdir, makedirs, listdir, rename as aiorename
from aioshutil import rmtree as aiormtree
from contextlib import suppress
from asyncio import create_subprocess_exec, create_task, gather, Semaphore
from asyncio.subprocess import PIPE
from telegraph import upload_file
from langcodes import Language
from urllib.parse import quote_plus
from PIL import Image

from bot import bot_cache, LOGGER, MAX_SPLIT_SIZE, config_dict, user_data
from bot.modules.autorename import get_autorename, get_title_for_thumbnail
from bot.modules.poster import fetch_json
from bot.modules.mediainfo import parseinfo
from bot.helper.ext_utils.bot_utils import cmd_exec, sync_to_async, get_readable_file_size, get_readable_time
from bot.helper.ext_utils.fs_utils import ARCH_EXT, get_mime_type
from bot.helper.ext_utils.telegraph_helper import telegraph


async def remux_container(inp_path, out_path):
    """
    When the user's Auto Rename format has an explicit extension at the end
    (e.g. .mkv), previously only the filename was changed (os.rename) - the
    actual container/bytes stayed unchanged. So a real .mp4 file would just
    get renamed to .mkv (or vice versa) without actually being re-muxed.
    Players like VLC/MX Player detect the real content and play it fine, but
    Telegram itself parses the file's structure (moov/EBML etc.) to build
    streaming/preview, and a mismatch between the extension and the real
    container causes issues there - missing audio, stuck downloads, or the
    file not playing on Telegram at all.

    So when the extension is genuinely being changed, an actual remux
    (stream copy, no re-encoding - so it's fast and lossless) is done here,
    so both the bytes and the extension match.
    """
    out_ext = ospath.splitext(out_path)[1].lower()
    cmd = [bot_cache['pkgs'][2], '-hide_banner', '-loglevel', 'error',
           '-i', inp_path, '-map', '0', '-c', 'copy']
    if out_ext == '.mp4':
        # The MP4 container can't hold many subtitle codecs directly (e.g.
        # ASS/SRT), so text subtitles are converted to mov_text. faststart
        # moves the moov atom (the file's index) to the front, so Telegram
        # (and other players) can start streaming immediately instead of
        # having to fetch/seek to the end of the file first.
        cmd += ['-c:s', 'mov_text', '-movflags', '+faststart']
    cmd.append(out_path)

    proc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await proc.wait()
    if code == 0 and await aiopath.exists(out_path):
        return True

    err = (await proc.stderr.read()).decode().strip()
    LOGGER.warning(f'Remux to {out_ext} failed once, retrying without incompatible streams. {inp_path} : {err}')
    with suppress(Exception):
        await aioremove(out_path)

    if out_ext == '.mp4':
        # If there's a bitmap/PGS subtitle or another incompatible stream,
        # drop it and retry with just video + audio, so at least a file with
        # working video/audio is produced.
        cmd2 = [bot_cache['pkgs'][2], '-hide_banner', '-loglevel', 'error',
                '-i', inp_path, '-map', '0:v', '-map', '0:a?', '-c', 'copy',
                '-movflags', '+faststart', out_path]
        proc2 = await create_subprocess_exec(*cmd2, stderr=PIPE)
        code2 = await proc2.wait()
        if code2 == 0 and await aiopath.exists(out_path):
            return True
        err2 = (await proc2.stderr.read()).decode().strip()
        LOGGER.error(f'Remux fallback also failed, keeping original container. {inp_path} : {err2}')
        with suppress(Exception):
            await aioremove(out_path)

    return False


def _moov_at_end(path):
    """True when an MP4/MOV has its 'mdat' before 'moov' (needs faststart). Reads only box headers."""
    try:
        size = ospath.getsize(path)
        pos = 0
        with open(path, 'rb') as f:
            while pos + 8 <= size:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                bsize = int.from_bytes(hdr[:4], 'big')
                btype = hdr[4:8]
                if bsize == 1:
                    bsize = int.from_bytes(f.read(8), 'big')
                elif bsize == 0:
                    bsize = size - pos
                if btype == b'moov':
                    return False
                if btype == b'mdat':
                    return True
                if bsize < 8:
                    break
                pos += bsize
    except Exception:
        pass
    return False


async def ensure_streamable(path):
    """
    Re-muxes a video (stream copy, no re-encoding - fast and lossless) so it
    starts playing on Telegram immediately instead of buffering/lagging
    before playback begins. For MP4/MOV specifically, the source file's
    `moov` atom (its index: duration, codecs, keyframes) may sit at the very
    END of the file, forcing players (including Telegram's own) to fetch or
    seek through most of the file before they can start - "faststart"
    rewrites the container with that index moved to the front instead.
    MKV/WebM don't have this exact issue, but a clean remux still tends to
    produce a more standards-compliant seek index.

    This runs on every video before upload, regardless of whether Auto
    Rename changed its name/extension. Failure here is never fatal - if the
    remux doesn't work for any reason, the original file just gets uploaded
    as-is, exactly as before this existed.
    """
    ext = ospath.splitext(path)[1].lower()
    # PERF: remuxing rewrites the WHOLE file (disk read+write, minutes for big files) for
    # every upload. Only MP4-family files whose moov atom sits at the END need it; MKV/WebM
    # and already-faststart MP4 are uploaded as they are.
    if ext not in ('.mp4', '.mov', '.m4v') or not await sync_to_async(_moov_at_end, path):
        return path

    tmp_path = f"{path}.streamable{ext}"
    with suppress(Exception):
        if await remux_container(path, tmp_path):
            await aioremove(path)
            await aiorename(tmp_path, path)
            return path
    with suppress(Exception):
        if await aiopath.exists(tmp_path):
            await aioremove(tmp_path)
    return path


async def is_multi_streams(path):
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_streams", path])
        if res := result[1]:
            LOGGER.debug(f'Get Video Streams: {res}')
    except Exception as e:
        LOGGER.error(f'Get Video Streams: {e}. Mostly File not found!')
        return False
    fields = __import__('json').loads(result[0] or '{}').get('streams')
    if fields is None:
        LOGGER.error(f"get_video_streams: {result}")
        return False
    videos = 0
    audios = 0
    for stream in fields:
        if stream.get('codec_type') == 'video':
            videos += 1
        elif stream.get('codec_type') == 'audio':
            audios += 1
    return videos > 1 or audios > 1


async def get_media_info(path, metadata=False):
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_format", "-show_streams", path])
        if res := result[1]:
            LOGGER.debug(f'Media Info FF: {res}')
    except Exception as e:
        LOGGER.error(f'Media Info: {e}. Mostly File not found!')
        return (0, "", "", "") if metadata else (0, None, None)
    try:
        ffresult = __import__('json').loads(result[0] or '{}')
    except Exception:
        ffresult = {}
    fields = ffresult.get('format')
    if fields is None:
        LOGGER.debug(f"Media Info Sections: {result}")
        return (0, "", "", "") if metadata else (0, None, None)
    duration = round(float(fields.get('duration', 0)))
    if metadata:
        lang, qual, stitles = "", "", ""
        if (streams := ffresult.get('streams')) and streams[0].get('codec_type') == 'video':
            qual = int(streams[0].get('height'))
            qual = f"{480 if qual <= 480 else 540 if qual <= 540 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
            for stream in streams:
                if stream.get('codec_type') == 'audio' and (lc := stream.get('tags', {}).get('language')):
                    with suppress(Exception):
                        lc = Language.get(lc).display_name()
                    if lc not in lang:
                        lang += f"{lc}, "
                if stream.get('codec_type') == 'subtitle' and (st := stream.get('tags', {}).get('language')):
                    with suppress(Exception):
                        st = Language.get(st).display_name()
                    if st not in stitles:
                        stitles += f"{st}, "
        return duration, qual, lang[:-2], stitles[:-2]
    tags = fields.get('tags', {})
    artist = tags.get('artist') or tags.get('ARTIST') or tags.get("Artist")
    title = tags.get('title') or tags.get('TITLE') or tags.get("Title")
    return duration, artist, title


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if path.endswith(tuple(ARCH_EXT)) or re_search(r'.+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$', path):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith('audio'):
        return False, True, False
    if mime_type.startswith('image'):
        return False, False, True
    if not mime_type.startswith('video') and not mime_type.endswith('octet-stream'):
        return is_video, is_audio, is_image
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_streams", path])
        if res := result[1]:
            LOGGER.debug(f'Get Document Type: {res}')
    except Exception as e:
        LOGGER.error(f'Get Document Type: {e}. Mostly File not found!')
        return is_video, is_audio, is_image
    fields = __import__('json').loads(result[0] or '{}').get('streams')
    if fields is None:
        LOGGER.debug(f"get_document_type: {result}")
        return is_video, is_audio, is_image
    for stream in fields:
        if stream.get('codec_type') == 'video':
            is_video = True
        elif stream.get('codec_type') == 'audio':
            is_audio = True
    return is_video, is_audio, is_image


_AUTO_THUMB_URLS = {}


async def _download_auto_thumb(tmdb_id, full_url):
        des_dir = 'Thumbnails'
        if not await aiopath.exists(des_dir):
            await mkdir(des_dir)
        raw_path = ospath.join(des_dir, f"auto_thumb_{tmdb_id}_{int(time())}.jpg")

        from aiohttp import ClientSession
        async with ClientSession() as session:
            async with session.get(full_url) as resp:
                if resp.status != 200:
                    return None
                with open(raw_path, 'wb') as f:
                    f.write(await resp.read())

        # Telegram wants a small thumbnail (<=320px on the long side), not
        # the full backdrop - resize it down in a thread (PIL is blocking).
        def _resize():
            with Image.open(raw_path) as img:
                img = img.convert('RGB')
                img.thumbnail((320, 320))
                img.save(raw_path, 'JPEG')
        await sync_to_async(_resize)
        return raw_path


async def fetch_auto_thumbnail(title):
    """
    Auto Thumbnail: given a resolved title, find a landscape (backdrop)
    image via TMDB - the same "English landscape" images shown under
    /poster's Landscape button - download it, and resize it down to a
    proper Telegram video-thumbnail (max 320px on the long side, JPEG).

    Returns a path to a temp file the caller should delete after the
    upload, or None if no match/image/API key is available. Never raises -
    a failure here should never block the leech itself.
    """
    if not title or not config_dict.get('TMDB_API_KEY'):
        return None
    try:
        if (cached := _AUTO_THUMB_URLS.get(title)):
            tmdb_id, full_url = cached
            return await _download_auto_thumb(tmdb_id, full_url)
        safe_query = quote_plus(title)
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={config_dict['TMDB_API_KEY']}&query={safe_query}"
        search_result = await fetch_json(search_url)
        if not search_result or not search_result.get('results'):
            return None
        valid = [r for r in search_result['results'] if r.get('media_type') in ('movie', 'tv')]
        if not valid:
            return None
        media_type, tmdb_id = valid[0]['media_type'], valid[0]['id']

        img_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/images?api_key={config_dict['TMDB_API_KEY']}"
        images = await fetch_json(img_url)
        backdrops = (images or {}).get('backdrops', [])
        if not backdrops:
            return None
        # Same preference as /poster's Landscape button: English-language
        # backdrops first, then whatever's left.
        landscape = [b for b in backdrops if b.get('iso_639_1') not in (None, 'xx')]
        landscape.sort(key=lambda x: (0 if x.get('iso_639_1') == 'en' else 1, x.get('iso_639_1', '')))
        best = (landscape or backdrops)[0]
        full_url = f"https://image.tmdb.org/t/p/w780{best['file_path']}"

        if len(_AUTO_THUMB_URLS) > 200:
            _AUTO_THUMB_URLS.clear()
        _AUTO_THUMB_URLS[title] = (tmdb_id, full_url)
        return await _download_auto_thumb(tmdb_id, full_url)
    except Exception as e:
        LOGGER.error(f"Auto Thumbnail fetch failed for '{title}': {e}")
        return None


async def get_audio_thumb(audio_file):
    des_dir = 'Thumbnails'
    if not await aiopath.exists(des_dir):
        await mkdir(des_dir)
    des_dir = ospath.join(des_dir, f"{time()}.jpg")
    cmd = [bot_cache['pkgs'][2], "-hide_banner", "-loglevel", "error",
           "-i", audio_file, "-an", "-vcodec", "copy", des_dir]
    status = await create_subprocess_exec(*cmd, stderr=PIPE)
    if await status.wait() != 0 or not await aiopath.exists(des_dir):
        err = (await status.stderr.read()).decode().strip()
        if 'does not contain any stream' in err:
            # Most audio files (e.g. FLAC rips) simply have no embedded
            # cover art - this is normal, not worth logging as an error.
            LOGGER.debug(f'No embedded thumbnail found in audio: {audio_file}')
        else:
            LOGGER.error(
                f'Error while extracting thumbnail from audio. Name: {audio_file} stderr: {err}')
        return None
    return des_dir


async def take_ss(video_file, duration=None, total=1, gen_ss=False):
    des_dir = ospath.join('Thumbnails', f"{time()}")
    await makedirs(des_dir, exist_ok=True)
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration - (duration * 2 / 100)
    cmd = [bot_cache['pkgs'][2], "-hide_banner", "-loglevel", "error", "-ss", "",
           "-i", video_file, "-vf", "thumbnail", "-frames:v", "1", des_dir]
    tstamps = {}
    thumb_sem = Semaphore(3)
    
    async def extract_ss(eq_thumb):
        async with thumb_sem:
            cmd[5] = str((duration // total) * eq_thumb)
            tstamps[f"wz_thumb_{eq_thumb}.jpg"] = strftime("%H:%M:%S", gmtime(float(cmd[5])))
            cmd[-1] = ospath.join(des_dir, f"wz_thumb_{eq_thumb}.jpg")
            task = await create_subprocess_exec(*cmd, stderr=PIPE)
            return (task, await task.wait(), eq_thumb)
    
    tasks = [extract_ss(eq_thumb) for eq_thumb in range(1, total+1)]
    status = await gather(*tasks)
    
    for task, rtype, eq_thumb in status:
        if rtype != 0 or not await aiopath.exists(ospath.join(des_dir, f"wz_thumb_{eq_thumb}.jpg")):
            err = (await task.stderr.read()).decode().strip()
            LOGGER.error(f'Error while extracting thumbnail no. {eq_thumb} from video. Name: {video_file} stderr: {err}')
            await aiormtree(des_dir)
            return None
    return (des_dir, tstamps) if gen_ss else ospath.join(des_dir, "wz_thumb_1.jpg")


async def split_file(path, size, file_, dirpath, split_size, listener, start_time=0, i=1, inLoop=False, multi_streams=True):
    if listener.suproc == 'cancelled' or listener.suproc is not None and listener.suproc.returncode == -9:
        return False
    if listener.seed and not listener.newDir:
        dirpath = f"{dirpath}/splited_files_mltb"
        if not await aiopath.exists(dirpath):
            await mkdir(dirpath)
    user_id = listener.message.from_user.id
    user_dict = user_data.get(user_id, {})
    leech_split_size = user_dict.get(
        'split_size') or config_dict['LEECH_SPLIT_SIZE']
    parts = -(-size // leech_split_size)
    if (user_dict.get('equal_splits') or config_dict['EQUAL_SPLITS'] and 'equal_splits' not in user_dict) and not inLoop:
        split_size = ((size + parts - 1) // parts) + 1000
    if (await get_document_type(path))[0]:
        if multi_streams:
            multi_streams = await is_multi_streams(path)
        duration = (await get_media_info(path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 5000000
        while i <= parts or start_time < duration - 4:
            parted_name = f"{base_name}.part{i:03}{extension}"
            out_path = ospath.join(dirpath, parted_name)
            cmd = [bot_cache['pkgs'][2], "-hide_banner", "-loglevel", "error", "-ss", str(start_time), "-i", path,
                   "-fs", str(split_size), "-map", "0", "-map_chapters", "-1", "-async", "1", "-strict",
                   "-2", "-c", "copy", out_path]
            if not multi_streams:
                del cmd[10]
                del cmd[10]
            if listener.suproc == 'cancelled' or listener.suproc is not None and listener.suproc.returncode == -9:
                return False
            listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
            code = await listener.suproc.wait()
            if code == -9:
                return False
            elif code != 0:
                err = (await listener.suproc.stderr.read()).decode().strip()
                try:
                    await aioremove(out_path)
                except Exception:
                    pass
                if multi_streams:
                    LOGGER.warning(
                        f"{err}. Retrying without map, -map 0 not working in all situations. Path: {path}")
                    return await split_file(path, size, file_, dirpath, split_size, listener, start_time, i, True, False)
                else:
                    LOGGER.warning(
                        f"{err}. Unable to split this video, if it's size less than {MAX_SPLIT_SIZE} will be uploaded as it is. Path: {path}")
                return "errored"
            out_size = await aiopath.getsize(out_path)
            if out_size > MAX_SPLIT_SIZE:
                dif = out_size - MAX_SPLIT_SIZE
                split_size -= dif + 5000000
                await aioremove(out_path)
                return await split_file(path, size, file_, dirpath, split_size, listener, start_time, i, True, )
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f'Something went wrong while splitting, mostly file is corrupted. Path: {path}')
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {path}")
                break
            elif lpd <= 3:
                await aioremove(out_path)
                break
            start_time += lpd - 3
            i += 1
    else:
        out_path = ospath.join(dirpath, f"{file_}.")
        listener.suproc = await create_subprocess_exec("split", "--numeric-suffixes=1", "--suffix-length=3",
                                                       f"--bytes={split_size}", path, out_path, stderr=PIPE)
        code = await listener.suproc.wait()
        if code == -9:
            return False
        elif code != 0:
            err = (await listener.suproc.stderr.read()).decode().strip()
            LOGGER.error(err)
    return True

async def format_filename(file_, user_id, dirpath=None, isMirror=False, has_custom_name=False, caption=""):
    orig_file = file_
    up_path = ospath.join(dirpath, orig_file) if dirpath else None
    
    # Extract meta info once to feed both autorename and caption dynamically
    dur, qual, lang, subs = 0, "", "", ""
    fsize = ""
    # Non-media companion files (cue sheets, rip logs, playlists, images,
    # subtitles etc.) that often sit alongside audio/video in a folder can't
    # be probed by ffprobe - skip them instead of logging an ffprobe error
    # for every one of them.
    NON_MEDIA_EXTS = ('.cue', '.log', '.m3u', '.m3u8', '.txt', '.nfo', '.sfv',
                       '.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp',
                       '.srt', '.ass', '.ssa', '.vtt', '.url', '.md5', '.sha1')
    is_probeable = ospath.splitext(orig_file)[1].lower() not in NON_MEDIA_EXTS
    if up_path and is_probeable and await aiopath.exists(up_path):
        fsize = get_readable_file_size(await aiopath.getsize(up_path))
        dur, qual, lang, subs = await get_media_info(up_path, True)
    elif up_path and await aiopath.exists(up_path):
        fsize = get_readable_file_size(await aiopath.getsize(up_path))

    if not isMirror:
        file_ = await get_autorename(file_, user_id, size=fsize, media_quality=qual, lang=lang, subs=subs, caption=caption, skip=has_custom_name)

    user_dict = user_data.get(user_id, {})
    ftag, ctag = ('m', 'MIRROR') if isMirror else ('l', 'LEECH')
    prefix = config_dict.get(f'{ctag}_FILENAME_PREFIX', '') if (val:=user_dict.get(f'{ftag}prefix', '')) == '' else val
    remname = config_dict.get(f'{ctag}_FILENAME_REMNAME', '') if (val:=user_dict.get(f'{ftag}remname', '')) == '' else val
    suffix = config_dict.get(f'{ctag}_FILENAME_SUFFIX', '') if (val:=user_dict.get(f'{ftag}suffix', '')) == '' else val
    lcaption = config_dict.get('LEECH_FILENAME_CAPTION', '') if (val:=user_dict.get('lcaption', '')) == '' else val
 
    # Remove URLs starting with "www"
    file_ = re_sub(r'www\S+', '', file_, flags=IGNORECASE)

    # Remove leading/trailing dashes and extra spaces
    file_ = re_sub(r'(^\s*-\s*|(\s*-\s*){2,})', '', file_)
        
    if remname:
        if not remname.startswith('|'):
            remname = f"|{remname}"
        remname = remname.replace('\s', ' ')
        slit = remname.split("|")
        __newFileName = ospath.splitext(file_)[0]
        for rep in range(1, len(slit)):
            args = slit[rep].split(":")
            if len(args) == 3:
                __newFileName = re_sub(args[0], args[1], __newFileName, int(args[2]))
            elif len(args) == 2:
                __newFileName = re_sub(args[0], args[1], __newFileName)
            elif len(args) == 1:
                __newFileName = re_sub(args[0], '', __newFileName)
        file_ = __newFileName + ospath.splitext(file_)[1]
        LOGGER.debug(f"New Remname : {file_}")

    nfile_ = file_
    if prefix:
        nfile_ = prefix.replace('\s', ' ') + file_
        prefix_clean = re_sub(r'<.*?>', '', prefix).replace('\s', ' ')
        if not file_.startswith(prefix_clean):
            file_ = f"{prefix_clean}{file_}"

    if suffix and not isMirror:
        suffix = suffix.replace('\s', ' ')
        sufLen = len(suffix)
        fileDict = file_.split('.')
        _extIn = 1 + len(fileDict[-1])
        _extOutName = '.'.join(
            fileDict[:-1]).replace('.', ' ').replace('-', ' ')
        _newExtFileName = f"{_extOutName}{suffix}.{fileDict[-1]}"
        if len(_extOutName) > (64 - (sufLen + _extIn)):
            _newExtFileName = (
                _extOutName[: 64 - (sufLen + _extIn)]
                + f"{suffix}.{fileDict[-1]}"
            )
        file_ = _newExtFileName
    elif suffix:
        suffix = suffix.replace('\s', ' ')
        file_ = f"{ospath.splitext(file_)[0]}{suffix}{ospath.splitext(file_)[1]}" if '.' in file_ else f"{file_}{suffix}"

    cap_font = config_dict.get('CAP_FONT', '')
    # The filename can end up containing characters like & < > (e.g. a title
    # such as "Fast & Furious", or something odd an Auto Rename lookup
    # returns) - left unescaped inside an HTML tag, Telegram rejects the
    # whole caption with an entity-bounds/parse error instead of just
    # showing it as plain text, breaking the upload's completion message.
    cap_mono = f"<{cap_font}>{escape(nfile_)}</{cap_font}>" if cap_font else nfile_
    
    if lcaption and dirpath and not isMirror:
        def lowerVars(match):
            return f"{{{match.group(1).lower()}}}"

        lcaption = lcaption.replace('\|', '%%').replace('\{', '&%&').replace('\}', '$%$').replace('\s', ' ')
        slit = lcaption.split("|")
        slit[0] = re_sub(r'\{([^}]+)\}', lowerVars, slit[0])
        
        # md5 reads the WHOLE file: only do it when the caption really uses {md5_hash}, off the event loop
        md5_val = ''
        if '{md5_hash' in slit[0] and up_path and await aiopath.exists(up_path):
            md5_val = await sync_to_async(get_md5_hash, up_path)
        cap_mono = slit[0].format(
            filename = escape(nfile_),
            size = fsize,
            duration = get_readable_time(dur),
            quality = qual,
            languages = lang,
            subtitles = subs,
            md5_hash = md5_val
        )
        if len(slit) > 1:
            for rep in range(1, len(slit)):
                args = slit[rep].split(":")
                if len(args) == 3:
                    cap_mono = cap_mono.replace(args[0], args[1], int(args[2]))
                elif len(args) == 2:
                    cap_mono = cap_mono.replace(args[0], args[1])
                elif len(args) == 1:
                    cap_mono = cap_mono.replace(args[0], '')
        cap_mono = cap_mono.replace('%%', '|').replace('&%&', '{').replace('$%$', '}')
        
    return file_, cap_mono


async def get_ss(up_path, ss_no):
    thumbs_path, tstamps = await take_ss(up_path, total=min(ss_no, 250), gen_ss=True)
    th_html = f"📌 <h4>{ospath.basename(up_path)}</h4><br>📇 <b>Total Screenshots:</b> {ss_no}<br><br>"
    up_sem = Semaphore(25)
    async def telefile(thumb):
        async with up_sem:
            tele_id = await sync_to_async(upload_file, ospath.join(thumbs_path, thumb))
            return tele_id[0], tstamps[thumb]
    tasks = [telefile(thumb) for thumb in natsorted(await listdir(thumbs_path))]
    results = await gather(*tasks)
    th_html += ''.join(f'<img src="https://graph.org{tele_id}"><br><pre>Screenshot at {stamp}</pre>' for tele_id, stamp in results)
    await aiormtree(thumbs_path)
    link_id = (await telegraph.create_page(title="ScreenShots X", content=th_html))["path"]
    return f"https://graph.org/{link_id}"


async def get_mediainfo_link(up_path):
    stdout, __, _ = await cmd_exec(ssplit(f'mediainfo "{up_path}"'))
    tc = f"📌 <h4>{ospath.basename(up_path)}</h4><br><br>"
    if len(stdout) != 0:
        tc += parseinfo(stdout)
    link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]
    return f"https://graph.org/{link_id}"


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()
