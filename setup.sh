#!/bin/bash
# One-line setup & installer launcher for MeowAce-Self

REPO_URL="https://github.com/MahdiAce02/MeowAce-Self.git"
INSTALL_DIR="$HOME/MeowAce-Self"

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}🐾 MeowAce-Self One-Line Setup 🐾${NC}"

# Ensure git is installed
if ! command -v git &>/dev/null; then
    echo -e "${YELLOW}⚙️ Installing git...${NC}"
    sudo apt update && sudo apt install -y git
fi

if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${CYAN}📥 Downloading MeowAce-Self source code from GitHub...${NC}"
    git clone "$REPO_URL" "$INSTALL_DIR"
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Failed to clone repository.${NC}"
        exit 1
    fi
else
    echo -e "${CYAN}🔄 Updating local repository in $INSTALL_DIR...${NC}"
    cd "$INSTALL_DIR" || exit 1
    git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null
    git rebase --abort 2>/dev/null
    git merge --abort 2>/dev/null
    git fetch origin main 2>/dev/null || git fetch --all 2>/dev/null
    git reset --hard origin/main 2>/dev/null || git reset --hard origin/master 2>/dev/null
fi

# Create global 'meowace' command
cat <<EOF | sudo tee /usr/local/bin/meowace > /dev/null
#!/bin/bash
cd "$INSTALL_DIR" || exit 1
exec bash install.sh "\$@"
EOF
sudo chmod +x /usr/local/bin/meowace

cd "$INSTALL_DIR" || exit 1
chmod +x install.sh
exec bash install.sh "$@"
