import hashlib
import json

from urllib.parse import urlparse

from agent_spine.actions import amount_str


SUPPORTED_SCHEMES = ['exact', 'upto']
SUPPORTED_NETWORKS = ['eip155:84532', 'eip155:11155111']
NETWORK_CHAINS = {'eip155:84532': 'base', 'eip155:11155111': 'ethereum'}


def requirement_inspect(requirement):
    if not isinstance(requirement, dict):
        raise ValueError('x402 requirement must be an object')
    scheme = requirement.get('scheme')
    network = requirement.get('network')
    asset = requirement.get('asset')
    amount = amount_str(requirement.get('amount', '0'))
    resource = requirement.get('resource', '')
    pay_to = requirement.get('pay_to', '')
    if scheme not in SUPPORTED_SCHEMES:
        raise ValueError('unsupported x402 scheme')
    if network not in SUPPORTED_NETWORKS:
        raise ValueError('unsupported x402 network')
    if asset != 'USDC':
        raise ValueError('unsupported x402 asset')
    if urlparse(resource).scheme not in ['http', 'https']:
        raise ValueError('x402 resource must be an HTTP URL')
    if not pay_to:
        raise ValueError('x402 payment recipient is required')
    result = {
        'valid': True,
        'scheme': scheme,
        'network': network,
        'asset': asset,
        'amount': amount,
        'resource': resource,
        'pay_to': pay_to,
        'expires_at': requirement.get('expires_at'),
        'facilitator': requirement.get('facilitator'),
    }
    return result


def payment_prepare(ctx, requirement):
    inspected = requirement_inspect(requirement)
    canonical = json.dumps(inspected, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    result = {
        'requirement': inspected,
        'organization_id': ctx.principal.organization_id,
        'source_wallet_id': requirement.get('source_wallet_id', 'wallet-treasury'),
        'chain': NETWORK_CHAINS[inspected['network']],
        'idempotency_key': 'x402_%s' % digest,
        'requirement_digest': digest,
    }
    return result
