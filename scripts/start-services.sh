#!/usr/bin/env bash
set -euo pipefail

# Docker Compose startup script with environment-driven profiles

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

# Build compose command with conditional profiles
COMPOSE_CMD="docker compose"
PROFILES=()

# Add Redis profile if enabled
if [ "${ENABLE_REDIS:-false}" = "true" ]; then
    echo "✓ Redis enabled"
    PROFILES+=("--profile" "redis")
else
    echo "✗ Redis disabled"
fi

# Add Ollama profile if enabled
if [ "${ENABLE_OLLAMA:-false}" = "true" ]; then
    echo "✓ Ollama enabled"
    PROFILES+=("--profile" "ollama")
else
    echo "✗ Ollama disabled"
fi

# Start services
echo ""
echo "Starting vault-crawler infrastructure..."
$COMPOSE_CMD "${PROFILES[@]}" up -d "$@"

# Wait for services to be healthy
echo ""
echo "Waiting for services to be ready..."
$COMPOSE_CMD "${PROFILES[@]}" ps

# Pull Ollama models if Ollama is enabled
if [ "${ENABLE_OLLAMA:-false}" = "true" ] && [ -n "${OLLAMA_MODELS:-}" ]; then
    echo ""
    echo "Pulling Ollama models: ${OLLAMA_MODELS}"
    
    # Wait for Ollama to be fully ready
    echo "Waiting for Ollama to start..."
    for i in {1..30}; do
        if docker exec vault-crawler-ollama curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "Ollama is ready!"
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
        docker exec vault-crawler-ollama ollama pull "$model"
    done
    
    echo "✓ All Ollama models pulled successfully"
fi

echo ""
echo "✓ Infrastructure started successfully!"
echo ""
echo "Services running:"
$COMPOSE_CMD "${PROFILES[@]}" ps

echo ""
echo "To view logs: docker compose logs -f"
echo "To stop: docker compose down"
