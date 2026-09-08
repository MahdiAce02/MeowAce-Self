import re
import asyncio
from telethon.errors import RPCError
from modules.utils import load_json_setting, save_json_setting, convert_persian_digits

# کد خفاش -> ایموجی شکار (از لیست کاربر)
BAT_EMOJI = {
    1: "✨",
    2: "🧄",
    3: "👀",
    4: "👶",
    5: "💦",
    6: "👾",
    7: "🌦",
    8: "💨",
    9: "⚫️",
    10: "🕷",
    11: "🧼",
    12: "🐥",
    13: "💙",
    14: "💙",
    15: "🙍‍♀️",
    16: "🧽",
    17: "🌹",
    18: "🤖",
    19: "💥",
    20: "🍋",
    21: "🎭",
    22: "🗻",
    23: "🪞",
    24: "🃏",
    25: "❤️",
    26: "🚒",
    27: "🌕",
    28: "🧛",
    29: "🧊",
    30: "😇",
    31: "😈",
    32: "🔥",
    33: "🇫🇷",
    34: "⭐️",
    35: "🌧",
    36: "🪙",
    37: "⚡️",
    38: "🌑",
}

_bat_cfg_cache = {}

def get_bat_cfg(u_id: int) -> dict:
    if u_id in _bat_cfg_cache:
        return _bat_cfg_cache[u_id]
    cfg = load_json_setting(f"autobat_{u_id}.json", default={})
    _bat_cfg_cache[u_id] = cfg
    return cfg

def set_bat_cfg(u_id: int, cfg: dict):
    _bat_cfg_cache[u_id] = cfg
    save_json_setting(f"autobat_{u_id}.json", cfg)

def _norm_bat_txt(txt: str) -> str:
    """یکدست‌سازی ک/ك و ی/ي و اعداد فارسی برای تشخیص مطمئن پیام خفاش."""
    if not txt:
        return ""
    t = convert_persian_digits(txt)
    # عربی -> فارسی
    t = t.replace("ك", "ک").replace("ي", "ی").replace("ى", "ی")
    return t

def parse_bat_code(txt: str):
    """استخراج کد خفاش از متن پیام. برمی‌گرداند int یا None"""
    if not txt:
        return None
    t = _norm_bat_txt(txt)
    # الگو: (کد : 20) یا (کد : `20`) — کد ممکن است داخل بک‌تیک/بولد مارکدان باشد
    m = re.search(r'کد[^0-9]{0,10}([0-9]{1,3})', t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None

def is_bat_message(txt: str) -> bool:
    if not txt:
        return False
    t = _norm_bat_txt(txt)
    # عمدا شل گرفتیم: فقط «خفاش» + «کد» کافی است (سطر سوم هم همین را دارد)
    return "خفاش" in t and "کد" in t

async def autobat_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return

    raw = ev.raw_text or ""
    toks = raw.split()
    cid = str(ev.chat_id)
    all_cfg = get_bat_cfg(me_id)
    cfg = all_cfg.get(cid, {"status": False, "delay": 1})

    if len(toks) < 2:
        st = "🟢 فعال" if cfg.get("status") else "🔴 غیرفعال"
        delay_val = cfg.get("delay", 1)
        msg = (
            f"🦇 **سیستم شکار خودکار خفاش (AutoBat)**\n\n"
            f"▸ وضعیت در این چت: **{st}**\n"
            f"⏱️ تاخیر ارسال ایموجی (delay): `{delay_val} ثانیه`\n\n"
            f"💡 **راهنما:**\n"
            f"▸ `/autobat on` / `/autobat off` ── فعال/غیرفعال‌سازی در این چت\n"
            f"▸ `/autobat delay [0-115]` ── تنظیم تاخیر ارسال (ثانیه)\n"
            f"▸ `/autobat list` ── نمایش لیست کد → ایموجی\n\n"
            f"✋ **حالت دستی:** روی پیام خفاش ریپلای بزن و بنویس `batt` — پیامت پاک میشه و ایموجی درستش ارسال میشه."
        )
        await ev.edit(msg)
        return

    sub = toks[1].strip().lower()
    if sub == "on":
        cfg["status"] = True
        all_cfg[cid] = cfg
        set_bat_cfg(me_id, all_cfg)
        await ev.edit("🦇 **شکار خودکار خفاش در این چت فعال شد!** 🟢")
    elif sub == "off":
        cfg["status"] = False
        all_cfg[cid] = cfg
        set_bat_cfg(me_id, all_cfg)
        await ev.edit("🦇 **شکار خودکار خفاش در این چت غیرفعال شد.** 🔴")
    elif sub == "delay":
        if len(toks) >= 3 and toks[2].isdigit():
            val = max(0, min(115, int(convert_persian_digits(toks[2]))))
            cfg["delay"] = val
            all_cfg[cid] = cfg
            set_bat_cfg(me_id, all_cfg)
            await ev.edit(f"⏱️ **تاخیر شکار خفاش روی `{val}` ثانیه تنظیم شد.**")
        else:
            await ev.edit("⚠️ **لطفا یک عدد بین 0 تا 115 وارد کنید.** (مثال: `/autobat delay 2`)")
    elif sub == "list":
        lines = ["🦇 **لیست کد → ایموجی خفاش‌ها:**\n"]
        for code in sorted(BAT_EMOJI.keys()):
            lines.append(f"`{code}` ➔ {BAT_EMOJI[code]}")
        # تلگرام محدودیت طول دارد، خلاصه می‌فرستیم
        await ev.edit("\n".join(lines))
    else:
        await ev.edit("⚠️ **دستور نامعتبر. از `on`, `off`, `delay` یا `list` استفاده کنید.**")

async def handle_manual_bat(ev) -> bool:
    """حالت دستی: ریپلای روی پیام خفاش با متن bat -> پاک کردن پیام + ارسال ایموجی.

    برمی‌گرداند True اگر پیام مصرف شد (حذف شد)، وگرنه False.
    عمدا مستقل از on/off بودن autobat کار می‌کند.
    """
    try:
        raw = (ev.raw_text or "").strip()
    except Exception:
        return False
    if not raw:
        return False
    # فقط تریگر دقیق batt (با یا بدون پیشوند / . = و بدون حساسیت به حروف)
    cleaned = raw.lower().lstrip("/.=!").strip()
    if cleaned != "batt":
        return False

    print(f"[ManualBat] trigger seen, is_reply={getattr(ev, 'is_reply', '?')} out={getattr(ev, 'out', '?')} chat={getattr(ev, 'chat_id', '?')}")

    # ریپلای بودن را از دو راه چک می‌کنیم (is_reply گاهی گمراه‌کننده است، مخصوصا سیو مسیج)
    reply_msg = None
    try:
        reply_msg = await ev.get_reply_message()
    except Exception as e:
        print(f"[!] manual bat get_reply error: {e}")
        reply_msg = None

    reply_to_id = getattr(reply_msg, 'id', None) if reply_msg else None

    # فالبک برای سیو مسیج: اگر get_reply_message خالی داد، از هدر reply_to آیدی را بکش بیرون
    if not reply_msg or not reply_to_id:
        try:
            hdr = getattr(getattr(ev, 'message', None), 'reply_to', None)
            hdr_id = getattr(hdr, 'reply_to_msg_id', None) if hdr else None
            cand = (
                getattr(ev, 'reply_to_msg_id', None)
                or getattr(getattr(ev, 'message', None), 'reply_to_msg_id', None)
                or hdr_id
            )
            if cand:
                print(f"[ManualBat] fallback reply_to_id={cand}")
                reply_to_id = cand
                try:
                    reply_msg = await ev.client.get_messages(ev.chat_id, ids=cand)
                except Exception as e:
                    print(f"[!] manual bat fallback fetch error: {e}")
        except Exception as e:
            print(f"[!] manual bat fallback error: {e}")

    if not reply_msg:
        print("[!] manual bat: no replied message found (get_reply_message returned None)")
        return False
    txt = getattr(reply_msg, 'text', None) or getattr(reply_msg, 'message', None) or ""
    # اگر get_reply_message متن نداد، یک بار هم با get_messages تلاش کن
    if not txt and reply_to_id:
        try:
            client_tmp = ev.client
            target2 = await client_tmp.get_messages(ev.chat_id, ids=reply_to_id)
            if target2:
                txt = getattr(target2, 'text', None) or getattr(target2, 'message', None) or ""
        except Exception:
            pass

    print(f"[ManualBat] replied text head: {txt[:80]!r}")

    code = parse_bat_code(txt)
    print(f"[ManualBat] parsed code: {code}")
    if code is None:
        # روی پیام غیرخفاش ریپلای شده -> پیام تریگر را نگه می‌داریم تا اشتباهی پاک نشود
        return False

    emoji = BAT_EMOJI.get(code)
    if not emoji:
        print(f"[!] manual bat: unknown bat code {code}")
        try:
            await ev.delete()
        except Exception as e:
            print(f"[!] manual bat delete error: {e}")
        return True

    # اول پیام تریگر را پاک کن، بعد ایموجی را ریپلای کن
    try:
        await ev.delete()
        print("[ManualBat] trigger message deleted")
    except Exception as e:
        print(f"[!] manual bat delete error: {e}")

    try:
        await ev.client.send_message(ev.chat_id, emoji, reply_to=reply_to_id)
        print(f"[ManualBat] hunted bat code {code} in {ev.chat_id}")
    except RPCError as rpc:
        print(f"[!] manual bat send error: {rpc}")
    except Exception as e:
        print(f"[!] manual bat send error: {e}")
    return True

async def handle_autobat_trigger(ev):
    if ev.out:
        return

    # اول چک کن این چت روشن است یا نه؛ اگر خاموش بود اصلا پیام را نخوان
    client = ev.client
    me_id = getattr(client, 'uid', None)
    if not me_id:
        try:
            me_id = (await client.get_me()).id
        except Exception:
            return

    cid = str(ev.chat_id)
    all_cfg = get_bat_cfg(me_id)
    chat_cfg = all_cfg.get(cid)
    if not chat_cfg or not chat_cfg.get("status"):
        return

    msg = ev.message
    if not msg:
        return

    txt = getattr(msg, 'text', None) or ev.raw_text or ""
    if not txt:
        return

    if not is_bat_message(txt):
        return

    print(f"[AutoBat] detected bat spawn in {ev.chat_id}")

    code = parse_bat_code(txt)
    if code is None:
        print(f"[AutoBat] bat msg without parseable code in {ev.chat_id}")
        return

    emoji = BAT_EMOJI.get(code)
    if not emoji:
        print(f"[!] autobat: unknown bat code {code}")
        return

    d = chat_cfg.get("delay", 1)
    if d > 0:
        await asyncio.sleep(d)

    try:
        # حتما در پاسخ (ریپلای) به پیام خفاش ارسال شود
        await client.send_message(ev.chat_id, emoji, reply_to=msg.id)
        print(f"[AutoBat] hunted bat code {code} with {emoji} in {cid}")
    except RPCError as rpc:
        print(f"[!] autobat send error in {cid}: {rpc}")
    except Exception:
        pass
