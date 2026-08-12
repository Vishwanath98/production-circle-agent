import os
import sqlite3
import threading
import time

from langgraph.checkpoint.memory import MemorySaver

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:
    SqliteSaver = None


SAVERS = {}
LOCK = threading.Lock()


def get_checkpointer(db_path=None, ephemeral=False):
    if ephemeral:
        return MemorySaver()
    if not db_path:
        raise ValueError('durable db_path is required unless ephemeral=True')
    if SqliteSaver is None:
        raise RuntimeError('langgraph-checkpoint-sqlite is required for durable persistence')

    db_path = os.path.abspath(db_path)
    with LOCK:
        if db_path not in SAVERS:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute('PRAGMA busy_timeout = 10000')
            saver = SqliteSaver(conn)
            saver.setup()
            SAVERS[db_path] = saver
        checkpointer = SAVERS[db_path]
    return checkpointer


def make_config(thread_id=None):
    thread_id = thread_id or 'auto-%s' % int(time.time() * 1000)
    config = {'configurable': {'thread_id': thread_id}}
    return config


def merge_config(base, thread_id):
    base = dict(base) if base else {}
    configurable = dict(base.get('configurable') or {})
    if 'thread_id' not in configurable:
        configurable['thread_id'] = thread_id or 'auto-%s' % int(time.time() * 1000)
    base['configurable'] = configurable
    return base


def replay_from(agent, thread_id, override_state=None, new_thread_id=None):
    config = make_config(thread_id)
    snapshot = agent.get_state(config)
    if not snapshot.values:
        raise ValueError('no prior state for thread_id=%r' % thread_id)
    merged = dict(snapshot.values)
    if override_state:
        merged.update(override_state)
    sibling = new_thread_id or '%s::replay::%s' % (thread_id, int(time.time()))
    result = agent.invoke(merged, config=make_config(sibling))
    return result


def resume_from(agent, thread_id, override_state=None, new_thread_id=None):
    return replay_from(agent, thread_id, override_state, new_thread_id)


def default_db_path(agent_dir):
    configured = os.environ.get('CHECKPOINT_DB')
    if configured:
        return configured
    repo_root = os.path.abspath(os.path.join(agent_dir, '..'))
    agent_name = os.path.basename(os.path.abspath(agent_dir))
    filename = '%s-checkpoints.sqlite' % agent_name
    return os.path.join(repo_root, '.local', 'data', filename)
