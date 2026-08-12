import base64
import hashlib
import json
import os
import time

from uuid import uuid4

import requests

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from agent_spine.auth import utc_now

from circle_agent.circle_provider import STATUS_MAP


rest_client = requests.Session()


class CircleWebhookVerifier:

    def __init__(self, api_key='', base_url='https://api.circle.com', key_resolver=None):
        self.api_key = api_key or os.environ.get('CIRCLE_API_KEY', '')
        self.base_url = base_url.rstrip('/')
        self.key_resolver = key_resolver
        self.keys = {}

    def public_key_get(self, key_id):
        cached = self.keys.get(key_id)
        if cached and cached['expires_at'] > time.time():
            return cached['value']
        if self.key_resolver:
            value = self.key_resolver(key_id)
        else:
            if not self.api_key:
                raise ValueError('CIRCLE_API_KEY is required for webhook verification')
            url = '%s/v2/notifications/publicKey/%s' % (self.base_url, key_id)
            response = rest_client.get(
                url, headers={'Authorization': 'Bearer %s' % self.api_key}, timeout=15,
            )
            if response.status_code != 200:
                raise ConnectionError('Circle public key lookup failed status=%s' % response.status_code)
            payload = response.json()
            data = payload.get('data') or {}
            if data.get('algorithm') != 'ECDSA_SHA_256':
                raise ValueError('unsupported Circle webhook signature algorithm')
            value = data.get('publicKey', '')
        self.keys[key_id] = {'value': value, 'expires_at': time.time() + 3600}
        return value

    def verify(self, body, signature_text, key_id):
        if not signature_text or not key_id:
            return False
        public_key_der = base64.b64decode(self.public_key_get(key_id))
        signature = base64.b64decode(signature_text)
        public_key = serialization.load_der_public_key(public_key_der)
        try:
            public_key.verify(signature, body, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False


def webhook_process(store, body, signature, key_id, verifier):
    if not verifier.verify(body, signature, key_id):
        raise ValueError('Circle webhook signature is invalid')
    payload = json.loads(body.decode('utf-8'))
    event_id = str(payload.get('notificationId') or '')
    if not event_id:
        raise ValueError('Circle notificationId is required')
    subscription_id = str(payload.get('subscriptionId') or '')
    subscription = store.webhook_subscription_get('circle', subscription_id)
    if subscription is None:
        raise ValueError('Circle webhook subscription is not mapped to an organization')
    organization_id = subscription['organization_id']
    payload_hash = hashlib.sha256(body).hexdigest()
    webhook_id = 'wh_%s' % uuid4().hex
    event = {
        'webhook_id': webhook_id,
        'organization_id': organization_id,
        'provider': 'circle-testnet',
        'provider_event_id': event_id,
        'payload_hash': payload_hash,
        'signature_valid': True,
        'status': 'received',
        'received_at': utc_now(),
    }
    inserted = store.webhook_insert(event)
    if not inserted:
        return {'status': 'duplicate', 'notification_id': event_id}
    notification = payload.get('notification') or {}
    provider_reference = notification.get('id') or notification.get('transactionId')
    if provider_reference:
        transaction = store.transaction_get_by_provider_reference(
            organization_id, 'circle-testnet', provider_reference,
        )
        if transaction:
            provider_status = str(notification.get('state') or transaction['provider_status']).upper()
            normalized = STATUS_MAP.get(provider_status, 'pending')
            store.transaction_update(
                organization_id, transaction['transaction_id'], provider_status, normalized,
                raw_safe={'state': provider_status, 'notification_id': event_id},
            )
    store.webhook_status(webhook_id, 'processed')
    return {'status': 'processed', 'notification_id': event_id}
