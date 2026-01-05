#!/bin/bash
# Setup script for Polymarket Trading Platform
# Compatible with macOS and Ubuntu 22.04/24.04

set -e

echo "=========================================="
echo "Polymarket Trading Platform Setup"
echo "=========================================="

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    echo "Detected: macOS"
elif [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "$ID" == "ubuntu" ]]; then
        OS="ubuntu"
        echo "Detected: Ubuntu $VERSION_ID"
    fi
fi

if [[ "$OS" == "unknown" ]]; then
    echo "Warning: Unrecognized OS. Proceeding with generic setup..."
fi

# Check Python version
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3; do
    if command -v $cmd &> /dev/null; then
        version=$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo $version | cut -d. -f1)
        minor=$(echo $version | cut -d. -f2)
        if [[ $major -ge 3 && $minor -ge 11 ]]; then
            PYTHON_CMD=$cmd
            echo "Found Python $version at $(which $cmd)"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo "Error: Python 3.11+ is required but not found."
    echo ""
    if [[ "$OS" == "macos" ]]; then
        echo "Install Python with Homebrew:"
        echo "  brew install python@3.12"
    elif [[ "$OS" == "ubuntu" ]]; then
        echo "Install Python on Ubuntu:"
        echo "  sudo apt update"
        echo "  sudo apt install python3.12 python3.12-venv python3-pip"
    fi
    exit 1
fi

# Install system dependencies
echo ""
echo "Installing system dependencies..."
if [[ "$OS" == "macos" ]]; then
    if ! command -v brew &> /dev/null; then
        echo "Homebrew not found. Please install from https://brew.sh"
        exit 1
    fi
    # Ensure we have the required tools
    brew list openssl &>/dev/null || brew install openssl
    brew list libffi &>/dev/null || brew install libffi
elif [[ "$OS" == "ubuntu" ]]; then
    sudo apt-get update
    sudo apt-get install -y \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        python3-pip \
        python3-venv \
        git \
        curl
fi

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo ""
echo "Project root: $PROJECT_ROOT"

# Create virtual environment
VENV_DIR="$PROJECT_ROOT/venv"
if [[ -d "$VENV_DIR" ]]; then
    echo "Virtual environment already exists at $VENV_DIR"
    read -p "Recreate it? (y/N): " recreate
    if [[ "$recreate" =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_DIR"
        $PYTHON_CMD -m venv "$VENV_DIR"
        echo "Virtual environment recreated."
    fi
else
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    echo "Virtual environment created at $VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"
echo "Virtual environment activated."

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip setuptools wheel

# Install dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo ""
    echo "Creating .env file from template..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo "Created .env file. Please edit it with your credentials."
fi

# Make scripts executable
chmod +x "$PROJECT_ROOT/scripts/"*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT/scripts/"*.py 2>/dev/null || true

# Verify installation
echo ""
echo "Verifying installation..."
python -c "from poly import PolymarketClient, Config; print('Import successful!')"

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Activate the virtual environment:"
echo "     source venv/bin/activate"
echo ""
echo "  2. Edit .env with your Polymarket credentials"
echo ""
echo "  3. Run the platform:"
echo "     python scripts/run.py"
echo ""
echo "  4. Run tests:"
echo "     pytest tests/"
echo ""
