import re
import asyncio
from telethon import events
from telethon.errors import RPCError
from modules.utils import get_chat_lock, convert_persian_digits, load_json_setting, save_json_setting, send_message_safe
from modules.show import safe_edit_or_silent

fridge_tasks = {}

def get_fridge_cfg(u_id: int) -> dict:
    return load_json_setting(f"autofridge_{u_id}.json", default={})

def save_fridge_cfg(u_id: int, cfg: dict):
    save_json_setting(f"autofridge_{u_id}.json", cfg)

async def run_autofridge_loop(client, chat_id: int):
    # fridge auto-cooking loop
    uid = client.uid
    
    while (uid, chat_id) in fridge_tasks:
        cfg = get_fridge_cfg(uid)
        mode = cfg.get(str(chat_id), "off")
        if mode not in ["sell", "feed", "cat"]:
            break
            
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
                    
                    # process each fish item on the current inline message
                    while (uid, chat_id) in fridge_tasks:
                        latest = await client.get_messages(chat_id, ids=fridge_msg.id)
                        if not latest or not getattr(latest, 'buttons', None):
                            # empty fridge sleep 30 mins
                            sleep_dur = 1800
                            break
                            
                        # Find first non-upgrade button (skip upgrade button 'ارتقا')
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
                            # no fish items in fridge
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
    uid = client.uid
    if (uid, chat_id) in fridge_tasks:
        return
    t = asyncio.create_task(run_autofridge_loop(client, chat_id))
    fridge_tasks[(uid, chat_id)] = t

async def stop_autofridge(client, chat_id: int):
    uid = client.uid
    t = fridge_tasks.pop((uid, chat_id), None)
    if t:
        t.cancel()

async def resume_autofridge_tasks(client):
    uid = client.uid
    cfg = get_fridge_cfg(uid)
    for cid_s, mode in cfg.items():
        if mode != "off":
            try:
                await start_autofridge(client, int(cid_s))
            except Exception:
                pass

async def autofridge_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    toks = (ev.raw_text or "").split()
    cid = ev.chat_id
    
    cfg = get_fridge_cfg(me_id)
    cur = cfg.get(str(cid), "off")
    
    if len(toks) < 2:
        st_str = f"`فعال ({cur}) 🟢`" if cur != "off" else "`غیرفعال 🔴`"
        await safe_edit_or_silent(
            ev,
            f"🧊 **مدیریت خودکار یخچال میویی (AutoFridge)**\n\n"
            f"▸ وضعیت در این چت: {st_str}\n\n"
            f"💡 **راهنما:**\n"
            f"▸ `/autofridge sell` ── پختن ماهی‌های خام و فروش ماهی‌های پخته شده\n"
            f"▸ `/autofridge feed` ── پختن ماهی‌های خام و غذادادن به پیشی\n"
            f"▸ `/autofridge off` ── غیرفعال‌سازی در این چت"
        )
        return
        
    m = toks[1].strip().lower()
    if m in ["sell", "feed", "cat"]:
        cfg[str(cid)] = m
        save_fridge_cfg(me_id, cfg)
        await stop_autofridge(client, cid)
        await start_autofridge(client, cid)
        await safe_edit_or_silent(
            ev,
            f"🧊 **مدیریت خودکار یخچال با موفقیت فعال شد!** 🟢\n"
            f"▸ حالت: `{m}`\n"
            f"ℹ️ *بررسی یخچال و شروع چرخه...*"
        )
    elif m == "off":
        if str(cid) in cfg and cfg[str(cid)] != "off":
            cfg[str(cid)] = "off"
            save_fridge_cfg(me_id, cfg)
            await stop_autofridge(client, cid)
            await safe_edit_or_silent(ev, "🧊 **مدیریت خودکار یخچال در این چت غیرفعال شد.** 🔴")
        else:
            await safe_edit_or_silent(ev, "⚠️ **مدیریت خودکار یخچال در این چت فعال نیست.**")
    else:
        await safe_edit_or_silent(ev, "⚠️ **گزینه نامعتبر است. از `sell`, `feed` یا `off` استفاده کنید.**")
