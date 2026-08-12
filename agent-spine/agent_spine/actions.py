import hashlib
import json

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from agent_spine.auth import utc_now


SECRET_KEYS = [
    'api_key', 'authorization', 'credential', 'password', 'private_key', 'secret', 'token',
    'email', 'phone', 'ssn', 'tax_id', 'date_of_birth',
]


def amount_str(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('amount must be a decimal number')
    if not amount.is_finite():
        raise ValueError('amount must be finite')
    normalized = format(amount.normalize(), 'f')
    if '.' in normalized:
        normalized = normalized.rstrip('0').rstrip('.')
    return normalized or '0'


def value_normalize(value):
    if isinstance(value, dict):
        data = {}
        keys = sorted(value.keys())
        for key in keys:
            data[str(key)] = value_normalize(value[key])
        return data
    if isinstance(value, list):
        return [value_normalize(item) for item in value]
    if isinstance(value, Decimal):
        return amount_str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def value_redact(value):
    if isinstance(value, dict):
        data = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            secret = False
            for secret_key in SECRET_KEYS:
                if secret_key in key_lower:
                    secret = True
                    break
            data[key] = '[REDACTED]' if secret else value_redact(item)
        return data
    if isinstance(value, list):
        return [value_redact(item) for item in value]
    return value


def action_digest(data):
    payload = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def action_make(ctx, action_type, tool_name, provider, resource_ids, arguments,
                risk_level, policy_version, idempotency_key=None, expires_minutes=30):
    normalized_arguments = value_normalize(arguments)
    resource_ids = value_normalize(resource_ids or {})
    digest_data = {
        'organization_id': ctx.principal.organization_id,
        'actor_id': ctx.principal.principal_id,
        'action_type': action_type,
        'tool_name': tool_name,
        'provider': provider,
        'resource_ids': resource_ids,
        'normalized_arguments': normalized_arguments,
        'policy_version': policy_version,
        'profile': ctx.profile,
    }
    digest = action_digest(digest_data)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    action = {
        'action_id': 'act_%s' % uuid4().hex,
        'action_version': 1,
        'organization_id': ctx.principal.organization_id,
        'actor_id': ctx.principal.principal_id,
        'thread_id': ctx.thread_id,
        'action_type': action_type,
        'tool_name': tool_name,
        'provider': provider,
        'resource_ids': resource_ids,
        'normalized_arguments': normalized_arguments,
        'redacted_arguments': value_redact(normalized_arguments),
        'risk_level': risk_level,
        'policy_version': policy_version,
        'action_digest': digest,
        'idempotency_key': idempotency_key or 'idem_%s' % uuid4().hex,
        'status': 'proposed',
        'created_at': utc_now(),
        'expires_at': expires_at.isoformat(),
    }
    return action
