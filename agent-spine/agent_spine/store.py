import json
import os
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_spine.auth import secret_hash, token_create, utc_now


SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organizations (
    organization_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS principals (
    principal_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    roles_json TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, principal_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY (principal_id) REFERENCES principals(principal_id)
);
CREATE TABLE IF NOT EXISTS api_credentials (
    credential_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    secret_salt TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (organization_id, principal_id) REFERENCES memberships(organization_id, principal_id)
);
CREATE TABLE IF NOT EXISTS browser_sessions (
    session_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    secret_salt TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (organization_id, principal_id) REFERENCES memberships(organization_id, principal_id)
);
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    profile TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, thread_id),
    FOREIGN KEY (organization_id, principal_id) REFERENCES memberships(organization_id, principal_id)
);
CREATE TABLE IF NOT EXISTS thread_messages (
    message_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (organization_id, thread_id) REFERENCES threads(organization_id, thread_id)
);
CREATE TABLE IF NOT EXISTS wallets (
    wallet_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    owner_principal_id TEXT,
    custody_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_wallet_id TEXT,
    address TEXT NOT NULL,
    chain TEXT NOT NULL,
    asset TEXT NOT NULL,
    balance TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, wallet_id),
    UNIQUE (organization_id, address, chain, asset)
);
CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    action_version INTEGER NOT NULL,
    organization_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    resource_ids_json TEXT NOT NULL,
    normalized_arguments_json TEXT NOT NULL,
    redacted_arguments_json TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    error_code TEXT,
    error_message TEXT,
    UNIQUE (organization_id, idempotency_key),
    UNIQUE (action_id, action_version)
);
CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    action_version INTEGER NOT NULL,
    action_digest TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    status TEXT NOT NULL,
    required_roles_json TEXT NOT NULL,
    required_count INTEGER NOT NULL,
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (action_id) REFERENCES actions(action_id)
);
CREATE TABLE IF NOT EXISTS approval_decisions (
    decision_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    UNIQUE (approval_id, principal_id),
    FOREIGN KEY (approval_id) REFERENCES approval_requests(approval_id)
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_reference TEXT,
    provider_status TEXT NOT NULL,
    normalized_status TEXT NOT NULL,
    amount TEXT NOT NULL,
    asset TEXT NOT NULL,
    chain TEXT NOT NULL,
    source_wallet_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    raw_safe_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (provider, provider_reference),
    FOREIGN KEY (action_id) REFERENCES actions(action_id)
);
CREATE TABLE IF NOT EXISTS idempotency_records (
    organization_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    action_digest TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (organization_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS webhook_events (
    webhook_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature_valid INTEGER NOT NULL,
    status TEXT NOT NULL,
    received_at TEXT NOT NULL,
    processed_at TEXT,
    error_message TEXT,
    UNIQUE (provider, provider_event_id),
    UNIQUE (provider, payload_hash)
);
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    provider TEXT NOT NULL,
    provider_subscription_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_subscription_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(organization_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    request_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    safe_details_json TEXT NOT NULL,
    trace_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    organization_id TEXT,
    visibility TEXT NOT NULL,
    source_name TEXT NOT NULL,
    version TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    content_hash TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    ingestion_actor_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, source_name, version)
);
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    organization_id TEXT,
    ordinal INTEGER NOT NULL,
    heading TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    provenance TEXT NOT NULL,
    expires_at TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS onboarding_applications (
    application_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    business_name TEXT NOT NULL,
    business_type TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    use_case TEXT NOT NULL,
    monthly_volume INTEGER NOT NULL,
    verification_score TEXT NOT NULL,
    risk_json TEXT NOT NULL,
    recommended_decision TEXT NOT NULL,
    status TEXT NOT NULL,
    account_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, application_id),
    UNIQUE (organization_id, action_id),
    FOREIGN KEY (organization_id, principal_id) REFERENCES memberships(organization_id, principal_id),
    FOREIGN KEY (action_id) REFERENCES actions(action_id)
);
CREATE INDEX IF NOT EXISTS idx_threads_org_principal ON threads(organization_id, principal_id);
CREATE INDEX IF NOT EXISTS idx_messages_org_thread ON thread_messages(organization_id, thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_wallets_org_status ON wallets(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_actions_org_status ON actions(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_approvals_org_status ON approval_requests(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_transactions_org_status ON transactions(organization_id, normalized_status);
CREATE INDEX IF NOT EXISTS idx_audit_org_thread ON audit_events(organization_id, thread_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_chunks_org_document ON document_chunks(organization_id, document_id);
CREATE INDEX IF NOT EXISTS idx_memories_org_principal ON memories(organization_id, principal_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_sessions_org_principal ON browser_sessions(organization_id, principal_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_onboarding_org_status ON onboarding_applications(organization_id, status);
"""


class Store:

    def __init__(self, db_path):
        if not db_path:
            raise ValueError('db_path is required')
        self.db_path = os.path.abspath(db_path)

    def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA busy_timeout = 10000')
        return conn

    def migrate(self):
        conn = self.connect()
        try:
            wallet_columns = conn.execute('PRAGMA table_info(wallets)').fetchall()
            wallet_primary_key = [row['name'] for row in wallet_columns if row['pk']]
            if wallet_columns and wallet_primary_key == ['wallet_id']:
                conn.execute('ALTER TABLE wallets RENAME TO wallets_legacy')
                conn.execute(
                    '''CREATE TABLE wallets (
                       wallet_id TEXT NOT NULL, organization_id TEXT NOT NULL,
                       owner_principal_id TEXT, custody_type TEXT NOT NULL, provider TEXT NOT NULL,
                       provider_wallet_id TEXT, address TEXT NOT NULL, chain TEXT NOT NULL,
                       asset TEXT NOT NULL, balance TEXT NOT NULL, status TEXT NOT NULL,
                       created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                       PRIMARY KEY (organization_id, wallet_id),
                       UNIQUE (organization_id, address, chain, asset))'''
                )
                conn.execute('INSERT INTO wallets SELECT * FROM wallets_legacy')
                conn.execute('DROP TABLE wallets_legacy')
            conn.executescript(SCHEMA)
            conn.execute('INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)',
                         (SCHEMA_VERSION, utc_now()))
            conn.commit()
        finally:
            conn.close()

    def organization_create(self, organization_id, name):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO organizations VALUES (?, ?, 1, ?)
                   ON CONFLICT(organization_id) DO UPDATE SET name = excluded.name, active = 1''',
                (organization_id, name, utc_now()),
            )
            conn.commit()
        finally:
            conn.close()

    def principal_create(self, principal_id, display_name):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO principals VALUES (?, ?, 1, ?)
                   ON CONFLICT(principal_id) DO UPDATE SET display_name = excluded.display_name, active = 1''',
                (principal_id, display_name, utc_now()),
            )
            conn.commit()
        finally:
            conn.close()

    def membership_create(self, organization_id, principal_id, roles, scopes):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO memberships VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(organization_id, principal_id) DO UPDATE SET
                       roles_json = excluded.roles_json, scopes_json = excluded.scopes_json, active = 1''',
                (organization_id, principal_id, json.dumps(list(roles)),
                 json.dumps(list(scopes)), utc_now()),
            )
            conn.commit()
        finally:
            conn.close()

    def credential_create(self, organization_id, principal_id, expires_at=None):
        credential_id, secret, token = token_create()
        salt, digest = secret_hash(secret)
        conn = self.connect()
        try:
            conn.execute('INSERT INTO api_credentials VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)',
                         (credential_id, organization_id, principal_id, salt, digest,
                          expires_at, utc_now()))
            conn.commit()
        finally:
            conn.close()
        return token

    def credential_get(self, credential_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT c.*, p.display_name, p.active AS principal_active,
                          m.roles_json, m.scopes_json, m.active AS membership_active
                   FROM api_credentials c
                   JOIN principals p ON p.principal_id = c.principal_id
                   JOIN memberships m ON m.organization_id = c.organization_id
                                     AND m.principal_id = c.principal_id
                   WHERE c.credential_id = ?''',
                (credential_id,),
            ).fetchone()
            return row
        finally:
            conn.close()

    def credential_touch(self, credential_id):
        conn = self.connect()
        try:
            conn.execute('UPDATE api_credentials SET last_used_at = ? WHERE credential_id = ?',
                         (utc_now(), credential_id))
            conn.commit()
        finally:
            conn.close()

    def credential_revoke(self, credential_id):
        conn = self.connect()
        try:
            conn.execute('UPDATE api_credentials SET revoked_at = ? WHERE credential_id = ?',
                         (utc_now(), credential_id))
            conn.commit()
        finally:
            conn.close()

    def credential_active_list(self, organization_id, principal_id):
        conn = self.connect()
        try:
            rows = conn.execute(
                '''SELECT credential_id, expires_at, created_at FROM api_credentials
                   WHERE organization_id = ? AND principal_id = ? AND revoked_at IS NULL
                   ORDER BY created_at''',
                (organization_id, principal_id),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def credential_revoke_all(self, organization_id, principal_id):
        conn = self.connect()
        try:
            conn.execute(
                '''UPDATE api_credentials SET revoked_at = ? WHERE organization_id = ?
                   AND principal_id = ? AND revoked_at IS NULL''',
                (utc_now(), organization_id, principal_id),
            )
            conn.commit()
        finally:
            conn.close()

    def session_create(self, organization_id, principal_id, expires_at):
        session_id, secret, token = token_create(prefix='ses')
        csrf_token = 'csrf_%s' % uuid4().hex
        salt, digest = secret_hash(secret)
        conn = self.connect()
        try:
            conn.execute('INSERT INTO browser_sessions VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)',
                         (session_id, organization_id, principal_id, salt, digest, csrf_token,
                          expires_at, utc_now()))
            conn.commit()
        finally:
            conn.close()
        return token, csrf_token

    def session_get(self, session_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT s.*, p.display_name, p.active AS principal_active,
                          m.roles_json, m.scopes_json, m.active AS membership_active
                   FROM browser_sessions s
                   JOIN principals p ON p.principal_id = s.principal_id
                   JOIN memberships m ON m.organization_id = s.organization_id
                                     AND m.principal_id = s.principal_id
                   WHERE s.session_id = ?''',
                (session_id,),
            ).fetchone()
            return row
        finally:
            conn.close()

    def session_revoke(self, session_id):
        conn = self.connect()
        try:
            conn.execute('UPDATE browser_sessions SET revoked_at = ? WHERE session_id = ?',
                         (utc_now(), session_id))
            conn.commit()
        finally:
            conn.close()

    def thread_upsert(self, organization_id, principal_id, thread_id, profile, title=''):
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO threads(thread_id, organization_id, principal_id, profile, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(organization_id, thread_id) DO UPDATE SET updated_at = excluded.updated_at''',
                (thread_id, organization_id, principal_id, profile, title, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def thread_get(self, organization_id, thread_id):
        conn = self.connect()
        try:
            row = conn.execute('SELECT * FROM threads WHERE organization_id = ? AND thread_id = ?',
                               (organization_id, thread_id)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def thread_list(self, organization_id, principal_id=None, limit=100):
        conn = self.connect()
        try:
            if principal_id:
                rows = conn.execute(
                    '''SELECT * FROM threads WHERE organization_id = ? AND principal_id = ?
                       ORDER BY updated_at DESC LIMIT ?''',
                    (organization_id, principal_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    '''SELECT * FROM threads WHERE organization_id = ?
                       ORDER BY updated_at DESC LIMIT ?''',
                    (organization_id, int(limit)),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def message_add(self, organization_id, thread_id, principal_id, role, content, run_id):
        message_id = 'msg_%s' % uuid4().hex
        conn = self.connect()
        try:
            conn.execute('INSERT INTO thread_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (message_id, organization_id, thread_id, principal_id, role,
                          content, run_id, utc_now()))
            conn.execute('UPDATE threads SET updated_at = ? WHERE organization_id = ? AND thread_id = ?',
                         (utc_now(), organization_id, thread_id))
            conn.commit()
        finally:
            conn.close()
        return message_id

    def message_list(self, organization_id, thread_id, limit=200):
        conn = self.connect()
        try:
            rows = conn.execute(
                '''SELECT * FROM thread_messages WHERE organization_id = ? AND thread_id = ?
                   ORDER BY created_at, message_id LIMIT ?''',
                (organization_id, thread_id, int(limit)),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def wallet_upsert(self, wallet):
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO wallets(wallet_id, organization_id, owner_principal_id, custody_type,
                   provider, provider_wallet_id, address, chain, asset, balance, status,
                   created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(organization_id, wallet_id) DO UPDATE SET balance = excluded.balance,
                       status = excluded.status, updated_at = excluded.updated_at''',
                (wallet['wallet_id'], wallet['organization_id'], wallet.get('owner_principal_id'),
                 wallet['custody_type'], wallet['provider'], wallet.get('provider_wallet_id'),
                 wallet['address'], wallet['chain'], wallet['asset'], str(wallet['balance']),
                 wallet.get('status', 'active'), now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def wallet_get(self, organization_id, wallet_id):
        conn = self.connect()
        try:
            row = conn.execute('SELECT * FROM wallets WHERE organization_id = ? AND wallet_id = ?',
                               (organization_id, wallet_id)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def wallet_balance_set(self, organization_id, wallet_id, balance):
        conn = self.connect()
        try:
            cursor = conn.execute(
                'UPDATE wallets SET balance = ?, updated_at = ? WHERE organization_id = ? AND wallet_id = ?',
                (str(balance), utc_now(), organization_id, wallet_id),
            )
            conn.commit()
            if cursor.rowcount != 1:
                raise ValueError('wallet not found')
        finally:
            conn.close()

    def action_insert(self, action):
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO actions(action_id, action_version, organization_id, actor_id, thread_id,
                   action_type, tool_name, provider, resource_ids_json, normalized_arguments_json,
                   redacted_arguments_json, risk_level, policy_version, action_digest, idempotency_key,
                   status, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (action['action_id'], action['action_version'], action['organization_id'], action['actor_id'],
                 action['thread_id'], action['action_type'], action['tool_name'], action['provider'],
                 json.dumps(action['resource_ids'], sort_keys=True),
                 json.dumps(action['normalized_arguments'], sort_keys=True),
                 json.dumps(action['redacted_arguments'], sort_keys=True), action['risk_level'],
                 action['policy_version'], action['action_digest'], action['idempotency_key'],
                 action['status'], now, now, action.get('expires_at')),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            existing = conn.execute(
                'SELECT * FROM actions WHERE organization_id = ? AND idempotency_key = ?',
                (action['organization_id'], action['idempotency_key']),
            ).fetchone()
            if existing is None or existing['action_digest'] != action['action_digest']:
                raise ValueError('idempotency key was already used for a different action')
        finally:
            conn.close()

    def action_get(self, organization_id, action_id):
        conn = self.connect()
        try:
            row = conn.execute('SELECT * FROM actions WHERE organization_id = ? AND action_id = ?',
                               (organization_id, action_id)).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def action_get_by_idempotency(self, organization_id, idempotency_key):
        conn = self.connect()
        try:
            row = conn.execute(
                'SELECT * FROM actions WHERE organization_id = ? AND idempotency_key = ?',
                (organization_id, idempotency_key),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def action_status(self, organization_id, action_id, old_status, new_status,
                      error_code='', error_message=''):
        conn = self.connect()
        try:
            cursor = conn.execute(
                '''UPDATE actions SET status = ?, updated_at = ?, error_code = ?, error_message = ?
                   WHERE organization_id = ? AND action_id = ? AND status = ?''',
                (new_status, utc_now(), error_code or None, error_message or None,
                 organization_id, action_id, old_status),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def action_claim(self, organization_id, action_id, action_digest):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.execute(
                '''UPDATE actions SET status = ?, updated_at = ?
                   WHERE organization_id = ? AND action_id = ? AND action_digest = ? AND status = ?''',
                ('executing', utc_now(), organization_id, action_id, action_digest, 'approved'),
            )
            conn.commit()
            return cursor.rowcount == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def action_result(self, organization_id, action_id, succeeded, error_code='', error_message=''):
        new_status = 'submitted' if succeeded else 'failed'
        changed = self.action_status(
            organization_id, action_id, 'executing', new_status,
            error_code=error_code, error_message=error_message,
        )
        return changed

    def approval_insert(self, approval):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO approval_requests(approval_id, action_id, action_version, action_digest,
                   organization_id, status, required_roles_json, required_count, requested_at,
                   expires_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (approval['approval_id'], approval['action_id'], approval['action_version'],
                 approval['action_digest'], approval['organization_id'], approval['status'],
                 json.dumps(approval['required_roles']), approval['required_count'],
                 approval['requested_at'], approval['expires_at'], approval['requested_at']),
            )
            conn.commit()
        finally:
            conn.close()

    def approval_get(self, organization_id, approval_id):
        conn = self.connect()
        try:
            row = conn.execute(
                'SELECT * FROM approval_requests WHERE organization_id = ? AND approval_id = ?',
                (organization_id, approval_id),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def approval_list(self, organization_id, status='pending'):
        conn = self.connect()
        try:
            rows = conn.execute(
                'SELECT * FROM approval_requests WHERE organization_id = ? AND status = ? ORDER BY requested_at',
                (organization_id, status),
            ).fetchall()
            return [row_decode(row) for row in rows]
        finally:
            conn.close()

    def approval_detail_list(self, organization_id, status='pending'):
        conn = self.connect()
        try:
            rows = conn.execute(
                '''SELECT r.*, a.thread_id, a.actor_id, a.action_type, a.tool_name,
                          a.redacted_arguments_json, a.risk_level, a.status AS action_status
                   FROM approval_requests r JOIN actions a ON a.action_id = r.action_id
                   WHERE r.organization_id = ? AND r.status = ? ORDER BY r.requested_at''',
                (organization_id, status),
            ).fetchall()
            return [row_decode(row) for row in rows]
        finally:
            conn.close()

    def approval_for_action(self, organization_id, action_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT * FROM approval_requests WHERE organization_id = ? AND action_id = ?
                   ORDER BY requested_at DESC LIMIT 1''',
                (organization_id, action_id),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def approval_decide(self, organization_id, approval_id, principal_id, decision,
                        reason, action_digest):
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            approval = conn.execute(
                'SELECT * FROM approval_requests WHERE organization_id = ? AND approval_id = ?',
                (organization_id, approval_id),
            ).fetchone()
            if approval is None:
                raise ValueError('approval request not found')
            if approval['status'] != 'pending':
                raise ValueError('approval request is not pending')
            if approval['action_digest'] != action_digest:
                raise ValueError('approval action digest does not match')
            if datetime.fromisoformat(approval['expires_at']) <= datetime.now(timezone.utc):
                conn.execute('UPDATE approval_requests SET status = ?, updated_at = ? WHERE approval_id = ?',
                             ('expired', now, approval_id))
                conn.commit()
                raise ValueError('approval request is expired')
            decision_id = 'dec_%s' % uuid4().hex
            conn.execute(
                'INSERT INTO approval_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (decision_id, approval_id, organization_id, principal_id, decision,
                 reason or '', action_digest, now),
            )
            status = 'approved' if decision == 'approve' else 'rejected'
            conn.execute('UPDATE approval_requests SET status = ?, updated_at = ? WHERE approval_id = ?',
                         (status, now, approval_id))
            action_status = 'approved' if status == 'approved' else 'cancelled'
            conn.execute(
                '''UPDATE actions SET status = ?, updated_at = ?
                   WHERE action_id = ? AND organization_id = ? AND action_digest = ? AND status = ?''',
                (action_status, now, approval['action_id'], organization_id, action_digest,
                 'pending_approval'),
            )
            conn.commit()
            result = {
                'decision_id': decision_id,
                'approval_id': approval_id,
                'status': status,
                'action_id': approval['action_id'],
            }
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def transaction_insert(self, transaction):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO transactions(transaction_id, organization_id, action_id, provider,
                   provider_reference, provider_status, normalized_status, amount, asset, chain,
                   source_wallet_id, destination, raw_safe_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (transaction['transaction_id'], transaction['organization_id'], transaction['action_id'],
                 transaction['provider'], transaction.get('provider_reference'),
                 transaction['provider_status'], transaction['normalized_status'],
                 transaction['amount'], transaction['asset'], transaction['chain'],
                 transaction['source_wallet_id'], transaction['destination'],
                 json.dumps(transaction.get('raw_safe', {}), sort_keys=True),
                 transaction['created_at'], transaction['updated_at']),
            )
            conn.commit()
        finally:
            conn.close()

    def transaction_get(self, organization_id, transaction_id):
        conn = self.connect()
        try:
            row = conn.execute(
                'SELECT * FROM transactions WHERE organization_id = ? AND transaction_id = ?',
                (organization_id, transaction_id),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def transaction_get_by_provider_reference(self, organization_id, provider, provider_reference):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT * FROM transactions WHERE organization_id = ? AND provider = ?
                   AND provider_reference = ?''',
                (organization_id, provider, provider_reference),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def transaction_update(self, organization_id, transaction_id, provider_status,
                           normalized_status, raw_safe=None):
        conn = self.connect()
        try:
            cursor = conn.execute(
                '''UPDATE transactions SET provider_status = ?, normalized_status = ?,
                   raw_safe_json = ?, updated_at = ?
                   WHERE organization_id = ? AND transaction_id = ?''',
                (provider_status, normalized_status, json.dumps(raw_safe or {}, sort_keys=True),
                 utc_now(), organization_id, transaction_id),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def audit_insert(self, event):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (event['event_id'], event['timestamp'], event['request_id'], event['run_id'],
                 event['thread_id'], event['organization_id'], event['principal_id'],
                 event['event_type'], event['resource_type'], event['resource_id'], event['outcome'],
                 event['reason_code'], json.dumps(event['safe_details'], sort_keys=True),
                 event['trace_id']),
            )
            conn.commit()
        finally:
            conn.close()

    def webhook_insert(self, event):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO webhook_events(webhook_id, organization_id, provider,
                   provider_event_id, payload_hash, signature_valid, status, received_at,
                   processed_at, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (event['webhook_id'], event['organization_id'], event['provider'],
                 event['provider_event_id'], event['payload_hash'],
                 1 if event['signature_valid'] else 0, event['status'], event['received_at'],
                 event.get('processed_at'), event.get('error_message')),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.rollback()
            return False
        finally:
            conn.close()

    def webhook_subscription_upsert(self, provider, provider_subscription_id,
                                    organization_id, environment='testnet'):
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO webhook_subscriptions(provider, provider_subscription_id,
                   organization_id, environment, active, created_at) VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(provider, provider_subscription_id) DO UPDATE SET
                       organization_id = excluded.organization_id,
                       environment = excluded.environment, active = 1''',
                (provider, provider_subscription_id, organization_id, environment, utc_now()),
            )
            conn.commit()
        finally:
            conn.close()

    def webhook_subscription_get(self, provider, provider_subscription_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT * FROM webhook_subscriptions WHERE provider = ?
                   AND provider_subscription_id = ? AND active = 1''',
                (provider, provider_subscription_id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def webhook_status(self, webhook_id, status, error_message=''):
        conn = self.connect()
        try:
            conn.execute(
                '''UPDATE webhook_events SET status = ?, processed_at = ?, error_message = ?
                   WHERE webhook_id = ?''',
                (status, utc_now(), error_message or None, webhook_id),
            )
            conn.commit()
        finally:
            conn.close()

    def audit_list(self, organization_id, thread_id):
        conn = self.connect()
        try:
            rows = conn.execute(
                '''SELECT * FROM audit_events WHERE organization_id = ? AND thread_id = ?
                   ORDER BY timestamp, event_id''',
                (organization_id, thread_id),
            ).fetchall()
            return [row_decode(row) for row in rows]
        finally:
            conn.close()

    def document_upsert(self, document, chunks):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(
                '''INSERT INTO documents(document_id, organization_id, visibility, source_name,
                   version, effective_from, effective_to, content_hash, sensitivity,
                   ingestion_actor_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(document_id) DO UPDATE SET
                       visibility = excluded.visibility, effective_from = excluded.effective_from,
                       effective_to = excluded.effective_to, content_hash = excluded.content_hash,
                       sensitivity = excluded.sensitivity, status = excluded.status''',
                (document['document_id'], document.get('organization_id'), document['visibility'],
                 document['source_name'], document['version'], document.get('effective_from'),
                 document.get('effective_to'), document['content_hash'], document['sensitivity'],
                 document['ingestion_actor_id'], document.get('status', 'active'), utc_now()),
            )
            conn.execute('DELETE FROM document_chunks WHERE document_id = ?', (document['document_id'],))
            for chunk in chunks:
                conn.execute(
                    '''INSERT INTO document_chunks(chunk_id, document_id, organization_id, ordinal,
                       heading, content, embedding_json) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (chunk['chunk_id'], document['document_id'], document.get('organization_id'),
                     chunk['ordinal'], chunk.get('heading', ''), chunk['content'],
                     json.dumps(chunk.get('embedding', []))),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def document_list(self, organization_id):
        conn = self.connect()
        try:
            rows = conn.execute(
                '''SELECT * FROM documents WHERE status = 'active'
                   AND (organization_id IS NULL OR organization_id = ?)
                   ORDER BY source_name, version''',
                (organization_id,),
            ).fetchall()
            return [row_decode(row) for row in rows]
        finally:
            conn.close()

    def chunk_list(self, organization_id):
        conn = self.connect()
        try:
            rows = conn.execute(
                '''SELECT c.*, d.source_name, d.version, d.visibility, d.sensitivity,
                          d.effective_from, d.effective_to
                   FROM document_chunks c JOIN documents d ON d.document_id = c.document_id
                   WHERE d.status = 'active' AND (c.organization_id IS NULL OR c.organization_id = ?)
                   ORDER BY d.source_name, c.ordinal''',
                (organization_id,),
            ).fetchall()
            return [row_decode(row) for row in rows]
        finally:
            conn.close()

    def principal_membership_get(self, organization_id, principal_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT m.*, p.display_name, p.active AS principal_active
                   FROM memberships m JOIN principals p ON p.principal_id = m.principal_id
                   WHERE m.organization_id = ? AND m.principal_id = ?''',
                (organization_id, principal_id),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def onboarding_application_insert(self, application):
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO onboarding_applications(application_id, organization_id,
                   principal_id, action_id, business_name, business_type, email, phone,
                   use_case, monthly_volume, verification_score, risk_json,
                   recommended_decision, status, account_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)''',
                (application['application_id'], application['organization_id'],
                 application['principal_id'], application['action_id'],
                 application['business_name'], application['business_type'],
                 application['email'], application['phone'], application['use_case'],
                 int(application['monthly_volume']), str(application['verification_score']),
                 json.dumps(application.get('risk', [])), application['recommended_decision'],
                 application['status'], now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def onboarding_application_get(self, organization_id, application_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT * FROM onboarding_applications WHERE organization_id = ?
                   AND application_id = ?''',
                (organization_id, application_id),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def onboarding_application_by_action(self, organization_id, action_id):
        conn = self.connect()
        try:
            row = conn.execute(
                '''SELECT * FROM onboarding_applications WHERE organization_id = ?
                   AND action_id = ?''',
                (organization_id, action_id),
            ).fetchone()
            return row_decode(row) if row else None
        finally:
            conn.close()

    def onboarding_application_finalize(self, organization_id, application_id,
                                        old_status, new_status, account_id=None):
        conn = self.connect()
        try:
            cursor = conn.execute(
                '''UPDATE onboarding_applications SET status = ?, account_id = ?, updated_at = ?
                   WHERE organization_id = ? AND application_id = ? AND status = ?''',
                (new_status, account_id, utc_now(), organization_id, application_id, old_status),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def memory_add(self, organization_id, principal_id, thread_id, memory_type,
                   content, sensitivity, provenance, expires_at=None):
        memory_id = 'mem_%s' % uuid4().hex
        conn = self.connect()
        try:
            conn.execute(
                '''INSERT INTO memories(memory_id, organization_id, principal_id, thread_id,
                   memory_type, content, sensitivity, provenance, expires_at, deleted_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)''',
                (memory_id, organization_id, principal_id, thread_id, memory_type,
                 content, sensitivity, provenance, expires_at, utc_now()),
            )
            conn.commit()
        finally:
            conn.close()
        return memory_id

    def memory_list(self, organization_id, principal_id, thread_id=None):
        now = utc_now()
        conn = self.connect()
        try:
            if thread_id:
                rows = conn.execute(
                    '''SELECT * FROM memories WHERE organization_id = ? AND principal_id = ?
                       AND thread_id = ? AND deleted_at IS NULL
                       AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at''',
                    (organization_id, principal_id, thread_id, now),
                ).fetchall()
            else:
                rows = conn.execute(
                    '''SELECT * FROM memories WHERE organization_id = ? AND principal_id = ?
                       AND deleted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
                       ORDER BY created_at''',
                    (organization_id, principal_id, now),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def memory_delete(self, organization_id, principal_id, memory_id):
        conn = self.connect()
        try:
            cursor = conn.execute(
                '''UPDATE memories SET deleted_at = ? WHERE organization_id = ?
                   AND principal_id = ? AND memory_id = ? AND deleted_at IS NULL''',
                (utc_now(), organization_id, principal_id, memory_id),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()


def row_decode(row):
    data = dict(row)
    for key in list(data.keys()):
        if key.endswith('_json'):
            plain_key = key[:-5]
            data[plain_key] = json.loads(data[key] or 'null')
    return data
