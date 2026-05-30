#!/usr/bin/env bash
# =============================================================================
# scripts/commit-and-push.sh
# Automatización de Git con validación de calidad y protección de historial.
# =============================================================================

set -euo pipefail
export PYTHONPATH=.

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────
EXPECTED_REMOTE="git@github.com:RogerDevCode/booking-titanium-py.git"
BRANCH="main"

# ── FUNCIONES DE AYUDA ───────────────────────────────────────────────────────
error_exit() {
    echo -e "\n❌ ERROR: $1" >&2
    exit 1
}

log_info() {
    echo -e "\n🔵 $1"
}

# ── 1. VALIDACIÓN DE REMOTE ──────────────────────────────────────────────────
log_info "Verificando configuración de Git..."

if ! git remote get-url origin &>/dev/null; then
    echo "Añadiendo remote origin..."
    git remote add origin "$EXPECTED_REMOTE"
else
    CURRENT_URL=$(git remote get-url origin)
    if [[ "$CURRENT_URL" != "$EXPECTED_REMOTE" ]]; then
        echo "Cambiando remote origin de $CURRENT_URL a $EXPECTED_REMOTE..."
        git remote set-url origin "$EXPECTED_REMOTE"
    fi
fi

# ── 2. PRE-COMMIT CHECKS (FAIL FAST) ─────────────────────────────────────────
log_info "Ejecutando controles de calidad (Ruff, Mypy, Pyright, Pytest)..."

# Definir rutas de herramientas (priorizar .venv)
RUFF="./.venv/bin/ruff"
MYPY="./.venv/bin/mypy"
PYRIGHT="./.venv/bin/pyright"
PYTEST="./.venv/bin/pytest"

# Ruff (Linting & Formatting)
if [[ -f "$RUFF" ]]; then
    echo "  → Ruff check..."
    "$RUFF" check . || error_exit "Ruff detectó errores."
elif command -v ruff &>/dev/null; then
    echo "  → Ruff check (global)..."
    ruff check . || error_exit "Ruff detectó errores."
else
    echo "  ⚠️ Ruff no encontrado, saltando..."
fi

# Mypy (Static Typing)
if [[ -f "$MYPY" ]]; then
    echo "  → Mypy check..."
    "$MYPY" . || error_exit "Mypy detectó errores de tipos."
elif command -v mypy &>/dev/null; then
    echo "  → Mypy check (global)..."
    mypy . || error_exit "Mypy detectó errores de tipos."
else
    echo "  ⚠️ Mypy no encontrado, saltando..."
fi

# Pyright
if [[ -f "$PYRIGHT" ]]; then
    echo "  → Pyright check..."
    "$PYRIGHT" || error_exit "Pyright detectó errores."
elif command -v pyright &>/dev/null; then
    echo "  → Pyright check (global)..."
    pyright || error_exit "Pyright detectó errores."
else
    echo "  ⚠️ Pyright no encontrado, saltando..."
fi

# Pytest (Unit Tests)
if [[ -f "$PYTEST" ]]; then
    echo "  → Running Pytest..."
    "$PYTEST" || error_exit "Pytest falló. Corrige los tests antes de subir."
elif command -v pytest &>/dev/null; then
    echo "  → Running Pytest (global)..."
    pytest || error_exit "Pytest falló."
else
    echo "  ⚠️ Pytest no encontrado, saltando..."
fi

# ── 3. MANEJO DE MENSAJE DE COMMIT ───────────────────────────────────────────
COMMIT_MSG="${1:-}"

if [[ -z "$COMMIT_MSG" ]]; then
    echo -n "📝 Introduce mensaje para el commit: "
    read -r COMMIT_MSG
fi

if [[ -z "$COMMIT_MSG" ]]; then
    COMMIT_MSG="Auto-commit: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  ⚠️ Mensaje vacío, usando: $COMMIT_MSG"
fi

# ── 4. STAGING Y COMMIT ──────────────────────────────────────────────────────
log_info "Preparando cambios..."

# Importante: .gitignore ya excluye tests/ y logs.
git add .

# Verificar si hay cambios antes de seguir
if git diff --cached --quiet; then
    # Verificar si hay commits locales no pusheados
    if [[ -z "$(git log origin/$BRANCH..HEAD 2>/dev/null)" ]]; then
        error_exit "No hay cambios para committear ni commits pendientes de push."
    else
        echo "  ℹ️ Nada nuevo que añadir, procediendo con push de commits previos..."
    fi
else
    echo "💾 Creando commit..."
    git commit -m "$COMMIT_MSG" || error_exit "Fallo al crear el commit."
fi

# ── 5. PUSH CON SEGURIDAD ────────────────────────────────────────────────────
log_info "Sincronizando con remoto y subiendo a GitHub ($BRANCH)..."

# Actualizar info del remoto para evitar "stale info"
git fetch origin "$BRANCH"

# Intentar push con --force-with-lease
if ! git push origin "$BRANCH" --force-with-lease; then
    echo -e "\n⚠️ El push fue rechazado por seguridad (--force-with-lease)."
    echo "Esto sucede si alguien más subió cambios al remoto."
    echo "Para resolverlo de forma segura:"
    echo "  1. git pull --rebase origin $BRANCH"
    echo "  2. Ejecuta este script de nuevo."
    error_exit "Push abortado para proteger cambios remotos."
fi

log_info "✨ PROCESO COMPLETADO CON ÉXITO ✨"
