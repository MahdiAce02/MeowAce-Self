import html
import re
from telethon import events
from telethon.tl.types import User, Channel, Chat, PeerUser, PeerChannel, PeerChat
from telethon.errors import RPCError

def get_entity_type_str(entity) -> str:
    if isinstance(entity, User):
        if getattr(entity, 'bot', False):
            return "🤖 ربات (Bot)"
        return "👤 کاربر حقیقی"
    elif isinstance(entity, Channel):
        if getattr(entity, 'broadcast', False):
            return "📢 کانال (Channel)"
        return "👥 سوپرگروه (Supergroup)"
    elif isinstance(entity, Chat):
        return "👥 گروه معمولی (Group)"
    return "ناشناس"

async def get_info_text_and_entity(client, ev, target_arg: str = None):
    """
    Extract entity and format comprehensive information for info command.
    Returns (info_text, resolved_entity, forward_entity)
    """
    reply_msg = None
    if ev.is_reply:
        reply_msg = await ev.get_reply_message()

    target_entity = None
    fwd_entity = None
    fwd_hidden_name = None
    is_forwarded = False

    # 1. Check if argument was passed (e.g. @username, 1234567, etc.)
    if target_arg:
        arg = target_arg.strip()
        # Clean URL format
        if "t.me/" in arg:
            arg = arg.split("t.me/")[-1].replace("/", "").strip()
        if arg.startswith("@"):
            arg = arg[1:]
        
        # Check if numeric
        if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
            lookup_val = int(arg)
        else:
            lookup_val = arg

        try:
            target_entity = await client.get_entity(lookup_val)
        except Exception as e:
            return f"❌ کاربر یا چت با شناسه `{target_arg}` یافت نشد.\nعلت: {e}", None, None

    # 2. If no argument, but replied to a message
    elif reply_msg:
        # Check forwarded info
        fwd = getattr(reply_msg, 'fwd_from', None) or getattr(reply_msg, 'forward', None)
        if fwd:
            is_forwarded = True
            if getattr(fwd, 'from_id', None):
                try:
                    fwd_entity = await client.get_entity(fwd.from_id)
                except Exception:
                    fwd_entity = fwd.from_id
            elif getattr(fwd, 'from_name', None):
                fwd_hidden_name = fwd.from_name

        try:
            target_entity = await reply_msg.get_sender()
        except Exception:
            pass

        if not target_entity and reply_msg.sender_id:
            try:
                target_entity = await client.get_entity(reply_msg.sender_id)
            except Exception:
                pass

    # 3. If also event itself is a forward (e.g. user forwarded directly to bot)
    elif getattr(ev, 'fwd_from', None) or getattr(ev, 'forward', None):
        fwd = getattr(ev, 'fwd_from', None) or getattr(ev, 'forward', None)
        is_forwarded = True
        if getattr(fwd, 'from_id', None):
            try:
                target_entity = await client.get_entity(fwd.from_id)
            except Exception:
                target_entity = fwd.from_id
        elif getattr(fwd, 'from_name', None):
            fwd_hidden_name = fwd.from_name
            target_entity = None

    # 4. If neither, fallback to the sender or self (me)
    if not target_entity and not fwd_hidden_name:
        try:
            target_entity = await ev.get_sender()
        except Exception:
            target_entity = await client.get_me()

    # Build the report
    lines = ["🔍 **اطلاعات شناسایی (Info)**\n"]

    main_uid = None

    if target_entity:
        if isinstance(target_entity, (User, Channel, Chat)):
            main_uid = target_entity.id
            first_name = getattr(target_entity, 'first_name', '') or ''
            last_name = getattr(target_entity, 'last_name', '') or ''
            full_name = f"{first_name} {last_name}".strip() or getattr(target_entity, 'title', '') or 'بدون نام'
            username = f"@{target_entity.username}" if getattr(target_entity, 'username', None) else "ندارد"
            ent_type = get_entity_type_str(target_entity)
            dc_id = getattr(target_entity.photo, 'dc_id', 'نامشخص') if getattr(target_entity, 'photo', None) else 'ندارد'
            is_premium = "بله ⭐️" if getattr(target_entity, 'premium', False) else "خیر"
            is_verified = "بله 🔵" if getattr(target_entity, 'verified', False) else "خیر"
            is_scam = "⚠️ اخطار اسکم (Scam)" if getattr(target_entity, 'scam', False) else "خیر"
            
            lines.append(f"👤 **مشخصات کاربر / چت:**")
            lines.append(f"• **نام:** {full_name}")
            lines.append(f"• **یوزرنیم:** {username}")
            lines.append(f"• **آیدی عددی:** `{target_entity.id}`  *(لمس جهت کپی)*")
            lines.append(f"• **نوع:** {ent_type}")
            if isinstance(target_entity, User):
                lines.append(f"• **پرمیوم:** {is_premium}")
                lines.append(f"• **لینک پروفایل:** [پروفایل](tg://user?id={target_entity.id})")
            if is_verified != "خیر":
                lines.append(f"• **تایید شده:** {is_verified}")
            if is_scam != "خیر":
                lines.append(f"• **وضعیت:** {is_scam}")
            lines.append(f"• **دیتا سنتر (DC):** `{dc_id}`")
        else:
            # Raw Peer or ID
            pid = getattr(target_entity, 'user_id', None) or getattr(target_entity, 'channel_id', None) or getattr(target_entity, 'chat_id', None) or str(target_entity)
            main_uid = pid
            lines.append(f"• **آیدی عددی:** `{pid}`")

    # If forwarded message
    if is_forwarded:
        lines.append("\n📨 **اطلاعات فوروارد (Forward Source):**")
        if fwd_entity and isinstance(fwd_entity, (User, Channel, Chat)):
            fwd_fn = getattr(fwd_entity, 'first_name', '') or ''
            fwd_ln = getattr(fwd_entity, 'last_name', '') or ''
            fwd_full = f"{fwd_fn} {fwd_ln}".strip() or getattr(fwd_entity, 'title', '') or 'بدون نام'
            fwd_un = f"@{fwd_entity.username}" if getattr(fwd_entity, 'username', None) else "ندارد"
            lines.append(f"• **فرستنده اصلی:** {fwd_full}")
            lines.append(f"• **یوزرنیم اصلی:** {fwd_un}")
            lines.append(f"• **آیدی عددی اصلی:** `{fwd_entity.id}`  *(لمس جهت کپی)*")
            lines.append(f"• **نوع منبع:** {get_entity_type_str(fwd_entity)}")
            if not main_uid:
                main_uid = fwd_entity.id
        elif fwd_hidden_name:
            lines.append(f"• **نام مخفی:** {fwd_hidden_name}")
            lines.append("• **آیدی عددی:** 🔒 مخفی شده توسط تنظیمات حریم خصوصی فرستنده")
        elif fwd_entity:
            lines.append(f"• **شناسه منبع:** `{fwd_entity}`")

    # Current chat info
    chat_id = ev.chat_id
    if chat_id:
        lines.append(f"\n📍 **اطلاعات چت فعلی:**")
        lines.append(f"• **آیدی چت:** `{chat_id}`")
        if reply_msg:
            lines.append(f"• **آیدی پیام ریپلای شده:** `{reply_msg.id}`")

    return "\n".join(lines), target_entity, fwd_entity


async def info_command(ev):
    """Handler for selfbot outgoing info command."""
    client = ev.client
    me_id = getattr(client, 'uid', None)
    if not me_id:
        try:
            me_id = (await client.get_me()).id
        except Exception:
            pass

    # In selfbot, execute if message is outgoing or if sender matches client user ID
    is_outgoing = getattr(ev, 'out', False)
    if not is_outgoing and ev.sender_id != me_id:
        return

    text = ev.raw_text or ""
    parts = text.split(maxsplit=1)
    target_arg = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

    # Indicate processing if needed
    try:
        info_txt, ent, fwd_ent = await get_info_text_and_entity(client, ev, target_arg)
        await ev.edit(info_txt, link_preview=False)
    except Exception as e:
        try:
            await ev.edit(f"❌ خطا در استعلام اطلاعات: {e}", link_preview=False)
        except Exception:
            await ev.respond(f"❌ خطا در استعلام اطلاعات: {e}", link_preview=False)
