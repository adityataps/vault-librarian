#!/usr/bin/env bash
set -euo pipefail

# Compose startup script with environment-driven profiles
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
    # Prefer podman-compose over `podman compose` to avoid external provider conflicts
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

# Add Redis profile if enabled
if [ "${ENABLE_REDIS:-false}" = "true" ]; then
    echo "✓ Redis enabled"
    PROFILES+=("--profile" "redis")
else
    echo "✗ Redis disabled (set ENABLE_REDIS=true to enable)"
fi

# Add Ollama profile if enabled
if [ "${ENABLE_OLLAMA:-false}" = "true" ]; then
    echo "✓ Ollama enabled"
    PROFILES+=("--profile" "ollama")
else
    echo "✗ Ollama disabled (set ENABLE_OLLAMA=true to enable)"
fi

# Start services
echo ""
echo "Starting vault-crawler infrastructure..."
$COMPOSE_CMD "${PROFILES[@]+"${PROFILES[@]}"}" up -d "$@"

# Wait for Postgres to be healthy
echo ""
echo "Waiting for Postgres to be ready..."
for i in {1..30}; do
    if $COMPOSE_CMD exec -T postgres pg_isready -U "${POSTGRES_USER:-vault_crawler}" -d "${POSTGRES_DB:-vault_crawler}" &>/dev/null; then
        echo "✓ Postgres is ready"
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

# Pull Ollama models if Ollama is enabled
if [ "${ENABLE_OLLAMA:-false}" = "true" ] && [ -n "${OLLAMA_MODELS:-}" ]; then
    echo "Pulling Ollama models: ${OLLAMA_MODELS}"
    
    echo "Waiting for Ollama to start..."
    for i in {1..30}; do
        if $CONTAINER_CMD exec vault-crawler-ollama curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "✓ Ollama is ready"
            break
        fi
        echo -n "."
        sleep 2
    done
    echo ""
    
    # Pull each model
    IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
    for model in "${MODELS[@]}"; do
        model=$(echo "$model" | xargs)  # Trim whitespace
        echo "Pulling model: $model"
        $CONTAINER_CMD exec vault-crawler-ollama ollama pull "$model"
    done
    
    echo "✓ All Ollama models pulled successfully"
fi

echo ""
echo "✓ Infrastructure started successfully!"
echo ""
echo "Services running:"
$COMPOSE_CMD "${PROFILES[@]+"${PROFILES[@]}"}" ps

echo ""
echo "Next steps:"
echo "  Run migrations: uv run alembic upgrade head"
echo "  Start service:  uv run python -m src.main serve"
echo "  View logs:      $COMPOSE_CMD logs -f"
echo "  Stop services:  $COMPOSE_CMD down"
