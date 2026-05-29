import glob

files = glob.glob('tests/unit/*.py')

for f in files:
    with open(f, 'r') as fp:
        content = fp.read()
    
    # Replace singletons
    content = content.replace('from app.db.connection import db_client', 'from app.container import build_container\ndb_client = build_container().db_client')
    content = content.replace('from app.db.redis_client import redis_client', 'from app.container import build_container\nredis_client = build_container().redis_client')
    content = content.replace('from app.fsm.main import fsm_router', 'from app.container import build_container\nfsm_router = build_container().fsm_router')
    content = content.replace('from app.telegram.sender import telegram_sender', 'from app.container import build_container\ntelegram_sender = build_container().telegram_sender')
    content = content.replace('from app.fsm.main import idle_handler', 'from app.fsm.main import idle_handler') # wait idle_handler is completely gone
    
    # Actually idle_handler doesn't exist anymore. 
    # It's better to just leave it and let mypy complain so I can fix it manually.
    
    with open(f, 'w') as fp:
        fp.write(content)
