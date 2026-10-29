from time import time, monotonic
from datetime import datetime
from sys import executable
from os import execl as osexecl, environ
from asyncio import create_subprocess_exec, gather, run as asyrun, wait_for
from uuid import uuid4
from base64 import b64decode
from importlib import import_module, reload

from requests import get as rget
from pytz import timezone
from bs4 import BeautifulSoup
from signal import signal, SIGINT
from aiofiles.os import path as aiopath, remove as aioremove
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, private, regex
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot import bot, bot_loop, user, bot_name, config_dict, user_data, botStartTime, LOGGER, Interval, DATABASE_URL, QbInterval, INCOMPLETE_TASK_NOTIFIER, scheduler, bot_cache
from bot.version import get_version
from .helper.ext_utils.fs_utils import start_cleanup, clean_all, exit_clean_up
from .helper.ext_utils.bot_utils import get_readable_time, cmd_exec, sync_to_async, new_task, set_commands, update_user_ldata, get_stats
from .helper.ext_utils.db_handler import DbManger
from .helper.telegram_helper.bot_commands import BotCommands
from .helper.telegram_helper.message_utils import sendMessage, editMessage, editReplyMarkup, sendFile, deleteMessage, delete_all_messages
from .helper.telegram_helper.filters import CustomFilters
from .helper.telegram_helper.button_build import ButtonMaker
from .helper.listeners.aria2_listener import start_aria2_listener
from .helper.themes import BotTheme
from .modules import authorize, clone, gd_count, gd_delete, gd_list, cancel_mirror, mirror_leech, status, torrent_search, torrent_select, ytdlp, \
                     rss, shell, eval, users_settings, bot_settings, speedtest, save_msg, images, imdb, anilist, mediainfo, mydramalist, gen_pyro_sess, \
                     gd_clean, broadcast, category_select, poster, autorename

async def stats(client, message):
    msg, btns = await get_stats(message)
    await sendMessage(message, msg, btns, photo='IMAGES')

@new_task
async def start(client, message):
    buttons = ButtonMaker()
    buttons.ubutton(BotTheme('ST_BN1_NAME'), BotTheme('ST_BN1_URL'))
    buttons.ubutton(BotTheme('ST_BN2_NAME'), BotTheme('ST_BN2_URL'))
    reply_markup = buttons.build_menu(2)
    if len(message.command) > 1 and message.command[1] == "kpsmlx":
        await deleteMessage(message)
    elif len(message.command) > 1 and config_dict['TOKEN_TIMEOUT']:
        userid = message.from_user.id
        encrypted_url = message.command[1]
        input_token, pre_uid = (b64decode(encrypted_url.encode()).decode()).split('&&')
        if int(pre_uid) != userid:
            return await sendMessage(message, BotTheme('OWN_TOKEN_GENERATE'))
        data = user_data.get(userid, {})
        if 'token' not in data or data['token'] != input_token:
            return await sendMessage(message, BotTheme('USED_TOKEN'))
        elif config_dict['LOGIN_PASS'] is not None and data['token'] == config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('LOGGED_PASSWORD'))
        buttons.ibutton(BotTheme('ACTIVATE_BUTTON'), f'pass {input_token}', 'header')
        reply_markup = buttons.build_menu(2)
        msg = BotTheme('TOKEN_MSG', token=input_token, validity=get_readable_time(int(config_dict["TOKEN_TIMEOUT"])))
        return await sendMessage(message, msg, reply_markup)
    elif await CustomFilters.authorized(client, message):
        start_string = BotTheme('ST_MSG', help_command=f"/{BotCommands.HelpCommand}")
        await sendMessage(message, start_string, reply_markup, photo='IMAGES')
    elif config_dict['BOT_PM']:
        await sendMessage(message, BotTheme('ST_BOTPM'), reply_markup, photo='IMAGES')
    else:
        await sendMessage(message, BotTheme('ST_UNAUTH'), reply_markup, photo='IMAGES')
    await DbManger().update_pm_users(message.from_user.id)


async def token_callback(_, query):
    user_id = query.from_user.id
    input_token = query.data.split()[1]
    data = user_data.get(user_id, {})
    if 'token' not in data or data['token'] != input_token:
        return await query.answer('Already Used, Generate New One', show_alert=True)
    update_user_ldata(user_id, 'token', str(uuid4()))
    update_user_ldata(user_id, 'time', time())
    await query.answer('Activated Temporary Token!', show_alert=True)
    kb = query.message.reply_markup.inline_keyboard[1:]
    kb.insert(0, [InlineKeyboardButton(BotTheme('ACTIVATED'), callback_data='pass activated')])
    await editReplyMarkup(query.message, InlineKeyboardMarkup(kb))


async def login(_, message):
    if config_dict['LOGIN_PASS'] is None:
        return
    elif len(message.command) > 1:
        user_id = message.from_user.id
        input_pass = message.command[1]
        if user_data.get(user_id, {}).get('token', '') == config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('LOGGED_IN'))
        if input_pass != config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('INVALID_PASS'))
        update_user_ldata(user_id, 'token', config_dict['LOGIN_PASS'])
        return await sendMessage(message, BotTheme('PASS_LOGGED'))
    else:
        await sendMessage(message, BotTheme('LOGIN_USED'))



RESTART_FILES = ('.restartmsg', '/tmp/.kpsml_restartmsg')


def _restartmsg_path():
    from os.path import isfile
    return next((f for f in RESTART_FILES if isfile(f)), None)


def _rm_restartmsg():
    from os import remove
    for f in RESTART_FILES:
        try:
            remove(f)
        except Exception:
            pass


async def restart(client, message):
    restart_message = await sendMessage(message, BotTheme('RESTARTING'))
    if isinstance(restart_message, str):
        chat_id, msg_id = message.chat.id, message.id
    else:
        chat_id, msg_id = restart_message.chat.id, restart_message.id
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        for interval in [QbInterval, Interval]:
            if interval:
                interval[0].cancel()
    except Exception as e:
        LOGGER.error(f"restart: stop scheduler/intervals failed: {e}")
    # every step has a timeout so /r can never hang forever
    for coro in (delete_all_messages(), sync_to_async(clean_all)):
        try:
            await wait_for(coro, 30)
        except Exception as e:
            LOGGER.error(f"restart: cleanup step failed/timeout: {e!r}")
    # close the Telegram session cleanly (flushes the sqlite WAL) before update.py touches the folder
    try:
        await wait_for(bot.stop(), 15)
    except Exception as e:
        LOGGER.error(f"restart: bot.stop failed/timeout: {e!r}")
    try:
        proc1 = await create_subprocess_exec('pkill', '-9', '-f', f'gunicorn|{bot_cache["pkgs"][-1]}')
        proc2 = await create_subprocess_exec('python3', 'update.py')
        try:
            await wait_for(gather(proc1.wait(), proc2.wait()), 90)
        except Exception as e:
            LOGGER.error(f"restart: pkill/update timeout: {e!r}")
            for pr in (proc1, proc2):
                try:
                    pr.kill()
                except Exception:
                    pass
    except Exception as e:
        LOGGER.error(f"restart: subprocess failed: {e!r}")
    # Written AFTER update.py: update.py does `git reset --hard`, which deletes files
    # from the repo dir. A copy in /tmp survives it, so the "Restarted" edit always works.
    for rf in RESTART_FILES:
        try:
            with open(rf, "w") as f:
                f.write(f"{chat_id}\n{msg_id}\n")
        except Exception as e:
            LOGGER.error(f"restartmsg write failed ({rf}): {e}")
    osexecl(executable, executable, "-m", "bot")


async def ping(_, message):
    start_time = monotonic()
    reply = await sendMessage(message, BotTheme('PING'))
    end_time = monotonic()
    await editMessage(reply, BotTheme('PING_VALUE', value=int((end_time - start_time) * 1000)))


async def log(_, message):
    try:
        size = await aiopath.getsize('log.txt') if await aiopath.exists('log.txt') else 0
    except Exception:
        size = 0
    if size == 0:
        return await sendMessage(message, "<b>Log is empty</b> (logging level is low). Set <code>LOG_LEVEL=INFO</code> to get more logs.")
    send_path = 'log.txt'
    if size > 8 * 1024 * 1024:  # keep only the tail, Telegram/slow upload safe
        try:
            async with aiopen('log.txt', 'rb') as f:
                await f.seek(size - 4 * 1024 * 1024)
                data = await f.read()
            async with aiopen('log_tail.txt', 'wb') as f:
                await f.write(data)
            send_path = 'log_tail.txt'
        except Exception as e:
            LOGGER.error(f"log tail failed: {e}")
    buttons = ButtonMaker()
    buttons.ibutton(BotTheme('LOG_DISPLAY_BT'), f'kpsmlx {message.from_user.id} logdisplay')
    buttons.ibutton(BotTheme('WEB_PASTE_BT'), f'kpsmlx {message.from_user.id} webpaste')
    # uploads go through a media session; if that one is hung, don't leave /log silent
    try:
        res = await wait_for(sendFile(message, send_path, buttons=buttons.build_menu(1)), 60)
    except Exception as e:
        res = f"{type(e).__name__}: {e}"
    if isinstance(res, str):
        try:
            async with aiopen('log.txt', 'rb') as f:
                await f.seek(max(0, size - 3200))
                tail = (await f.read()).decode('utf-8', 'ignore')
        except Exception:
            tail = ''
        from html import escape as _esc
        await sendMessage(message, f"<b>Log file upload failed</b> (<code>{_esc(res[:150])}</code>)\n<b>Last lines:</b>\n<pre>{_esc(tail[-3200:])}</pre>")


async def search_images():
    if not (query_list := config_dict['IMG_SEARCH']):
        return
    try:
        total_pages = config_dict['IMG_PAGE']
        base_url = "https://www.wallpaperflare.com/search"
        for query in query_list:
            query = query.strip().replace(" ", "+")
            for page in range(1, total_pages + 1):
                url = f"{base_url}?wallpaper={query}&width=1280&height=720&page={page}"
                r = await sync_to_async(rget, url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")
                images = soup.select('img[data-src^="https://c4.wallpaperflare.com/wallpaper"]')
                if len(images) == 0:
                    LOGGER.info("Maybe Site is Blocked on your Server, Add Images Manually !!")
                for img in images:
                    img_url = img['data-src']
                    if img_url not in config_dict['IMAGES']:
                        config_dict['IMAGES'].append(img_url)
        if len(config_dict['IMAGES']) != 0:
            config_dict['STATUS_LIMIT'] = 2
        if DATABASE_URL:
            await DbManger().update_config({'IMAGES': config_dict['IMAGES'], 'STATUS_LIMIT': config_dict['STATUS_LIMIT']})
    except Exception as e:
        LOGGER.error(f"An error occurred: {e}")


async def bot_help(client, message):
    buttons = ButtonMaker()
    user_id = message.from_user.id
    buttons.ibutton(BotTheme('BASIC_BT'), f'kpsmlx {user_id} guide basic')
    buttons.ibutton(BotTheme('USER_BT'), f'kpsmlx {user_id} guide users')
    buttons.ibutton(BotTheme('MICS_BT'), f'kpsmlx {user_id} guide miscs')
    buttons.ibutton(BotTheme('O_S_BT'), f'kpsmlx {user_id} guide admin')
    buttons.ibutton(BotTheme('CLOSE_BT'), f'kpsmlx {user_id} close')
    await sendMessage(message, BotTheme('HELP_HEADER'), buttons.build_menu(2))


async def restart_notification():
    now=datetime.now(timezone(config_dict['TIMEZONE']))
    if rpath := _restartmsg_path():
        try:
            with open(rpath) as f:
                chat_id, msg_id = map(int, f)
        except Exception as e:
            LOGGER.error(f"restartmsg read failed: {e}")
            chat_id, msg_id = 0, 0
    else:
        chat_id, msg_id = 0, 0

    async def send_incompelete_task_message(cid, msg):
        try:
            if msg.startswith("⌬ <b><i>Restarted Successfully!</i></b>"):
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=msg, disable_web_page_preview=True)
                _rm_restartmsg()
            else:
                await bot.send_message(chat_id=cid, text=msg, disable_web_page_preview=True, disable_notification=True)
        except Exception as e:
            LOGGER.error(e)

    if INCOMPLETE_TASK_NOTIFIER and DATABASE_URL:
        if notifier_dict := await DbManger().get_incomplete_tasks():
            for cid, data in notifier_dict.items():
                msg = BotTheme('RESTART_SUCCESS', time=now.strftime('%I:%M:%S %p'), date=now.strftime('%d/%m/%y'), timz=config_dict['TIMEZONE'], version=get_version()) if cid == chat_id else BotTheme('RESTARTED')
                msg += "\n\n⌬ <b><i>Incomplete Tasks!</i></b>"
                for tag, links in data.items():
                    msg += f"\n➲ <b>User:</b> {tag}\n┖ <b>Tasks:</b>"
                    for index, link in enumerate(links, start=1):
                        msg_link, source = next(iter(link.items()))
                        msg += f" {index}. <a href='{source}'>S</a> ->  <a href='{msg_link}'>L</a> |"
                        if len(msg.encode()) > 4000:
                            await send_incompelete_task_message(cid, msg)
                            msg = ''
                if msg:
                    await send_incompelete_task_message(cid, msg)

    if chat_id and msg_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=BotTheme('RESTART_SUCCESS', time=now.strftime('%I:%M:%S %p'), date=now.strftime('%d/%m/%y'), timz=config_dict['TIMEZONE'], version=get_version()))
        except Exception as e:
            LOGGER.error(f"Restart message edit failed: {e}")
        _rm_restartmsg()


async def log_check():
    if config_dict['LEECH_LOG_ID']:
        for chat_id in config_dict['LEECH_LOG_ID'].split():
            chat_id, *topic_id = chat_id.split(":")
            try:
                try:
                    chat = await bot.get_chat(int(chat_id))
                except Exception:
                    LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make sure the Bot is Added!")
                    continue
                if chat.type == ChatType.CHANNEL:
                    if not (await chat.get_member(bot.me.id)).privileges.can_post_messages:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the Bot is Admin in Channel to Connect!")
                        continue
                    if user and not (await chat.get_member(user.me.id)).privileges.can_post_messages:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the User is Admin in Channel to Connect!")
                        continue
                elif chat.type == ChatType.SUPERGROUP:
                    if not (await chat.get_member(bot.me.id)).status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the Bot is Admin in Group to Connect!")
                        continue
                    if user and not (await chat.get_member(user.me.id)).status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the User is Admin in Group to Connect!")
                        continue
                LOGGER.info(f"Connected Chat ID : {chat_id}")
            except Exception as e:
                LOGGER.error(f"Not Connected Chat ID : {chat_id}, ERROR: {e}")
    

async def _self_restart():
    # same as /r but without a chat message: stop client, kill helpers, re-exec
    try:
        await wait_for(bot.stop(), 10)
    except Exception:
        pass
    try:
        pk = await create_subprocess_exec('pkill', '-9', '-f', f'gunicorn|{bot_cache["pkgs"][-1]}')
        await wait_for(pk.wait(), 10)
    except Exception:
        pass
    osexecl(executable, executable, "-m", "bot")


async def tg_health_watchdog():
    # Seen in the logs: Telegram connection dies ("Session restart failed: Request timed out"),
    # uploads hang, commands answer minutes late, and only a manual /r helps. This does the /r for you:
    #   TG_DEAD_RECONNECT_MIN (3)  -> reconnect the Telegram client
    #   TG_DEAD_RESTART_MIN   (10) -> restart the whole bot process       (0 = off)
    from asyncio import sleep as asleep
    soft = int(environ.get('TG_DEAD_RECONNECT_MIN', '3') or 0) * 60
    hard = int(environ.get('TG_DEAD_RESTART_MIN', '10') or 0) * 60
    if not soft and not hard:
        return
    down_since, soft_done = None, False
    while True:
        await asleep(30)
        try:
            await wait_for(bot.get_me(), 25)
            if down_since is not None:
                LOGGER.warning(f"Telegram reachable again after {int(monotonic() - down_since)}s")
            down_since, soft_done = None, False
            continue
        except Exception as e:
            err = e
        now = monotonic()
        if down_since is None:
            down_since = now
            LOGGER.warning(f"Telegram not reachable: {err!r}")
        dead = now - down_since
        if hard and dead >= hard:
            LOGGER.error(f"Telegram unreachable for {int(dead)}s - restarting the bot process")
            await _self_restart()
        elif soft and dead >= soft and not soft_done:
            soft_done = True
            LOGGER.error(f"Telegram unreachable for {int(dead)}s - reconnecting the client")
            try:
                await wait_for(bot.restart(), 60)
            except Exception as e:
                LOGGER.error(f"client reconnect failed: {e!r}")


async def loop_lag_watch():
    # Heartbeat on the loop + a watcher THREAD. When the loop stops answering for >1.5s the
    # thread logs the exact stack the loop is stuck in, so the blocker shows up in /log.
    import sys, threading, traceback
    from asyncio import sleep as asleep
    state = {'beat': monotonic(), 'tid': threading.get_ident(), 'reported': 0.0}

    def watcher():
        import time as _t
        while True:
            _t.sleep(0.5)
            lag = monotonic() - state['beat']
            if lag > 1.5 and state['reported'] != state['beat']:
                state['reported'] = state['beat']
                try:
                    frame = sys._current_frames().get(state['tid'])
                    stack = ''.join(traceback.format_stack(frame)[-6:]) if frame else '?'
                    LOGGER.warning(f"Event loop blocked >{lag:.1f}s at:\n{stack}")
                except Exception:
                    pass

    threading.Thread(target=watcher, daemon=True, name='loop-watchdog').start()
    while True:
        t = monotonic()
        state['beat'] = t
        await asleep(0.5)
        lag = monotonic() - t - 0.5
        if lag > 2:
            LOGGER.warning(f"Event loop lagged {lag:.1f}s (something blocked the bot)")


async def main():
    # GC tuning: random 2-6s stalls landed on harmless lines (a whole-process pause). Freezing the
    # start-up objects and collecting less often shortens garbage-collector pauses. GC_TUNE=false to skip.
    if environ.get('GC_TUNE', 'true').lower() not in ('0', 'false', 'no'):
        import gc
        gc.collect()
        gc.freeze()
        gc.set_threshold(10000, 20, 50)
    from bot.helper.ext_utils.tg_recover import install_write_hint
    install_write_hint()
    bot_loop.create_task(loop_lag_watch())
    bot_loop.create_task(tg_health_watchdog())
    from bot.helper.telegram_helper.button_style import selftest as _btn_selftest
    await _btn_selftest(bot)
    from bot.helper.ext_utils.ram_guard import ram_guard_loop
    bot_loop.create_task(ram_guard_loop())
    await gather(start_cleanup(), torrent_search.initiate_search_tools(), restart_notification(), search_images(), set_commands(bot), log_check())
    await sync_to_async(start_aria2_listener, wait=False)
    
    bot.add_handler(MessageHandler(
        start, filters=command(BotCommands.StartCommand) & private))
    bot.add_handler(CallbackQueryHandler(
        token_callback, filters=regex(r'^pass')))
    bot.add_handler(MessageHandler(
        login, filters=command(BotCommands.LoginCommand) & private))
    bot.add_handler(MessageHandler(log, filters=command(
        BotCommands.LogCommand) & CustomFilters.sudo))
    bot.add_handler(MessageHandler(restart, filters=command(
        BotCommands.RestartCommand) & CustomFilters.sudo))
    bot.add_handler(MessageHandler(ping, filters=command(
        BotCommands.PingCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(bot_help, filters=command(
        BotCommands.HelpCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(stats, filters=command(
        BotCommands.StatsCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    LOGGER.info(f"KPSML-X Bot [@{bot_name}] Started!")
    if user:
        LOGGER.info(f"KPSML-X User [@{user.me.username}] Ready!")
    signal(SIGINT, exit_clean_up)

async def stop_signals():
    if user:
        await gather(bot.stop(), user.stop())
    else:
        await bot.stop()


bot_run = bot_loop.run_until_complete
bot_run(main())
bot_run(idle())
bot_run(stop_signals())
