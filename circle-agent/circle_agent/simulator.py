import hashlib

from decimal import Decimal
from uuid import uuid4

from agent_spine.auth import utc_now

from circle_agent.provider import CircleProvider


FINAL_STATUSES = ['confirmed', 'failed', 'denied', 'cancelled']


class SimulatorProvider(CircleProvider):

    name = 'simulator'

    def __init__(self, store):
        self.store = store

    def wallet_balance(self, organization_id, wallet_id):
        wallet = self.store.wallet_get(organization_id, wallet_id)
        if wallet is None:
            raise ValueError('wallet not found')
        result = {
            'wallet_id': wallet['wallet_id'],
            'balance': wallet['balance'],
            'asset': wallet['asset'],
            'chain': wallet['chain'],
            'custody_type': wallet['custody_type'],
            'status': wallet['status'],
            'provider': self.name,
        }
        return result

    def transfer_quote(self, organization_id, wallet_id, amount, asset, chain, destination):
        wallet = self.store.wallet_get(organization_id, wallet_id)
        if wallet is None:
            raise ValueError('wallet not found')
        fee_table = {
            'ethereum': Decimal('5'),
            'arbitrum': Decimal('0.25'),
            'polygon': Decimal('0.02'),
            'base': Decimal('0.01'),
            'solana': Decimal('0.001'),
        }
        amount_value = Decimal(str(amount))
        fee = fee_table.get(chain)
        if fee is None:
            raise ValueError('unsupported chain')
        available = Decimal(wallet['balance'])
        total = amount_value + fee
        result = {
            'amount': str(amount_value),
            'asset': asset,
            'chain': chain,
            'destination': destination,
            'network_fee': str(fee),
            'available_balance': str(available),
            'total_required': str(total),
            'balance_ok': available >= total,
            'provider': self.name,
        }
        return result

    def screen_transfer(self, organization_id, wallet_id, amount, asset, chain, destination):
        destination_lower = (destination or '').lower()
        denied = destination == '0x' + '5' * 40
        denied = denied or any(word in destination_lower for word in ['sanction', 'blocked', 'ofac'])
        amount_value = Decimal(str(amount))
        if denied:
            status = 'sanctioned'
            flags = ['sanctions_match']
        elif amount_value >= Decimal('50000'):
            status = 'review'
            flags = ['large_amount_review']
        else:
            status = 'clear'
            flags = []
        result = {
            'status': status,
            'flags': flags,
            'provider': self.name,
            'screened_at': utc_now(),
        }
        return result

    def submit_transfer(self, action):
        args = action['normalized_arguments']
        organization_id = action['organization_id']
        wallet_id = args['source_wallet_id']
        quote = self.transfer_quote(
            organization_id, wallet_id, args['amount'], args['asset'],
            args['chain'], args['destination'],
        )
        if not quote['balance_ok']:
            raise ValueError('insufficient balance at execution time')
        if args.get('simulate_failure'):
            raise ConnectionError('simulated provider failure')

        reference_seed = '%s:%s' % (organization_id, action['idempotency_key'])
        provider_reference = 'sim_%s' % hashlib.sha256(reference_seed.encode('utf-8')).hexdigest()[:32]
        transaction_id = 'txn_%s' % uuid4().hex
        normalized_status = args.get('simulate_status') or 'pending'
        provider_status = normalized_status.upper()
        now = utc_now()
        transaction = {
            'transaction_id': transaction_id,
            'organization_id': organization_id,
            'action_id': action['action_id'],
            'provider': self.name,
            'provider_reference': provider_reference,
            'provider_status': provider_status,
            'normalized_status': normalized_status,
            'amount': args['amount'],
            'asset': args['asset'],
            'chain': args['chain'],
            'source_wallet_id': wallet_id,
            'destination': args['destination'],
            'raw_safe': {'mode': 'deterministic-simulator'},
            'created_at': now,
            'updated_at': now,
        }
        self.store.transaction_insert(transaction)
        total = Decimal(args['amount']) + Decimal(args['network_fee'])
        new_balance = Decimal(quote['available_balance']) - total
        self.store.wallet_balance_set(organization_id, wallet_id, str(new_balance))
        return transaction

    def transaction_status(self, organization_id, transaction_id):
        transaction = self.store.transaction_get(organization_id, transaction_id)
        if transaction is None:
            raise ValueError('transaction not found')
        return transaction

    def advance_transaction(self, organization_id, transaction_id, status):
        allowed = ['pending', 'submitted', 'confirmed', 'failed', 'denied', 'cancelled', 'stuck']
        if status not in allowed:
            raise ValueError('unsupported simulator transaction status')
        updated = self.store.transaction_update(
            organization_id, transaction_id, status.upper(), status,
            raw_safe={'mode': 'deterministic-simulator', 'advanced': True},
        )
        if not updated:
            raise ValueError('transaction not found')
        return self.transaction_status(organization_id, transaction_id)
