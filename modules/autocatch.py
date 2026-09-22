import time
import asyncio
from telethon.errors import MessageIdInvalidError, RPCError
from modules.utils import load_json_setting, save_json_setting
from modules.show import safe_edit_or_silent

_click_db = {}  # (me_id, cid, msg_id) -> (clicks, timestamp)
_catch_cfg_cache = {}

def _prune_click_db(now: float):
    if len(_click_db) > 1000:
        cutoff = now - 600.0  # 10 minutes
        to_del = [key for key, (_, ts) in _click_db.items() if ts < cutoff]
        for key in to_del:
            _click_db.pop(key, None)

def get_catch_cfg(u_id: int) -> dict:
    if u_id in _catch_cfg_cache:
        return _catch_cfg_cache[u_id]
    cfg = load_json_setting(f"autocatch_{u_id}.json", default={})
    _catch_cfg_cache[u_id] = cfg
    return cfg

def set_catch_cfg(u_id: int, cfg: dict):
    _catch_cfg_cache[u_id] = cfg
    save_json_setting(f"autocatch_{u_id}.json", cfg)

async def autocatch_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    raw = ev.raw_text or ""
    toks = raw.split()
    cid = str(ev.chat_id)
    all_cfg = get_catch_cfg(me_id)
    
    cfg = all_cfg.get(cid, {"status": False, "delay": 0, "times": 1})
    
    if len(toks) < 2:
        st = "🟢 فعال" if cfg.get("status") else "🔴 غیرفعال"
        delay_val = cfg.get("delay", 0)
        times_val = cfg.get("times", 1)
        
        msg = (
            f"🐱 **سیستم نجات خودکار گربه خیابونی (AutoCatch)**\n\n"
            f"▸ وضعیت در این چت: **{st}**\n"
            f"⏱️ تاخیر کلیک (delay): `{delay_val} ثانیه`\n"
            f"🔢 تعداد تلاش برروی ادیت (times): `{times_val} بار`\n\n"
            f"💡 **راهنما:**\n"
            f"▸ `/autocatch on` / `/autocatch off` ── فعال/غیرفعال‌سازی در این چت\n"
            f"▸ `/autocatch delay [0-10]` ── تنظیم تاخیر زمان کلیک (ثانیه)\n"
            f"▸ `/autocatch times [1-3]` ── تنظیم تعداد کلیک مجدد هنگام ادیت پیام"
        )
        await safe_edit_or_silent(ev, msg)
        return
        
    sub = toks[1].strip().lower()
    if sub == "on":
        cfg["status"] = True
        all_cfg[cid] = cfg
        set_catch_cfg(me_id, all_cfg)
        await safe_edit_or_silent(ev, "🐱 **نجات خودکار گربه خیابونی در این چت فعال شد!** 🟢")
    elif sub == "off":
        cfg["status"] = False
        all_cfg[cid] = cfg
        set_catch_cfg(me_id, all_cfg)
        await safe_edit_or_silent(ev, "🐱 **نجات خودکار گربه خیابونی در این چت غیرفعال شد.** 🔴")
    elif sub == "delay":
        if len(toks) >= 3 and toks[2].isdigit():
            val = max(0, min(10, int(toks[2])))
            cfg["delay"] = val
            all_cfg[cid] = cfg
            set_catch_cfg(me_id, all_cfg)
            await safe_edit_or_silent(ev, f"⏱️ **تاخیر کلیک روی `{val}` ثانیه تنظیم شد.**")
        else:
            await safe_edit_or_silent(ev, "⚠️ **لطفا یک عدد بین ۰ تا ۱۰ وارد کنید.** (مثال: `/autocatch delay 2`)")
    elif sub == "times":
        if len(toks) >= 3 and toks[2].isdigit():
            val = max(1, min(3, int(toks[2])))
            cfg["times"] = val
            all_cfg[cid] = cfg
            set_catch_cfg(me_id, all_cfg)
            await safe_edit_or_silent(ev, f"🔢 **تعداد کلیک مجدد هنگام ادیت روی `{val}` بار تنظیم شد.**")
        else:
            await safe_edit_or_silent(ev, "⚠️ **لطفا یک عدد بین ۱ تا ۳ وارد کنید.** (مثال: `/autocatch times 2`)")
    else:
        await safe_edit_or_silent(ev, "⚠️ **دستور نامعتبر. از `on`, `off`, `delay` یا `times` استفاده کنید.**")

async def handle_autocatch_trigger(ev, is_edit: bool = False):
    if ev.out:
        return

    msg = ev.message
    if not msg or not getattr(msg, 'buttons', None):
        return

    btn_found = None
    btn_pos = None
    for r_idx, r in enumerate(msg.buttons):
        for c_idx, b in enumerate(r):
            if b.text and "نجات" in b.text:
                btn_found = b
                btn_pos = (r_idx, c_idx)
                break
        if btn_found:
            break

    if not btn_found:
        return

    client = ev.client
    me_id = getattr(client, 'uid', None)
    if not me_id:
        try:
            me_id = (await client.get_me()).id
        except Exception:
            return

    cid = str(ev.chat_id)
    all_cfg = get_catch_cfg(me_id)
    chat_cfg = all_cfg.get(cid)

    if not chat_cfg or not chat_cfg.get("status"):
        return

    now = time.time()
    _prune_click_db(now)

    k = (me_id, cid, msg.id)
    entry = _click_db.get(k)
    clicks = entry[0] if entry else 0
    max_tries = chat_cfg.get("times", 1)

    if clicks >= max_tries:
        return

    d = chat_cfg.get("delay", 0)
    if is_edit:
        d = max(2, d)

    if d > 0:
        await asyncio.sleep(d)

    try:
        _click_db[k] = (clicks + 1, now)
        if btn_pos:
            await ev.click(btn_pos[0], btn_pos[1])
        else:
            await btn_found.click()

        if max_tries > 1 and clicks + 1 < max_tries:
            async def _burst():
                await asyncio.sleep(0.08)
                try:
                    if btn_pos:
                        await ev.click(btn_pos[0], btn_pos[1])
                    else:
                        await btn_found.click()
                except Exception:
                    pass
            asyncio.create_task(_burst())
    except MessageIdInvalidError:
        pass
    except RPCError as rpc:
        print(f"[!] autocatch click error (user {me_id}) in {cid}: {rpc}")
    except Exception:
        pass
