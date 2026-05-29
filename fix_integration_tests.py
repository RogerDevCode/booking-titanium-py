import glob

files = glob.glob('tests/integration/*.py')

for f in files:
    with open(f, 'r') as fp:
        content = fp.read()
    
    # Replace process_message import
    if 'from app.worker.tasks import process_message' in content:
        content = content.replace('from app.worker.tasks import process_message', 'from app.worker.tasks import make_process_message\nfrom app.container import build_container\nprocess_message = make_process_message(build_container())')
    
    # Replace singletons
    content = content.replace('from app.db.connection import db_client', 'from app.container import build_container\ndb_client = build_container().db_client')
    content = content.replace('from app.db.redis_client import redis_client', 'from app.container import build_container\nredis_client = build_container().redis_client')
    content = content.replace('from app.fsm.main import fsm_router', 'from app.container import build_container\nfsm_router = build_container().fsm_router')
    content = content.replace('from app.telegram.sender import telegram_sender', 'from app.container import build_container\ntelegram_sender = build_container().telegram_sender')

    with open(f, 'w') as fp:
        fp.write(content)
