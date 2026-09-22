import sys
from urllib.parse import urlparse, parse_qs

try:
    import python_socks
    HAS_PYTHON_SOCKS = True
except ImportError:
    HAS_PYTHON_SOCKS = False

try:
    import socks
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False

try:
    from telethon.network.connection import (
        ConnectionTcpMTProxyIntermediate,
        ConnectionTcpMTProxyRandomizedIntermediate
    )
    HAS_TELETHON = True
except ImportError:
    HAS_TELETHON = False


def parse_proxy_link(link: str) -> dict:
    """
    Parses proxy URLs or links (tg://, https://t.me, socks5://, http://)
    and returns a normalized dict of proxy settings.
    """
    if not link or not isinstance(link, str):
        return {}

    link = link.strip()

    # tg://proxy?server=... or https://t.me/proxy?server=...
    if "tg://proxy" in link or "t.me/proxy" in link:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        server = qs.get("server", [""])[0]
        port = qs.get("port", ["443"])[0]
        secret = qs.get("secret", [""])[0]
        if server:
            return {
                "enabled": True,
                "type": "mtproto",
                "host": server,
                "port": int(port) if port.isdigit() else 443,
                "secret": secret
            }

    # tg://socks?server=... or https://t.me/socks?server=...
    if "tg://socks" in link or "t.me/socks" in link:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        server = qs.get("server", [""])[0]
        port = qs.get("port", ["1080"])[0]
        user = qs.get("user", [""])[0]
        password = qs.get("pass", [""])[0]
        if server:
            return {
                "enabled": True,
                "type": "socks5",
                "host": server,
                "port": int(port) if port.isdigit() else 1080,
                "username": user or None,
                "password": password or None
            }

    # URI schemes: socks5://, socks4://, http://, https://
    for proto in ("socks5://", "socks4://", "socks://", "http://", "https://"):
        if link.lower().startswith(proto):
            parsed = urlparse(link)
            ptype = "socks5" if "socks" in parsed.scheme else "http"
            port = parsed.port or (1080 if ptype == "socks5" else 8080)
            return {
                "enabled": True,
                "type": ptype,
                "host": parsed.hostname or "127.0.0.1",
                "port": port,
                "username": parsed.username or None,
                "password": parsed.password or None
            }

    return {}


def get_proxy_kwargs(cfg: dict) -> dict:
    """
    Parses proxy settings from config dictionary and returns kwargs for Telethon TelegramClient.
    Supported types: 'socks5', 'socks4', 'http', 'https', 'mtproto'.
    """
    if not isinstance(cfg, dict):
        return {}

    p_cfg = cfg.get("proxy")
    if not isinstance(p_cfg, dict) or not p_cfg.get("enabled", False):
        return {}

    # If the user passed a full proxy URL into "url" or "host"
    raw_input = p_cfg.get("url") or p_cfg.get("host") or ""
    if isinstance(raw_input, str) and ("://" in raw_input or raw_input.startswith("tg://")):
        parsed_link = parse_proxy_link(raw_input)
        if parsed_link:
            for k, v in parsed_link.items():
                if v and not p_cfg.get(k):
                    p_cfg[k] = v

    p_type = str(p_cfg.get("type", "socks5")).strip().lower()
    host = str(p_cfg.get("host") or p_cfg.get("addr") or "127.0.0.1").strip()

    try:
        port = int(p_cfg.get("port", 1080))
    except (ValueError, TypeError):
        print(f"[!] Invalid proxy port: '{p_cfg.get('port')}'. Disabling proxy.")
        return {}

    username = p_cfg.get("username") or None
    password = p_cfg.get("password") or None
    secret = p_cfg.get("secret") or None
    rdns = bool(p_cfg.get("rdns", True))

    if p_type in ("socks5", "socks", "socks4", "http", "https"):
        if not HAS_PYTHON_SOCKS and not HAS_SOCKS:
            print("[!] Warning: Neither 'python-socks' nor 'PySocks' is installed! Proxy disabled.")
            print("[!] Please run: pip install python-socks[asyncio] PySocks")
            return {}

        if p_type in ("socks5", "socks"):
            proxy_type = socks.SOCKS5 if HAS_SOCKS else "socks5"
            type_str = "SOCKS5"
        elif p_type == "socks4":
            proxy_type = socks.SOCKS4 if HAS_SOCKS else "socks4"
            type_str = "SOCKS4"
        else:
            proxy_type = socks.HTTP if HAS_SOCKS else "http"
            type_str = "HTTP"

        auth_str = f" (user: {username})" if username else ""
        engine_str = "python-socks" if HAS_PYTHON_SOCKS else "PySocks"
        print(f"[+] Enabling {type_str} Proxy -> {host}:{port}{auth_str} [{engine_str}]")
        return {
            "proxy": (proxy_type, host, port, rdns, username, password)
        }

    elif p_type == "mtproto":
        if not HAS_TELETHON:
            print("[!] Error: Telethon library not found when configuring MTProto proxy.")
            return {}

        if not secret:
            print("[!] Warning: MTProto proxy requires a secret! Disabling proxy.")
            return {}

        secret_str = str(secret).strip()
        sec_lower = secret_str.lower()
        if sec_lower.startswith("dd") or sec_lower.startswith("ee") or len(secret_str) > 32:
            conn_class = ConnectionTcpMTProxyRandomizedIntermediate
            mode_str = "Randomized / Fake-TLS"
        else:
            conn_class = ConnectionTcpMTProxyIntermediate
            mode_str = "Standard"

        print(f"[+] Enabling MTProto Proxy ({mode_str}) -> {host}:{port}")
        return {
            "connection": conn_class,
            "proxy": (host, port, secret_str)
        }

    else:
        print(f"[!] Unknown proxy type '{p_type}'. Proxy disabled.")
        return {}
