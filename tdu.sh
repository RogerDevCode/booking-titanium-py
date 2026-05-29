#!/usr/bin/env bash
# =============================================================================
# tdu.sh — Titanium Docker Up
# Levanta el stack completo con auto-build y watch de cambios.
# Uso:
#   ./tdu.sh          → perfil DEV (hot-reload, volúmenes de código)
#   ./tdu.sh --prod   → perfil PROD (multi-worker, imagen sellada)
#   ./tdu.sh --watch  → DEV con `docker compose watch` (auto-sync/rebuild)
# =============================================================================
set -euo pipefail

PROFILE="dev"
WATCH=false

# ── Parse arguments ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --prod)   PROFILE="prod" ;;
    --watch)  WATCH=true ;;
    --help|-h)
      echo "Uso: ./tdu.sh [--prod] [--watch]"
      echo "  (sin argumentos) → perfil dev con hot-reload"
      echo "  --prod           → perfil prod con 4 workers"
      echo "  --watch          → activa docker compose watch (auto-rebuild/sync)"
      exit 0
      ;;
    *)
      echo "❌ Argumento desconocido: $arg"
      echo "Usa --help para ver las opciones."
      exit 1
      ;;
  esac
done

# ── Preflight checks ─────────────────────────────────────────────────────────
echo ""
echo "🔍 Verificando requisitos previos..."

# Verificar Docker v2 (plugin, no el wrapper v1 deprecado)
if ! docker compose version &>/dev/null; then
  echo "❌ Error: 'docker compose' (v2) no está disponible."
  echo "   Instala Docker Desktop >= 20.10 o el plugin 'docker-compose-plugin'."
  echo "   https://docs.docker.com/compose/install/"
  exit 1
fi

DOCKER_COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "desconocida")
echo "   ✅ docker compose v${DOCKER_COMPOSE_VERSION} detectado"

# Verificar que .env existe
if [ ! -f ".env" ]; then
  echo "❌ Error: archivo '.env' no encontrado en $(pwd)."
  echo "   Copia .env.example a .env y rellena las variables antes de continuar."
  exit 1
fi
echo "   ✅ .env encontrado"

# Verificar que docker-compose.yml existe
if [ ! -f "docker-compose.yml" ]; then
  echo "❌ Error: docker-compose.yml no encontrado en $(pwd)."
  exit 1
fi
echo "   ✅ docker-compose.yml encontrado"

# Verificar que Docker daemon está corriendo
if ! docker info &>/dev/null; then
  echo "❌ Error: el daemon de Docker no está corriendo."
  echo "   Inicia Docker Desktop o ejecuta: sudo systemctl start docker"
  exit 1
fi
echo "   ✅ Docker daemon activo"

# ── Build y arranque ─────────────────────────────────────────────────────────
echo ""
echo "🚀 Levantando Titanium Booking Engine [perfil: ${PROFILE}]..."
echo ""

if [ "$WATCH" = true ]; then
  # docker compose watch hace build + sync/rebuild automático
  echo "👁️  Modo watch activo — cambios en ./app se sincronizarán automáticamente."
  echo "     Cambios en pyproject.toml o uv.lock dispararán rebuild completo."
  echo ""
  docker compose --profile "$PROFILE" up --build -d
  docker compose --profile "$PROFILE" watch
else
  # --build garantiza que cualquier cambio al Dockerfile o dependencias se refleje
  docker compose --profile "$PROFILE" up --build -d
fi

# ── Estado post-arranque ─────────────────────────────────────────────────────
echo ""
echo "✅ Stack levantado. Estado de servicios:"
echo ""
docker compose --profile "$PROFILE" ps

echo ""
echo "📋 Comandos útiles:"
if [ "$PROFILE" = "dev" ]; then
  echo "   Ver logs en vivo:  docker compose --profile dev logs -f api worker poller"
  echo "   Detener todo:      ./tdd.sh"
  echo "   Watch (auto-sync): ./tdu.sh --watch"
else
  echo "   Ver logs en vivo:  docker compose --profile prod logs -f api-prod worker-prod poller-prod"
  echo "   Detener todo:      ./tdd.sh --prod"
fi
echo ""
