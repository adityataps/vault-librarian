#!/usr/bin/env bash
set -euo pipefail

# Compose startup script — starts optional Ollama service
# Supports both Docker and Podman

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Load .env if it exists
if [ -f .env ]; then
    echo "Loading configuration from .env..."
    set -a
    source .env
    set +a
else
    echo "Warning: .env file not found. Using defaults."
fi

# Auto-detect container runtime: prefer podman if available
if command -v podman &>/dev/null; then
    CONTAINER_CMD="podman"
    if command -v podman-compose &>/dev/null; then
        COMPOSE_CMD="podman-compose"
    else
        COMPOSE_CMD="podman compose"
    fi
    echo "🦭 Using Podman ($COMPOSE_CMD)"
elif command -v docker &>/dev/null; then
    CONTAINER_CMD="docker"
    COMPOSE_CMD="docker compose"
    echo "🐳 Using Docker"
else
    echo "Error: Neither podman nor docker found in PATH." >&2
    exit 1
fi

# Build compose command with conditional profiles
PROFILES=()

if [ "${ENABLE_OLLAMA:-false}" = "true" ]; then
    echo "✓ Ollama enabled"
    PROFILES+=("--profile" "ollama")
else
    echo "✗ Ollama disabled (set ENABLE_OLLAMA=true to enable)"
fi

if [ ${#PROFILES[@]} -eq 0 ]; then
    echo ""
    echo "No services to start. Set ENABLE_OLLAMA=true in .env to start Ollama."
    exit 0
fi

# Start services
echo ""
echo "Starting vault-librarian infrastructure..."
$COMPOSE_CMD "${PROFILES[@]}" up -d --force-recreate "$@"

# Pull Ollama models if configured
if [ "${ENABLE_OLLAMA:-false}" = "true" ] && [ -n "${OLLAMA_MODELS:-}" ]; then
    echo ""
    echo "Pulling Ollama models: ${OLLAMA_MODELS}"

    echo "Waiting for Ollama to start..."
    for i in {1..30}; do
        if $CONTAINER_CMD exec vault-librarian-ollama curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "✓ Ollama is ready"
            break
        fi
        echo -n "."
        sleep 2
    done
    echo ""

    IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
    for model in "${MODELS[@]}"; do
        model=$(echo "$model" | xargs)
        echo "Pulling model: $model"
        $CONTAINER_CMD exec vault-librarian-ollama ollama pull "$model"
    done

    echo "✓ All Ollama models pulled successfully"
fi

echo ""
echo "✓ Infrastructure started successfully!"
echo ""
echo "Services running:"
$COMPOSE_CMD "${PROFILES[@]}" ps

echo ""
echo "Next steps:"
echo "  Start service:  uv run vault-librarian serve"
echo "  View logs:      $COMPOSE_CMD logs -f"
echo "  Stop services:  $COMPOSE_CMD down"
