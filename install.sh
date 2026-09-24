#!/bin/bash
# Installer & Service Manager for MeowAce-Self

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Ensure Python 3 & Git
if ! command -v python3 &>/dev/null || ! command -v git &>/dev/null; then
    echo -e "${YELLOW}⚙️ Installing python3, git & dependencies...${NC}"
    sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
fi

PY="python3"
if [ -d "venv" ]; then
    PY="venv/bin/python"
fi

do_multisession_config() {
    echo -e "${CYAN}${BOLD}🤖 Multi-Session & Bot Configuration${NC}"
    read -p "▸ Bot Token (from @BotFather): " bot_token
    read -p "▸ Admin Telegram User ID: " admin_id
    read -p "▸ Bot API ID (from my.telegram.org): " bot_api_id
    read -p "▸ Bot API HASH (from my.telegram.org): " bot_api_hash
    read -p "▸ Card Number for Payments (default: 6037997000000000): " card_num
    card_num=${card_num:-"6037997000000000"}

    if [ -z "$bot_token" ] || [ -z "$admin_id" ] || [ -z "$bot_api_id" ] || [ -z "$bot_api_hash" ]; then
        echo -e "${RED}❌ Bot token, Admin ID, API ID and API HASH cannot be empty!${NC}"
        return 1
    fi

    cat <<EOF > bot_config.json
{
  "bot_token": "$bot_token",
  "admin_id": $admin_id,
  "bot_api_id": $bot_api_id,
  "bot_api_hash": "$bot_api_hash",
  "card_number": "$card_num",
  "mode": "private",
  "public_type": "free",
  "subscription": {
    "price_toman": 50000,
    "duration_days": 30
  },
  "trial": {
    "enabled": true,
    "duration_hours": 24
  }
}
EOF
    echo -e "${GREEN}✅ bot_config.json created successfully.${NC}"

    # Always ensure multi_session: true is set in config.json
    if [ ! -f "config.json" ]; then
        echo "{\"multi_session\": true}" > config.json
    else
        $PY -c '
import json
try:
    with open("config.json", "r", encoding="utf-8") as f:
        d = json.load(f)
except Exception:
    d = {}
d["multi_session"] = True
with open("config.json", "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
' 2>/dev/null || echo "{\"multi_session\": true}" > config.json
    fi
    echo -e "${GREEN}✅ Multi-session mode enabled in config.json.${NC}"

    if systemctl is_active --quiet meowace-self 2>/dev/null; then
        echo -e "${YELLOW}🔄 Restarting meowace-self service to apply changes...${NC}"
        sudo systemctl restart meowace-self
    fi
}

do_install() {
    echo -e "${CYAN}${BOLD}🚀 Setting up MeowAce-Self...${NC}"
    
    echo -e "\nSelect Mode:"
    echo -e "  [1] Multi-Session (Multi-account bot manager) [RECOMMENDED]"
    echo -e "  [2] Single-Session (Single account login via config.json)"
    read -p "Choice [1-2] (default: 1): " mode_choice
    mode_choice=${mode_choice:-"1"}

    if [ "$mode_choice" == "1" ]; then
        echo "{\"multi_session\": true}" > config.json
        do_multisession_config
    else
        echo -e "${YELLOW}🔑 Enter your Telegram API credentials:${NC}"
        read -p "▸ API ID: " api_id
        read -p "▸ API HASH: " api_hash
        if [ -z "$api_id" ] || [ -z "$api_hash" ]; then
            echo -e "${RED}❌ API credentials cannot be empty!${NC}"
            exit 1
        fi
        echo "{\"multi_session\": false, \"api_id\": $api_id, \"api_hash\": \"$api_hash\"}" > config.json
        echo -e "${GREEN}✅ config.json saved successfully.${NC}"
    fi

    read -p "▸ Do you need to set up a Proxy (SOCKS5/HTTP/MTProto)? [y/N]: " setup_proxy
    if [[ "$setup_proxy" =~ ^[Yy]$ ]]; then
        do_proxy_config
    fi

    # Virtual environment & packages
    if [ ! -d "venv" ]; then
        echo -e "${CYAN}📦 Creating virtual environment...${NC}"
        python3 -m venv venv
    fi
    echo -e "${CYAN}📥 Installing Python packages...${NC}"
    venv/bin/pip install -q -r requirements.txt
    PY="venv/bin/python"

    if [ "$mode_choice" == "2" ]; then
        # Interactive Telethon Login for Single Session
        $PY login.py
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Login failed or cancelled.${NC}"
            exit 1
        fi
    fi

    # Systemd Service Creation
    USER_NAME=$(whoami)
    cat <<EOF | sudo tee /etc/systemd/system/meowace-self.service > /dev/null
[Unit]
Description=MeowAce-Self Bot Service
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/$PY $DIR/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable --now meowace-self

    # Register global CLI command
    cat <<EOF | sudo tee /usr/local/bin/meowace > /dev/null
#!/bin/bash
cd "$DIR" || exit 1
exec bash install.sh "\$@"
EOF
    sudo chmod +x /usr/local/bin/meowace

    echo -e "${GREEN}${BOLD}🎉 MeowAce-Self installed and running successfully as systemd service!${NC}"
    echo -e "${CYAN}💡 You can now manage the panel anytime by typing: ${BOLD}meowace${NC}"
}

do_relogin() {
    echo -e "${YELLOW}🔄 Stopping service & resetting Telegram session...${NC}"
    sudo systemctl stop meowace-self 2>/dev/null
    rm -f meowace_self.session meowace_self.session-journal
    $PY login.py
    if [ $? -eq 0 ]; then
        sudo systemctl restart meowace-self
        echo -e "${GREEN}✅ Re-logged in & service restarted successfully!${NC}"
    fi
}

do_update() {
    cat << 'WORKER_EOF' > /tmp/meowace_updater.sh
#!/bin/bash
DIR="$1"
cd "$DIR" || exit 1

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "\n${CYAN}${BOLD}🔄 Starting MeowAce-Self Safe Updater...${NC}"

# 1. Stop service & any stray processes
echo -e "${YELLOW}🛑 Stopping bot service...${NC}"
sudo systemctl stop meowace-self 2>/dev/null
pkill -f "$DIR/main.py" 2>/dev/null

# 2. Configure safe directory
git config --global --add safe.directory "$DIR" 2>/dev/null

if [ ! -d ".git" ]; then
    echo -e "${RED}❌ .git directory not found in $DIR! Cannot pull updates.${NC}"
    sudo systemctl restart meowace-self 2>/dev/null
    exit 1
fi

# 3. Ensure remote origin exists
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if [ -z "$REMOTE_URL" ]; then
    git remote add origin "https://github.com/MahdiAce02/MeowAce-Self.git" 2>/dev/null
fi

# 4. Abort any broken git merge/rebase
git rebase --abort 2>/dev/null
git merge --abort 2>/dev/null

# 5. Backup critical configs in /tmp
echo -e "${CYAN}💾 Securing configs and session files...${NC}"
mkdir -p /tmp/meowace_backup
[ -f "config.json" ] && cp -f "config.json" /tmp/meowace_backup/ 2>/dev/null
[ -f "bot_config.json" ] && cp -f "bot_config.json" /tmp/meowace_backup/ 2>/dev/null
[ -f "bot_data.json" ] && cp -f "bot_data.json" /tmp/meowace_backup/ 2>/dev/null

# 6. Fetch remote updates
echo -e "${CYAN}📥 Pulling latest source code from GitHub...${NC}"
git fetch origin main 2>/dev/null || git fetch origin master 2>/dev/null || git fetch --all 2>/dev/null

TARGET_BRANCH="main"
if git show-ref --verify --quiet refs/remotes/origin/main; then
    TARGET_BRANCH="main"
elif git show-ref --verify --quiet refs/remotes/origin/master; then
    TARGET_BRANCH="master"
fi

# Discard all local modifications to tracked files
git reset --hard "origin/$TARGET_BRANCH" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}⚠️ Direct reset failed, attempting forced checkout recovery...${NC}"
    git checkout -B "$TARGET_BRANCH" "origin/$TARGET_BRANCH" --force 2>/dev/null
    git reset --hard "origin/$TARGET_BRANCH" 2>/dev/null
fi

# Restore configs if needed
[ -f "/tmp/meowace_backup/config.json" ] && [ ! -f "config.json" ] && cp -f "/tmp/meowace_backup/config.json" ./
[ -f "/tmp/meowace_backup/bot_config.json" ] && [ ! -f "bot_config.json" ] && cp -f "/tmp/meowace_backup/bot_config.json" ./
[ -f "/tmp/meowace_backup/bot_data.json" ] && [ ! -f "bot_data.json" ] && cp -f "/tmp/meowace_backup/bot_data.json" ./
rm -rf /tmp/meowace_backup

# 7. Clear old python caches
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# 8. Update dependencies
if [ -d "venv" ]; then
    echo -e "${CYAN}📦 Updating Python dependencies in virtualenv...${NC}"
    venv/bin/pip install -q --upgrade pip 2>/dev/null
    venv/bin/pip install -q -r requirements.txt
else
    echo -e "${CYAN}📦 Creating virtualenv and installing dependencies...${NC}"
    python3 -m venv venv
    venv/bin/pip install -q -r requirements.txt
fi

# 9. Ensure systemd service configuration
USER_NAME=$(whoami)
cat <<SVC_EOF | sudo tee /etc/systemd/system/meowace-self.service > /dev/null
[Unit]
Description=MeowAce-Self Bot Service
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python -u $DIR/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVC_EOF

sudo systemctl daemon-reload
sudo systemctl restart meowace-self

# 10. Ensure executable permissions
chmod +x install.sh setup.sh 2>/dev/null

# 11. Update global shortcut
cat <<SH_EOF | sudo tee /usr/local/bin/meowace > /dev/null
#!/bin/bash
cd "$DIR" || exit 1
exec bash install.sh "\$@"
SH_EOF
sudo chmod +x /usr/local/bin/meowace 2>/dev/null

sleep 1
if systemctl is-active --quiet meowace-self 2>/dev/null; then
    echo -e "\n${GREEN}${BOLD}═════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}${BOLD}✅ Update successfully completed & service restarted!${NC}"
    echo -e "${GREEN}${BOLD}═════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}📌 All sessions, settings, and databases preserved.${NC}"
    echo -e "${CYAN}💡 View real-time logs anytime with: ${BOLD}journalctl -u meowace-self -f${NC}\n"
else
    echo -e "\n${YELLOW}⚠️ Service restarted, checking status:${NC}"
    sudo systemctl status meowace-self --no-pager
fi

rm -f /tmp/meowace_updater.sh
exit 0
WORKER_EOF

    chmod +x /tmp/meowace_updater.sh
    exec bash /tmp/meowace_updater.sh "$DIR"
}

do_uninstall() {
    echo -e "${RED}${BOLD}⚠️ WARNING: This will stop and remove the MeowAce-Self service, sessions, and configuration!${NC}"
    read -p "Are you sure you want to completely uninstall MeowAce-Self? [y/N]: " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}🗑️ Stopping & disabling systemd service...${NC}"
        sudo systemctl stop meowace-self 2>/dev/null
        sudo systemctl disable meowace-self 2>/dev/null
        sudo rm -f /etc/systemd/system/meowace-self.service
        sudo systemctl daemon-reload

        echo -e "${YELLOW}🗑️ Removing CLI shortcut...${NC}"
        sudo rm -f /usr/local/bin/meowace

        echo -e "${YELLOW}🗑️ Removing sessions, virtualenv, and configs...${NC}"
        rm -rf venv meowace_self.session meowace_self.session-journal sessions/ config.json bot_config.json bot_data.json settings/

        echo -e "${GREEN}${BOLD}✅ MeowAce-Self has been completely uninstalled and wiped!${NC}"
    else
        echo -e "${CYAN}Uninstall cancelled.${NC}"
    fi
}

do_proxy_config() {
    echo -e "${CYAN}${BOLD}🌐 Proxy Configuration Manager${NC}"
    if [ ! -f "config.json" ]; then
        echo -e "${RED}❌ config.json not found! Please run installation first.${NC}"
        return
    fi
    PY_CMD="python3"
    if [ -d "venv" ]; then
        PY_CMD="venv/bin/python"
    fi
    $PY_CMD -c '
import json, sys
try:
    from modules.proxy import parse_proxy_link
except ImportError:
    parse_proxy_link = None

cfg_file = "config.json"
try:
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    print(f"❌ Error loading config.json: {e}")
    sys.exit(1)

proxy = cfg.get("proxy", {})
current_st = "Enabled 🟢" if proxy.get("enabled") else "Disabled 🔴"
print(f"Current Proxy Status: {current_st}")
if proxy.get("enabled"):
    print(f"  ▸ Type: {proxy.get(\"type\", \"socks5\").upper()}")
    print(f"  ▸ Host: {proxy.get(\"host\", \"127.0.0.1\")}:{proxy.get(\"port\", 1080)}")
    if proxy.get("type") == "mtproto" and proxy.get("secret"):
        sec = str(proxy.get("secret"))
        sec_abbr = sec[:6] + "..." + sec[-4:] if len(sec) > 12 else sec
        print(f"  ▸ Secret: {sec_abbr}")

print("\nProxy Options:")
print("  [1] 🔗 Quick Setup via Proxy Link (tg://, https://t.me/proxy, socks5://)")
print("  [2] ⚙️ Manual Configuration (SOCKS5 / HTTP / MTProto)")
print("  [3] 🔴 Disable Proxy")
print("  [0] ↩️ Return")
choice = input("Select option [0-3]: ").strip()

if choice == "3":
    proxy["enabled"] = False
    cfg["proxy"] = proxy
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("🔴 Proxy disabled and saved to config.json.")
    sys.exit(0)
elif choice == "1":
    link = input("\n▸ Paste Proxy Link: ").strip()
    parsed = parse_proxy_link(link) if parse_proxy_link else {}
    if not parsed:
        print("❌ Invalid or unsupported proxy link format.")
        sys.exit(1)
    cfg["proxy"] = parsed
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Proxy ({parsed.get(\"type\", \"\").upper()}) saved successfully!")
    sys.exit(0)
elif choice == "2":
    print("\nSelect Proxy Type:")
    print("  [1] SOCKS5 (Default)")
    print("  [2] HTTP / HTTPS")
    print("  [3] MTProto")
    t_choice = input("Choice [1-3] (default: 1): ").strip()

    p_type = "socks5"
    if t_choice == "2":
        p_type = "http"
    elif t_choice == "3":
        p_type = "mtproto"

    host = input("▸ Host IP/Domain [default: 127.0.0.1]: ").strip() or "127.0.0.1"
    if parse_proxy_link and ("://" in host or host.startswith("tg://")):
        parsed = parse_proxy_link(host)
        if parsed:
            cfg["proxy"] = parsed
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            print(f"\n✅ Proxy ({parsed.get(\"type\", \"\").upper()}) link detected and saved!")
            sys.exit(0)

    default_port = "443" if p_type == "mtproto" else ("8080" if p_type == "http" else "1080")
    port_str = input(f"▸ Port [default: {default_port}]: ").strip() or default_port

    try:
        port = int(port_str)
    except ValueError:
        port = int(default_port)

    username = ""
    password = ""
    secret = ""

    if p_type in ("socks5", "http"):
        username = input("▸ Username (leave empty if none): ").strip()
        password = input("▸ Password (leave empty if none): ").strip()
    elif p_type == "mtproto":
        secret = input("▸ MTProto Secret (required): ").strip()

    proxy_obj = {
        "enabled": True,
        "type": p_type,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "secret": secret
    }

    cfg["proxy"] = proxy_obj
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Proxy ({p_type.upper()}) configured and saved to config.json!")
'
    if systemctl is_active --quiet meowace-self 2>/dev/null; then
        echo -e "${YELLOW}🔄 Restarting meowace-self service to apply changes...${NC}"
        sudo systemctl restart meowace-self
    fi
}

case "$1" in
    --install) do_install ;;
    --relogin) do_relogin ;;
    --update) do_update ;;
    --proxy) do_proxy_config ;;
    --uninstall) do_uninstall ;;
    *)
        clear
        echo -e "${CYAN}${BOLD}"
        echo "====================================================="
        echo "         🐾 MeowAce-Self Control Panel 🐾            "
        echo "====================================================="
        echo -e "${NC}"
        echo -e "  ${BOLD}[1]${NC} 🚀 Full Install & Start Service"
        echo -e "  ${BOLD}[2]${NC} 🔑 Re-login Single Account"
        echo -e "  ${BOLD}[3]${NC} 🔄 Update Source & Restart"
        echo -e "  ${BOLD}[4]${NC} ⚡ Restart Service"
        echo -e "  ${BOLD}[5]${NC} 📊 View Service Status"
        echo -e "  ${BOLD}[6]${NC} 🗑️ Complete Uninstall & Wipe"
        echo -e "  ${BOLD}[7]${NC} 🌐 Configure / Toggle Proxy"
        echo -e "  ${BOLD}[8]${NC} 🤖 Configure Multi-Session & Bot"
        echo -e "  ${BOLD}[0]${NC} ❌ Exit"
        echo -e "${CYAN}=====================================================${NC}"
        read -p "Select option [0-8]: " choice
        case "$choice" in
            1) do_install ;;
            2) do_relogin ;;
            3) do_update ;;
            4) sudo systemctl restart meowace-self && sudo systemctl status meowace-self --no-pager ;;
            5) sudo systemctl status meowace-self --no-pager ;;
            6) do_uninstall ;;
            7) do_proxy_config ;;
            8) do_multisession_config ;;
            0) exit 0 ;;
            *) echo -e "${RED}Invalid choice.${NC}" ;;
        esac
        ;;
esac
