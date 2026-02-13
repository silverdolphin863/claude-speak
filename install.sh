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

# 1. Install edge-tts
echo "[1/3] Installing edge-tts..."
if command -v pip3 &>/dev/null; then
    pip3 install edge-tts --quiet 2>/dev/null
    echo "  OK - edge-tts installed"
elif command -v pip &>/dev/null; then
    pip install edge-tts --quiet 2>/dev/null
    echo "  OK - edge-tts installed"
else
    echo "  ERROR - pip not found. Install Python 3 first."
    exit 1
fi

# 2. Copy scripts to ~/.claude/tools/
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

# 3. Install /speak skill
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
echo "    python3 $TOOLS_DIR/claude-speak.py"
echo ""
echo "    # Open settings UI:"
echo "    python3 $TOOLS_DIR/configure.py"
echo ""
echo "    # In Claude Code, use /speak to toggle"
echo ""
