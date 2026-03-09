#!/usr/bin/env bash
#
# claude-speak installer for Linux/macOS
# Free text-to-speech for Claude Code
#

set -e

echo ""
echo "  claude-speak installer"
echo "  Free text-to-speech for Claude Code"
echo ""

# Determine source directory
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

# Target directories
CLAUDE_DIR="$HOME/.claude"
TOOLS_DIR="$CLAUDE_DIR/tools"
SKILL_DIR="$CLAUDE_DIR/skills/speak"

# ── Pre-flight checks ──────────────────────────────────────────────

# Check Python 3 is available
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null && python --version 2>&1 | grep -q "Python 3"; then
    PYTHON_CMD="python"
else
    echo "  ERROR: Python 3 is required but not found."
    echo "  Install Python 3.8+ from https://www.python.org/downloads/"
    exit 1
fi

# Check Python version >= 3.8
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]; }; then
    echo "  ERROR: Python 3.8+ is required (found $PYTHON_VERSION)."
    echo "  Please upgrade Python: https://www.python.org/downloads/"
    exit 1
fi

echo "  Python $PYTHON_VERSION detected ($PYTHON_CMD)"

# Warn if tools directory already exists
if [ -d "$TOOLS_DIR" ] && ls "$TOOLS_DIR"/claude-speak.py &>/dev/null 2>&1; then
    echo ""
    echo "  NOTE: Existing installation found in $TOOLS_DIR"
    echo "  Files will be overwritten."
    echo ""
fi

# ── Step 1: Install edge-tts ───────────────────────────────────────

echo "[1/3] Installing edge-tts..."
if command -v pip3 &>/dev/null; then
    pip3 install edge-tts --quiet || { echo "  ERROR: Failed to install edge-tts via pip3"; exit 1; }
elif command -v pip &>/dev/null; then
    pip install edge-tts --quiet || { echo "  ERROR: Failed to install edge-tts via pip"; exit 1; }
else
    echo "  ERROR: pip not found. Install Python 3 first."
    exit 1
fi

# Verify edge-tts is importable
if ! $PYTHON_CMD -c "import edge_tts" 2>/dev/null; then
    echo "  ERROR: edge-tts installed but cannot be imported."
    echo "  Try: $PYTHON_CMD -m pip install edge-tts"
    exit 1
fi

echo "  OK - edge-tts installed"

# ── Step 2: Copy scripts ───────────────────────────────────────────

echo "[2/3] Copying scripts to $TOOLS_DIR..."
mkdir -p "$TOOLS_DIR"

for script in claude-speak.py cc-speak.py configure.py settings.html; do
    if [ -f "$SOURCE_DIR/$script" ]; then
        cp "$SOURCE_DIR/$script" "$TOOLS_DIR/$script"
        chmod +x "$TOOLS_DIR/$script"
        echo "  OK - $script"
    else
        echo "  SKIP - $script not found in $SOURCE_DIR"
    fi
done

# ── Step 3: Install /speak skill ───────────────────────────────────

echo "[3/3] Installing /speak skill..."
mkdir -p "$SKILL_DIR"

if [ -f "$SOURCE_DIR/skill/SKILL.md" ]; then
    cp "$SOURCE_DIR/skill/SKILL.md" "$SKILL_DIR/SKILL.md"
    echo "  OK - /speak skill installed"
else
    echo "  SKIP - skill/SKILL.md not found"
fi

# Check for ffplay on Linux
if [[ "$OSTYPE" == "linux"* ]] && ! command -v ffplay &>/dev/null; then
    echo ""
    echo "  NOTE: ffplay not found. Install ffmpeg for audio playback:"
    echo "    sudo apt install ffmpeg    # Debian/Ubuntu"
    echo "    sudo dnf install ffmpeg    # Fedora"
    echo "    sudo pacman -S ffmpeg      # Arch"
fi

# Done
echo ""
echo "  Installation complete!"
echo ""
echo "  Quick start:"
echo "    # Start the speech monitor (all projects):"
echo "    $PYTHON_CMD $TOOLS_DIR/claude-speak.py"
echo ""
echo "    # Open settings UI:"
echo "    $PYTHON_CMD $TOOLS_DIR/configure.py"
echo ""
echo "    # In Claude Code, use /speak to toggle"
echo ""
