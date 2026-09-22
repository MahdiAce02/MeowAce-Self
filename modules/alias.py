import re
from modules.utils import load_json_setting, save_json_setting
from modules.show import safe_edit_or_silent

def load_user_aliases(uid: int) -> dict:
    return load_json_setting(f"aliases_{uid}.json", default={})

def save_user_aliases(uid: int, al_dict: dict):
    save_json_setting(f"aliases_{uid}.json", al_dict)

def add_alias(uid: int, alias_name: str, target_cmd: str):
    name = alias_name.strip().lstrip('/.').lower()
    if not name or not target_cmd:
        return False, "نام الیاس یا دستور مقصد نمی‌تواند خالی باشد."
        
    al = load_user_aliases(uid)
    al[name] = target_cmd.strip()
    save_user_aliases(uid, al)
    return True, f"✅ الیاس `{name}` برای دستور `{target_cmd}` با موفقیت ثبت شد."

def delete_alias(uid: int, alias_name: str):
    name = alias_name.strip().lstrip('/.').lower()
    al = load_user_aliases(uid)
    if name in al:
        del al[name]
        save_user_aliases(uid, al)
        return True, f"✅ الیاس `{name}` با موفقیت حذف شد."
    return False, f"⚠️ الیاس `{name}` یافت نشد."

def clear_aliases(uid: int):
    al = load_user_aliases(uid)
    al.clear()
    save_user_aliases(uid, al)
    return True, "✅ تمامی الیاس‌ها پاکسازی شدند."

def resolve_alias(uid: int, raw_text: str):
    # alias shortcut macro parser ($1, $2, $*, &&)
    if not raw_text or not isinstance(raw_text, str):
        return False, []

    s = raw_text.strip()
    if not s:
        return False, []

    al = load_user_aliases(uid)
    if not al:
        return False, []

    m = re.match(r'^(?:[/.])?([^\s]+)(?:\s+(.*))?$', s, re.DOTALL)
    if not m:
        return False, []

    head = m.group(1).lower()
    rest = m.group(2) if m.group(2) else ""

    if head not in al:
        return False, []

    target = al[head]

    chunks = [c.strip() for c in target.split("&&") if c.strip()][:5]
    res = []
    args = rest.split() if rest else []

    for chunk in chunks:
        cmd = chunk
        if re.search(r'\$(?:\d+|\*)', cmd):
            for idx, val in enumerate(args, start=1):
                cmd = cmd.replace(f"${idx}", val)
            cmd = cmd.replace("$*", rest)
            cmd = re.sub(r'\$\d+', '', cmd).strip()
        else:
            if rest:
                cmd = f"{cmd} {rest}"
        
        res.append(cmd.strip())

    return True, res

async def alias_command(ev):
    client = ev.client
    me_id = getattr(client, 'uid', None) or (await client.get_me()).id
    if ev.sender_id != me_id:
        return

    raw = ev.raw_text or ""
    toks = raw.split(maxsplit=2)
    
    if len(toks) < 2:
        await safe_edit_or_silent(
            ev,
            "🔗 **مدیریت الیاس و میانبر دستورات (Command Alias)**\n\n"
            "💡 **توضیحات:**\n"
            "تعریف اسم کوتاه برای اجرای دستورات دلخواه به همراه پشتیبانی از آرگومان‌ها.\n\n"
            "📖 **راهنمای استفاده:**\n"
            "▸ `/alias add [نام الیاس] [دستور مقصد]` ── افزودن الیاس جدید\n"
            "▸ `/alias del [نام الیاس]` ── حذف الیاس\n"
            "▸ `/alias list` ── مشاهده لیست الیاس‌های فعال\n"
            "▸ `/alias clear` ── پاکسازی تمام الیاس‌ها\n\n"
            "📌 **مثال:**\n"
            "`alias add am automeow` ── با ارسال `am` دستور `automeow` اجرا می‌شود."
        )
        return

    sub = toks[1].lower()

    if sub == "add":
        sp = raw.split(maxsplit=3)
        if len(sp) < 4:
            await safe_edit_or_silent(ev, "⚠️ **راهنما:** `alias add [alias_name] [target_cmd]`\nمثال: `alias add am automeow`")
            return
        _, msg = add_alias(me_id, sp[2], sp[3])
        await safe_edit_or_silent(ev, msg)

    elif sub == "del":
        sp = raw.split(maxsplit=2)
        if len(sp) < 3:
            await safe_edit_or_silent(ev, "⚠️ **راهنما:** `alias del [alias_name]`")
            return
        _, msg = delete_alias(me_id, sp[2])
        await safe_edit_or_silent(ev, msg)

    elif sub == "list":
        al = load_user_aliases(me_id)
        if not al:
            await safe_edit_or_silent(ev, "⚠️ **هیچ الیاسی ثبت نشده است.**")
            return

        out = "🔗 **لیست الیاس‌های فعال شما:**\n\n"
        for i, (k, v) in enumerate(al.items(), 1):
            out += f"{i}. `{k}` ➔ `{v}`\n"
        await safe_edit_or_silent(ev, out)

    elif sub in ["clear", "reset"]:
        clear_aliases(me_id)
        await safe_edit_or_silent(ev, "✅ **تمامی الیاس‌های ثبت شده پاکسازی شدند.**")
    else:
        await safe_edit_or_silent(ev, "⚠️ **دستور نامعتبر. از `add`, `del`, `list` یا `clear` استفاده کنید.**")
