import re
import time
import random
import asyncio
import datetime
from telethon import events
from telethon.errors import RPCError
from modules.utils import get_chat_lock, convert_persian_digits, load_json_setting, save_json_setting, send_message_safe
from modules.show import safe_edit_or_silent

fish_tasks = {}

def get_fish_cfg(u_id: int) -> dict:
    return load_json_setting(f"autofish_{u_id}.json", default={})

def save_fish_cfg(u_id: int, config: dict):
    save_json_setting(f"autofish_{u_id}.json", config)

def get_chat_fish_mode(u_id: int, cid_str: str) -> dict:
    cfg = get_fish_cfg(u_id)
    modes = cfg.get("modes", {}) if isinstance(cfg.get("modes"), dict) else {}
    val = modes.get(cid_str) or cfg.get(cid_str)
    
    if isinstance(val, dict):
        action = val.get("action", "feed")
        m_type = val.get("type", "instant")
        count = val.get("count", 1)
        return {"action": action, "type": m_type, "count": count, "active": m_type in ["instant", "schedule"]}
    elif isinstance(val, str):
        if val in ["feed", "cat", "sell", "fridge"]:
            return {"action": val, "type": "instant", "count": 1, "active": True}
        return {"action": "feed", "type": "off", "count": 1, "active": False}
    return {"action": "feed", "type": "off", "count": 1, "active": False}

def set_chat_fish_mode(u_id: int, cid_str: str, action: str, m_type: str, count: int = 1):
    cfg = get_fish_cfg(u_id)
    if "modes" not in cfg or not isinstance(cfg["modes"], dict):
        cfg["modes"] = {}
    if m_type == "off" or action == "off":
        cfg["modes"].pop(cid_str, None)
        cfg.pop(cid_str, None)
    else:
        cfg["modes"][cid_str] = {
            "action": action,
            "type": m_type,
            "count": count
        }
        cfg.pop(cid_str, None)
    save_fish_cfg(u_id, cfg)

def parse_fish_cooldown(txt: str):
    if not txt:
        return None
    t_clean = convert_persian_digits(txt)
    if not any(key in t_clean for key in ["صبر کنی", "خوابن", "کولداون", "کافیه"]):
        return None
        
    mc = re.search(r'(\d+):(\d+)', t_clean)
    if mc:
        return int(mc.group(1)) * 60 + int(mc.group(2))
        
    mm = re.search(r'(\d+)\s*دقیقه', t_clean)
    sm = re.search(r'(\d+)\s*ثانیه', t_clean)
    m_num = int(mm.group(1)) if mm else 0
    s_num = int(sm.group(1)) if sm else 0
    if m_num or s_num:
        return m_num * 60 + s_num
    return 300

async def schedule_next_fish(client, cid: int, remaining_cd: int, target_count: int = 1):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    try:
        existing_sched = await client.get_messages(cid, scheduled=True)
    except Exception:
        existing_sched = []
        
    fish_words = ["ماهی", "ماهیگیری"]
    fish_sched = []
    if existing_sched:
        for m in existing_sched:
            txt = (m.text or "").strip()
            if any(w in txt for w in fish_words):
                fish_sched.append(m)
                
    now_ts = time.time()
    
    # If cooldown active, clean up any scheduled fish messages set before cooldown expires
    if remaining_cd > 10 and fish_sched:
        invalid_ids = [m.id for m in fish_sched if m.date.timestamp() < (now_ts + remaining_cd)]
        if invalid_ids:
            try:
                await client.delete_messages(cid, invalid_ids)
                fish_sched = [m for m in fish_sched if m.id not in invalid_ids]
            except Exception as del_err:
                print(f"[AutoFish] Error deleting invalid scheduled messages in {cid}: {del_err}")

    existing_count = len(fish_sched)
    needed = target_count - existing_count
    if needed <= 0:
        return

    main_cd = 300  # 5 minutes fishing cycle
    if existing_count == 0:
        buf = random.randint(3, 8) if remaining_cd > 10 else 2
        next_ts = now_ts + remaining_cd + buf
    else:
        max_existing_ts = max(m.date.timestamp() for m in fish_sched)
        buf = random.randint(3, 8)
        next_ts = max(max_existing_ts + main_cd + buf, now_ts + remaining_cd + buf)

    for i in range(needed):
        word = random.choice(fish_words)
        target_dt = datetime.datetime.fromtimestamp(next_ts, tz=datetime.timezone.utc)
        try:
            await client.send_message(cid, word, schedule=target_dt)
            print(f"[AutoFish] Scheduled fish #{existing_count + i + 1} for chat {cid} at {target_dt}")
        except Exception as e:
            print(f"[!] AutoFish schedule send error in {cid}: {e}")
            break
            
        buf = random.randint(3, 8)
        next_ts += main_cd + buf

async def start_autofish_schedule(client, chat_id: int, target_count: int = 1):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    try:
        msgs = await client.get_messages(chat_id, scheduled=True)
        fish_sched = [m for m in msgs if m.text and any(w in m.text for w in ["ماهی", "ماهیگیری"])]
        if len(fish_sched) >= target_count:
            print(f"[AutoFish] Schedule queue already has {len(fish_sched)} messages for chat {chat_id}")
            return
    except Exception:
        pass

    # Schedule the initial fish message for 4 seconds in the future
    # Telegram sends it as a scheduled message so the account does NOT become online!
    await schedule_next_fish(client, chat_id, remaining_cd=4, target_count=target_count)

async def _handle_fish_schedule_response(client, chat_id: int, uid: int, init_msg, cfg_mode: dict):
    lk = get_chat_lock(uid, chat_id)
    async with lk:
        action = cfg_mode.get("action", "feed")
        target_count = cfg_mode.get("count", 1)
        
        target_msg = None
        if getattr(init_msg, 'buttons', None):
            target_msg = init_msg
        else:
            edit_fut = asyncio.Future()
            async def _on_edit(e):
                if e.chat_id == chat_id and e.message.id == init_msg.id:
                    if e.message.buttons and not edit_fut.done():
                        edit_fut.set_result(e.message)
            client.add_event_handler(_on_edit, events.MessageEdited)
            try:
                target_msg = await asyncio.wait_for(edit_fut, timeout=24.0)
            except asyncio.TimeoutError:
                try:
                    target_msg = await client.get_messages(chat_id, ids=init_msg.id)
                except Exception:
                    pass
            finally:
                client.remove_event_handler(_on_edit, events.MessageEdited)

        if target_msg and getattr(target_msg, 'buttons', None):
            await asyncio.sleep(random.uniform(0.8, 1.6))
            kw = "پیشی" if action in ["feed", "cat"] else ("فروش" if action == "sell" else "یخچال")
            btn_to_click = None
            for r in target_msg.buttons:
                for b in r:
                    if b.text and kw in b.text:
                        btn_to_click = b
                        break
                if btn_to_click:
                    break
                    
            if btn_to_click:
                try:
                    await btn_to_click.click()
                except RPCError as rpc:
                    print(f"[!] AutoFish button click error: {rpc}")
                except Exception as ex:
                    print(f"[!] AutoFish button click exception: {ex}")
                
                # If fridge is full, click sell fallback button
                if action == "fridge":
                    fridge_fut = asyncio.Future()
                    async def _on_fridge_edit(e):
                        if e.chat_id == chat_id and e.message.id == target_msg.id:
                            if not fridge_fut.done():
                                fridge_fut.set_result(e.message)
                    client.add_event_handler(_on_fridge_edit, events.MessageEdited)
                    try:
                        f_msg = await asyncio.wait_for(fridge_fut, timeout=12.0)
                        f_txt = f_msg.text or ""
                        if any(k in f_txt for k in ["جا نداره", "پر", "قبل", "موجود", "یخچال"]):
                            s_btn = None
                            if f_msg.buttons:
                                for r in f_msg.buttons:
                                    for b in r:
                                        if b.text and "فروش" in b.text:
                                            s_btn = b
                                            break
                                    if s_btn:
                                        break
                            if s_btn:
                                await asyncio.sleep(1.0)
                                await s_btn.click()
                    except asyncio.TimeoutError:
                        pass
                    finally:
                        client.remove_event_handler(_on_fridge_edit, events.MessageEdited)

            # Successfully fished! Next scheduled fish in 300 seconds
            await schedule_next_fish(client, chat_id, remaining_cd=300, target_count=target_count)
        else:
            # Fallback if no buttons appeared
            await schedule_next_fish(client, chat_id, remaining_cd=60, target_count=target_count)

async def process_fish_schedule_event(ev):
    client = ev.client
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    cid = ev.chat_id
    
    cfg_mode = get_chat_fish_mode(uid, str(cid))
    if not cfg_mode.get("active") or cfg_mode.get("type") != "schedule":
        return
        
    if not ev.is_reply:
        return
        
    reply_msg = await ev.get_reply_message()
    if not reply_msg or reply_msg.sender_id != uid:
        return
        
    rep_txt = (reply_msg.text or "").strip()
    if not any(w in rep_txt for w in ["ماهی", "ماهیگیری"]):
        return

    txt = ev.text or ""
    cd_val = parse_fish_cooldown(txt)
    if cd_val is not None:
        await schedule_next_fish(client, cid, remaining_cd=cd_val, target_count=cfg_mode.get("count", 1))
        return

    asyncio.create_task(_handle_fish_schedule_response(client, cid, uid, ev.message, cfg_mode))

async def run_autofish_loop(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    fish_words = ["ماهی", "ماهیگیری"]
    
    while (uid, chat_id) in fish_tasks:
        cfg_mode = get_chat_fish_mode(uid, str(chat_id))
        if not cfg_mode.get("active") or cfg_mode.get("type") != "instant":
            break
        mode = cfg_mode.get("action", "feed")
            
        lk = get_chat_lock(uid, chat_id)
        sleep_time = None
        
        async with lk:
            w = random.choice(fish_words)
            sent = None
            try:
                sent = await send_message_safe(client, chat_id, w)
            except Exception:
                sleep_time = 60
                
            if sleep_time is None and sent:
                fut = asyncio.Future()
                
                async def _on_reply(ev):
                    if ev.chat_id == chat_id and ev.reply_to_msg_id == sent.id:
                        if not fut.done():
                            fut.set_result(ev.message)
                            
                client.add_event_handler(_on_reply, events.NewMessage)
                
                try:
                    init_msg = await asyncio.wait_for(fut, timeout=20.0)
                    cd_val = parse_fish_cooldown(init_msg.text or "")
                                
                    if cd_val is not None:
                        sleep_time = cd_val + 3
                    else:
                        target_msg = None
                        if getattr(init_msg, 'buttons', None):
                            target_msg = init_msg
                        else:
                            edit_fut = asyncio.Future()
                            
                            async def _on_edit(ev):
                                if ev.chat_id == chat_id and ev.message.id == init_msg.id:
                                    if ev.message.buttons and not edit_fut.done():
                                        edit_fut.set_result(ev.message)
                                            
                            client.add_event_handler(_on_edit, events.MessageEdited)
                            try:
                                target_msg = await asyncio.wait_for(edit_fut, timeout=24.0)
                            except asyncio.TimeoutError:
                                pass
                            finally:
                                client.remove_event_handler(_on_edit, events.MessageEdited)
                                
                        if target_msg and getattr(target_msg, 'buttons', None):
                            await asyncio.sleep(random.uniform(0.6, 1.4))
                            kw = "پیشی" if mode in ["feed", "cat"] else ("فروش" if mode == "sell" else "یخچال")
                            btn_to_click = None
                            for r in target_msg.buttons:
                                for b in r:
                                    if b.text and kw in b.text:
                                        btn_to_click = b
                                        break
                                if btn_to_click:
                                    break
                                    
                            if btn_to_click:
                                await btn_to_click.click()
                                
                                if mode == "fridge":
                                    fridge_fut = asyncio.Future()
                                    async def _on_fridge_edit(ev):
                                        if ev.chat_id == chat_id and ev.message.id == target_msg.id:
                                            if not fridge_fut.done():
                                                fridge_fut.set_result(ev.message)
                                                
                                    client.add_event_handler(_on_fridge_edit, events.MessageEdited)
                                    try:
                                        f_msg = await asyncio.wait_for(fridge_fut, timeout=12.0)
                                        f_txt = f_msg.text or ""
                                        if any(k in f_txt for k in ["جا نداره", "پر", "قبل", "موجود", "یخچال"]):
                                            s_btn = None
                                            if f_msg.buttons:
                                                for r in f_msg.buttons:
                                                    for b in r:
                                                        if b.text and "فروش" in b.text:
                                                            s_btn = b
                                                            break
                                                    if s_btn:
                                                        break
                                            if s_btn:
                                                await asyncio.sleep(1.0)
                                                await s_btn.click()
                                    except asyncio.TimeoutError:
                                        pass
                                    finally:
                                        client.remove_event_handler(_on_fridge_edit, events.MessageEdited)
                                        
                            sleep_time = 300
                        else:
                            sleep_time = 60
                except asyncio.TimeoutError:
                    sleep_time = 60
                except RPCError as rpc_e:
                    print(f"[!] autofish RPC error: {rpc_e}")
                    sleep_time = 60
                except Exception:
                    sleep_time = 60
                finally:
                    client.remove_event_handler(_on_reply, events.NewMessage)
                    
        if sleep_time is not None:
            await asyncio.sleep(sleep_time)

async def start_autofish(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    if (uid, chat_id) in fish_tasks:
        return
    t = asyncio.create_task(run_autofish_loop(client, chat_id))
    fish_tasks[(uid, chat_id)] = t

async def stop_autofish(client, chat_id: int, clear_scheduled: bool = False):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    t = fish_tasks.pop((uid, chat_id), None)
    if t:
        t.cancel()
    if clear_scheduled:
        try:
            msgs = await client.get_messages(chat_id, scheduled=True)
            fish_msgs = [m.id for m in msgs if m.text and any(w in m.text for w in ["ماهی", "ماهیگیری"])]
            if fish_msgs:
                await client.delete_messages(chat_id, fish_msgs)
        except Exception:
            pass

async def resume_autofish_tasks(client):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    cfg = get_fish_cfg(uid)
    modes = cfg.get("modes", {}) if isinstance(cfg.get("modes"), dict) else {}
    all_keys = set(list(modes.keys()) + [k for k in cfg.keys() if k != "modes"])
    
    for c_str in all_keys:
        try:
            cid = int(c_str)
        except ValueError:
            continue
            
        m_info = get_chat_fish_mode(uid, c_str)
        if not m_info.get("active"):
            continue
            
        t_type = m_info.get("type", "instant")
        if t_type == "instant":
            await start_autofish(client, cid)
        elif t_type == "schedule":
            try:
                msgs = await client.get_messages(cid, scheduled=True)
                fish_sched = [m for m in msgs if m.text and any(w in m.text for w in ["ماهی", "ماهیگیری"])]
                if not fish_sched:
                    asyncio.create_task(start_autofish_schedule(client, cid, target_count=m_info.get("count", 1)))
            except Exception as e:
                print(f"[!] error resuming fish schedule in {cid}: {e}")

async def autofish_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    parts = (ev.raw_text or "").split()
    cid = ev.chat_id
    str_cid = str(cid)
    
    cur_info = get_chat_fish_mode(me_id, str_cid)
    
    if len(parts) < 2:
        if cur_info.get("active"):
            if cur_info.get("type") == "instant":
                st_label = f"<code>لحظه‌ای ⚡ ({cur_info.get('action')})</code>"
            else:
                st_label = f"<code>زماندار سرور 📅 ({cur_info.get('action')} - {cur_info.get('count', 1)} پیام)</code>"
        else:
            st_label = "<code>غیرفعال 🔴</code>"
            
        await safe_edit_or_silent(
            ev,
            f"🎣 <b>ربات ماهیگیری خودکار (AutoFish)</b>\n\n"
            f"▸ وضعیت در این چت: {st_label}\n\n"
            f"💡 <b>راهنمای استفاده:</b>\n"
            f"▸ <code>/autofish feed instant</code> ── ماهیگیری لحظه‌ای و غذادادن به پیشی\n"
            f"▸ <code>/autofish sell instant</code> ── ماهیگیری لحظه‌ای و فروش مستقیم ماهی\n"
            f"▸ <code>/autofish fridge instant</code> ── ماهیگیری لحظه‌ای و قرار دادن در یخچال\n"
            f"▸ <code>/autofish [feed|sell|fridge] schedule [تعداد]</code> ── زمانبندی سرور تلگرام (عدم آنلاین شدن اکانت 🛡️)\n"
            f"▸ <code>/autofish off</code> ── غیرفعال‌سازی در این چت\n\n"
            f"ℹ️ <i>مثال زماندار: <code>/autofish feed schedule 5</code></i>",
            parse_mode='html'
        )
        return
        
    # Flexible argument parsing
    action = None
    mode_type = None
    count = 1
    is_off = False
    
    for tok in parts[1:]:
        t = tok.strip().lower()
        if t == "off":
            is_off = True
        elif t in ["feed", "cat"]:
            action = "feed"
        elif t == "sell":
            action = "sell"
        elif t == "fridge":
            action = "fridge"
        elif t in ["instant", "live", "on"]:
            mode_type = "instant"
        elif t in ["schedule", "sched"]:
            mode_type = "schedule"
        elif t.isdigit():
            count = max(1, min(100, int(t)))
            
    if is_off:
        set_chat_fish_mode(me_id, str_cid, "feed", "off")
        await stop_autofish(client, cid, clear_scheduled=True)
        await safe_edit_or_silent(ev, "🎣 <b>ماهیگیری خودکار در این چت غیرفعال شد.</b> 🔴", parse_mode='html')
        return
        
    if not action:
        action = cur_info.get("action", "feed") if cur_info.get("active") else "feed"
    if not mode_type:
        mode_type = "instant" if count == 1 and "schedule" not in (ev.raw_text or "").lower() else "schedule"
        
    action_labels = {
        "feed": "غذادادن به پیشی 🐱",
        "sell": "فروش مستقیم ماهی 💰",
        "fridge": "ذخیره در یخچال 🧊"
    }
    a_label = action_labels.get(action, action)
    
    set_chat_fish_mode(me_id, str_cid, action, mode_type, count)
    await stop_autofish(client, cid, clear_scheduled=True)
    
    if mode_type == "instant":
        await start_autofish(client, cid)
        await safe_edit_or_silent(
            ev,
            f"🎣 <b>ماهیگیری خودکار (حالت لحظه‌ای ⚡) فعال شد!</b>\n"
            f"▸ نوع عملکرد: <code>{a_label}</code>\n"
            f"ℹ️ <i>در حال ارسال کلمه و شروع چرخه...</i>",
            parse_mode='html'
        )
    else:
        await safe_edit_or_silent(
            ev,
            f"🎣 <b>ماهیگیری خودکار (حالت زماندار سرور 📅 - {count} پیام) فعال شد!</b>\n"
            f"▸ نوع عملکرد: <code>{a_label}</code>\n"
            f"🛡️ <i>پیام‌ها روی سرور تلگرام زمانبندی شدند (اکانت شما آنلاین نخواهد شد).</i>",
            parse_mode='html'
        )
        asyncio.create_task(start_autofish_schedule(client, cid, target_count=count))
