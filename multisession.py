"""
multisession.py - Multi-User Session & Lifetime Management for MeowAce-Self
Author: MahdiAce02
"""

import sys
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Tuple, Optional, Callable
from telethon import TelegramClient, events
from telethon.errors import RPCError

from modules.autocatch import autocatch_command, handle_autocatch_trigger
from modules.autobat import autobat_command, handle_autobat_trigger, handle_manual_bat
from modules.automeow import automeow_command, resume_automeow_tasks, process_schedule_event
from modules.autofish import autofish_command, resume_autofish_tasks
from modules.autofridge import autofridge_command, resume_autofridge_tasks
from modules.show import show_command
from modules.sched import sched_command
from modules.alias import alias_command, resolve_alias
from modules.proxy import get_proxy_kwargs

# File paths and directory definitions
BOT_CONFIG_FILE = Path("bot_config.json")
EXAMPLE_BOT_CONFIG_FILE = Path("bot_config.example.json")
BOT_DATA_FILE = Path("bot_data.json")
SESSIONS_DIR = Path("sessions")
SETTINGS_DIR = Path("settings")

# Global dict tracking currently active Telethon client instances for each user
active_user_clients: Dict[int, TelegramClient] = {}


def ensure_environment_directories() -> None:
    """Make sure required runtime folders exist on disk before file IO."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def load_bot_config() -> dict:
    """
    Load bot configuration from bot_config.json.
    If file doesn't exist, create it from bot_config.example.json template.
    """
    ensure_environment_directories()

    if not BOT_CONFIG_FILE.exists():
        if EXAMPLE_BOT_CONFIG_FILE.exists():
            # Copy template to active bot_config.json
            template_text = EXAMPLE_BOT_CONFIG_FILE.read_text(encoding="utf-8")
            BOT_CONFIG_FILE.write_text(template_text, encoding="utf-8")
            print(f"[!] Created '{BOT_CONFIG_FILE}' from template. Please configure bot_token and admin credentials.")
        else:
            print(f"[!] Critical Error: Template file '{EXAMPLE_BOT_CONFIG_FILE}' is missing!")
            sys.exit(1)

    try:
        with open(BOT_CONFIG_FILE, "r", encoding="utf-8") as file_stream:
            return json.load(file_stream)
    except json.JSONDecodeError as decode_err:
        print(f"[!] Invalid JSON format in '{BOT_CONFIG_FILE}': {decode_err}")
        sys.exit(1)
    except Exception as err:
        print(f"[!] Unexpected error reading '{BOT_CONFIG_FILE}': {err}")
        sys.exit(1)


def save_bot_config(config_data: dict) -> None:
    """Save updated bot configuration back to disk cleanly."""
    ensure_environment_directories()
    try:
        with open(BOT_CONFIG_FILE, "w", encoding="utf-8") as file_stream:
            json.dump(config_data, file_stream, ensure_ascii=False, indent=2)
    except Exception as write_err:
        print(f"[!] Failed to write '{BOT_CONFIG_FILE}': {write_err}")


def load_bot_data() -> dict:
    """Load persistent multi-user database (users, whitelist, payments)."""
    ensure_environment_directories()

    default_schema = {
        "users": {},
        "whitelist": [],
        "pending_payments": {}
    }

    if BOT_DATA_FILE.exists():
        try:
            with open(BOT_DATA_FILE, "r", encoding="utf-8") as file_stream:
                stored_data = json.load(file_stream)
                # Ensure all top-level keys exist even if file was partially edited
                for key, default_value in default_schema.items():
                    if key not in stored_data:
                        stored_data[key] = default_value
                return stored_data
        except Exception as read_err:
            print(f"[!] Warning: Could not parse '{BOT_DATA_FILE}': {read_err}")

    return default_schema


def save_bot_data(data_payload: dict) -> None:
    """Safely persist multi-user database to disk."""
    ensure_environment_directories()
    try:
        with open(BOT_DATA_FILE, "w", encoding="utf-8") as file_stream:
            json.dump(data_payload, file_stream, ensure_ascii=False, indent=2)
    except Exception as save_err:
        print(f"[!] Failed saving '{BOT_DATA_FILE}': {save_err}")


def is_admin(user_id: int, bot_config: dict) -> bool:
    """Check whether a user_id matches the configured primary admin ID."""
    primary_admin_id = bot_config.get("admin_id", 0)
    return str(user_id) == str(primary_admin_id) or user_id == primary_admin_id


def can_user_access(user_id: int, bot_config: dict, bot_data: dict) -> bool:
    """
    Evaluate user permission to run selfbot session based on bot mode,
    whitelist status, and subscription/trial expiration time.
    """
    # Primary admin always has unrestricted access
    if is_admin(user_id, bot_config):
        return True

    user_key = str(user_id)
    user_data = bot_data.get("users", {}).get(user_key, {})
    expiration_timestamp = user_data.get("subscription_expire", 0)

    current_mode = bot_config.get("mode", "private")

    if current_mode == "private":
        # In private mode, user must be in whitelist
        whitelisted_ids = [str(item) for item in bot_data.get("whitelist", [])]
        if user_key not in whitelisted_ids:
            return False
        # Whitelisted users get access if subscription active or set to permanent (-1)
        return expiration_timestamp > time.time() or expiration_timestamp == -1

    elif current_mode == "public":
        public_sub_type = bot_config.get("public_type", "free")
        if public_sub_type == "free":
            return True
        elif public_sub_type == "paid":
            return expiration_timestamp > time.time()

    return False


def attach_selfbot_handlers(client: TelegramClient, user_id: int) -> None:
    """
    Attach all event listeners (automeow, autocatch, autofish, autofridge, show, sched, alias)
    to an isolated Telethon client instance for a given user.
    """
    client.uid = user_id

    # Handle incoming server-side schedule events for automeow
    @client.on(events.NewMessage)
    async def _automeow_schedule_listener(event):
        await process_schedule_event(event)

    # Autocatch trigger event handlers (new messages and edited messages)
    @client.on(events.NewMessage)
    async def _autocatch_trigger_new(event):
        await handle_autocatch_trigger(event, is_edit=False)

    @client.on(events.MessageEdited)
    async def _autocatch_trigger_edit(event):
        await handle_autocatch_trigger(event, is_edit=True)

    # Autobat trigger event handlers
    @client.on(events.NewMessage)
    async def _autobat_trigger_new(event):
        await handle_autobat_trigger(event)

    # Command pattern event handlers
    @client.on(events.NewMessage(pattern='(?i)^/?automeow($|\\s+)'))
    async def _automeow_handler(event):
        await automeow_command(event)

    @client.on(events.NewMessage(pattern='(?i)^/?autofish($|\\s+)'))
    async def _autofish_handler(event):
        await autofish_command(event)

    @client.on(events.NewMessage(pattern='(?i)^/?autofridge($|\\s+)'))
    async def _autofridge_handler(event):
        await autofridge_command(event)

    @client.on(events.NewMessage(pattern='(?i)^/?autocatch($|\\s+)'))
    async def _autocatch_handler(event):
        await autocatch_command(event)

    @client.on(events.NewMessage(pattern='(?i)^/?autobat($|\\s+)'))
    async def _autobat_handler(event):
        await autobat_command(event)

    @client.on(events.NewMessage(outgoing=True))
    async def _manual_bat_handler(event):
        try:
            await handle_manual_bat(event)
        except Exception as bat_err:
            print(f"[!] Manual bat error (user {user_id}): {bat_err}")

    @client.on(events.NewMessage(pattern='(?i)^/?show(?:\\s+(.+))?'))
    async def _show_handler(event):
        await show_command(event)

    @client.on(events.NewMessage(pattern='(?i)^/?sched(?:\\s+(.+))?'))
    async def _sched_handler(event):
        await sched_command(event)

    @client.on(events.NewMessage(pattern=r'(?i)^[/.=]?alias(?:\s+(.+))?$'))
    async def _alias_handler(event):
        await alias_command(event)

    @client.on(events.NewMessage(pattern='(?i)^/?(status|meowhelp|help)($|\\s+)'))
    async def _status_handler(event):
        from main import status_command
        await status_command(event)

    # Intercept outgoing custom aliases
    @client.on(events.NewMessage(outgoing=True))
    async def _alias_interceptor(event):
        message_text = event.raw_text or ""
        if not message_text:
            return

        # Skip if message was consumed as manual batt reply
        if message_text.strip().lower().lstrip("/.=!") == "batt" and getattr(event, 'is_reply', False):
            return

        matched_alias, target_commands = resolve_alias(client.uid, message_text)
        if matched_alias and target_commands:
            for cmd_str in target_commands:
                try:
                    await client.send_message(event.chat_id, cmd_str)
                except RPCError as rpc_err:
                    print(f"[!] Alias send RPC error (user {user_id}): {rpc_err}")
                except Exception as send_err:
                    print(f"[!] Alias send exception (user {user_id}): {send_err}")


def get_session_filepath(user_id: int) -> str:
    """Return the absolute path string of the session file for user_id."""
    ensure_environment_directories()
    return str(SESSIONS_DIR / f"session_{user_id}.session")


async def start_user_client(
    user_id: int,
    api_id: int,
    api_hash: str,
    proxy_kwargs: Optional[dict] = None
) -> Tuple[bool, str]:
    """
    Connect and start a dedicated Telethon client for user_id.
    If authorized, registers handlers and background loops.
    """
    # Check if client is already connected and active
    if user_id in active_user_clients:
        existing_client = active_user_clients[user_id]
        if existing_client.is_connected():
            return True, "ربات شما هم‌اکنون آنلاین و در حال اجرا است."

    ensure_environment_directories()
    session_file_prefix = str(SESSIONS_DIR / f"session_{user_id}")
    proxy_options = proxy_kwargs or {}

    user_client = TelegramClient(session_file_prefix, api_id, api_hash, **proxy_options)

    try:
        await user_client.connect()

        if not await user_client.is_user_authorized():
            await user_client.disconnect()
            return False, "سشن شما معتبر نیست یا لاگ‌اوت شده است. لطفاً مجدداً لاگین کنید."

        account_info = await user_client.get_me()
        actual_user_id = account_info.id

        # Attach event handlers to client instance
        attach_selfbot_handlers(user_client, actual_user_id)

        # Resume background module tasks (automeow, autofish, autofridge loops)
        asyncio.create_task(resume_automeow_tasks(user_client))
        asyncio.create_task(resume_autofish_tasks(user_client))
        asyncio.create_task(resume_autofridge_tasks(user_client))

        # Store in active client registry
        active_user_clients[actual_user_id] = user_client

        full_name = account_info.first_name or "User"
        handle_name = f"@{account_info.username}" if account_info.username else "N/A"
        print(f"[+] MultiSession: Successfully started selfbot for {full_name} [{handle_name} - ID: {actual_user_id}]")

        return True, f"سشن با موفقیت آنلاین شد: {full_name} ({handle_name})"

    except Exception as connect_err:
        try:
            await user_client.disconnect()
        except Exception:
            pass
        return False, f"خطا در اتصال سشن: {connect_err}"


async def stop_user_client(user_id: int, logout: bool = False) -> bool:
    """
    Gracefully disconnect and unregister user client.
    If logout is True, logs out of Telegram session and deletes session file.
    Does NOT delete user's saved API credentials or module settings.
    """
    target_client = active_user_clients.pop(user_id, None)

    if target_client:
        try:
            if logout and target_client.is_connected():
                try:
                    await target_client.log_out()
                except Exception as logout_err:
                    print(f"[!] Non-fatal error logging out client {user_id}: {logout_err}")
            await target_client.disconnect()
        except Exception as stop_err:
            print(f"[!] Error stopping client for user {user_id}: {stop_err}")

    if logout:
        session_path = Path(get_session_filepath(user_id))
        if session_path.exists():
            try:
                session_path.unlink()
                print(f"[-] Deleted session file for user {user_id}")
            except Exception as remove_err:
                print(f"[!] Could not remove session file for user {user_id}: {remove_err}")

    return True


async def resume_all_sessions(main_config: dict) -> None:
    """
    Startup routine: scan database and resume all valid active user sessions.
    Runs on multi-session bot initialization.
    """
    proxy_options = get_proxy_kwargs(main_config)
    current_bot_config = load_bot_config()
    current_bot_data = load_bot_data()

    registered_users = current_bot_data.get("users", {})
    successful_resumes = 0

    for user_id_str, user_record in registered_users.items():
        try:
            target_user_id = int(user_id_str)
            api_id = user_record.get("api_id")
            api_hash = user_record.get("api_hash")

            if not api_id or not api_hash:
                continue

            session_file = Path(get_session_filepath(target_user_id))
            if not session_file.exists():
                continue

            if can_user_access(target_user_id, current_bot_config, current_bot_data):
                is_ok, message = await start_user_client(target_user_id, api_id, api_hash, proxy_options)
                if is_ok:
                    successful_resumes += 1
                else:
                    print(f"[!] Resume failed for user {target_user_id}: {message}")
            else:
                print(f"[-] Access expired for user {target_user_id}. Cleaning session...")
                await stop_user_client(target_user_id, logout=True)

        except ValueError:
            continue
        except Exception as resume_err:
            print(f"[!] Exception during session resume for {user_id_str}: {resume_err}")

    print(f"[+] MultiSession: Resumed {successful_resumes} active selfbot session(s).")


async def subscription_monitor_loop(notify_callback: Optional[Callable] = None) -> None:
    """
    Background worker task running every 60 seconds to check active subscriptions.
    Automatically disconnects and cleans up sessions whose subscription/trial has expired.
    """
    while True:
        try:
            await asyncio.sleep(60)

            latest_bot_config = load_bot_config()
            latest_bot_data = load_bot_data()

            active_user_ids = list(active_user_clients.keys())

            for current_user_id in active_user_ids:
                if not can_user_access(current_user_id, latest_bot_config, latest_bot_data):
                    print(f"[!] Access expired for user {current_user_id}. Terminating session...")
                    await stop_user_client(current_user_id, logout=True)

                    if notify_callback:
                        try:
                            notification_msg = (
                                "⚠️ **اشتراک/تست شما به پایان رسید!**\n\n"
                                "سشن حساب کاربری شما متوقف و لاگ‌اوت شد. تمامی تنظیمات و میانبرهای شما محفوظ است "
                                "و پس از تمدید اشتراک یا ورود مجدد در دسترس خواهند بود."
                            )
                            await notify_callback(current_user_id, notification_msg)
                        except Exception as notify_err:
                            print(f"[!] Could not send expiration alert to user {current_user_id}: {notify_err}")

        except asyncio.CancelledError:
            print("[i] Subscription monitor task cancelled.")
            break
        except Exception as loop_err:
            print(f"[!] Error inside subscription monitor loop: {loop_err}")
