import re
import time
import random
import asyncio
import datetime
from telethon import events
from telethon.errors import RPCError
from modules.utils import get_chat_lock, convert_persian_digits, load_json_setting, save_json_setting, send_message_safe
from modules.show import safe_edit_or_silent

active_meow_loops = {}
last_sched_times = {}
main_cooldown_cache = {}  # (uid, cid) -> int (main cooldown in seconds)

def get_meow_config(u_id: int) -> dict:
    return load_json_setting(f"automeow_{u_id}.json", default={})

def save_meow_config(u_id: int, config: dict):
    save_json_setting(f"automeow_{u_id}.json", config)

def get_chat_meow_mode(u_id: int, cid_str: str):
    config = get_meow_config(u_id)
    modes = config.get("modes", {})
    val = modes.get(cid_str)
    if isinstance(val, dict):
        return val.get("mode", "off"), val.get("count", 1)
    elif isinstance(val, str):
        return val, 1
    return "off", 1

def set_chat_meow_mode(u_id: int, cid_str: str, mode: str, count: int = 1):
    config = get_meow_config(u_id)
    if "modes" not in config:
        config["modes"] = {}
    if mode == "off":
        config["modes"].pop(cid_str, None)
    else:
        config["modes"][cid_str] = {"mode": mode, "count": count}
    save_meow_config(u_id, config)

def parse_cooldown(txt: str):
    if not txt:
        return None
    t_str = convert_persian_digits(txt)
    
    if any(k in t_str for k in ["ماهی", "ماهیا", "خوابن", "قلاب", "طعمه", "یخچال"]):
        return None

    m_colon = re.search(r'(\d+):(\d+)', t_str)
    if m_colon:
        return int(m_colon.group(1)) * 60 + int(m_colon.group(2))
    
    m_match = re.search(r'(\d+)\s*دقیقه', t_str)
    s_match = re.search(r'(\d+)\s*ثانیه', t_str)
    m_val = int(m_match.group(1)) if m_match else 0
    s_val = int(s_match.group(1)) if s_match else 0
    if m_val or s_val:
        return m_val * 60 + s_val
    return None

async def schedule_next_meow(client, cid: int, remaining_cd: int, main_cd: int = 255, target_count: int = 1):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    # Check existing scheduled messages in chat queue
    try:
        existing_sched = await client.get_messages(cid, scheduled=True)
    except Exception:
        existing_sched = []
        
    existing_count = len(existing_sched) if existing_sched else 0
    needed = target_count - existing_count
    if needed <= 0:
        return

    words = ["مع", "میو", "میو میو", "معو"]
    now_ts = time.time()
    
    if existing_count == 0:
        buf = random.randint(4, 9) if remaining_cd > 50 else 2
        next_ts = now_ts + remaining_cd + buf
    else:
        max_existing_ts = max(msg.date.timestamp() for msg in existing_sched)
        buf = random.randint(4, 9) if main_cd > 50 else 2
        next_ts = max(max_existing_ts + main_cd + buf, now_ts + remaining_cd + buf)

    for i in range(needed):
        word = random.choice(words)
        target_dt = datetime.datetime.fromtimestamp(next_ts, tz=datetime.timezone.utc)
        try:
            await client.send_message(cid, word, schedule=target_dt)
            print(f"[AutoMeow] Scheduled meow #{existing_count + i + 1} for chat {cid} at {target_dt}")
        except Exception as e:
            print(f"[!] schedule send error in {cid}: {e}")
            break
            
        buf = random.randint(4, 9) if main_cd > 50 else 2
        next_ts += main_cd + buf

async def process_schedule_event(ev):
    client = ev.client
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    cid = ev.chat_id
    
    mode, count = get_chat_meow_mode(uid, str(cid))
    if mode != "schedule":
        return
        
    if not ev.is_reply:
        return
        
    reply_msg = await ev.get_reply_message()
    if not reply_msg or reply_msg.sender_id != uid:
        return
        
    txt = ev.text or ""
    cd = parse_cooldown(txt)
    if cd is not None:
        if "هنوز میوت نمیاد" in txt:
            remaining_cd = cd
            main_cd = main_cooldown_cache.get((uid, cid), 255)
        else:
            main_cooldown_cache[(uid, cid)] = cd
            main_cd = cd
            remaining_cd = cd

        await schedule_next_meow(client, cid, remaining_cd, main_cd, target_count=count)

async def run_automeow_loop(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    words = ["مع", "میو", "میو میو", "معو"]
    
    while (uid, chat_id) in active_meow_loops:
        word = random.choice(words)
        lk = get_chat_lock(uid, chat_id)
        cd_sec = None
        
        async with lk:
            sent = None
            try:
                sent = await send_message_safe(client, chat_id, word)
            except Exception:
                cd_sec = 60
                
            if cd_sec is None and sent:
                fut = asyncio.Future()
                
                async def _reply_cb(ev):
                    if ev.chat_id == chat_id and ev.reply_to_msg_id == sent.id:
                        if not fut.done():
                            fut.set_result(ev.message)
                            
                client.add_event_handler(_reply_cb, events.NewMessage)
                
                try:
                    rep_msg = await asyncio.wait_for(fut, timeout=28.0)
                    r_txt = rep_msg.text or ""
                    cd_sec = parse_cooldown(r_txt)
                    if cd_sec is None:
                        cd_sec = 255
                    elif "هنوز میوت نمیاد" not in r_txt:
                        main_cooldown_cache[(uid, chat_id)] = cd_sec
                except asyncio.TimeoutError:
                    cd_sec = 60
                except Exception:
                    cd_sec = 60
                finally:
                    client.remove_event_handler(_reply_cb, events.NewMessage)
                    
        if cd_sec is not None:
            buf = random.randint(4, 9) if cd_sec > 50 else 2
            await asyncio.sleep(cd_sec + buf)

async def start_automeow(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    if (uid, chat_id) in active_meow_loops:
        return
    t = asyncio.create_task(run_automeow_loop(client, chat_id))
    active_meow_loops[(uid, chat_id)] = t

async def start_automeow_schedule(client, chat_id: int, target_count: int = 1):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    try:
        msgs = await client.get_messages(chat_id, scheduled=True)
        if msgs and len(msgs) >= target_count:
            print(f"[AutoMeow] Schedule queue already has {len(msgs)} messages for chat {chat_id}")
            return
    except Exception:
        msgs = []

    words = ["مع", "میو", "میو میو", "معو"]
    word = random.choice(words)
    
    sent = None
    try:
        sent = await send_message_safe(client, chat_id, word)
    except Exception:
        return

    if sent:
        fut = asyncio.Future()
        
        async def _reply_cb(ev):
            if ev.chat_id == chat_id and ev.reply_to_msg_id == sent.id:
                if not fut.done():
                    fut.set_result(ev.message)
                    
        client.add_event_handler(_reply_cb, events.NewMessage)
        
        try:
            rep_msg = await asyncio.wait_for(fut, timeout=28.0)
            r_txt = rep_msg.text or ""
            cd = parse_cooldown(r_txt)
            if cd is None:
                cd = 255
            
            if "هنوز میوت نمیاد" in r_txt:
                rem_cd = cd
                m_cd = main_cooldown_cache.get((uid, chat_id), 255)
            else:
                main_cooldown_cache[(uid, chat_id)] = cd
                m_cd = cd
                rem_cd = cd

            await schedule_next_meow(client, chat_id, rem_cd, m_cd, target_count=target_count)
        except Exception:
            m_cd = main_cooldown_cache.get((uid, chat_id), 255)
            await schedule_next_meow(client, chat_id, 255, m_cd, target_count=target_count)
        finally:
            client.remove_event_handler(_reply_cb, events.NewMessage)

async def stop_automeow(client, chat_id: int, clear_scheduled: bool = False):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    t = active_meow_loops.pop((uid, chat_id), None)
    if t:
        t.cancel()
    if clear_scheduled:
        try:
            msgs = await client.get_messages(chat_id, scheduled=True)
            words = ["مع", "میو", "میو میو", "معو"]
            meow_msgs = [m.id for m in msgs if m.text and any(w in m.text for w in words)]
            if meow_msgs:
                await client.delete_messages(chat_id, meow_msgs)
        except Exception:
            pass

async def resume_automeow_tasks(client):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    config = get_meow_config(uid)
    modes = config.get("modes", {})
    for cid_str, val in modes.items():
        try:
            cid = int(cid_str)
        except ValueError:
            continue
        
        if isinstance(val, dict):
            mode = val.get("mode", "off")
            count = val.get("count", 1)
        else:
            mode = str(val)
            count = 1
            
        if mode == "instant":
            await start_automeow(client, cid)
        elif mode == "schedule":
            try:
                msgs = await client.get_messages(cid, scheduled=True)
                if not msgs:
                    asyncio.create_task(start_automeow_schedule(client, cid, target_count=count))
            except Exception as e:
                print(f"[!] error resuming schedule in {cid}: {e}")

async def automeow_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    parts = (ev.raw_text or "").split()
    cid = ev.chat_id
    str_cid = str(cid)
    
    mode, count = get_chat_meow_mode(me_id, str_cid)
    
    if len(parts) < 2:
        if mode == "instant":
            st_label = "<code>لحظه‌ای ⚡</code>"
        elif mode == "schedule":
            st_label = f"<code>زماندار سرور 📅 ({count} پیام)</code>"
        else:
            st_label = "<code>غیرفعال 🔴</code>"
            
        await safe_edit_or_silent(
            ev,
            f"🐱 <b>ربات بازی خودکار میویی (AutoMeow)</b>\n\n"
            f"▸ وضعیت در این چت: {st_label}\n\n"
            f"💡 <b>راهنما:</b>\n"
            f"▸ <code>/automeow instant</code> ── بازی آنلاین لحظه‌ای (حالت زنده)\n"
            f"▸ <code>/automeow schedule [تعداد 1-100]</code> ── زمانبندی روی سرور تلگرام (عدم آنلاین شدن اکانت 🛡️)\n"
            f"▸ <code>/automeow off</code> ── غیرفعال‌سازی در چت جاری",
            parse_mode='html'
        )
        return
        
    cmd = parts[1].strip().lower()
    if cmd in ["instant", "on"]:
        set_chat_meow_mode(me_id, str_cid, "instant", 1)
        await stop_automeow(client, cid)
        await start_automeow(client, cid)
        await safe_edit_or_silent(ev, "🐱 <b>بازی خودکار میویی (حالت لحظه‌ای ⚡) فعال شد!</b>", parse_mode='html')
    elif cmd in ["schedule", "sched"]:
        target_count = 1
        if len(parts) >= 3 and parts[2].isdigit():
            target_count = max(1, min(100, int(parts[2])))
            
        set_chat_meow_mode(me_id, str_cid, "schedule", target_count)
        await stop_automeow(client, cid)
        await safe_edit_or_silent(
            ev,
            f"🐱 <b>بازی خودکار میویی (حالت زماندار 📅 - {target_count} پیام) فعال شد!</b>\n"
            f"ℹ️ <i>پیام اولیه ارسال شد تا پیام‌ها روی سرور تلگرام زمانبندی گردند.</i>",
            parse_mode='html'
        )
        asyncio.create_task(start_automeow_schedule(client, cid, target_count=target_count))
    elif cmd == "off":
        set_chat_meow_mode(me_id, str_cid, "off")
        await stop_automeow(client, cid, clear_scheduled=True)
        await safe_edit_or_silent(ev, "🐱 <b>بازی خودکار میویی در این چت غیرفعال شد.</b> 🔴", parse_mode='html')
    else:
        await safe_edit_or_silent(ev, "⚠️ <b>دستور نامعتبر. از <code>instant</code>, <code>schedule [تعداد]</code> یا <code>off</code> استفاده کنید.</b>", parse_mode='html')
