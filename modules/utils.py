import os
import json
import time
import random
import asyncio
from telethon.errors import SlowModeWaitError, RPCError

# global state tracking for rate limiting & locks
_locks = {}
_last_sent = {}

def convert_persian_digits(txt: str) -> str:
    # convert fa/ar numbers to en for math and regex parsing
    if not txt:
        return ""
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    en = "0123456789"
    for i in range(10):
        txt = txt.replace(fa[i], en[i]).replace(ar[i], en[i])
    return txt

def get_chat_lock(u_id: int, c_id: int) -> asyncio.Lock:
    # lock per user and chat to avoid concurrent message collisions
    k = (u_id, c_id)
    if k not in _locks:
        _locks[k] = asyncio.Lock()
    return _locks[k]

def _check_dir():
    if not os.path.exists("settings"):
        try:
            os.makedirs("settings", exist_ok=True)
            if hasattr(os, 'chmod'):
                try: os.chmod("settings", 0o700)
                except Exception: pass
        except Exception as err:
            print(f"[!] cant create settings dir: {err}")

def load_json_setting(fn: str, default=None):
    _check_dir()
    fp = os.path.join("settings", fn)
    if os.path.isfile(fp):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # print(f"json load error in {fn}: {e}")
            pass
    return default if default is not None else {}

def save_json_setting(fn: str, data):
    _check_dir()
    fp = os.path.join("settings", fn)
    tmp_fp = f"{fp}.tmp_{random.randint(1000, 9999)}"
    try:
        with open(tmp_fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_fp, fp)
    except Exception as ex:
        print(f"[!] error saving {fn}: {ex}")
        if os.path.exists(tmp_fp):
            try: os.remove(tmp_fp)
            except Exception: pass

async def get_slowmode_delay(client, chat_id: int) -> int:
    try:
        ent = await client.get_entity(chat_id)
        return getattr(ent, 'slowmode_seconds', 0) or 0
    except RPCError:
        return 0
    except Exception:
        return 0

async def send_message_safe(client, chat_id: int, text: str, **kwargs):
    # safe sender with slowmode wait handling
    uid = getattr(client, 'uid', 0)
    key = (uid, chat_id)
    
    sm_delay = await get_slowmode_delay(client, chat_id)
    if sm_delay > 0:
        prev = _last_sent.get(key, 0)
        diff = time.time() - prev
        if diff < sm_delay:
            wait = sm_delay - diff + random.uniform(1.5, 3.5)
            # print(f"waiting {wait:.1f}s for slowmode...")
            await asyncio.sleep(wait)
            
    retry_count = 0
    while retry_count < 3:
        try:
            res = await client.send_message(chat_id, text, **kwargs)
            _last_sent[key] = time.time()
            return res
        except SlowModeWaitError as e:
            w = e.seconds + random.randint(2, 5)
            # print(f"hit slowmode wait error: {w}s")
            await asyncio.sleep(w)
            retry_count += 1
        except RPCError as rpc_e:
            print(f"[!] send_message_safe RPC error in {chat_id}: {rpc_e}")
            raise rpc_e
        except Exception as ex:
            retry_count += 1
            if retry_count >= 3:
                raise ex
            await asyncio.sleep(2)
