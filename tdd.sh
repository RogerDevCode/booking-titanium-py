#!/usr/bin/env bash
# =============================================================================
# tdd.sh — Titanium Docker Down
# Detiene y elimina los contenedores del stack.
# Uso:
#   ./tdd.sh          → baja perfil DEV
#   ./tdd.sh --prod   → baja perfil PROD
#   ./tdd.sh --clean  → baja + elimina volúmenes (⚠️  borra datos de BD)
#   ./tdd.sh --all    → baja TODOS los perfiles (dev + prod)
# =============================================================================
set -euo pipefail

PROFILE="dev"
CLEAN=false
ALL=false

# ── Parse arguments ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --prod)   PROFILE="prod" ;;
    --clean)  CLEAN=true ;;
    --all)    ALL=true ;;
    --help|-h)
      echo "Uso: ./tdd.sh [--prod] [--clean] [--all]"
      echo "  (sin argumentos) → baja perfil dev"
      echo "  --prod           → baja perfil prod"
      echo "  --clean          → baja + elimina volúmenes (⚠️  BORRA BD)"
      echo "  --all            → baja todos los perfiles"
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
if ! docker compose version &>/dev/null; then
  echo "❌ Error: 'docker compose' (v2) no está disponible."
  exit 1
fi

if [ ! -f "docker-compose.yml" ]; then
  echo "❌ Error: docker-compose.yml no encontrado en $(pwd)."
  exit 1
fi

# ── Down ─────────────────────────────────────────────────────────────────────
if [ "$CLEAN" = true ]; then
  echo ""
  echo "⚠️  ADVERTENCIA: --clean eliminará los volúmenes de datos (incluida la BD)."
  read -r -p "   ¿Estás seguro? [s/N]: " confirm
  case "$confirm" in
    [sS]) echo "" ;;
    *)
      echo "Operación cancelada."
      exit 0
      ;;
  esac
fi

echo ""
if [ "$ALL" = true ]; then
  echo "🛑 Bajando TODOS los servicios (dev + prod)..."
  DOWN_CMD="docker compose --profile dev --profile prod down"
else
  echo "🛑 Bajando servicios [perfil: ${PROFILE}]..."
  DOWN_CMD="docker compose --profile ${PROFILE} down"
fi

if [ "$CLEAN" = true ]; then
  DOWN_CMD="$DOWN_CMD --volumes"
  echo "   (con eliminación de volúmenes)"
fi

$DOWN_CMD

echo ""
echo "✅ Servicios detenidos y contenedores eliminados."
if [ "$CLEAN" = true ]; then
  echo "   ⚠️  Volúmenes eliminados. La próxima vez que levantes se creará una BD vacía."
fi
echo ""
