import asyncio
from modules.utils import load_json_setting, save_json_setting

# toggle silent execution mode
def get_show_mode(uid: int) -> bool:
    d = load_json_setting(f"show_{uid}.json", default={"show_mode": True})
    return d.get("show_mode", True)

def set_show_mode(uid: int, status: bool):
    save_json_setting(f"show_{uid}.json", {"show_mode": status})

async def show_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return
        
    toks = (ev.raw_text or "").split()
    if len(toks) < 2:
        cur = get_show_mode(me_id)
        st_txt = "`فعال (ON) 🟢`" if cur else "`غیرفعال (OFF) 🔴`"
        await ev.edit(
            f"👁️ **حالت نمایش دستورات (Show Mode)**\n\n"
            f"▸ وضعیت فعلی: {st_txt}\n\n"
            f"💡 **توضیحات:**\n"
            f"خاموش کردن پاسخ به دستورات بازیکن جهت عدم شناسایی ربات توسط ادمین‌ها و حذف آنی کامند.\n\n"
            f"▸ `/show on` ── نمایش پیام‌های خروجی و وضعیت ربات\n"
            f"▸ `/show off` ── خاموش کردن پاسخ‌ها و حذف خودکار پیام دستور"
        )
        return
        
    opt = toks[1].strip().lower()
    if opt == "on":
        set_show_mode(me_id, True)
        await ev.edit("👁️ **حالت نمایش دستورات فعال شد.** 🟢\nپیام‌های وضعیت نمایش داده خواهند شد.")
    elif opt == "off":
        set_show_mode(me_id, False)
        await ev.edit("👁️ **حالت نمایش دستورات غیرفعال شد.** 🔴\nدستورات به صورت مخفیانه اجرا شده و پیام پاک می‌شود.")
        await asyncio.sleep(2)
        try:
            await ev.delete()
        except Exception:
            pass
    else:
        await ev.edit("⚠️ **گزینه نامعتبر است. از `/show on` یا `/show off` استفاده کنید.**")

async def safe_edit_or_silent(ev, text: str, parse_mode: str = None, delete_after: float = 1.0):
    """
    If show mode is True for this user, edits the message with text.
    If show mode is False, deletes the message silently after executing command.
    """
    client = ev.client
    me_id = getattr(client, 'uid', None)
    if not me_id:
        try:
            me_id = (await client.get_me()).id
        except Exception:
            me_id = 0

    if get_show_mode(me_id):
        kwargs = {}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        try:
            await ev.edit(text, **kwargs)
        except Exception:
            pass
    else:
        if delete_after > 0:
            await asyncio.sleep(delete_after)
        try:
            await ev.delete()
        except Exception:
            pass

