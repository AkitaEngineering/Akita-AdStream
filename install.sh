#!/usr/bin/env bash
# Akita AdStream Installer
set -e

# Palette Colors
WHITE='\033[1;37m'
BLACK='\033[0;30m'
GRAY='\033[1;30m'
ORANGE='\033[38;5;208m'
BABY_BLUE='\033[38;5;117m'
NC='\033[0m' # No Color

echo -e "${ORANGE}=======================================${NC}"
echo -e "${WHITE}  Akita AdStream Professional Installer${NC}"
echo -e "${ORANGE}=======================================${NC}"

echo -e "\n${BABY_BLUE}[1/5] Checking OS environment...${NC}"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    echo -e "${GRAY}Detected OS: $OS${NC}"
else
    echo -e "\033[1;31mUnsupported OS. Please run on a Linux environment.\033[0m"
    exit 1
fi

echo -e "\n${BABY_BLUE}[2/5] Installing system dependencies...${NC}"
if [ "$OS" == "ubuntu" ] || [ "$OS" == "debian" ]; then
    sudo apt-get update
    sudo apt-get install -y ffmpeg pipewire python3-venv python3-pip
elif command -v pacman &> /dev/null; then
    echo -e "${GRAY}Using pacman...${NC}"
    sudo pacman -Sy --noconfirm ffmpeg pipewire python-virtualenv python-pip
else
    echo -e "${ORANGE}Warning: OS not explicitly supported for auto-install. Attempting to proceed assuming dependencies are met.${NC}"
fi

echo -e "\n${BABY_BLUE}[3/5] Setting up Python Virtual Environment...${NC}"
if [ ! -f ".venv/bin/activate" ]; then
    rm -rf .venv
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip

echo -e "\n${BABY_BLUE}[4/5] Installing Akita AdStream dependencies...${NC}"
pip install -r requirements.txt

# Create an alias or executable in local path
echo -e "\n${BABY_BLUE}[5/5] Creating executable alias...${NC}"
chmod +x run.py
mkdir -p ~/.local/bin
ln -sf $(pwd)/run.py ~/.local/bin/akita
echo -e "${GRAY}Added 'akita' command to ~/.local/bin${NC}"

# Validation
echo -e "\n${BABY_BLUE}Validating Installation...${NC}"
if ! command -v ffmpeg &> /dev/null; then
    echo -e "\033[1;31mValidation Failed: FFmpeg could not be found.\033[0m"
    exit 1
fi

if ! python -c "import RNS" &> /dev/null; then
    echo -e "\033[1;31mValidation Failed: Reticulum Network Stack (RNS) could not be loaded.\033[0m"
    exit 1
fi

echo -e "\n${BABY_BLUE}[6/6] Configuring Reticulum...${NC}"
if [ ! -f ~/.reticulum/config ]; then
    echo -e "${GRAY}Generating default Reticulum configuration...${NC}"
    rnsd --exampleconfig || true
    echo -e "${WHITE}Default configuration created at ~/.reticulum/config${NC}"
else
    echo -e "${GRAY}Reticulum configuration already exists at ~/.reticulum/config${NC}"
fi

echo -e "\n${BABY_BLUE}[7/7] Setting up Reticulum Background Service (systemd)...${NC}"
SERVICE_FILE="/etc/systemd/system/rnsd.service"
echo -e "${GRAY}Requesting sudo to configure systemd service...${NC}"
if sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Reticulum Network Stack Daemon
After=network.target

[Service]
Type=simple
User=$USER
ExecStart=$(command -v rnsd) --config ~/.reticulum
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
then
    sudo systemctl daemon-reload
    sudo systemctl enable rnsd.service
    sudo systemctl start rnsd.service
    echo -e "${WHITE}rnsd.service installed and started successfully!${NC}"
else
    echo -e "\033[1;31mFailed to create systemd service. You may need to start rnsd manually.\033[0m"
fi

echo -e "\n${ORANGE}=======================================${NC}"
echo -e "${WHITE}  Installation Complete!${NC}"
echo -e "${ORANGE}=======================================${NC}"
echo -e "${BABY_BLUE}Run the application using: ${WHITE}~/.local/bin/akita --help${NC}"
echo -e "${GRAY}Note: Ensure ~/.local/bin is in your PATH.${NC}\n"
