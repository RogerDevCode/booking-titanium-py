#!/usr/bin/env bash
# =============================================================================
# trs — Titanium Restart Services
# Reinicia el stack completo (down + up --build).
# Basado en tdu.sh.
# Uso:
#   ./scripts/trs          → Reinicia perfil DEV
#   ./scripts/trs --prod   → Reinicia perfil PROD
# =============================================================================
set -euo pipefail

PROFILE="dev"

# ── Parse arguments ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --prod)   PROFILE="prod" ;;
    --help|-h)
      echo "Uso: $0 [--prod]"
      echo "  (sin argumentos) → reinicia perfil dev"
      echo "  --prod           → reinicia perfil prod"
      exit 0
      ;;
    *)
      echo "❌ Argumento desconocido: $arg"
      exit 1
      ;;
  esac
done

echo "🔄 Reiniciando Titanium [perfil: ${PROFILE}]..."

# Usar docker compose down para limpiar y luego up para reconstruir
docker compose --profile "$PROFILE" down
sleep 1
docker compose --profile "$PROFILE" up --build -d

echo ""
echo "✅ Stack reiniciado. Estado:"
docker compose --profile "$PROFILE" ps
