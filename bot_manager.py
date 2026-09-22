import os
import sys
import time
import re
import asyncio
from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    RPCError
)

from multisession import (
    load_bot_config, save_bot_config,
    load_bot_data, save_bot_data,
    is_admin, can_user_access,
    start_user_client, stop_user_client,
    get_session_filepath, active_user_clients,
    ensure_environment_directories,
    resume_all_sessions, subscription_monitor_loop
)
from modules.proxy import get_proxy_kwargs
from modules.utils import convert_persian_digits
from modules.info import get_info_text_and_entity

user_login_states = {}
user_admin_states = {}
last_code_request_time = {}
bot_client_instance = None

TELEGRAM_PRESETS = {
    "macos": {
        "title": "⚡ ورود سریع (Telegram macOS - رسمی اپل)",
        "api_id": 2834,
        "api_hash": "68875f756c9b437a8b916ca3de215815",
        "device_model": "MacBook Pro",
        "system_version": "macOS 14.4.1",
        "app_version": "10.11",
        "lang_code": "en",
        "system_lang_code": "en"
    },
    "server": {
        "title": "🤖 ورود با API پیش‌فرض سرور",
        "device_model": "PC 64bit",
        "system_version": "Windows 11",
        "app_version": "5.4.1",
        "lang_code": "en",
        "system_lang_code": "en"
    }
}

def get_otp_numpad_buttons(current_code: str = ""):
    return [
        [
            Button.inline("1", b"numpad_1"),
            Button.inline("2", b"numpad_2"),
            Button.inline("3", b"numpad_3")
        ],
        [
            Button.inline("4", b"numpad_4"),
            Button.inline("5", b"numpad_5"),
            Button.inline("6", b"numpad_6")
        ],
        [
            Button.inline("7", b"numpad_7"),
            Button.inline("8", b"numpad_8"),
            Button.inline("9", b"numpad_9")
        ],
        [
            Button.inline("⌫ پاک کردن", b"numpad_del"),
            Button.inline("0", b"numpad_0"),
            Button.inline("✅ تایید و ورود", b"numpad_submit")
        ],
        [Button.inline("❌ انصراف", b"cancel_login")]
    ]

async def process_otp_sign_in(ev, user_id: int, otp_code: str, state: dict, main_config: dict, bot: TelegramClient):
    temp_client = state.get("temp_client")
    phone = state.get("phone")
    phone_code_hash = state.get("phone_code_hash")
    api_id = state["api_id"]
    api_hash = state["api_hash"]
    device_model = state.get("device_model", "PC 64bit")
    system_version = state.get("system_version", "Windows 11")
    app_version = state.get("app_version", "5.4.1")
    lang_code = state.get("lang_code", "en")
    system_lang_code = state.get("system_lang_code", "en")

    bot_cfg = load_bot_config()
    bot_dt = load_bot_data()

    try:
        await temp_client.sign_in(phone=phone, code=otp_code, phone_code_hash=phone_code_hash)
        me = await temp_client.get_me()
        await temp_client.disconnect()

        uid_str = str(user_id)
        bot_dt["users"].setdefault(uid_str, {})
        bot_dt["users"][uid_str]["api_id"] = api_id
        bot_dt["users"][uid_str]["api_hash"] = api_hash
        bot_dt["users"][uid_str]["phone"] = phone
        bot_dt["users"][uid_str]["first_name"] = getattr(me, 'first_name', '') or ''
        bot_dt["users"][uid_str]["username"] = getattr(me, 'username', '') or ''
        if device_model: bot_dt["users"][uid_str]["device_model"] = device_model
        if system_version: bot_dt["users"][uid_str]["system_version"] = system_version
        if app_version: bot_dt["users"][uid_str]["app_version"] = app_version
        if lang_code: bot_dt["users"][uid_str]["lang_code"] = lang_code
        if system_lang_code: bot_dt["users"][uid_str]["system_lang_code"] = system_lang_code
        save_bot_data(bot_dt)

        proxy_kw = get_proxy_kwargs(main_config)
        success, msg = await start_user_client(
            user_id, api_id, api_hash, proxy_kw,
            device_model=device_model,
            system_version=system_version,
            app_version=app_version,
            lang_code=lang_code,
            system_lang_code=system_lang_code
        )
        user_login_states.pop(user_id, None)
        buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
        if success:
            await bot.send_message(user_id, f"🎉 **ورود با موفقیت انجام شد!**\n{msg}", buttons=buttons)
            admin_id = bot_cfg.get("admin_id")
            if admin_id and str(admin_id) != str(user_id):
                try:
                    uname = f"@{me.username}" if getattr(me, 'username', None) else "بدون یوزرنیم"
                    await bot.send_message(
                        admin_id,
                        f"🔔 **ورود سشن جدید کاربر:**\n\n"
                        f"👤 کاربر: {me.first_name} ({uname})\n"
                        f"🆔 آیدی: `{user_id}`\n"
                        f"📱 شماره: `{phone}`\n"
                        f"⚡ زمان: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except Exception:
                    pass
        else:
            await bot.send_message(user_id, f"❌ خطا در فعال‌سازی سشن: {msg}", buttons=buttons)

    except SessionPasswordNeededError:
        state["step"] = "ENTER_2FA"
        cancel_btn = [[Button.inline("❌ انصراف", b"cancel_login")]]
        await bot.send_message(
            user_id,
            "🔐 این حساب دارای **رمز عبور دو مرحله‌ای (2FA)** است.\nلطفاً رمز عبور خود را وارد کنید:\n\n"
            "🔒 پیام حاوی رمز عبور بلافاصله جهت حفظ امنیت شما حذف خواهد شد.",
            buttons=cancel_btn
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        state["entered_otp"] = ""
        await bot.send_message(
            user_id,
            "❌ کد تایید وارد شده اشتباه یا منقضی شده است.\n"
            "لطفاً از طریق کیبورد شیشه‌ای زیر یا با ارسال با اعداد فارسی / با فاصله مجدداً وارد نمایید:",
            buttons=get_otp_numpad_buttons("")
        )
    except Exception as e:
        try: await temp_client.disconnect()
        except Exception: pass
        buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
        await bot.send_message(user_id, f"❌ خطا در ورود: {e}", buttons=buttons)
        user_login_states.pop(user_id, None)

def get_main_menu_buttons(user_id: int, bot_config: dict, bot_data: dict):
    buttons = []
    
    uid_str = str(user_id)
    running = user_id in active_user_clients
    
    if running:
        buttons.append([Button.inline("🛑 خروج / توقف سشن", b"btn_logout")])
    else:
        buttons.append([Button.inline("🔐 ورود / شروع حساب", b"btn_login")])

    buttons.append([Button.inline("📊 وضعیت اشتراک", b"btn_status"), Button.inline("🔍 استعلام آیدی (Info)", b"btn_info_query")])

    mode = bot_config.get("mode", "private")
    public_type = bot_config.get("public_type", "free")
    trial_cfg = bot_config.get("trial", {})
    
    if mode == "public" and public_type == "paid":
        buttons.append([Button.inline("💳 خرید اشتراک", b"btn_buy_sub")])
        if trial_cfg.get("enabled", False):
            u_info = bot_data.get("users", {}).get(uid_str, {})
            if not u_info.get("trial_used", False):
                buttons.append([Button.inline("🎁 تست رایگان", b"btn_trial")])

    if is_admin(user_id, bot_config):
        buttons.append([Button.inline("⚙️ پنل مدیریت ادمین", b"btn_admin_panel")])

    return buttons

def get_admin_panel_buttons(bot_config: dict):
    mode = bot_config.get("mode", "private")
    pub_type = bot_config.get("public_type", "free")
    trial_on = bot_config.get("trial", {}).get("enabled", False)
    
    mode_str = "🔒 خصوصی (Private)" if mode == "private" else "🌐 عمومی (Public)"
    pub_str = "🆓 رایگان" if pub_type == "free" else "💰 اشتراکی"
    trial_str = "🟢 روشن" if trial_on else "🔴 خاموش"

    return [
        [Button.inline(f"حالت ربات: {mode_str}", b"toggle_mode")],
        [Button.inline(f"نوع حالت عمومی: {pub_str}", b"toggle_pub_type")],
        [Button.inline(f"تست رایگان: {trial_str}", b"toggle_trial")],
        [Button.inline("✏️ تغییر قیمت اشتراک", b"set_price"), Button.inline("✏️ تغییر مدت اشتراک (روز)", b"set_days")],
        [Button.inline("✏️ تغییر مدت تست (ساعت)", b"set_trial_hrs"), Button.inline("💳 تغییر شماره کارت", b"set_card")],
        [Button.inline("📊 آمار و گزارش زنده", b"admin_stats"), Button.inline("📢 پیام همگانی", b"admin_broadcast")],
        [Button.inline("👥 لیست کاربران و سشن‌ها", b"admin_list_users"), Button.inline("📋 لیست وایت‌لیست", b"admin_list_wl")],
        [Button.inline("➕ افزودن به وایت‌لیست", b"admin_add_wl"), Button.inline("➖ حذف از وایت‌لیست", b"admin_rem_wl")],
        [Button.inline("➕ اعطای اشتراک", b"admin_add_sub"), Button.inline("🛑 توقف سشن کاربر", b"admin_stop_user")],
        [Button.inline("🔙 بازگشت به منوی اصلی", b"btn_main_menu")]
    ]

def format_user_status(user_id: int, bot_config: dict, bot_data: dict) -> str:
    uid_str = str(user_id)
    u_info = bot_data.get("users", {}).get(uid_str, {})
    sub_exp = u_info.get("subscription_expire", 0)
    running = user_id in active_user_clients

    run_str = "🟢 آنلاین و فعال" if running else "🔴 غیرفعال / خاموش"
    
    if is_admin(user_id, bot_config):
        sub_str = "👑 مدیر اصلی (دسترسی نامحدود)"
    elif sub_exp == -1:
        sub_str = "♾️ دائم (وایت‌لیست)"
    elif sub_exp > time.time():
        rem_sec = sub_exp - time.time()
        rem_days = int(rem_sec // 86400)
        rem_hrs = int((rem_sec % 86400) // 3600)
        sub_str = f"🟢 فعال (باقیمانده: {rem_days} روز و {rem_hrs} ساعت)"
    else:
        sub_str = "🔴 منقضی شده"

    return (
        f"📊 **وضعیت حساب کاربری شما**\n\n"
        f"👤 **شناسه:** `{user_id}`\n"
        f"⚡ **وضعیت سشن:** {run_str}\n"
        f"⏱️ **وضعیت اشتراک:** {sub_str}\n"
    )

async def notify_admin_payment_request(bot: TelegramClient, payment_id: str, user_id: int, bot_config: dict, bot_data: dict):
    admin_id = bot_config.get("admin_id")
    if not admin_id:
        return

    sub_cfg = bot_config.get("subscription", {})
    price = sub_cfg.get("price_toman", 50000)
    days = sub_cfg.get("duration_days", 30)

    u_info = bot_data.get("users", {}).get(str(user_id), {})
    name = u_info.get("first_name", "کاربر")
    username = f"@{u_info['username']}" if u_info.get("username") else "بدون یوزرنیم"

    msg = (
        f"📥 **درخواست جدید خرید اشتراک**\n\n"
        f"👤 **کاربر:** {name} ({username}) [`{user_id}`]\n"
        f"💰 **مبلغ:** {price:,} تومان\n"
        f"⏱️ **مدت:** {days} روز\n\n"
        f"آیا درخواست اولیه کاربر تایید می‌شود؟"
    )
    buttons = [
        [Button.inline("✅ تایید (ارسال شماره کارت)", f"pay_app1_{payment_id}".encode())],
        [Button.inline("❌ رد درخواست", f"pay_rej1_{payment_id}".encode())]
    ]
    try:
        await bot.send_message(admin_id, msg, buttons=buttons)
    except Exception as e:
        print(f"[!] Error notifying admin of payment request: {e}")

async def notify_admin_receipt(bot: TelegramClient, payment_id: str, user_id: int, receipt_msg: events.NewMessage.Event, bot_config: dict, bot_data: dict):
    admin_id = bot_config.get("admin_id")
    if not admin_id:
        return

    sub_cfg = bot_config.get("subscription", {})
    price = sub_cfg.get("price_toman", 50000)
    days = sub_cfg.get("duration_days", 30)

    u_info = bot_data.get("users", {}).get(str(user_id), {})
    name = u_info.get("first_name", "کاربر")
    username = f"@{u_info['username']}" if u_info.get("username") else "بدون یوزرنیم"

    msg_caption = (
        f"📥 **رسید واریز جدید دریافت شد!**\n\n"
        f"👤 **کاربر:** {name} ({username}) [`{user_id}`]\n"
        f"💰 **مبلغ:** {price:,} تومان\n"
        f"⏱️ **مدت:** {days} روز\n\n"
        f"لطفاً تصویر رسید را بررسی و تایید یا رد کنید:"
    )
    buttons = [
        [Button.inline("✅ تایید واریز و فعال‌سازی اشتراک", f"pay_app2_{payment_id}".encode())],
        [Button.inline("❌ رد رسید", f"pay_rej2_{payment_id}".encode())]
    ]
    try:
        if receipt_msg.media:
            await bot.send_message(admin_id, msg_caption, file=receipt_msg.media, buttons=buttons)
        else:
            await bot.send_message(admin_id, msg_caption, buttons=buttons)
    except Exception as e:
        print(f"[!] Error forwarding receipt to admin: {e}")

async def start_bot_manager(main_config: dict):
    global bot_client_instance
    ensure_environment_directories()
    bot_config = load_bot_config()
    
    bot_token = bot_config.get("bot_token")
    admin_id = bot_config.get("admin_id")
    bot_api_id = bot_config.get("bot_api_id")
    bot_api_hash = bot_config.get("bot_api_hash")

    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        print("[!] Error: 'bot_token' is missing or invalid in 'bot_config.json'. Please configure it.")
        sys.exit(1)
    if not bot_api_id or not bot_api_hash or bot_api_id == 123456:
        print("[!] Error: 'bot_api_id' / 'bot_api_hash' missing in 'bot_config.json'.")
        sys.exit(1)

    proxy_kwargs = get_proxy_kwargs(main_config)
    
    bot = TelegramClient("sessions/bot_session", bot_api_id, bot_api_hash, **proxy_kwargs)
    await bot.start(bot_token=bot_token)
    bot_client_instance = bot

    me = await bot.get_me()
    print(f"[+] MultiSession Management Bot started as: @{me.username} [ID: {me.id}]")

    @bot.on(events.NewMessage(pattern=r'^/cancel'))
    async def _cancel_cmd(ev):
        user_id = ev.sender_id
        old_st = user_login_states.pop(user_id, None)
        if old_st and old_st.get("temp_client"):
            try: await old_st["temp_client"].disconnect()
            except Exception: pass
        user_admin_states.pop(user_id, None)
        bot_cfg = load_bot_config()
        bot_dt = load_bot_data()
        buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
        await ev.respond("❌ تمامی عملیات‌های جاری لغو شدند.", buttons=buttons)

    @bot.on(events.NewMessage(pattern=r'^/help'))
    async def _help_cmd(ev):
        help_text = (
            "💡 **راهنمای ربات مدیریت MeowAce-Self:**\n\n"
            "• با زدن دکمه «🔐 ورود / شروع حساب» و وارد کردن مشخصات، سلف‌بات روی اکانت شما فعال خواهد شد.\n"
            "• در هر مرحله برای انصراف می‌توانید از دستور `/cancel` استفاده کنید.\n"
            "• پس از ورود، دستورات سلف‌بات نظیر `/status`، `/automeow`، `/autofish`، `/autocatch` و `/autobat` در تلگرام شما فعال خواهند بود."
        )
        await ev.respond(help_text)

    @bot.on(events.NewMessage(pattern=r'^/(?:info|id)($|\s+.*)'))
    async def _info_cmd(ev):
        user_id = ev.sender_id
        bot_cfg = load_bot_config()
        bot_dt = load_bot_data()
        parts = (ev.raw_text or "").split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else None
        
        info_txt, ent, fwd_ent = await get_info_text_and_entity(bot, ev, arg)
        
        buttons = []
        target_uid = getattr(ent, 'id', None) or getattr(fwd_ent, 'id', None)
        if target_uid and is_admin(user_id, bot_cfg):
            wl = bot_dt.get("whitelist", [])
            if target_uid not in wl:
                buttons.append([Button.inline("➕ افزودن به وایت‌لیست (دسترسی دائم)", f"quick_wl_{target_uid}".encode())])
            else:
                buttons.append([Button.inline("➖ حذف از وایت‌لیست", f"quick_unwl_{target_uid}".encode())])
        buttons.append([Button.inline("🔙 منوی اصلی", b"btn_main_menu")])
        await ev.respond(info_txt, buttons=buttons)

    @bot.on(events.NewMessage(pattern=r'^/start'))
    async def _start_handler(ev):
        user_id = ev.sender_id
        bot_cfg = load_bot_config()
        bot_dt = load_bot_data()
        
        # update user metadata
        uid_str = str(user_id)
        if uid_str not in bot_dt["users"]:
            bot_dt["users"][uid_str] = {
                "created_at": time.time(),
                "trial_used": False,
                "subscription_expire": 0
            }
        sender = await ev.get_sender()
        if sender:
            bot_dt["users"][uid_str]["first_name"] = getattr(sender, 'first_name', '') or ''
            bot_dt["users"][uid_str]["username"] = getattr(sender, 'username', '') or ''
        save_bot_data(bot_dt)

        welcome_text = (
            f"👋 **سلام {sender.first_name if sender else ''}! به ربات مدیریت MeowAce-Self خوش آمدید.**\n\n"
            f"از طریق این ربات می‌توانید حساب خودکار تلگرام (Selfbot) خود را فعال، مدیریت یا تمدید کنید."
        )
        buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
        await ev.respond(welcome_text, buttons=buttons)

    @bot.on(events.CallbackQuery)
    async def _callback_handler(ev):
        user_id = ev.sender_id
        data = ev.data.decode('utf-8')
        bot_cfg = load_bot_config()
        bot_dt = load_bot_data()

        if data == "btn_main_menu":
            buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
            await ev.edit("📌 **منوی اصلی:**", buttons=buttons)
            return

        elif data == "btn_status":
            st_text = format_user_status(user_id, bot_cfg, bot_dt)
            buttons = [[Button.inline("🔙 بازگشت", b"btn_main_menu")]]
            await ev.edit(st_text, buttons=buttons)
            return

        elif data == "btn_info_query":
            user_admin_states[user_id] = "awaiting_info_query"
            await ev.edit(
                "🔍 **استعلام آیدی و مشخصات کاربر (Info):**\n\n"
                "جهت دریافت مشخصات و آیدی، یکی از کارهای زیر را انجام دهید:\n"
                "• **یوزرنیم** فرد را ارسال کنید (مثال: `@username`)\n"
                "• **آیدی عددی** فرد را وارد کنید (مثال: `5202998534`)\n"
                "• یا یک پیام از کاربر مورد نظر را به این بات **فوروارد (Forward)** کنید.\n\n"
                "(جهت لغو، دکمه زیر را لمس کنید)",
                buttons=[[Button.inline("🔙 بازگشت به منوی اصلی", b"btn_main_menu")]]
            )
            return

        elif data.startswith("quick_wl_"):
            if not is_admin(user_id, bot_cfg): return
            target_uid = int(data.replace("quick_wl_", ""))
            if target_uid not in bot_dt["whitelist"]:
                bot_dt["whitelist"].append(target_uid)
            uid_str = str(target_uid)
            bot_dt["users"].setdefault(uid_str, {})
            bot_dt["users"][uid_str]["subscription_expire"] = -1
            save_bot_data(bot_dt)
            await ev.answer("✅ به وایت‌لیست اضافه شد!", alert=True)
            buttons = [
                [Button.inline("➖ حذف از وایت‌لیست", f"quick_unwl_{target_uid}".encode())],
                [Button.inline("🔙 منوی اصلی", b"btn_main_menu")]
            ]
            await ev.edit(f"✅ **کاربر `{target_uid}` با موفقیت به وایت‌لیست اضافه شد و دسترسی دائم برای او فعال گردید.**", buttons=buttons)
            return

        elif data.startswith("quick_unwl_"):
            if not is_admin(user_id, bot_cfg): return
            target_uid = int(data.replace("quick_unwl_", ""))
            if target_uid in bot_dt["whitelist"]:
                bot_dt["whitelist"].remove(target_uid)
            uid_str = str(target_uid)
            if uid_str in bot_dt["users"] and bot_dt["users"][uid_str].get("subscription_expire") == -1:
                bot_dt["users"][uid_str]["subscription_expire"] = 0
            save_bot_data(bot_dt)
            await ev.answer("✅ از وایت‌لیست حذف شد!", alert=True)
            buttons = [
                [Button.inline("➕ افزودن به وایت‌لیست", f"quick_wl_{target_uid}".encode())],
                [Button.inline("🔙 منوی اصلی", b"btn_main_menu")]
            ]
            await ev.edit(f"✅ **کاربر `{target_uid}` از وایت‌لیست حذف شد.**", buttons=buttons)
            return

        elif data == "btn_trial":
            trial_cfg = bot_cfg.get("trial", {})
            if not trial_cfg.get("enabled", False):
                await ev.answer("❌ تست رایگان در حال حاضر فعال نیست.", alert=True)
                return
            
            uid_str = str(user_id)
            u_info = bot_dt["users"].get(uid_str, {})
            if u_info.get("trial_used", False):
                await ev.answer("❌ شما قبلاً از مهلت تست رایگان استفاده کرده‌اید.", alert=True)
                return

            dur_hrs = trial_cfg.get("duration_hours", 24)
            add_sec = dur_hrs * 3600
            curr_exp = u_info.get("subscription_expire", 0)
            base_t = max(time.time(), curr_exp)
            new_exp = base_t + add_sec
            
            u_info["subscription_expire"] = new_exp
            u_info["trial_used"] = True
            bot_dt["users"][uid_str] = u_info
            save_bot_data(bot_dt)

            await ev.edit(
                f"🎉 **تست رایگان {dur_hrs} ساعته برای شما با موفقیت فعال شد!**\n\n"
                f"اکنون می‌توانید از گزینه «🔐 ورود / شروع حساب» جهت فعال‌سازی ربات خود استفاده کنید.",
                buttons=[[Button.inline("🔐 ورود به حساب", b"btn_login")], [Button.inline("🔙 منوی اصلی", b"btn_main_menu")]]
            )
            return

        elif data == "btn_logout":
            await ev.answer("در حال توقف و لاگ‌اوت سشن...")
            await stop_user_client(user_id, logout=True)
            await ev.edit(
                "🛑 **سشن کاربری شما با موفقیت غیرفعال و لاگ‌اوت شد.**\n\n"
                "تمامی کانفیگ‌ها و الیاس‌های شما محفوظ است.",
                buttons=[[Button.inline("🔙 منوی اصلی", b"btn_main_menu")]]
            )
            return

        elif data == "btn_buy_sub":
            sub_cfg = bot_cfg.get("subscription", {})
            price = sub_cfg.get("price_toman", 50000)
            days = sub_cfg.get("duration_days", 30)

            msg = (
                f"💳 **خرید اشتراک ربات خودکار MeowAce-Self**\n\n"
                f"💰 **قیمت:** {price:,} تومان\n"
                f"⏱️ **مدت زمان:** {days} روز\n\n"
                f"پس از کلیک بر روی دکمه زیر، درخواست شما برای مدیر ارسال شده و پس از تایید اولیه، شماره کارت جهت واریز خدمتتان ارسال می‌گردد."
            )
            buttons = [
                [Button.inline("📌 درخواست شماره کارت و پرداخت", b"req_payment")],
                [Button.inline("🔙 بازگشت", b"btn_main_menu")]
            ]
            await ev.edit(msg, buttons=buttons)
            return

        elif data == "req_payment":
            pid = f"pay_{user_id}_{int(time.time())}"
            bot_dt["pending_payments"][pid] = {
                "user_id": user_id,
                "status": "awaiting_admin_approval",
                "created_at": time.time()
            }
            save_bot_data(bot_dt)

            await ev.edit(
                "⏳ **درخواست خرید شما برای مدیر ارسال شد.**\nلطفاً شکیبا باشید، به محض تایید مدیر شماره کارت خدمت شما ارسال خواهد شد.",
                buttons=[[Button.inline("🔙 منوی اصلی", b"btn_main_menu")]]
            )
            await notify_admin_payment_request(bot, pid, user_id, bot_cfg, bot_dt)
            return

        elif data.startswith("pay_app1_"):
            pid = data.replace("pay_app1_", "")
            pay_info = bot_dt.get("pending_payments", {}).get(pid)
            if not pay_info:
                await ev.answer("درخواست یافت نشد.", alert=True)
                return

            pay_info["status"] = "awaiting_receipt"
            save_bot_data(bot_dt)
            target_uid = pay_info["user_id"]
            
            card_num = bot_cfg.get("card_number", "6037997000000000")
            sub_cfg = bot_cfg.get("subscription", {})
            price = sub_cfg.get("price_toman", 50000)

            user_login_states[target_uid] = {"step": "AWAITING_RECEIPT", "payment_id": pid}

            try:
                await bot.send_message(
                    target_uid,
                    f"✅ **درخواست خرید شما توسط مدیر تایید شد!**\n\n"
                    f"💳 **شماره کارت جهت واریز:**\n`{card_num}`\n\n"
                    f"💰 **مبلغ:** {price:,} تومان\n\n"
                    f"لطفاً تصویر یا عکس فیش واریزی خود را همین‌جا ارسال کنید."
                )
            except Exception as e:
                print(f"[!] Failed to send card to user {target_uid}: {e}")

            await ev.edit(f"✅ درخواست اولیه کاربر `{target_uid}` تایید و شماره کارت ارسال گردید.")
            return

        elif data.startswith("pay_rej1_"):
            pid = data.replace("pay_rej1_", "")
            pay_info = bot_dt.get("pending_payments", {}).pop(pid, None)
            save_bot_data(bot_dt)
            if pay_info:
                target_uid = pay_info["user_id"]
                try:
                    await bot.send_message(target_uid, "❌ **درخواست خرید اشتراک شما توسط مدیر رد شد.**")
                except Exception:
                    pass
            await ev.edit("❌ درخواست خرید رد شد.")
            return

        elif data.startswith("pay_app2_"):
            pid = data.replace("pay_app2_", "")
            pay_info = bot_dt.get("pending_payments", {}).pop(pid, None)
            if not pay_info:
                await ev.answer("پرداخت یافت نشد یا قبلاً پردازش شده.", alert=True)
                return

            target_uid = pay_info["user_id"]
            uid_str = str(target_uid)

            sub_cfg = bot_cfg.get("subscription", {})
            days = sub_cfg.get("duration_days", 30)
            add_sec = days * 86400

            u_info = bot_dt["users"].get(uid_str, {})
            curr_exp = u_info.get("subscription_expire", 0)
            base_t = max(time.time(), curr_exp)
            new_exp = base_t + add_sec
            
            u_info["subscription_expire"] = new_exp
            bot_dt["users"][uid_str] = u_info
            save_bot_data(bot_dt)

            user_login_states.pop(target_uid, None)

            try:
                await bot.send_message(
                    target_uid,
                    f"🎉 **واریز شما تایید و اشتراک {days} روزه با موفقیت فعال شد!**\n\n"
                    f"اکنون می‌توانید از گزینه «🔐 ورود / شروع حساب» استفاده کنید.",
                    buttons=[[Button.inline("🔐 ورود به حساب", b"btn_login")]]
                )
            except Exception as e:
                print(f"[!] Error notifying user {target_uid} of sub activation: {e}")

            await ev.edit(f"🎉 اشتراک {days} روزه کاربر `{target_uid}` فعال شد.")
            return

        elif data.startswith("pay_rej2_"):
            pid = data.replace("pay_rej2_", "")
            pay_info = bot_dt.get("pending_payments", {}).pop(pid, None)
            save_bot_data(bot_dt)
            if pay_info:
                target_uid = pay_info["user_id"]
                user_login_states.pop(target_uid, None)
                try:
                    await bot.send_message(target_uid, "❌ **فیش واریزی شما توسط مدیر تایید نشد.**")
                except Exception:
                    pass
            await ev.edit("❌ رسید واریزی رد شد.")
            return

        elif data == "btn_login":
            if not can_user_access(user_id, bot_cfg, bot_dt):
                await ev.answer("❌ شما مجاز به فعال‌سازی ربات نیستید. (نیاز به اشتراک یا قرارگیری در وایت‌لیست)", alert=True)
                return

            uid_str = str(user_id)
            u_info = bot_dt["users"].get(uid_str, {})
            saved_api_id = u_info.get("api_id")
            saved_api_hash = u_info.get("api_hash")

            login_buttons = [
                [Button.inline("⚡ ورود سریع (Telegram macOS - بدون نیاز به API)", b"login_preset_macos")],
                [Button.inline("🤖 ورود با API پیش‌فرض سرور", b"login_preset_server")],
                [Button.inline("🔑 ورود با API ID و Hash اختصاصی", b"login_custom_creds")]
            ]
            if saved_api_id and saved_api_hash:
                login_buttons.insert(0, [Button.inline("✅ ورود با اطلاعات API قبلی", b"use_saved_creds")])
            login_buttons.append([Button.inline("🔙 بازگشت به منوی اصلی", b"btn_main_menu")])

            menu_text = (
                "🔐 **انتخاب روش ورود به سلف‌بات:**\n\n"
                "جهت فعال‌سازی ربات روی اکانت خود، یکی از روش‌های زیر را انتخاب کنید:\n\n"
                "• **⚡ ورود سریع (Telegram macOS):** بدون نیاز به ساخت API ID، سریع‌ترین و سازگارترین روش رسمی اپل.\n"
                "• **🤖 ورود با API سرور:** استفاده از API پیش‌فرض تنظیم‌شده روی سرور.\n"
                "• **🔑 ورود اختصاصی:** وارد کردن API ID و API Hash اختصاصی خودتان از my.telegram.org."
            )
            await ev.edit(menu_text, buttons=login_buttons)
            return

        elif data == "login_preset_macos":
            preset = TELEGRAM_PRESETS["macos"]
            user_login_states[user_id] = {
                "step": "ENTER_PHONE",
                "api_id": preset["api_id"],
                "api_hash": preset["api_hash"],
                "device_model": preset["device_model"],
                "system_version": preset["system_version"],
                "app_version": preset["app_version"],
                "lang_code": preset.get("lang_code", "en"),
                "system_lang_code": preset.get("system_lang_code", "en")
            }
            cancel_btn = [[Button.inline("❌ انصراف", b"cancel_login")]]
            await ev.edit(
                "📱 **ورود سریع با Telegram macOS (رسمی اپل)**\n\n"
                "لطفاً **شماره تلفن** حساب تلگرام خود را با کد کشور وارد کنید:\n"
                "(مثال: `+989123456789`)\n\n"
                "💡 نیازی به ساخت یا وارد کردن API ID ندارید.",
                buttons=cancel_btn
            )
            return

        elif data == "login_preset_server":
            s_api_id = bot_cfg.get("bot_api_id")
            s_api_hash = bot_cfg.get("bot_api_hash")
            if not s_api_id or not s_api_hash:
                await ev.answer("❌ API سرور پیکربندی نشده است.", alert=True)
                return
            preset = TELEGRAM_PRESETS["server"]
            user_login_states[user_id] = {
                "step": "ENTER_PHONE",
                "api_id": s_api_id,
                "api_hash": s_api_hash,
                "device_model": preset["device_model"],
                "system_version": preset["system_version"],
                "app_version": preset["app_version"],
                "lang_code": preset.get("lang_code", "en"),
                "system_lang_code": preset.get("system_lang_code", "en")
            }
            cancel_btn = [[Button.inline("❌ انصراف", b"cancel_login")]]
            await ev.edit(
                "📱 **ورود با API سرور**\n\n"
                "لطفاً **شماره تلفن** حساب تلگرام خود را با کد کشور وارد کنید:\n"
                "(مثال: `+989123456789`)",
                buttons=cancel_btn
            )
            return

        elif data == "login_custom_creds":
            user_login_states[user_id] = {"step": "ENTER_API_ID"}
            cancel_btn = [[Button.inline("❌ انصراف", b"cancel_login")]]
            await ev.edit(
                "🔑 **ورود با API ID و Hash اختصاصی**\n\n"
                "لطفاً **API ID** خود را از سایت my.telegram.org دریافت و وارد کنید (مثال: `1234567`):\n\n"
                "(جهت انصراف، دکمه زیر یا دستور `/cancel` را لمس کنید)",
                buttons=cancel_btn
            )
            return

        elif data == "use_saved_creds":
            uid_str = str(user_id)
            u_info = bot_dt["users"].get(uid_str, {})
            api_id = u_info.get("api_id")
            api_hash = u_info.get("api_hash")
            
            user_login_states[user_id] = {
                "step": "ENTER_PHONE",
                "api_id": api_id,
                "api_hash": api_hash,
                "device_model": u_info.get("device_model", "MacBook Pro"),
                "system_version": u_info.get("system_version", "macOS 14.4.1"),
                "app_version": u_info.get("app_version", "10.11"),
                "lang_code": u_info.get("lang_code", "en"),
                "system_lang_code": u_info.get("system_lang_code", "en")
            }
            cancel_btn = [[Button.inline("❌ انصراف", b"cancel_login")]]
            await ev.edit("📱 لطفاً **شماره تلفن** حساب تلگرام خود را با کد کشور وارد کنید (مثال: `+989123456789`):", buttons=cancel_btn)
            return

        elif data == "cancel_login":
            old_st = user_login_states.pop(user_id, None)
            if old_st and old_st.get("temp_client"):
                try: await old_st["temp_client"].disconnect()
                except Exception: pass
            buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
            await ev.edit("❌ فرآیند ورود لغو شد.", buttons=buttons)
            return

        elif data.startswith("numpad_"):
            action = data.replace("numpad_", "")
            state = user_login_states.get(user_id)
            if not state or state.get("step") != "ENTER_OTP":
                await ev.answer("درخواست ورود منقضی شده است.", alert=True)
                return

            current_otp = state.get("entered_otp", "")
            if action == "del":
                current_otp = current_otp[:-1]
            elif action == "submit":
                if len(current_otp) < 4:
                    await ev.answer("لطفاً کد تایید را کامل وارد کنید.", alert=True)
                    return
                await ev.answer("در حال بررسی کد تایید...")
                await process_otp_sign_in(ev, user_id, current_otp, state, main_config, bot)
                return
            elif action in "0123456789":
                if len(current_otp) < 7:
                    current_otp += action

            state["entered_otp"] = current_otp
            masked_code = "  ".join(list(current_otp)) if current_otp else "— — — — —"

            otp_ui_text = (
                f"📩 **کد تایید ارسال شده به تلگرام را وارد کنید:**\n\n"
                f"🔢 **کد وارد شده:** `{masked_code}`\n\n"
                f"🛡️ **روش‌های ورود امن (ضد باطل شدن کد توسط تلگرام):**\n"
                f"۱. **کیبورد شیشه‌ای (کاملاً ایمن):** ارقام کد را با دکمه‌های زیر لمس کرده و «✅ تایید و ورود» را بزنید.\n"
                f"۲. **ارسال با اعداد فارسی:** ارسال در چت با اعداد فارسی (مثال: `۱۲۳۴۵`)\n"
                f"۳. **ارسال با فاصله:** بین ارقام فاصله بگذارید (مثال: `1 2 3 4 5` یا `1-2-3-4-5`)\n\n"
                f"⚠️ **مهم:** از کپی و پیست مستقیم کد انگلیسی بدون فاصله خودداری کنید."
            )
            try:
                await ev.edit(otp_ui_text, buttons=get_otp_numpad_buttons(current_otp))
            except Exception:
                pass
            return

        # ADMIN PANEL BUTTONS
        elif data == "btn_admin_panel":
            if not is_admin(user_id, bot_cfg):
                await ev.answer("❌ دسترسی غیرمجاز.", alert=True)
                return
            buttons = get_admin_panel_buttons(bot_cfg)
            await ev.edit("⚙️ **پنل مدیریت ادمین:**", buttons=buttons)
            return

        elif data == "toggle_mode":
            if not is_admin(user_id, bot_cfg): return
            curr = bot_cfg.get("mode", "private")
            bot_cfg["mode"] = "public" if curr == "private" else "private"
            save_bot_config(bot_cfg)
            await ev.edit("⚙️ **پنل مدیریت ادمین:**", buttons=get_admin_panel_buttons(bot_cfg))
            return

        elif data == "toggle_pub_type":
            if not is_admin(user_id, bot_cfg): return
            curr = bot_cfg.get("public_type", "free")
            bot_cfg["public_type"] = "paid" if curr == "free" else "free"
            save_bot_config(bot_cfg)
            await ev.edit("⚙️ **پنل مدیریت ادمین:**", buttons=get_admin_panel_buttons(bot_cfg))
            return

        elif data == "toggle_trial":
            if not is_admin(user_id, bot_cfg): return
            if "trial" not in bot_cfg: bot_cfg["trial"] = {}
            curr = bot_cfg["trial"].get("enabled", False)
            bot_cfg["trial"]["enabled"] = not curr
            save_bot_config(bot_cfg)
            await ev.edit("⚙️ **پنل مدیریت ادمین:**", buttons=get_admin_panel_buttons(bot_cfg))
            return

        elif data in ["set_price", "set_days", "set_trial_hrs", "set_card", "admin_add_wl", "admin_rem_wl", "admin_add_sub", "admin_stop_user"]:
            if not is_admin(user_id, bot_cfg): return
            user_admin_states[user_id] = data
            prompts = {
                "set_price": "💰 قیمت جدید اشتراک را به تومان وارد کنید (مثال: `50000`):",
                "set_days": "⏱️ مدت زمان جدید اشتراک را به روز وارد کنید (مثال: `30`):",
                "set_trial_hrs": "⏳ مدت زمان جدید تست رایگان را به ساعت وارد کنید (مثال: `24`):",
                "set_card": "💳 شماره کارت جدید را وارد کنید:",
                "admin_add_wl": "➕ آیدی عددی (User ID) کاربر را جهت افزودن به وایت‌لیست وارد کنید:",
                "admin_rem_wl": "➖ آیدی عددی کاربر را جهت حذف از وایت‌لیست وارد کنید:",
                "admin_add_sub": "➕ آیدی کاربر و تعداد روز را با فاصله وارد کنید (مثال: `123456789 30`):",
                "admin_stop_user": "🛑 آیدی عددی کاربر را جهت متوقف کردن سشن وارد کنید:"
            }
            await ev.edit(prompts[data], buttons=[[Button.inline("🔙 لغو", b"btn_admin_panel")]])
            return

        elif data == "admin_stats":
            if not is_admin(user_id, bot_cfg): return
            users = bot_dt.get("users", {})
            total_users = len(users)
            online_users = len(active_user_clients)
            wl_count = len(bot_dt.get("whitelist", []))
            pending_pays = len(bot_dt.get("pending_payments", {}))
            stats_text = (
                f"📊 **آمار کلی ربات مدیریت:**\n\n"
                f"👥 کل کاربران ثبت شده: `{total_users}`\n"
                f"⚡ سشن‌های آنلاین و فعال: `{online_users}`\n"
                f"📋 کاربران وایت‌لیست: `{wl_count}`\n"
                f"💳 تراکنش‌های در انتظار تایید: `{pending_pays}`\n\n"
                f"⚙️ **وضعیت سیستم:**\n"
                f"• مود ربات: `{bot_cfg.get('mode', 'private')}`\n"
                f"• مود دسترسی: `{bot_cfg.get('public_type', 'free')}`\n"
                f"• تست رایگان: `{'روشن' if bot_cfg.get('trial', {}).get('enabled') else 'خاموش'}`"
            )
            await ev.edit(stats_text, buttons=[[Button.inline("🔙 بازگشت", b"btn_admin_panel")]])
            return

        elif data == "admin_broadcast":
            if not is_admin(user_id, bot_cfg): return
            user_admin_states[user_id] = "admin_broadcast"
            await ev.edit(
                "📢 **ارسال پیام همگانی:**\n\n"
                "لطفاً متن پیامی که می‌خواهید برای تمام کاربران ارسال شود را وارد کنید:\n"
                "(جهت لغو، دستور `/cancel` را بفرستید)",
                buttons=[[Button.inline("🔙 لغو", b"btn_admin_panel")]]
            )
            return

        elif data == "admin_list_users":
            if not is_admin(user_id, bot_cfg): return
            users = bot_dt.get("users", {})
            out = "👥 **لیست کاربران و سشن‌ها:**\n\n"
            for uid, uinfo in users.items():
                running = int(uid) in active_user_clients
                st = "🟢 آنلاین" if running else "🔴 آفلاین"
                exp = uinfo.get("subscription_expire", 0)
                exp_str = "دائم" if exp == -1 else (f"تا {time.strftime('%Y-%m-%d %H:%M', time.localtime(exp))}" if exp > time.time() else "منقضی")
                out += f"• `{uid}` ({uinfo.get('first_name', '')}) ── {st} | اشتراک: {exp_str}\n"
            await ev.edit(out[:4000], buttons=[[Button.inline("🔙 بازگشت", b"btn_admin_panel")]])
            return

        elif data == "admin_list_wl":
            if not is_admin(user_id, bot_cfg): return
            wl = bot_dt.get("whitelist", [])
            out = "📋 **لیست وایت‌لیست:**\n\n" + "\n".join([f"• `{x}`" for x in wl])
            await ev.edit(out, buttons=[[Button.inline("🔙 بازگشت", b"btn_admin_panel")]])
            return

    @bot.on(events.NewMessage)
    async def _message_handler(ev):
        if ev.text and ev.text.startswith('/'):
            return

        user_id = ev.sender_id
        text = ev.text.strip() if ev.text else ""
        bot_cfg = load_bot_config()
        bot_dt = load_bot_data()

        # Handle Info Query State or Direct Forward to Bot
        is_info_query = user_admin_states.get(user_id) == "awaiting_info_query"
        is_forward = bool(getattr(ev, 'forward', None) or getattr(ev, 'fwd_from', None))
        if is_info_query or (is_forward and ev.is_private):
            user_admin_states.pop(user_id, None)
            target_arg = text if not is_forward else None
            info_txt, ent, fwd_ent = await get_info_text_and_entity(bot, ev, target_arg)
            
            buttons = []
            target_uid = getattr(ent, 'id', None) or getattr(fwd_ent, 'id', None)
            if target_uid and is_admin(user_id, bot_cfg):
                wl = bot_dt.get("whitelist", [])
                if target_uid not in wl:
                    buttons.append([Button.inline("➕ افزودن به وایت‌لیست (دسترسی دائم)", f"quick_wl_{target_uid}".encode())])
                else:
                    buttons.append([Button.inline("➖ حذف از وایت‌لیست", f"quick_unwl_{target_uid}".encode())])
            buttons.append([Button.inline("🔙 منوی اصلی", b"btn_main_menu")])
            await ev.respond(info_txt, buttons=buttons)
            return

        # Handle Admin Input Prompt States
        if user_id in user_admin_states:
            action = user_admin_states.pop(user_id)
            if action == "set_price":
                try:
                    bot_cfg["subscription"]["price_toman"] = int(text)
                    save_bot_config(bot_cfg)
                    await ev.respond("✅ قیمت جدید اشتراک با موفقیت ثبت شد.")
                except Exception:
                    await ev.respond("❌ قیمت وارد شده معتبر نیست.")
            elif action == "set_days":
                try:
                    bot_cfg["subscription"]["duration_days"] = int(text)
                    save_bot_config(bot_cfg)
                    await ev.respond("✅ مدت زمان جدید اشتراک با موفقیت ثبت شد.")
                except Exception:
                    await ev.respond("❌ عدد وارد شده معتبر نیست.")
            elif action == "set_trial_hrs":
                try:
                    bot_cfg["trial"]["duration_hours"] = int(text)
                    save_bot_config(bot_cfg)
                    await ev.respond("✅ مدت زمان جدید تست رایگان با موفقیت ثبت شد.")
                except Exception:
                    await ev.respond("❌ عدد وارد شده معتبر نیست.")
            elif action == "set_card":
                bot_cfg["card_number"] = text
                save_bot_config(bot_cfg)
                await ev.respond("✅ شماره کارت جدید با موفقیت ثبت شد.")
            elif action == "admin_add_wl":
                try:
                    target_uid = int(text)
                    if target_uid not in bot_dt["whitelist"]:
                        bot_dt["whitelist"].append(target_uid)
                    uid_str = str(target_uid)
                    bot_dt["users"].setdefault(uid_str, {})
                    bot_dt["users"][uid_str]["subscription_expire"] = -1
                    save_bot_data(bot_dt)
                    await ev.respond(f"✅ کاربر `{target_uid}` با موفقیت به وایت‌لیست اضافه شد (دسترسی دائم فعال شد).")
                except Exception:
                    await ev.respond("❌ آیدی وارد شده معتبر نیست.")
            elif action == "admin_rem_wl":
                try:
                    target_uid = int(text)
                    if target_uid in bot_dt["whitelist"]:
                        bot_dt["whitelist"].remove(target_uid)
                    uid_str = str(target_uid)
                    if uid_str in bot_dt["users"] and bot_dt["users"][uid_str].get("subscription_expire") == -1:
                        bot_dt["users"][uid_str]["subscription_expire"] = 0
                    save_bot_data(bot_dt)
                    await ev.respond(f"✅ کاربر `{target_uid}` از وایت‌لیست حذف شد.")
                except Exception:
                    await ev.respond("❌ آیدی وارد شده معتبر نیست.")
            elif action == "admin_add_sub":
                try:
                    parts = text.split()
                    target_uid = int(parts[0])
                    days = int(parts[1])
                    uid_str = str(target_uid)
                    u_info = bot_dt["users"].get(uid_str, {})
                    curr_exp = u_info.get("subscription_expire", 0)
                    base_t = max(time.time(), curr_exp)
                    u_info["subscription_expire"] = base_t + days * 86400
                    bot_dt["users"][uid_str] = u_info
                    save_bot_data(bot_dt)
                    await ev.respond(f"✅ {days} روز اشتراک با موفقیت برای کاربر `{target_uid}` فعال شد.")
                except Exception:
                    await ev.respond("❌ فرمت وارد شده اشتباه است. مثال: `123456789 30`")
            elif action == "admin_stop_user":
                try:
                    target_uid = int(text)
                    await stop_user_client(target_uid, logout=True)
                    await ev.respond(f"🛑 سشن کاربر `{target_uid}` متوقف و لاگ‌اوت شد.")
                except Exception as e:
                    await ev.respond(f"❌ خطا در متوقف سازی سشن: {e}")
            elif action == "admin_broadcast":
                users = bot_dt.get("users", {})
                sent_count = 0
                failed_count = 0
                progress_msg = await ev.respond("⏳ در حال ارسال پیام همگانی به تمامی کاربران...")
                for target_uid_str in list(users.keys()):
                    try:
                        t_uid = int(target_uid_str)
                        await bot.send_message(t_uid, f"📢 **اطلاعیه مدیریت:**\n\n{text}")
                        sent_count += 1
                        await asyncio.sleep(0.05)
                    except Exception:
                        failed_count += 1
                await progress_msg.edit(f"✅ پیام همگانی با موفقیت ارسال شد.\n\n📤 موفق: `{sent_count}`\n❌ ناموفق: `{failed_count}`")
            return

        # Handle Receipt Submission
        if user_id in user_login_states and user_login_states[user_id].get("step") == "AWAITING_RECEIPT":
            state = user_login_states[user_id]
            pid = state.get("payment_id")
            await ev.respond("✅ **فیش واریزی شما دریافت شد.** لطفا منتظر بررسی و تایید ادمین باشید.")
            await notify_admin_receipt(bot, pid, user_id, ev, bot_cfg, bot_dt)
            return

        # Handle Login States
        if user_id in user_login_states:
            state = user_login_states[user_id]
            step = state.get("step")
            cancel_btn = [[Button.inline("❌ انصراف", b"cancel_login")]]

            if step == "ENTER_API_ID":
                try:
                    api_id = int(text)
                    state["api_id"] = api_id
                    state["step"] = "ENTER_API_HASH"
                    await ev.respond("🔑 عالی! حالا **API Hash** حساب تلگرام خود را وارد کنید:", buttons=cancel_btn)
                except ValueError:
                    await ev.respond("❌ API ID باید فقط عدد باشد. لطفاً مجدداً وارد کنید:", buttons=cancel_btn)

            elif step == "ENTER_API_HASH":
                state["api_hash"] = text
                state["step"] = "ENTER_PHONE"
                await ev.respond("📱 لطفاً **شماره تلفن** حساب تلگرام خود را با کد کشور وارد کنید (مثال: `+989123456789`):", buttons=cancel_btn)

            elif step == "ENTER_PHONE":
                now = time.time()
                last_req = last_code_request_time.get(user_id, 0)
                if now - last_req < 30:
                    wait_s = int(30 - (now - last_req))
                    await ev.respond(f"⏳ لطفاً {wait_s} ثانیه دیگر جهت درخواست مجدد کد شکیبا باشید.", buttons=cancel_btn)
                    return
                last_code_request_time[user_id] = now

                phone = text.replace(" ", "")
                state["phone"] = phone
                api_id = state["api_id"]
                api_hash = state["api_hash"]
                device_model = state.get("device_model", "MacBook Pro")
                system_version = state.get("system_version", "macOS 14.4.1")
                app_version = state.get("app_version", "10.11")
                lang_code = state.get("lang_code", "en")
                system_lang_code = state.get("system_lang_code", "en")

                await ev.respond("⚡ در حال اتصال به سرور تلگرام و ارسال کد تایید...")
                sess_file = get_session_filepath(user_id)
                if os.path.exists(sess_file):
                    try: os.remove(sess_file)
                    except Exception: pass

                proxy_kw = get_proxy_kwargs(main_config)
                temp_client = TelegramClient(
                    f"sessions/session_{user_id}",
                    api_id,
                    api_hash,
                    device_model=device_model,
                    system_version=system_version,
                    app_version=app_version,
                    lang_code=lang_code,
                    system_lang_code=system_lang_code,
                    **proxy_kw
                )
                try:
                    await temp_client.connect()
                    res = await temp_client.send_code_request(phone)
                    state["temp_client"] = temp_client
                    state["phone_code_hash"] = res.phone_code_hash
                    state["step"] = "ENTER_OTP"
                    state["entered_otp"] = ""
                    
                    otp_msg_text = (
                        "📩 **کد تایید ورود به تلگرام شما ارسال شد!**\n\n"
                        "🔢 **کد وارد شده:** `— — — — —`\n\n"
                        "🛡️ **روش‌های ورود امن (ضد باطل شدن کد توسط تلگرام):**\n"
                        "۱. **کیبورد شیشه‌ای (پیشنهادی و کاملاً ایمن):** ارقام کد را با دکمه‌های زیر لمس کرده و دکمه «✅ تایید و ورود» را بزنید.\n"
                        "۲. **ارسال با اعداد فارسی:** کد را با اعداد فارسی بفرستید (مثال: `۱۲۳۴۵`)\n"
                        "۳. **ارسال با فاصله یا خط‌تیره:** بین هر رقم فاصله بگذارید (مثال: `1 2 3 4 5` یا `1-2-3-4-5`)\n\n"
                        "⚠️ **هشدار:** هرگز کد را به صورت انگلیسی پیوسته کپی‌پیست نکنید، در غیر این صورت تلگرام کد را فاش شده دانسته و سریعاً باطل می‌کند!\n"
                        "🔒 پیام‌های شما بلافاصله پس از دریافت جهت حفظ امنیت حذف خواهند شد."
                    )
                    await ev.respond(otp_msg_text, buttons=get_otp_numpad_buttons(""))
                except PhoneNumberInvalidError:
                    await temp_client.disconnect()
                    await ev.respond("❌ شماره تلفن وارد شده معتبر نیست. لطفاً مجدداً شماره تلفن را وارد کنید:", buttons=cancel_btn)
                except Exception as e:
                    try: await temp_client.disconnect()
                    except Exception: pass
                    await ev.respond(f"❌ خطا در ارسال کد تایید: {e}\nلطفاً مجدداً تلاش کنید.")
                    user_login_states.pop(user_id, None)

            elif step == "ENTER_OTP":
                try:
                    await ev.delete()
                except Exception:
                    pass

                raw_txt = convert_persian_digits(text or "")
                otp_code = "".join(re.findall(r'\d', raw_txt))
                if not otp_code or len(otp_code) < 4:
                    await ev.respond("❌ کد تایید معتبر نیست. لطفاً از کیبورد شیشه‌ای استفاده کنید یا ارقام را با فاصله/اعداد فارسی ارسال نمایید:", buttons=get_otp_numpad_buttons(""))
                    return

                await process_otp_sign_in(ev, user_id, otp_code, state, main_config, bot)

            elif step == "ENTER_2FA":
                try:
                    await ev.delete()
                except Exception:
                    pass

                password = text
                temp_client = state.get("temp_client")
                phone = state.get("phone", "")
                api_id = state["api_id"]
                api_hash = state["api_hash"]
                device_model = state.get("device_model", "MacBook Pro")
                system_version = state.get("system_version", "macOS 14.4.1")
                app_version = state.get("app_version", "10.11")
                lang_code = state.get("lang_code", "en")
                system_lang_code = state.get("system_lang_code", "en")

                try:
                    await temp_client.sign_in(password=password)
                    me = await temp_client.get_me()
                    await temp_client.disconnect()

                    uid_str = str(user_id)
                    bot_dt["users"].setdefault(uid_str, {})
                    bot_dt["users"][uid_str]["api_id"] = api_id
                    bot_dt["users"][uid_str]["api_hash"] = api_hash
                    bot_dt["users"][uid_str]["phone"] = phone
                    bot_dt["users"][uid_str]["first_name"] = getattr(me, 'first_name', '') or ''
                    bot_dt["users"][uid_str]["username"] = getattr(me, 'username', '') or ''
                    if device_model: bot_dt["users"][uid_str]["device_model"] = device_model
                    if system_version: bot_dt["users"][uid_str]["system_version"] = system_version
                    if app_version: bot_dt["users"][uid_str]["app_version"] = app_version
                    if lang_code: bot_dt["users"][uid_str]["lang_code"] = lang_code
                    if system_lang_code: bot_dt["users"][uid_str]["system_lang_code"] = system_lang_code
                    save_bot_data(bot_dt)

                    proxy_kw = get_proxy_kwargs(main_config)
                    success, msg = await start_user_client(
                        user_id, api_id, api_hash, proxy_kw,
                        device_model=device_model,
                        system_version=system_version,
                        app_version=app_version,
                        lang_code=lang_code,
                        system_lang_code=system_lang_code
                    )
                    user_login_states.pop(user_id, None)
                    buttons = get_main_menu_buttons(user_id, bot_cfg, bot_dt)
                    if success:
                        await ev.respond(f"🎉 **ورود با موفقیت انجام شد!**\n{msg}", buttons=buttons)
                        admin_id = bot_cfg.get("admin_id")
                        if admin_id and str(admin_id) != str(user_id):
                            try:
                                uname = f"@{me.username}" if getattr(me, 'username', None) else "بدون یوزرنیم"
                                await bot.send_message(
                                    admin_id,
                                    f"🔔 **ورود سشن جدید کاربر (با 2FA):**\n\n"
                                    f"👤 کاربر: {me.first_name} ({uname})\n"
                                    f"🆔 آیدی: `{user_id}`\n"
                                    f"📱 شماره: `{phone}`\n"
                                    f"⚡ زمان: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                            except Exception:
                                pass
                    else:
                        await ev.respond(f"❌ خطا در فعال‌سازی سشن: {msg}", buttons=buttons)

                except PasswordHashInvalidError:
                    await ev.respond("❌ رمز عبور دو مرحله‌ای اشتباه است. لطفاً مجدداً وارد کنید:", buttons=cancel_btn)
                except Exception as e:
                    try: await temp_client.disconnect()
                    except Exception: pass
                    await ev.respond(f"❌ خطا در ورود: {e}")
                    user_login_states.pop(user_id, None)

    # Start background auto-resumption and subscription monitor
    asyncio.create_task(resume_all_sessions(main_config))
    async def _notify_user(uid: int, msg: str):
        try:
            await bot.send_message(uid, msg)
        except Exception as e:
            print(f"[!] Notification error to {uid}: {e}")
    asyncio.create_task(subscription_monitor_loop(_notify_user))

    print("[+] MultiSession Management Bot is fully running and ready. Waiting for events...")
    await bot.run_until_disconnected()
