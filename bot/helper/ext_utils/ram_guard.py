"""RAM watchdog for small dynos (Heroku Basic = 512 MB).

When the dyno runs out of RAM everything slows to a crawl and only a restart helps. This module
  * measures the REAL container RAM (cgroup anon memory, page cache not counted),
  * logs a WARNING with a per-process breakdown when it gets high (so /log shows who ate it),
  * runs gc + malloc_trim, and
  * when it is really critical and nothing is running, shuts the idle qBittorrent down
    (bot.get_client() starts it again automatically on the next qBit task).
Env: RAM_GUARD=false to disable, RAM_WARN_PCT (80), RAM_CRIT_PCT (90), RAM_GUARD_INTERVAL (120s).
"""
import gc
from asyncio import sleep
from os import environ

from bot import LOGGER, download_dict, download_dict_lock, bot_cache
from bot.helper.ext_utils.bot_utils import sync_to_async


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def container_memory():
    """(real_used_bytes, limit_bytes) or None."""
    limit = used = None
    cur, mx = _read('/sys/fs/cgroup/memory.current'), _read('/sys/fs/cgroup/memory.max')
    if cur and mx and mx != 'max':
        used, limit = int(cur), int(mx)
        stat = _read('/sys/fs/cgroup/memory.stat') or ''
        for line in stat.splitlines():
            if line.startswith('anon '):
                used = int(line.split()[1])
                break
    else:
        u1, l1 = _read('/sys/fs/cgroup/memory/memory.usage_in_bytes'), _read('/sys/fs/cgroup/memory/memory.limit_in_bytes')
        if u1 and l1:
            used, limit = int(u1), int(l1)
            for line in (_read('/sys/fs/cgroup/memory/memory.stat') or '').splitlines():
                if line.startswith('rss '):
                    used = int(line.split()[1])
                    break
    if used is None or not limit or limit >= (1 << 60):
        # Heroku hides the cgroup files: sum the RSS of the bot and its children against the dyno size
        try:
            from psutil import Process
            me = Process()
            used = me.memory_info().rss + sum(c.memory_info().rss for c in me.children(recursive=True))
            lim_mb = float(environ.get('RAM_LIMIT_MB') or environ.get('MEMORY_AVAILABLE') or 0)
            if not lim_mb and environ.get('DYNO'):
                lim_mb = 512.0      # Heroku Basic / Standard-1X
            if not lim_mb:
                return None
            return used, int(lim_mb * 1024 * 1024)
        except Exception:
            return None
    return used, limit


def trim_memory():
    try:
        from ctypes import CDLL
        CDLL('libc.so.6').malloc_trim(0)
    except Exception:
        pass


def _breakdown():
    try:
        from psutil import Process
        me = Process()
        kids = {}
        for c in me.children(recursive=True):
            try:
                kids[c.name()] = kids.get(c.name(), 0) + c.memory_info().rss
            except Exception:
                pass
        kid_s = ' '.join(f'{k}={v >> 20}MB' for k, v in sorted(kids.items(), key=lambda x: -x[1]))
        return f"bot={me.memory_info().rss >> 20}MB {kid_s}"
    except Exception:
        return ''


def _qbit_running():
    from socket import create_connection
    try:
        create_connection(('127.0.0.1', 8090), timeout=0.4).close()
        return True
    except Exception:
        return False


def _stop_idle_qbit():
    from bot import get_client
    if not _qbit_running():
        return False
    c = get_client()
    if c.torrents_info():
        return False
    c.app_shutdown()
    bot_cache['qbit_idle_stopped'] = True
    return True


async def ram_guard_loop():
    if environ.get('RAM_GUARD', 'true').lower() in ('0', 'false', 'no'):
        return
    warn = float(environ.get('RAM_WARN_PCT', '80') or 80)
    crit = float(environ.get('RAM_CRIT_PCT', '90') or 90)
    every = int(environ.get('RAM_GUARD_INTERVAL', '120') or 120)
    last_warn = 0
    _m = container_memory()
    LOGGER.warning(f"RAM guard on: {'limit %dMB, now %.0f%%' % (_m[1] >> 20, _m[0] * 100 / _m[1]) if _m else 'cannot read container memory (guard idle)'}")
    while True:
        await sleep(every)
        try:
            mem = container_memory()
            if not mem:
                continue
            pct = mem[0] * 100 / mem[1]
            if pct < warn:
                last_warn = 0
                continue
            # log when it first gets high and again every ~10 min while it stays high
            last_warn = (last_warn + 1) % max(1, 600 // every)
            if last_warn == 1 or pct >= crit:
                LOGGER.warning(f"RAM {pct:.0f}% of {mem[1] >> 20}MB | {await sync_to_async(_breakdown)}")
            gc.collect()
            trim_memory()
            if pct >= crit:
                async with download_dict_lock:
                    busy = bool(download_dict)
                if not busy and await sync_to_async(_stop_idle_qbit):
                    LOGGER.warning("RAM critical and idle: qBittorrent stopped (it restarts on the next qBit task)")
        except Exception as e:
            LOGGER.error(f"ram_guard: {e!r}")
