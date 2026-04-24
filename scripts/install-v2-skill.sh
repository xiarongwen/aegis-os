#!/bin/bash
# AEGIS v2.0 Skill Installer
# Installs AEGIS v2.0 as a Claude Code skill

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SKILL_NAME="aegis-v2"

echo "🛡️  AEGIS v2.0 Skill Installer"
echo "=============================="
echo ""

# Check Claude Code CLI installation
if ! command -v claude &> /dev/null; then
    echo "⚠️  Warning: Claude Code CLI not found in PATH"
    echo "   Install from: https://claude.ai/code"
    echo ""
fi

# Determine skills directory
if [ -n "$CLAUDE_CODE_HOME" ]; then
    SKILLS_DIR="$CLAUDE_CODE_HOME/skills"
elif [ -d "$HOME/.claude/skills" ]; then
    SKILLS_DIR="$HOME/.claude/skills"
elif [ -d "$HOME/Library/Application Support/Claude/skills" ]; then
    SKILLS_DIR="$HOME/Library/Application Support/Claude/skills"
else
    SKILLS_DIR="$HOME/.claude/skills"
fi

echo "📁 Skills directory: $SKILLS_DIR"

# Create skills directory if needed
mkdir -p "$SKILLS_DIR"

# Check if skill already exists
if [ -d "$SKILLS_DIR/$SKILL_NAME" ]; then
    echo "⚠️  Skill '$SKILL_NAME' already exists"
    read -p "   Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Installation cancelled"
        exit 1
    fi
    rm -rf "$SKILLS_DIR/$SKILL_NAME"
fi

# Create skill directory
mkdir -p "$SKILLS_DIR/$SKILL_NAME"

# Copy skill files
cp "$PROJECT_ROOT/agents/aegis/SKILL-v2.md" "$SKILLS_DIR/$SKILL_NAME/SKILL.md"
cp "$PROJECT_ROOT/agents/aegis/COMMAND-v2.md" "$SKILLS_DIR/$SKILL_NAME/COMMAND.md"

echo "✅ Skill files copied"

# Create command file for Claude Code
COMMANDS_DIR="$(dirname "$SKILLS_DIR")/commands"
mkdir -p "$COMMANDS_DIR"

cat > "$COMMANDS_DIR/$SKILL_NAME.md" << 'EOF'
---
description: Invoke AEGIS v2.0 multi-model collaboration engine for intelligent task routing and multi-model coding assistance.
argument-hint: [pattern] [request] [--mode {quality,speed,cost,balanced}] [--models model1,model2] [--budget amount] [--execute|--simulate]
---

You are invoking AEGIS v2.0 multi-model collaboration via `/aegis-v2`.

User request: $ARGUMENTS

Parse the request and execute the appropriate AEGIS v2.0 command:

1. Check if a pattern is specified (pair, swarm, pipeline, moa)
2. Build the appropriate CLI command
3. Execute and parse JSON output
4. Present results in a user-friendly format

Available patterns:
- pair: Coder + Reviewer iterative collaboration
- swarm: Multiple workers in parallel
- pipeline: Sequential stages (Design → Code → Test → Review)
- moa: Multiple expert perspectives + synthesis

Examples:
- /aegis-v2 pair "Fix the SQL injection bug"
- /aegis-v2 swarm "Generate test cases"
- /aegis-v2 pipeline "Build user management system"
- /aegis-v2 moa "Review architecture design"
EOF

echo "✅ Command file created"

# Install aegis CLI if not already installed
if [ ! -f "$PROJECT_ROOT/aegis" ]; then
    echo "⚠️  AEGIS CLI not found at $PROJECT_ROOT/aegis"
    echo "   Run: bash scripts/bootstrap.sh"
else
    # Make executable
    chmod +x "$PROJECT_ROOT/aegis"

    # Create symlink in ~/.local/bin if possible
    if [ -d "$HOME/.local/bin" ]; then
        if [ -L "$HOME/.local/bin/aegis" ]; then
            rm "$HOME/.local/bin/aegis"
        fi
        ln -sf "$PROJECT_ROOT/aegis" "$HOME/.local/bin/aegis"
        echo "✅ AEGIS CLI linked to ~/.local/bin/aegis"
    fi
fi

echo ""
echo "🎉 Installation complete!"
echo ""
echo "Usage:"
echo "  /aegis-v2 'your request'           # Auto-route"
echo "  /aegis-v2 pair 'fix this bug'      # Pair programming"
echo "  /aegis-v2 swarm 'generate tests'   # Swarm mode"
echo "  /aegis-v2 pipeline 'build feature' # Pipeline mode"
echo "  /aegis-v2 moa 'review design'      # Mixture of Agents"
echo ""
echo "Tips:"
echo "  - Use --mode quality|speed|cost|balanced"
echo "  - Use --budget 5.00 to set cost limit"
echo "  - Use --execute for real API calls"
echo "  - Use --simulate to preview without cost"
echo ""
echo "Documentation:"
echo "  - Skill: agents/aegis/SKILL-v2.md"
echo "  - Command: agents/aegis/COMMAND-v2.md"
echo ""
