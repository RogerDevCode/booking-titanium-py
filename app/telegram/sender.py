import httpx
import json
from typing import Optional, List, Dict, Any
from app.core.logging import logger
from app.domain.protocols import DatabaseClientProtocol

from app.telegram.callback import encode

class TelegramSender:
    def __init__(self, db: DatabaseClientProtocol, token: str) -> None:
        self._db = db
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        """
        Instead of sending via HTTP immediately, we queue the message in the outbox table.
        This respects the current DB transaction. If the transaction rolls back, 
        the message is never sent.
        """
        query = """
            INSERT INTO outbox_messages (chat_id, text, reply_markup, status)
            VALUES ($1, $2, $3, 'PENDING')
        """
        rm_json = json.dumps(reply_markup) if reply_markup else None
        await self._db.execute(query, chat_id, text, rm_json)

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        """
        We still execute this immediately (non-transactional) because we want 
        buttons to disappear instantly to prevent double clicks, and it doesn't 
        affect business state consistency.
        """
        url = f"{self.base_url}/editMessageReplyMarkup"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup or {"inline_keyboard": []}
        }
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json=payload, timeout=5.0)
            except Exception as e:
                logger.warning("Failed to edit message markup", error=str(e))

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None, show_alert: bool = False) -> None:
        """
        Answers a callback query to stop the loading indicator on the client.
        Optionally shows a toast notification or alert box.
        """
        url = f"{self.base_url}/answerCallbackQuery"
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
            
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json=payload, timeout=5.0)
            except Exception as e:
                logger.warning("Failed to answer callback query", error=str(e))

    async def send_document(self, chat_id: int, document: bytes, filename: str, caption: Optional[str] = None) -> None:
        """Sends a document using multipart/form-data."""
        url = f"{self.base_url}/sendDocument"
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        files = {"document": (filename, document, "application/pdf")}
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, data=data, files=files, timeout=30.0)
            except Exception as e:
                logger.error("Failed to send document", error=str(e), chat_id=chat_id)

    async def flush_outbox(self, chat_id: int) -> None:
        """
        Reads PENDING messages from the outbox for a specific chat_id and sends them.
        Should be called AFTER the main DB transaction has committed.
        """
        # We don't want this in the main transaction, so we use a separate fetch
        query = "SELECT id, text, reply_markup FROM outbox_messages WHERE chat_id = $1 AND status = 'PENDING' ORDER BY id ASC"
        
        # It's safe to fetch outside a transaction block
        messages = await self._db.fetch(query, chat_id)
        if not messages:
            return

        async with httpx.AsyncClient() as client:
            for msg_row in messages:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": msg_row["text"],
                    "parse_mode": "Markdown",
                }
                
                rm_str = msg_row["reply_markup"]
                if rm_str:
                    payload["reply_markup"] = json.loads(rm_str)

                try:
                    response = await client.post(url, json=payload, timeout=10.0)
                    response.raise_for_status()
                    # Mark as sent
                    await self._db.execute("UPDATE outbox_messages SET status = 'SENT' WHERE id = $1", msg_row["id"])
                    
                    # Log to conversations table
                    provider_id = None
                    try:
                        state_row = await self._db.fetchrow(
                            "SELECT context, booking_draft FROM conversation_states WHERE chat_id = $1",
                            chat_id
                        )
                        if state_row:
                            ctx_data = state_row["context"] or {}
                            draft_data = state_row["booking_draft"] or {}
                            if isinstance(ctx_data, str):
                                ctx_data = json.loads(ctx_data)
                            if isinstance(draft_data, str):
                                draft_data = json.loads(draft_data)
                            
                            raw_p_id = draft_data.get("provider_id") or ctx_data.get("provider_id")
                            if raw_p_id:
                                try:
                                    from uuid import UUID
                                    UUID(str(raw_p_id))
                                    provider_id = str(raw_p_id)
                                except ValueError:
                                    provider_id = None
                    except Exception as select_err:
                        logger.warning("Failed to extract provider_id for outbound log", error=str(select_err), chat_id=chat_id)

                    try:
                        await self._db.execute(
                            """
                            INSERT INTO conversations (
                                client_id, direction, content, metadata, provider_id
                            ) VALUES ($1, 'outbound', $2, $3::jsonb, $4::uuid)
                            """,
                            chat_id,
                            msg_row["text"],
                            json.dumps({"reply_markup": json.loads(rm_str) if rm_str else None}),
                            provider_id
                        )
                    except Exception as log_err:
                        logger.warning("Failed to log outbound conversation message", error=str(log_err), chat_id=chat_id)

                    # Update conversation_states with the message_id of the active menu if it has reply_markup
                    res_json = response.json()
                    if res_json.get("ok") and rm_str:
                        sent_msg = res_json.get("result", {})
                        sent_msg_id = sent_msg.get("message_id")
                        if sent_msg_id:
                            await self._db.execute(
                                "UPDATE conversation_states SET message_id = $1 WHERE chat_id = $2",
                                sent_msg_id, chat_id
                            )
                except Exception as e:
                    logger.error("Failed to flush Telegram message", error=str(e), chat_id=chat_id)
                    # We break to preserve order for next flush attempt
                    break

    @staticmethod
    def build_inline_keyboard(options: List[str], version: int, include_nav: bool = False) -> Dict[str, Any]:
        """Helper to build a numbered inline keyboard."""
        keyboard = []
        for i, opt in enumerate(options, 1):
            keyboard.append([{"text": f"{i}️⃣ {opt}", "callback_data": encode(version, "select", str(i))}])
        
        if include_nav:
            keyboard.append([
                {"text": "🏠", "callback_data": encode(version, "nav", "home")},
                {"text": "🔙", "callback_data": encode(version, "nav", "back")},
                {"text": "❌", "callback_data": encode(version, "nav", "cancel")}
            ])
            
        return {"inline_keyboard": keyboard}

    @staticmethod
    def build_paginated_keyboard(options: List[str], version: int, start_idx: int, page: int, total_pages: int, include_nav: bool = False) -> Dict[str, Any]:
        """Helper to build a numbered inline keyboard with pagination controls."""
        keyboard = []
        for i, opt in enumerate(options, start_idx + 1):
            keyboard.append([{"text": f"{i}️⃣ {opt}", "callback_data": encode(version, "select", str(i))}])
        
        nav_row = []
        if page > 0:
            nav_row.append({"text": "⬅️ Anterior", "callback_data": encode(version, "nav", "page_prev")})
        if page < total_pages - 1:
            nav_row.append({"text": "Siguiente ➡️", "callback_data": encode(version, "nav", "page_next")})
            
        if nav_row:
            keyboard.append(nav_row)
            
        if include_nav:
            keyboard.append([
                {"text": "🏠", "callback_data": encode(version, "nav", "home")},
                {"text": "🔙", "callback_data": encode(version, "nav", "back")},
                {"text": "❌", "callback_data": encode(version, "nav", "cancel")}
            ])
            
        return {"inline_keyboard": keyboard}

