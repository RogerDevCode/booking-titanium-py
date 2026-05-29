import asyncio
import httpx
import sys
import os

# Add parent directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.logging import logger

async def poll_telegram():
    bot_token = settings.TELEGRAM_BOT_TOKEN
    
    if not bot_token or bot_token == "YOUR_TELEGRAM_TOKEN_HERE" or bot_token == "":
        logger.error("🚨 TELEGRAM_BOT_TOKEN no está configurado en .env")
        logger.error("Por favor, obtén uno de @BotFather en Telegram y ponlo en el archivo .env")
        return

    base_url = f"https://api.telegram.org/bot{bot_token}"
    
    async with httpx.AsyncClient() as client:
        # Delete any existing webhook to allow polling
        resp = await client.post(f"{base_url}/deleteWebhook")
        if not resp.json().get("ok"):
            logger.warning("No se pudo eliminar el webhook anterior. Esto podría afectar el polling.")

    logger.info("📡 Iniciando Telegram Poller local... (Bypasseando Webhook para Desarrollo)")
    logger.info("Asegúrate de tener corriendo: 1. FastAPI (uvicorn) y 2. ARQ Worker")
    
    offset = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            try:
                # getUpdates with long polling
                response = await client.get(f"{base_url}/getUpdates?offset={offset}&timeout=50")
                data = response.json()
                
                if not data.get("ok"):
                    logger.error(f"Telegram API Error: {data}")
                    await asyncio.sleep(5)
                    continue
                
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    # Forward to our local FastAPI webhook endpoint
                    try:
                        webhook_url = os.getenv("API_WEBHOOK_URL", "http://localhost:8000/api/v1/webhook")
                        logger.info(f"Reenviando update {update['update_id']} a {webhook_url}...")
                        webhook_resp = await client.post(webhook_url, json=update)
                        if webhook_resp.status_code != 200:
                            logger.error(f"FastAPI rechazó el mensaje: {webhook_resp.text}")
                    except Exception as e:
                        logger.error(f"Falla al enviar a FastAPI: {e}")
                        
            except httpx.ReadTimeout:
                continue
            except Exception as e:
                logger.error(f"Error de red haciendo polling: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(poll_telegram())
    except KeyboardInterrupt:
        logger.info("Poller detenido manualmente.")
