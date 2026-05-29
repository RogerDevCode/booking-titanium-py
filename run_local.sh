#!/bin/bash
echo "================================================"
echo "🚀 INICIANDO TITANIUM BOOKING ENGINE (LOCAL) 🚀"
echo "================================================"

# Asegurar que uv está instalado
if ! command -v uv &> /dev/null; then
    echo "❌ Error: 'uv' no está instalado."
    exit 1
fi

# Variables de entorno temporales para apuntar a localhost en vez de 'db' y 'redis' de docker
export DATABASE_URL="postgresql://booking:booking@localhost:5432/booking?sslmode=disable"
export REDIS_URL="redis://localhost:6379"

echo "1. Levantando FastAPI en el puerto 8000..."
uv run uvicorn app.main:app --port 8000 &
FASTAPI_PID=$!

echo "2. Levantando ARQ Worker..."
# Asumimos que worker_settings está en app.worker.main o similar, ajusta si es necesario
uv run arq app.worker.main.WorkerSettings &
WORKER_PID=$!

echo "3. Levantando Telegram Poller (Bypass de Webhook)..."
sleep 3  # Dar tiempo a FastAPI para iniciar
uv run python scripts/telegram_poller.py &
POLLER_PID=$!

echo "================================================"
echo "✅ Todo en marcha. Puedes hablarle a tu bot en Telegram."
echo "Presiona Ctrl+C para apagar todo."
echo "================================================"

# Atrapar Ctrl+C para matar procesos hijos
trap "echo 'Apagando...'; kill $FASTAPI_PID $WORKER_PID $POLLER_PID; exit 0" SIGINT SIGTERM

wait
