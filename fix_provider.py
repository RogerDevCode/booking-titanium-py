import re

with open('app/api/v1/provider.py', 'r') as f:
    content = f.read()

# Add Request to imports if not there
content = content.replace("from fastapi import APIRouter, HTTPException, BackgroundTasks", "from fastapi import APIRouter, HTTPException, BackgroundTasks, Request")

# Remove global imports
content = re.sub(r'from app\.db\.connection import db_client\n', '', content)
content = re.sub(r'from app\.telegram\.sender import telegram_sender\n', '', content)

# Inject container into routes
content = content.replace('async def get_dashboard(provider_id: str):', 'async def get_dashboard(provider_id: str, request: Request):\n    db_client = request.app.state.container.db_client')
content = content.replace('async def get_appointments(provider_id: str, start_date: datetime, end_date: datetime):', 'async def get_appointments(provider_id: str, start_date: datetime, end_date: datetime, request: Request):\n    db_client = request.app.state.container.db_client')
content = content.replace('async def create_exception(provider_id: str, payload: ExceptionCreate, background_tasks: BackgroundTasks):', 'async def create_exception(provider_id: str, payload: ExceptionCreate, background_tasks: BackgroundTasks, request: Request):\n    db_client = request.app.state.container.db_client\n    telegram_sender = request.app.state.container.telegram_sender')
content = content.replace('async def cancel_and_notify_users(provider_id: str, start_dt: datetime, end_dt: datetime):', 'async def cancel_and_notify_users(provider_id: str, start_dt: datetime, end_dt: datetime, db_client, telegram_sender):')

# In create_exception, it calls background_tasks.add_task(cancel_and_notify_users, ...)
# I need to pass db_client and telegram_sender to it!
content = content.replace('background_tasks.add_task(cancel_and_notify_users, provider_id, payload.start_datetime, payload.end_datetime)', 'background_tasks.add_task(cancel_and_notify_users, provider_id, payload.start_datetime, payload.end_datetime, db_client, telegram_sender)')

content = content.replace('async def update_settings(provider_id: str, payload: SettingsUpdate):', 'async def update_settings(provider_id: str, payload: SettingsUpdate, request: Request):\n    db_client = request.app.state.container.db_client')

with open('app/api/v1/provider.py', 'w') as f:
    f.write(content)
