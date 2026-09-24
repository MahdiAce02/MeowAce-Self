import os
import sys
import json
import asyncio
from telethon import TelegramClient, events
from telethon.errors import RPCError

from modules.autocatch import autocatch_command, handle_autocatch_trigger, get_catch_cfg
from modules.autobat import autobat_command, handle_autobat_trigger, handle_manual_bat, get_bat_cfg
from modules.automeow import automeow_command, resume_automeow_tasks, get_meow_config, get_chat_meow_mode, process_schedule_event
from modules.autofish import autofish_command, resume_autofish_tasks, get_fish_cfg, get_chat_fish_mode, process_fish_schedule_event
from modules.autofridge import autofridge_command, resume_autofridge_tasks, get_fridge_cfg, get_chat_fridge_mode, process_fridge_schedule_event
from modules.show import show_command, get_show_mode
from modules.sched import sched_command
from modules.alias import alias_command, resolve_alias
from modules.info import info_command
from modules.proxy import get_proxy_kwargs

# configuration filenames
CONFIG_FILE = "config.json"
EXAMPLE_CONFIG_FILE = "config.example.json"

def read_config():
    # If bot_config.json exists with a valid bot_token, auto-enable multi_session
    if os.path.exists("bot_config.json"):
        try:
            with open("bot_config.json", 'r', encoding='utf-8') as bf:
                b_cfg = json.load(bf)
                token = b_cfg.get("bot_token")
                if token and token != "YOUR_BOT_TOKEN" and token != "YOUR_BOT_TOKEN_HERE":
                    cfg = {}
                    if os.path.exists(CONFIG_FILE):
                        try:
                            with open(CONFIG_FILE, 'r', encoding='utf-8') as cf:
                                cfg = json.load(cf)
                        except Exception:
                            pass
                    if not cfg.get("multi_session"):
                        cfg["multi_session"] = True
                        try:
                            with open(CONFIG_FILE, 'w', encoding='utf-8') as cf:
                                json.dump(cfg, cf, indent=2, ensure_ascii=False)
                        except Exception:
                            pass
                    return cfg
        except Exception:
            pass

    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(EXAMPLE_CONFIG_FILE):
            with open(EXAMPLE_CONFIG_FILE, 'r', encoding='utf-8') as s_file:
                c_data = s_file.read()
            with open(CONFIG_FILE, 'w', encoding='utf-8') as d_file:
                d_file.write(c_data)
        else:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as d_file:
                d_file.write('{"multi_session": false}')

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg_json = json.load(f)
            if cfg_json.get("multi_session", False):
                return cfg_json
            a_id = cfg_json.get("api_id")
            a_hash = cfg_json.get("api_hash")
            if not a_id or a_id == 123456 or not a_hash or a_hash == "YOUR_API_HASH_HERE":
                print(f"[!] Invalid api_id/api_hash in '{CONFIG_FILE}'.")
                sys.exit(1)
            return cfg_json
    except Exception as err:
        print(f"[!] Config load error: {err}")
        sys.exit(1)

async def status_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    chat_id = ev.chat_id
    cid_str = str(chat_id)
    
    m_mode, m_count = get_chat_meow_mode(me_id, cid_str)
    if m_mode == "instant":
        meow_st = "🟢 فعال (لحظه‌ای ⚡)"
    elif m_mode == "schedule":
        meow_st = f"🟢 فعال (زماندار سرور 📅 - {m_count} پیام)"
    else:
        meow_st = "🔴 غیرفعال"
    
    f_info = get_chat_fish_mode(me_id, cid_str)
    if f_info.get("active"):
        f_type = f_info.get("type")
        f_act = f_info.get("action")
        f_cnt = f_info.get("count", 1)
        if f_type == "instant":
            fish_st = f"🟢 فعال (لحظه‌ای ⚡ - {f_act})"
        else:
            fish_st = f"🟢 فعال (زماندار سرور 📅 - {f_act}, {f_cnt} پیام)"
    else:
        fish_st = "🔴 غیرفعال"
    
    fr_info = get_chat_fridge_mode(me_id, cid_str)
    if fr_info.get("active"):
        fr_type = fr_info.get("type")
        fr_act = fr_info.get("action")
        fr_cnt = fr_info.get("count", 1)
        if fr_type == "instant":
            fridge_st = f"🟢 فعال (لحظه‌ای ⚡ - {fr_act})"
        else:
            fridge_st = f"🟢 فعال (زماندار سرور 📅 - {fr_act}, {fr_cnt} پیام)"
    else:
        fridge_st = "🔴 غیرفعال"
    
    c_cfg = get_catch_cfg(me_id).get(cid_str, {})
    catch_st = "🟢 فعال" if c_cfg.get("status") else "🔴 غیرفعال"
    c_delay = c_cfg.get("delay", 0)
    c_times = c_cfg.get("times", 1)

    b_cfg = get_bat_cfg(me_id).get(cid_str, {})
    bat_st = "🟢 فعال" if b_cfg.get("status") else "🔴 غیرفعال"
    b_delay = b_cfg.get("delay", 1)
    
    sh_st = "🟢 ON" if get_show_mode(me_id) else "🔴 OFF"

    msg_out = (
        f"🐾 **وضعیت ربات خودکار MeowAce-Self**\n\n"
        f"📍 **چت فعلی:** `{chat_id}`\n\n"
        f"🐱 **AutoMeow:** {meow_st}\n"
        f"🎣 **AutoFish:** {fish_st}\n"
        f"🧊 **AutoFridge:** {fridge_st}\n"
        f"🐈 **AutoCatch:** {catch_st} *(Delay: {c_delay}s, Times: {c_times})*\n"
        f"🦇 **AutoBat:** {bat_st} *(Delay: {b_delay}s)*\n"
        f"👁️ **Show Mode:** {sh_st}\n\n"
        f"💡 **دستورات راهنما:**\n"
        f"▸ `/automeow` ── مدیریت ارسال خودکار کلمات میو (instant/schedule/off)\n"
        f"▸ `/autofish` ── مدیریت ماهیگیری خودکار\n"
        f"▸ `/autofridge` ── مدیریت پخت و فروش خودکار یخچال\n"
        f"▸ `/autocatch` ── مدیریت نجات خودکار گربه‌ها\n"
        f"▸ `/autobat` ── مدیریت شکار خودکار خفاش 🦇\n"
        f"▸ `/show` ── خاموش/روشن کردن پاسخ به دستورات\n"
        f"▸ `/sched` ── زمانبندی پیام روی سرور تلگرام\n"
        f"▸ `/alias` ── تعریف اسم کوتاه و میانبر دستورات\n"
        f"▸ `/info` ── دریافت آیدی و مشخصات کاربر/چت (با ریپلای یا یوزرنیم)\n"
        f"▸ `/status` ── مشاهده وضعیت در این چت"
    )
    await ev.edit(msg_out)

async def main():
    conf = read_config()

    # Route to MultiSession Bot Manager if enabled
    if conf.get("multi_session", False):
        print("[+] Multi-Session mode enabled. Starting Telegram Bot Manager...")
        from bot_manager import start_bot_manager
        await start_bot_manager(conf)
        return

    api_id = conf["api_id"]
    api_hash = conf["api_hash"]
    
    print("[+] Connecting Telethon client...")
    proxy_kwargs = get_proxy_kwargs(conf)
    client = TelegramClient("meowace_self", api_id, api_hash, **proxy_kwargs)
    try:
        await client.start()
    except Exception as e:
        print(f"[!] Error starting Telethon client: {e}")
        if proxy_kwargs:
            print("[!] Note: Proxy is enabled. If connection fails or times out, please verify your proxy settings.")
        sys.exit(1)
    
    me = await client.get_me()
    client.uid = me.id
    print(f"[+] Logged in as: {me.first_name} (@{me.username or 'N/A'}) [ID: {me.id}]")

    @client.on(events.NewMessage)
    async def _automeow_schedule_listener(ev):
        await process_schedule_event(ev)

    @client.on(events.NewMessage)
    async def _autofish_schedule_listener(ev):
        await process_fish_schedule_event(ev)

    @client.on(events.NewMessage)
    async def _autofridge_schedule_listener(ev):
        await process_fridge_schedule_event(ev)

    # high priority autocatch trigger listeners
    @client.on(events.NewMessage)
    async def _autocatch_trigger_new(ev):
        await handle_autocatch_trigger(ev, is_edit=False)

    @client.on(events.MessageEdited)
    async def _autocatch_trigger_edit(ev):
        await handle_autocatch_trigger(ev, is_edit=True)

    @client.on(events.NewMessage)
    async def _autobat_trigger_new(ev):
        await handle_autobat_trigger(ev)

    # bind event handlers
    @client.on(events.NewMessage(pattern='(?i)^/?automeow($|\\s+)'))
    async def _automeow_h(ev):
        await automeow_command(ev)

    @client.on(events.NewMessage(pattern='(?i)^/?autofish($|\\s+)'))
    async def _autofish_h(ev):
        await autofish_command(ev)

    @client.on(events.NewMessage(pattern='(?i)^/?autofridge($|\\s+)'))
    async def _autofridge_h(ev):
        await autofridge_command(ev)

    @client.on(events.NewMessage(pattern='(?i)^/?autocatch($|\\s+)'))
    async def _autocatch_h(ev):
        await autocatch_command(ev)

    @client.on(events.NewMessage(pattern='(?i)^/?autobat($|\\s+)'))
    async def _autobat_h(ev):
        await autobat_command(ev)

    @client.on(events.NewMessage(outgoing=True))
    async def _manual_bat_h(ev):
        # حالت دستی bat باید قبل از alias اجرا شود؛ اگر مصرف شد دیگر کاری نکن
        try:
            handled = await handle_manual_bat(ev)
        except Exception as e:
            print(f"[!] manual bat handler error: {e}")
            handled = False
        # اگر handled بود، alias نباید دوباره همان پیام را پردازش کند (پیام حذف شده)

    @client.on(events.NewMessage(pattern='(?i)^/?show(?:\\s+(.+))?'))
    async def _show_h(ev):
        await show_command(ev)

    @client.on(events.NewMessage(pattern='(?i)^/?sched(?:\\s+(.+))?'))
    async def _sched_h(ev):
        await sched_command(ev)

    @client.on(events.NewMessage(pattern=r'(?i)^[/.=]?alias(?:\s+(.+))?$'))
    async def _alias_h(ev):
        await alias_command(ev)

    @client.on(events.NewMessage(pattern=r'(?i)^[/.=!]?(?:info|id)($|\s+.*)'))
    async def _info_h(ev):
        await info_command(ev)

    @client.on(events.NewMessage(pattern='(?i)^/?(status|meowhelp|help)($|\\s+)'))
    async def _status_h(ev):
        await status_command(ev)

    _dispatched_alias_ids = set()

    @client.on(events.NewMessage(outgoing=True))
    async def _alias_interceptor(ev):
        if ev.id in _dispatched_alias_ids:
            _dispatched_alias_ids.discard(ev.id)
            return

        raw = ev.raw_text or ""
        if not raw:
            return
        # پیام دستی batt قبلا مصرف (و حذف) شده؛ alias روی آن اجرا نشود
        if raw.strip().lower().lstrip("/.=!") == "batt" and getattr(ev, 'is_reply', False):
            return
        is_alias, cmds = resolve_alias(client.uid, raw)
        if is_alias and cmds:
            for c in cmds:
                try:
                    sent = await client.send_message(ev.chat_id, c)
                    if sent:
                        _dispatched_alias_ids.add(sent.id)
                        if len(_dispatched_alias_ids) > 1000:
                            _dispatched_alias_ids.clear()
                except RPCError as rpc:
                    print(f"[!] alias send error: {rpc}")
                except Exception:
                    pass

    # restore loops
    asyncio.create_task(resume_automeow_tasks(client))
    asyncio.create_task(resume_autofish_tasks(client))
    asyncio.create_task(resume_autofridge_tasks(client))
    print("[+] MeowAce-Self client ready.")

    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[-] Shutting down.")
