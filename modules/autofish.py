import re
import random
import asyncio
from telethon import events
from telethon.errors import RPCError
from modules.utils import get_chat_lock, convert_persian_digits, load_json_setting, save_json_setting, send_message_safe
from modules.show import safe_edit_or_silent

fish_tasks = {}

def get_fish_cfg(u_id: int) -> dict:
    return load_json_setting(f"autofish_{u_id}.json", default={})

def save_fish_cfg(u_id: int, config: dict):
    save_json_setting(f"autofish_{u_id}.json", config)

async def run_autofish_loop(client, chat_id: int):
    uid = client.uid
    fish_words = ["ماهی", "ماهیگیری"]
    
    while (uid, chat_id) in fish_tasks:
        cfg = get_fish_cfg(uid)
        mode = cfg.get(str(chat_id), "off")
        if mode not in ["feed", "cat", "sell", "fridge"]:
            break
            
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
                    t_clean = convert_persian_digits(init_msg.text or "")
                    
                    cd_val = None
                    if any(key in t_clean for key in ["صبر کنی", "خوابن", "کولداون", "کافیه"]):
                        mc = re.search(r'(\d+):(\d+)', t_clean)
                        if mc:
                            cd_val = int(mc.group(1)) * 60 + int(mc.group(2))
                        else:
                            mm = re.search(r'(\d+)\s*دقیقه', t_clean)
                            sm = re.search(r'(\d+)\s*ثانیه', t_clean)
                            m_num = int(mm.group(1)) if mm else 0
                            s_num = int(sm.group(1)) if sm else 0
                            if m_num or s_num:
                                cd_val = m_num * 60 + s_num
                                
                    if cd_val is not None:
                        sleep_time = cd_val + 3
                    else:
                        target_msg = None
                        if getattr(init_msg, 'buttons', None):
                            target_msg = init_msg
                        else:
                            # animation edit wait
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
                                
                                # if fridge is full, click sell fallback button
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
                                        
                            # 5 mins interval after successful fishing action
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
    uid = client.uid
    if (uid, chat_id) in fish_tasks:
        return
    t = asyncio.create_task(run_autofish_loop(client, chat_id))
    fish_tasks[(uid, chat_id)] = t

async def stop_autofish(client, chat_id: int):
    uid = client.uid
    t = fish_tasks.pop((uid, chat_id), None)
    if t:
        t.cancel()

async def resume_autofish_tasks(client):
    uid = client.uid
    cfg = get_fish_cfg(uid)
    for c_str, mode in cfg.items():
        if mode != "off":
            try:
                await start_autofish(client, int(c_str))
            except Exception:
                pass

async def autofish_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    toks = (ev.raw_text or "").split()
    cid = ev.chat_id
    
    cfg = get_fish_cfg(me_id)
    
    if len(toks) < 2:
        cur_mode = cfg.get(str(cid), "off")
        st_text = f"`فعال ({cur_mode}) 🟢`" if cur_mode != "off" else "`غیرفعال 🔴`"
        await safe_edit_or_silent(
            ev,
            f"🎣 **ماهیگیری خودکار ربات میویی (AutoFish)**\n\n"
            f"▸ وضعیت در این چت: {st_text}\n\n"
            f"💡 **راهنمای استفاده:**\n"
            f"▸ `/autofish feed` ── ماهیگیری خودکار و غذادادن به پیشی\n"
            f"▸ `/autofish sell` ── ماهیگیری خودکار و فروش مستقیم ماهی\n"
            f"▸ `/autofish fridge` ── ماهیگیری خودکار و قرار دادن در یخچال (در صورت پر بودن: فروش)\n"
            f"▸ `/autofish off` ── غیرفعال‌سازی ماهیگیری خودکار در این چت"
        )
        return
        
    m = toks[1].strip().lower()
    if m in ["feed", "cat", "sell", "fridge"]:
        cfg[str(cid)] = m
        save_fish_cfg(me_id, cfg)
        await stop_autofish(client, cid)
        await start_autofish(client, cid)
        await safe_edit_or_silent(
            ev,
            f"🎣 **ماهیگیری خودکار با موفقیت فعال شد!** 🟢\n"
            f"▸ حالت: `{m}`\n"
            f"ℹ️ *در حال ارسال کلمه و شروع چرخه...*"
        )
    elif m == "off":
        if str(cid) in cfg and cfg[str(cid)] != "off":
            cfg[str(cid)] = "off"
            save_fish_cfg(me_id, cfg)
            await stop_autofish(client, cid)
            await safe_edit_or_silent(ev, "🎣 **ماهیگیری خودکار در این چت غیرفعال شد.** 🔴")
        else:
            await safe_edit_or_silent(ev, "⚠️ **ماهیگیری خودکار در این چت فعال نیست.**")
    else:
        await safe_edit_or_silent(ev, "⚠️ **گزینه نامعتبر است. از `feed`, `sell`, `fridge` یا `off` استفاده کنید.**")
