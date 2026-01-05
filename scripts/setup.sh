#!/bin/bash
# Setup script for Polymarket Trading Platform
# Compatible with macOS and Ubuntu 22.04/24.04
# Uses uv for fast package management

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

# Check/install uv
echo ""
if command -v uv &> /dev/null; then
    echo "Found uv at $(which uv)"
    uv --version
else
    echo "Installing uv..."
    if [[ "$OS" == "macos" ]]; then
        if command -v brew &> /dev/null; then
            brew install uv
        else
            curl -LsSf https://astral.sh/uv/install.sh | sh
            export PATH="$HOME/.local/bin:$PATH"
        fi
    elif [[ "$OS" == "ubuntu" ]]; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
    echo "uv installed successfully"
fi

# Install system dependencies (for native extensions)
echo ""
echo "Checking system dependencies..."
if [[ "$OS" == "macos" ]]; then
    if command -v brew &> /dev/null; then
        brew list openssl &>/dev/null || brew install openssl
        brew list libffi &>/dev/null || brew install libffi
    fi
elif [[ "$OS" == "ubuntu" ]]; then
    sudo apt-get update
    sudo apt-get install -y \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        git \
        curl
fi

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo ""
echo "Project root: $PROJECT_ROOT"

# Create virtual environment with uv
VENV_DIR="$PROJECT_ROOT/.venv"
if [[ -d "$VENV_DIR" ]]; then
    echo "Virtual environment already exists at $VENV_DIR"
    read -p "Recreate it? (y/N): " recreate
    if [[ "$recreate" =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_DIR"
        uv venv --python 3.12 "$VENV_DIR"
        echo "Virtual environment recreated."
    fi
else
    echo "Creating virtual environment with uv..."
    uv venv --python 3.12 "$VENV_DIR"
    echo "Virtual environment created at $VENV_DIR"
fi

# Install dependencies with uv
echo ""
echo "Installing Python dependencies with uv..."
uv pip install -r requirements.txt

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
source "$VENV_DIR/bin/activate"
python -c "from poly import PolymarketClient, Config; print('Import successful!')"

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Activate the virtual environment:"
echo "     source .venv/bin/activate"
echo ""
echo "  2. Edit .env with your Polymarket credentials"
echo ""
echo "  3. Run the platform:"
echo "     python scripts/run.py"
echo ""
echo "  4. Run tests:"
echo "     pytest tests/"
echo ""
echo "uv commands:"
echo "  uv pip install <package>    # Install a package"
echo "  uv pip list                 # List installed packages"
echo "  uv pip compile              # Lock dependencies"
echo ""
