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
    read -p "▸ Bot Token: " bot_token
    read -p "▸ Admin Telegram User ID: " admin_id
    read -p "▸ Bot API ID: " bot_api_id
    read -p "▸ Bot API HASH: " bot_api_hash
    read -p "▸ Card Number for Payments (default: 6037997000000000): " card_num
    card_num=${card_num:-"6037997000000000"}

    if [ -z "$bot_token" ] || [ -z "$admin_id" ] || [ -z "$bot_api_id" ] || [ -z "$bot_api_hash" ]; then
        echo -e "${RED}❌ Bot token, Admin ID, and API credentials cannot be empty!${NC}"
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
}

do_install() {
    echo -e "${CYAN}${BOLD}🚀 Setting up MeowAce-Self...${NC}"
    
    echo -e "\nSelect Mode:"
    echo -e "  [1] Single-Session (Single account login via config.json)"
    echo -e "  [2] Multi-Session (Multi-account login managed by Telegram Bot)"
    read -p "Choice [1-2] (default: 1): " mode_choice

    if [ "$mode_choice" == "2" ]; then
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

    if [ "$mode_choice" != "2" ]; then
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
    echo -e "${CYAN}🔄 Fetching latest source code from GitHub...${NC}"
    sudo systemctl stop meowace-self 2>/dev/null

    if [ -d ".git" ]; then
        git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || git pull
        if [ $? -ne 0 ]; then
            echo -e "${RED}⚠️ Git pull failed. Please check your git status or network connection.${NC}"
        else
            echo -e "${GREEN}📥 Source code updated successfully.${NC}"
        fi
    else
        echo -e "${RED}❌ .git repository not found! Cannot pull updates.${NC}"
    fi

    if [ -d "venv" ]; then
        echo -e "${CYAN}📦 Updating Python dependencies...${NC}"
        venv/bin/pip install -q --upgrade pip 2>/dev/null
        venv/bin/pip install -q -r requirements.txt
    fi

    sudo systemctl restart meowace-self
    echo -e "${GREEN}✅ Update finished & service restarted! (Session preserved)${NC}"
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
    $PY -c '
import json, sys

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
    print(f"  ▸ Type: {proxy.get(\"type\", \"socks5\")}")
    print(f"  ▸ Host: {proxy.get(\"host\", \"127.0.0.1\")}:{proxy.get(\"port\", 1080)}")

ans = input("\nDo you want to enable/configure Proxy? [y/N]: ").strip().lower()
if ans not in ("y", "yes"):
    proxy["enabled"] = False
    cfg["proxy"] = proxy
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("🔴 Proxy disabled and saved to config.json.")
    sys.exit(0)

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
d choice.${NC}" ;;
        esac
        ;;
esac
