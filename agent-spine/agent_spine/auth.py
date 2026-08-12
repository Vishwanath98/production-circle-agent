import base64
import hashlib
import hmac
import json
import secrets

from datetime import datetime, timezone


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


class Principal:

    def __init__(self, principal_id, organization_id, display_name, roles, scopes,
                 auth_method='dev_token', credential_id='', authenticated_at=''):
        self.principal_id = str(principal_id)
        self.organization_id = str(organization_id)
        self.display_name = display_name or ''
        self.roles = list(roles or [])
        self.scopes = list(scopes or [])
        self.auth_method = auth_method
        self.credential_id = credential_id or ''
        self.authenticated_at = authenticated_at or utc_now()

    def has_role(self, role):
        return role in self.roles or 'admin' in self.roles

    def has_scope(self, scope):
        return '*' in self.scopes or scope in self.scopes

    def to_dict(self):
        data = {
            'principal_id': self.principal_id,
            'organization_id': self.organization_id,
            'display_name': self.display_name,
            'roles': list(self.roles),
            'scopes': list(self.scopes),
            'auth_method': self.auth_method,
            'credential_id': self.credential_id,
            'authenticated_at': self.authenticated_at,
        }
        return data


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def token_create(credential_id=None, prefix='dev'):
    credential_id = credential_id or secrets.token_hex(12)
    secret = secrets.token_urlsafe(32)
    token = '%s_%s.%s' % (prefix, credential_id, secret)
    return credential_id, secret, token


def token_parse(token):
    if not token or not token.startswith('dev_') or '.' not in token:
        raise AuthenticationError('invalid development credential')
    prefix, secret = token.split('.', 1)
    credential_id = prefix[4:]
    if not credential_id or not secret:
        raise AuthenticationError('invalid development credential')
    return credential_id, secret


def secret_hash(secret, salt=None):
    salt_bytes = base64.b64decode(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.scrypt(secret.encode('utf-8'), salt=salt_bytes, n=16384, r=8, p=1, dklen=32)
    salt_text = base64.b64encode(salt_bytes).decode('ascii')
    digest_text = base64.b64encode(digest).decode('ascii')
    return salt_text, digest_text


def secret_verify(secret, salt, expected_hash):
    unused_salt, actual_hash = secret_hash(secret, salt=salt)
    return hmac.compare_digest(actual_hash, expected_hash)


def principal_from_row(row):
    roles = json.loads(row['roles_json'] or '[]')
    scopes = json.loads(row['scopes_json'] or '[]')
    principal = Principal(
        principal_id=row['principal_id'],
        organization_id=row['organization_id'],
        display_name=row['display_name'],
        roles=roles,
        scopes=scopes,
        credential_id=row['credential_id'],
    )
    return principal


def resolve_principal(store, token):
    credential_id, secret = token_parse(token)
    row = store.credential_get(credential_id)
    if row is None:
        raise AuthenticationError('invalid development credential')
    if row['revoked_at']:
        raise AuthenticationError('development credential is revoked')
    if not row['principal_active'] or not row['membership_active']:
        raise AuthenticationError('principal is inactive')
    if row['expires_at']:
        expires_at = datetime.fromisoformat(row['expires_at'])
        if expires_at <= datetime.now(timezone.utc):
            raise AuthenticationError('development credential is expired')
    if not secret_verify(secret, row['secret_salt'], row['secret_hash']):
        raise AuthenticationError('invalid development credential')

    store.credential_touch(credential_id)
    principal = principal_from_row(row)
    return principal


def resolve_session(store, token):
    if not token or not token.startswith('ses_') or '.' not in token:
        raise AuthenticationError('invalid browser session')
    prefix, secret = token.split('.', 1)
    session_id = prefix[4:]
    row = store.session_get(session_id)
    if row is None or row['revoked_at']:
        raise AuthenticationError('invalid browser session')
    if not row['principal_active'] or not row['membership_active']:
        raise AuthenticationError('principal is inactive')
    if datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
        raise AuthenticationError('browser session is expired')
    if not secret_verify(secret, row['secret_salt'], row['secret_hash']):
        raise AuthenticationError('invalid browser session')
    data = dict(row)
    data['credential_id'] = session_id
    principal = principal_from_row(data)
    principal.auth_method = 'browser_session'
    return principal, row['csrf_token']


def require_scope(principal, scope):
    if not principal.has_scope(scope):
        raise AuthorizationError('scope %s is required' % scope)
    return True


def require_organization(principal, organization_id):
    if principal.organization_id != str(organization_id):
        raise AuthorizationError('resource is outside the authenticated organization')
    return True
