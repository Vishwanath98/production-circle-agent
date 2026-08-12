import hashlib
import os

from decimal import Decimal
from uuid import UUID, uuid4

from agent_spine.auth import utc_now

from circle_agent.provider import CircleProvider


STATUS_MAP = {
    'INITIATED': 'pending',
    'PENDING_RISK_SCREENING': 'pending',
    'DENIED': 'denied',
    'QUEUED': 'submitted',
    'SENT': 'submitted',
    'CONFIRMED': 'confirmed',
    'COMPLETE': 'confirmed',
    'FAILED': 'failed',
    'CANCELLED': 'cancelled',
}


def uuid_v4_for_key(value):
    digest = hashlib.sha256(value.encode('utf-8')).digest()[:16]
    return str(UUID(bytes=digest, version=4))


def model_dict(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(by_alias=True, mode='json')
    if isinstance(value, dict):
        return dict(value)
    raise ValueError('Circle SDK returned an unsupported response')


class CircleSdkGateway:

    def __init__(self, api_key, entity_secret, host=''):
        if not api_key or not entity_secret:
            raise ValueError('CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET are required for testnet')
        if not api_key.upper().startswith('TEST'):
            raise ValueError('Circle lab requires a TEST-prefixed API key')
        from circle.web3 import developer_controlled_wallets
        from circle.web3 import utils

        kwargs = {'api_key': api_key, 'entity_secret': entity_secret}
        if host:
            kwargs['host'] = host
        api_client = utils.init_developer_controlled_wallets_client(**kwargs)
        self.developer_controlled_wallets = developer_controlled_wallets
        self.wallets_api = developer_controlled_wallets.WalletsApi(api_client)
        self.transactions_api = developer_controlled_wallets.TransactionsApi(api_client)

    def wallet_balances(self, provider_wallet_id):
        response = self.wallets_api.list_wallet_balance(provider_wallet_id, include_all=True)
        return model_dict(response)

    def submit_transfer(self, provider_wallet_id, token_id, amount, destination,
                        idempotency_key, request_id):
        dcw = self.developer_controlled_wallets
        request = dcw.CreateTransferTransactionForDeveloperRequest(
            idempotencyKey=idempotency_key,
            amounts=[amount],
            destinationAddress=destination,
            entitySecretCiphertext='',
            feeLevel=dcw.FeeLevel('MEDIUM'),
            tokenId=token_id,
            walletId=provider_wallet_id,
        )
        response = self.transactions_api.create_developer_transaction_transfer(
            request, x_request_id=UUID(request_id),
        )
        return model_dict(response)

    def transaction(self, provider_reference, request_id):
        response = self.transactions_api.get_transaction(
            UUID(provider_reference), x_request_id=UUID(request_id),
        )
        return model_dict(response)


class CircleTestnetProvider(CircleProvider):

    name = 'circle-testnet'

    def __init__(self, store, gateway=None):
        self.store = store
        self.host = os.environ.get('CIRCLE_API_HOST', '')
        if 'test' not in self.host.lower() and self.host:
            raise ValueError('Circle lab permits testnet hosts only')
        self.gateway = gateway

    def gateway_get(self):
        if self.gateway is None:
            self.gateway = CircleSdkGateway(
                os.environ.get('CIRCLE_API_KEY', ''),
                os.environ.get('CIRCLE_ENTITY_SECRET', ''),
                host=self.host,
            )
        return self.gateway

    def wallet_balance(self, organization_id, wallet_id):
        wallet = self.store.wallet_get(organization_id, wallet_id)
        if wallet is None or not wallet.get('provider_wallet_id'):
            raise ValueError('testnet wallet mapping not found')
        payload = self.gateway_get().wallet_balances(wallet['provider_wallet_id'])
        balances = payload.get('data', {}).get('tokenBalances', [])
        selected = None
        for item in balances:
            token = item.get('token', {})
            if token.get('symbol') == wallet['asset']:
                selected = item
                break
        if selected is None:
            raise ValueError('requested asset balance was not returned by Circle')
        result = {
            'wallet_id': wallet_id,
            'balance': selected.get('amount', '0'),
            'asset': wallet['asset'],
            'chain': wallet['chain'],
            'custody_type': wallet['custody_type'],
            'status': wallet['status'],
            'provider': self.name,
        }
        return result

    def transfer_quote(self, organization_id, wallet_id, amount, asset, chain, destination):
        balance = self.wallet_balance(organization_id, wallet_id)
        fee = Decimal(os.environ.get('CIRCLE_TESTNET_FEE_RESERVE_USDC', '1'))
        available = Decimal(balance['balance'])
        total = Decimal(str(amount)) + fee
        result = {
            'amount': str(amount),
            'asset': asset,
            'chain': chain,
            'destination': destination,
            'network_fee': str(fee),
            'available_balance': str(available),
            'total_required': str(total),
            'balance_ok': available >= total,
            'provider': self.name,
            'fee_kind': 'configured_testnet_reserve',
        }
        return result

    def screen_transfer(self, organization_id, wallet_id, amount, asset, chain, destination):
        allowlist = os.environ.get('CIRCLE_TESTNET_DESTINATION_ALLOWLIST', '')
        allowed = [item.strip().lower() for item in allowlist.split(',') if item.strip()]
        status = 'clear' if destination.lower() in allowed else 'unavailable'
        flags = [] if status == 'clear' else ['destination_not_allowlisted']
        result = {'status': status, 'flags': flags, 'provider': self.name, 'screened_at': utc_now()}
        return result

    def submit_transfer(self, action):
        args = action['normalized_arguments']
        organization_id = action['organization_id']
        wallet = self.store.wallet_get(organization_id, args['source_wallet_id'])
        if wallet is None or not wallet.get('provider_wallet_id'):
            raise ValueError('testnet wallet mapping not found')
        token_id = os.environ.get('CIRCLE_TESTNET_USDC_TOKEN_ID', '')
        if not token_id:
            raise ValueError('CIRCLE_TESTNET_USDC_TOKEN_ID is required')
        provider_key = uuid_v4_for_key(action['idempotency_key'])
        request_id = uuid_v4_for_key(action['action_id'])
        payload = self.gateway_get().submit_transfer(
            wallet['provider_wallet_id'], token_id, args['amount'], args['destination'],
            provider_key, request_id,
        )
        data = payload.get('data', {})
        provider_reference = data.get('id')
        if not provider_reference:
            raise ValueError('Circle SDK response did not include a transaction id')
        provider_status = str(data.get('state') or 'INITIATED').upper()
        now = utc_now()
        transaction = {
            'transaction_id': 'txn_%s' % uuid4().hex,
            'organization_id': organization_id,
            'action_id': action['action_id'],
            'provider': self.name,
            'provider_reference': provider_reference,
            'provider_status': provider_status,
            'normalized_status': STATUS_MAP.get(provider_status, 'pending'),
            'amount': args['amount'],
            'asset': args['asset'],
            'chain': args['chain'],
            'source_wallet_id': args['source_wallet_id'],
            'destination': args['destination'],
            'raw_safe': {'state': provider_status, 'idempotency_key': provider_key},
            'created_at': now,
            'updated_at': now,
        }
        self.store.transaction_insert(transaction)
        return transaction

    def transaction_status(self, organization_id, transaction_id):
        transaction = self.store.transaction_get(organization_id, transaction_id)
        if transaction is None:
            raise ValueError('transaction not found')
        request_id = uuid_v4_for_key(transaction_id)
        payload = self.gateway_get().transaction(transaction['provider_reference'], request_id)
        data = payload.get('data', {}).get('transaction', payload.get('data', {}))
        provider_status = str(data.get('state') or transaction['provider_status']).upper()
        normalized_status = STATUS_MAP.get(provider_status, 'pending')
        self.store.transaction_update(
            organization_id, transaction_id, provider_status, normalized_status,
            raw_safe={'state': provider_status},
        )
        return self.store.transaction_get(organization_id, transaction_id)
