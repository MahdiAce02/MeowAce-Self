import re
import time
import random
import asyncio
import datetime
from telethon import events
from telethon.errors import RPCError
from modules.utils import get_chat_lock, convert_persian_digits, load_json_setting, save_json_setting, send_message_safe
from modules.show import safe_edit_or_silent

fridge_tasks = {}

def get_fridge_cfg(u_id: int) -> dict:
    return load_json_setting(f"autofridge_{u_id}.json", default={})

def save_fridge_cfg(u_id: int, cfg: dict):
    save_json_setting(f"autofridge_{u_id}.json", cfg)

def get_chat_fridge_mode(u_id: int, cid_str: str) -> dict:
    cfg = get_fridge_cfg(u_id)
    modes = cfg.get("modes", {}) if isinstance(cfg.get("modes"), dict) else {}
    val = modes.get(cid_str) or cfg.get(cid_str)
    
    if isinstance(val, dict):
        action = val.get("action", "sell")
        m_type = val.get("type", "instant")
        count = val.get("count", 1)
        return {"action": action, "type": m_type, "count": count, "active": m_type in ["instant", "schedule"]}
    elif isinstance(val, str):
        if val in ["sell", "feed", "cat"]:
            return {"action": val, "type": "instant", "count": 1, "active": True}
        return {"action": "sell", "type": "off", "count": 1, "active": False}
    return {"action": "sell", "type": "off", "count": 1, "active": False}

def set_chat_fridge_mode(u_id: int, cid_str: str, action: str, m_type: str, count: int = 1):
    cfg = get_fridge_cfg(u_id)
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
    save_fridge_cfg(u_id, cfg)

async def schedule_next_fridge(client, cid: int, remaining_cd: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    try:
        existing_sched = await client.get_messages(cid, scheduled=True)
    except Exception:
        existing_sched = []
        
    fridge_words = ["یخچال میویی", "یخچال"]
    fridge_sched = []
    if existing_sched:
        for m in existing_sched:
            txt = (m.text or "").strip()
            if any(w in txt for w in fridge_words):
                fridge_sched.append(m)

    now_ts = time.time()
    
    # Clean up any scheduled fridge messages set before cooldown expires
    if remaining_cd > 10 and fridge_sched:
        invalid_ids = [m.id for m in fridge_sched if m.date.timestamp() < (now_ts + remaining_cd)]
        if invalid_ids:
            try:
                await client.delete_messages(cid, invalid_ids)
                fridge_sched = [m for m in fridge_sched if m.id not in invalid_ids]
            except Exception as del_err:
                print(f"[AutoFridge] Error deleting invalid scheduled messages in {cid}: {del_err}")

    # If there is already a valid scheduled fridge message, we don't need to add another
    if fridge_sched:
        return

    buf = random.randint(3, 8) if remaining_cd > 10 else 2
    next_ts = now_ts + remaining_cd + buf
    target_dt = datetime.datetime.fromtimestamp(next_ts, tz=datetime.timezone.utc)
    
    try:
        await client.send_message(cid, "یخچال میویی", schedule=target_dt)
        print(f"[AutoFridge] Scheduled next fridge check for chat {cid} at {target_dt}")
    except Exception as e:
        print(f"[!] AutoFridge schedule send error in {cid}: {e}")

async def start_autofridge_schedule(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    try:
        msgs = await client.get_messages(chat_id, scheduled=True)
        fridge_sched = [m for m in msgs if m.text and any(w in m.text for w in ["یخچال میویی", "یخچال"])]
        if fridge_sched:
            print(f"[AutoFridge] A scheduled fridge message is already waiting in chat {chat_id}")
            return
    except Exception:
        pass

    # Schedule the initial fridge inspection for 4 seconds in the future
    # Telegram sends it as a scheduled message so the account does NOT become online!
    await schedule_next_fridge(client, chat_id, remaining_cd=4)

async def _handle_fridge_schedule_response(client, chat_id: int, uid: int, fridge_msg, cfg_mode: dict):
    lk = get_chat_lock(uid, chat_id)
    async with lk:
        action = cfg_mode.get("action", "sell")
        target_count = cfg_mode.get("count", 1)
        sleep_dur = 1800
        
        while True:
            cur_cfg = get_chat_fridge_mode(uid, str(chat_id))
            if not cur_cfg.get("active") or cur_cfg.get("type") != "schedule":
                return
                
            try:
                latest = await client.get_messages(chat_id, ids=fridge_msg.id)
            except Exception:
                sleep_dur = 1800
                break
                
            if not latest or not getattr(latest, 'buttons', None):
                sleep_dur = 1800
                break
                
            first_btn = None
            for row in latest.buttons:
                for b in row:
                    if b.text and "ارتقا" in b.text:
                        continue
                    first_btn = b
                    break
                if first_btn:
                    break

            if not first_btn:
                sleep_dur = 1800
                break

            await asyncio.sleep(1.8)
            f_fut = asyncio.Future()
            async def _on_fish_edit(ev):
                if ev.chat_id == chat_id and ev.message.id == fridge_msg.id:
                    if ev.message.buttons and not f_fut.done():
                        f_fut.set_result(ev.message)
            client.add_event_handler(_on_fish_edit, events.MessageEdited)
            
            try:
                await first_btn.click()
                try:
                    fish_menu = await asyncio.wait_for(f_fut, timeout=8.0)
                except asyncio.TimeoutError:
                    fish_menu = await client.get_messages(chat_id, ids=fridge_msg.id)
                    
                if not fish_menu or not getattr(fish_menu, 'buttons', None):
                    sleep_dur = 1800
                    break
                    
                txt = convert_persian_digits(fish_menu.text or "")
                cook_btn = None
                act_btn = None
                
                for r in fish_menu.buttons:
                    for b in r:
                        if b.text and "بپوخش" in b.text:
                            cook_btn = b
                        elif b.text and "فروش" in b.text and action == "sell":
                            act_btn = b
                        elif b.text and "پیشی" in b.text and action in ["feed", "cat"]:
                            act_btn = b
                            
                if "پخته شده" in txt or (act_btn and not cook_btn):
                    if not act_btn:
                        t_kw = "فروش" if action == "sell" else "پیشی"
                        for r in fish_menu.buttons:
                            for b in r:
                                if b.text and t_kw in b.text:
                                    act_btn = b
                                    break
                            if act_btn:
                                break
                                
                    if act_btn:
                        await asyncio.sleep(2.0)
                        b_fut = asyncio.Future()
                        async def _on_back_edit(ev):
                            if ev.chat_id == chat_id and ev.message.id == fridge_msg.id:
                                if ev.message.buttons and not b_fut.done():
                                    b_fut.set_result(ev.message)
                        client.add_event_handler(_on_back_edit, events.MessageEdited)
                        
                        try:
                            await act_btn.click()
                            try:
                                act_msg = await asyncio.wait_for(b_fut, timeout=6.0)
                            except asyncio.TimeoutError:
                                act_msg = await client.get_messages(chat_id, ids=fridge_msg.id)
                                
                            if act_msg and getattr(act_msg, 'buttons', None):
                                b_btn = act_msg.buttons[0][0]
                                await asyncio.sleep(1.8)
                                await b_btn.click()
                                await asyncio.sleep(1.8)
                        finally:
                            client.remove_event_handler(_on_back_edit, events.MessageEdited)
                        continue
                    else:
                        sleep_dur = 1800
                        break
                        
                elif cook_btn:
                    await asyncio.sleep(2.0)
                    c_fut = asyncio.Future()
                    async def _on_confirm_edit(ev):
                        if ev.chat_id == chat_id and ev.message.id == fridge_msg.id:
                            if ev.message.buttons and not c_fut.done():
                                c_fut.set_result(ev.message)
                    client.add_event_handler(_on_confirm_edit, events.MessageEdited)
                    
                    try:
                        await cook_btn.click()
                        try:
                            confirm_menu = await asyncio.wait_for(c_fut, timeout=6.0)
                        except asyncio.TimeoutError:
                            confirm_menu = await client.get_messages(chat_id, ids=fridge_msg.id)
                            
                        if confirm_menu and getattr(confirm_menu, 'buttons', None):
                            c_txt = convert_persian_digits(confirm_menu.text or "")
                            cook_sec = 180
                            m_time = re.search(r'زمان\s*مورد\s*نیاز\s*پخیدن\s*:\s*(\d+):(\d+)', c_txt)
                            if not m_time:
                                m_time = re.search(r'(\d+):(\d+)', c_txt)
                            if m_time:
                                cook_sec = int(m_time.group(1)) * 60 + int(m_time.group(2))
                                
                            chk_btn = confirm_menu.buttons[0][0]
                            await asyncio.sleep(2.0)
                            await chk_btn.click()
                            sleep_dur = cook_sec + 60
                            break
                        else:
                            sleep_dur = 1800
                            break
                    finally:
                        client.remove_event_handler(_on_confirm_edit, events.MessageEdited)
                else:
                    sleep_dur = 1800
                    break
            except Exception as loop_e:
                print(f"[!] Error in fridge schedule processing: {loop_e}")
                sleep_dur = 1800
                break
            finally:
                client.remove_event_handler(_on_fish_edit, events.MessageEdited)

        await schedule_next_fridge(client, chat_id, remaining_cd=sleep_dur)

async def process_fridge_schedule_event(ev):
    client = ev.client
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    cid = ev.chat_id
    
    cfg_mode = get_chat_fridge_mode(uid, str(cid))
    if not cfg_mode.get("active") or cfg_mode.get("type") != "schedule":
        return
        
    if not ev.is_reply:
        return
        
    reply_msg = await ev.get_reply_message()
    if not reply_msg or reply_msg.sender_id != uid:
        return
        
    rep_txt = (reply_msg.text or "").strip()
    if not any(w in rep_txt for w in ["یخچال میویی", "یخچال"]):
        return

    asyncio.create_task(_handle_fridge_schedule_response(client, cid, uid, ev.message, cfg_mode))

async def run_autofridge_loop(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    
    while (uid, chat_id) in fridge_tasks:
        cfg_mode = get_chat_fridge_mode(uid, str(chat_id))
        if not cfg_mode.get("active") or cfg_mode.get("type") != "instant":
            break
        mode = cfg_mode.get("action", "sell")
            
        lk = get_chat_lock(uid, chat_id)
        sleep_dur = None
        
        async with lk:
            sent = None
            try:
                sent = await send_message_safe(client, chat_id, "یخچال میویی")
            except Exception:
                sleep_dur = 60
                
            if sleep_dur is None and sent:
                fut = asyncio.Future()
                async def _on_new_msg(ev):
                    if ev.chat_id == chat_id and ev.reply_to_msg_id == sent.id:
                        if not fut.done():
                            fut.set_result(ev.message)
                client.add_event_handler(_on_new_msg, events.NewMessage)
                
                try:
                    fridge_msg = await asyncio.wait_for(fut, timeout=20.0)
                    
                    while (uid, chat_id) in fridge_tasks:
                        latest = await client.get_messages(chat_id, ids=fridge_msg.id)
                        if not latest or not getattr(latest, 'buttons', None):
                            sleep_dur = 1800
                            break
                            
                        first_btn = None
                        for row in latest.buttons:
                            for b in row:
                                if b.text and "ارتقا" in b.text:
                                    continue
                                first_btn = b
                                break
                            if first_btn:
                                break

                        if not first_btn:
                            sleep_dur = 1800
                            break

                        await asyncio.sleep(1.8)
                        
                        f_fut = asyncio.Future()
                        async def _on_fish_edit(ev):
                            if ev.chat_id == chat_id and ev.message.id == fridge_msg.id:
                                if ev.message.buttons and not f_fut.done():
                                    f_fut.set_result(ev.message)
                        client.add_event_handler(_on_fish_edit, events.MessageEdited)
                        
                        try:
                            await first_btn.click()
                            try:
                                fish_menu = await asyncio.wait_for(f_fut, timeout=8.0)
                            except asyncio.TimeoutError:
                                fish_menu = await client.get_messages(chat_id, ids=fridge_msg.id)
                                
                            if not fish_menu or not getattr(fish_menu, 'buttons', None):
                                break
                                
                            txt = convert_persian_digits(fish_menu.text or "")
                            cook_btn = None
                            act_btn = None
                            
                            for r in fish_menu.buttons:
                                for b in r:
                                    if b.text and "بپوخش" in b.text:
                                        cook_btn = b
                                    elif b.text and "فروش" in b.text and mode == "sell":
                                        act_btn = b
                                    elif b.text and "پیشی" in b.text and mode in ["feed", "cat"]:
                                        act_btn = b
                                        
                            if "پخته شده" in txt or (act_btn and not cook_btn):
                                if not act_btn:
                                    t_kw = "فروش" if mode == "sell" else "پیشی"
                                    for r in fish_menu.buttons:
                                        for b in r:
                                            if b.text and t_kw in b.text:
                                                act_btn = b
                                                break
                                        if act_btn:
                                            break
                                if act_btn:
                                    await asyncio.sleep(2.0)
                                    
                                    b_fut = asyncio.Future()
                                    async def _on_back_edit(ev):
                                        if ev.chat_id == chat_id and ev.message.id == fridge_msg.id:
                                            if ev.message.buttons and not b_fut.done():
                                                b_fut.set_result(ev.message)
                                    client.add_event_handler(_on_back_edit, events.MessageEdited)
                                    
                                    try:
                                        await act_btn.click()
                                        try:
                                            act_msg = await asyncio.wait_for(b_fut, timeout=6.0)
                                        except asyncio.TimeoutError:
                                            act_msg = await client.get_messages(chat_id, ids=fridge_msg.id)
                                            
                                        if act_msg and getattr(act_msg, 'buttons', None):
                                            b_btn = act_msg.buttons[0][0]
                                            await asyncio.sleep(1.8)
                                            await b_btn.click()
                                            await asyncio.sleep(1.8)
                                    finally:
                                        client.remove_event_handler(_on_back_edit, events.MessageEdited)
                                        
                                    continue
                                else:
                                    break
                                    
                            elif cook_btn:
                                await asyncio.sleep(2.0)
                                
                                c_fut = asyncio.Future()
                                async def _on_confirm_edit(ev):
                                    if ev.chat_id == chat_id and ev.message.id == fridge_msg.id:
                                        if ev.message.buttons and not c_fut.done():
                                            c_fut.set_result(ev.message)
                                client.add_event_handler(_on_confirm_edit, events.MessageEdited)
                                
                                try:
                                    await cook_btn.click()
                                    try:
                                        confirm_menu = await asyncio.wait_for(c_fut, timeout=6.0)
                                    except asyncio.TimeoutError:
                                        confirm_menu = await client.get_messages(chat_id, ids=fridge_msg.id)
                                        
                                    if confirm_menu and getattr(confirm_menu, 'buttons', None):
                                        c_txt = convert_persian_digits(confirm_menu.text or "")
                                        cook_sec = 180
                                        m_time = re.search(r'زمان\s*مورد\s*نیاز\s*پخیدن\s*:\s*(\d+):(\d+)', c_txt)
                                        if not m_time:
                                            m_time = re.search(r'(\d+):(\d+)', c_txt)
                                        if m_time:
                                            cook_sec = int(m_time.group(1)) * 60 + int(m_time.group(2))
                                            
                                        chk_btn = confirm_menu.buttons[0][0]
                                        await asyncio.sleep(2.0)
                                        await chk_btn.click()
                                        
                                        sleep_dur = cook_sec + 60
                                        break
                                    else:
                                        sleep_dur = 60
                                        break
                                finally:
                                    client.remove_event_handler(_on_confirm_edit, events.MessageEdited)
                            else:
                                break
                        except asyncio.TimeoutError:
                            break
                        finally:
                            client.remove_event_handler(_on_fish_edit, events.MessageEdited)
                            
                except asyncio.TimeoutError:
                    sleep_dur = 60
                except RPCError as rpc_e:
                    print(f"[!] autofridge RPC exception: {rpc_e}")
                    sleep_dur = 60
                finally:
                    client.remove_event_handler(_on_new_msg, events.NewMessage)
                    
        if sleep_dur is not None:
            await asyncio.sleep(sleep_dur)

async def start_autofridge(client, chat_id: int):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    if (uid, chat_id) in fridge_tasks:
        return
    t = asyncio.create_task(run_autofridge_loop(client, chat_id))
    fridge_tasks[(uid, chat_id)] = t

async def stop_autofridge(client, chat_id: int, clear_scheduled: bool = False):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    t = fridge_tasks.pop((uid, chat_id), None)
    if t:
        t.cancel()
    if clear_scheduled:
        try:
            msgs = await client.get_messages(chat_id, scheduled=True)
            fridge_msgs = [m.id for m in msgs if m.text and any(w in m.text for w in ["یخچال میویی", "یخچال"])]
            if fridge_msgs:
                await client.delete_messages(chat_id, fridge_msgs)
        except Exception:
            pass

async def resume_autofridge_tasks(client):
    uid = getattr(client, 'uid', None) or (await client.get_me()).id
    cfg = get_fridge_cfg(uid)
    modes = cfg.get("modes", {}) if isinstance(cfg.get("modes"), dict) else {}
    all_keys = set(list(modes.keys()) + [k for k in cfg.keys() if k != "modes"])
    
    for c_str in all_keys:
        try:
            cid = int(c_str)
        except ValueError:
            continue
            
        m_info = get_chat_fridge_mode(uid, c_str)
        if not m_info.get("active"):
            continue
            
        t_type = m_info.get("type", "instant")
        if t_type == "instant":
            await start_autofridge(client, cid)
        elif t_type == "schedule":
            try:
                msgs = await client.get_messages(cid, scheduled=True)
                fridge_sched = [m for m in msgs if m.text and any(w in m.text for w in ["یخچال میویی", "یخچال"])]
                if not fridge_sched:
                    asyncio.create_task(start_autofridge_schedule(client, cid))
            except Exception as e:
                print(f"[!] error resuming fridge schedule in {cid}: {e}")

async def autofridge_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    parts = (ev.raw_text or "").split()
    cid = ev.chat_id
    str_cid = str(cid)
    
    cur_info = get_chat_fridge_mode(me_id, str_cid)
    
    if len(parts) < 2:
        if cur_info.get("active"):
            if cur_info.get("type") == "instant":
                st_label = f"<code>لحظه‌ای ⚡ ({cur_info.get('action')})</code>"
            else:
                st_label = f"<code>زماندار سرور 📅 ({cur_info.get('action')})</code>"
        else:
            st_label = "<code>غیرفعال 🔴</code>"
            
        await safe_edit_or_silent(
            ev,
            f"🧊 <b>مدیریت خودکار یخچال میویی (AutoFridge)</b>\n\n"
            f"▸ وضعیت در این چت: {st_label}\n\n"
            f"💡 <b>راهنمای استفاده:</b>\n"
            f"▸ <code>/autofridge sell schedule</code> ── پخت و فروش زماندار سرور (عدم آنلاین شدن 🛡️)\n"
            f"▸ <code>/autofridge feed schedule</code> ── پخت و غذادادن زماندار سرور (عدم آنلاین شدن 🛡️)\n"
            f"▸ <code>/autofridge [sell|feed] instant</code> ── حالت لحظه‌ای زنده ⚡\n"
            f"▸ <code>/autofridge off</code> ── غیرفعال‌سازی در این چت\n\n"
            f"ℹ️ <i>در حالت schedule پیام‌ها تک‌به‌تک و بر اساس زمان پخت روی سرور تلگرام زمانبندی می‌شوند.</i>",
            parse_mode='html'
        )
        return
        
    # Flexible argument parsing
    action = None
    mode_type = None
    is_off = False
    
    for tok in parts[1:]:
        t = tok.strip().lower()
        if t == "off":
            is_off = True
        elif t == "sell":
            action = "sell"
        elif t in ["feed", "cat"]:
            action = "feed"
        elif t in ["instant", "live", "on"]:
            mode_type = "instant"
        elif t in ["schedule", "sched"]:
            mode_type = "schedule"
            
    if is_off:
        set_chat_fridge_mode(me_id, str_cid, "sell", "off")
        await stop_autofridge(client, cid, clear_scheduled=True)
        await safe_edit_or_silent(ev, "🧊 <b>مدیریت خودکار یخچال در این چت غیرفعال شد.</b> 🔴", parse_mode='html')
        return
        
    if not action:
        action = cur_info.get("action", "sell") if cur_info.get("active") else "sell"
    if not mode_type:
        mode_type = "schedule" if "sched" in (ev.raw_text or "").lower() else ("instant" if "instant" in (ev.raw_text or "").lower() else "instant")
        
    action_labels = {
        "sell": "پخت ماهی خام و فروش پخته‌ها 💰",
        "feed": "پخت ماهی خام و غذادادن به پیشی 🐱"
    }
    a_label = action_labels.get(action, action)
    
    set_chat_fridge_mode(me_id, str_cid, action, mode_type, 1)
    await stop_autofridge(client, cid, clear_scheduled=True)
    
    if mode_type == "instant":
        await start_autofridge(client, cid)
        await safe_edit_or_silent(
            ev,
            f"🧊 <b>مدیریت خودکار یخچال (حالت لحظه‌ای ⚡) فعال شد!</b>\n"
            f"▸ نوع عملکرد: <code>{a_label}</code>\n"
            f"ℹ️ <i>بررسی یخچال و شروع چرخه...</i>",
            parse_mode='html'
        )
    else:
        await safe_edit_or_silent(
            ev,
            f"🧊 <b>مدیریت خودکار یخچال (حالت زماندار سرور 📅) فعال شد!</b>\n"
            f"▸ نوع عملکرد: <code>{a_label}</code>\n"
            f"🛡️ <i>پیام‌ها به صورت زماندار روی سرور ارسال می‌شوند و اکانت شما آنلاین نخواهد شد.</i>",
            parse_mode='html'
        )
        asyncio.create_task(start_autofridge_schedule(client, cid))
