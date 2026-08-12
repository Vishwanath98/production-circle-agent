import hashlib
import json
import re

from datetime import datetime, timezone
from decimal import Decimal

from agent_spine import audit
from agent_spine.actions import action_make, amount_str
from agent_spine.approvals import approval_make
from agent_spine.policy import POLICY_VERSION, action_evaluate
from agent_spine.store import Store
from agent_spine.tenant_rag import search

from circle_agent.profiles import profile_get
from circle_agent.simulator import SimulatorProvider


EVM_ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
SOLANA_ADDRESS = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')


def store_for_context(ctx):
    if not ctx.db_path:
        raise ValueError('runtime context has no durable database path')
    store = Store(ctx.db_path)
    store.migrate()
    return store


def provider_for_context(ctx, store=None):
    store = store or store_for_context(ctx)
    profile = profile_get(ctx.profile)
    if profile['provider'] == 'simulator':
        return SimulatorProvider(store)
    if profile['provider'] == 'circle-testnet':
        from circle_agent.circle_provider import CircleTestnetProvider
        return CircleTestnetProvider(store)
    raise ValueError('unsupported Circle provider: %s' % profile['provider'])


def destination_validate(destination, chain):
    destination = (destination or '').strip()
    if chain == 'solana':
        valid = bool(SOLANA_ADDRESS.match(destination))
    else:
        valid = bool(EVM_ADDRESS.match(destination))
    if not valid:
        raise ValueError('destination address is invalid for %s' % chain)
    return destination


def idempotency_for_transfer(ctx, wallet_id, amount, asset, chain, destination, client_key=''):
    if client_key:
        return client_key
    data = {
        'organization_id': ctx.principal.organization_id,
        'principal_id': ctx.principal.principal_id,
        'thread_id': ctx.thread_id,
        'wallet_id': wallet_id,
        'amount': amount,
        'asset': asset,
        'chain': chain,
        'destination': destination,
    }
    payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    return 'circle_%s' % digest


def transfer_prepare(ctx, source_wallet_id, amount, asset, chain, destination,
                     idempotency_key='', simulate_failure=False, simulate_status=''):
    store = store_for_context(ctx)
    provider = provider_for_context(ctx, store)
    organization_id = ctx.principal.organization_id
    wallet = store.wallet_get(organization_id, source_wallet_id)
    if wallet is None:
        raise ValueError('source wallet not found')
    if wallet['status'] != 'active':
        raise ValueError('source wallet is not active')
    if wallet['asset'] != asset:
        raise ValueError('source wallet does not hold the requested asset')
    if wallet['chain'] != chain:
        raise ValueError('source wallet is not on the requested chain')
    normalized_amount = amount_str(amount)
    if Decimal(normalized_amount) <= Decimal('0'):
        raise ValueError('amount must be greater than zero')
    destination = destination_validate(destination, chain)
    quote = provider.transfer_quote(
        organization_id, source_wallet_id, normalized_amount, asset, chain, destination,
    )
    screening = provider.screen_transfer(
        organization_id, source_wallet_id, normalized_amount, asset, chain, destination,
    )
    profile = profile_get(ctx.profile)
    policy_result = {'grounded': False, 'citations': []}
    if profile['rag']:
        policy_query = 'USDC transfer %s %s compliance balance approval' % (chain, normalized_amount)
        policy_result = search(store, organization_id, policy_query, k=4)
    evidence = []
    for citation in policy_result['citations']:
        evidence.append({
            'citation_id': citation['citation_id'], 'source': citation['source'],
            'version': citation['version'], 'score': citation['score'],
        })
    arguments = {
        'source_wallet_id': source_wallet_id,
        'amount': normalized_amount,
        'asset': asset,
        'chain': chain,
        'destination': destination,
        'network_fee': quote['network_fee'],
        'available_balance': quote['available_balance'],
        'balance_ok': quote['balance_ok'],
        'compliance_status': screening['status'],
        'compliance_flags': screening['flags'],
        'custody_type': wallet['custody_type'],
        'simulate_failure': bool(simulate_failure),
        'simulate_status': simulate_status or '',
        'policy_required': bool(profile['rag']),
        'policy_grounded': bool(policy_result['grounded']),
        'policy_evidence': evidence,
    }
    stable_key = idempotency_for_transfer(
        ctx, source_wallet_id, normalized_amount, asset, chain, destination,
        client_key=idempotency_key,
    )
    action = action_make(
        ctx, 'transfer', 'circle_request_transfer', provider.name,
        {'source_wallet_id': source_wallet_id}, arguments, 'high', POLICY_VERSION,
        idempotency_key=stable_key,
    )
    decision = action_evaluate(ctx.principal, action, resource_organization_id=wallet['organization_id'])
    audit.emit(
        store, ctx, 'policy_decision', 'action', action['action_id'], decision.outcome,
        decision.reason_code, {'action_digest': action['action_digest'], 'tool': action['tool_name']},
    )
    return store, provider, action, decision


def transfer_propose(ctx, source_wallet_id, amount, asset, chain, destination,
                     idempotency_key='', simulate_failure=False, simulate_status=''):
    store, provider, action, decision = transfer_prepare(
        ctx, source_wallet_id, amount, asset, chain, destination,
        idempotency_key=idempotency_key, simulate_failure=simulate_failure,
        simulate_status=simulate_status,
    )
    existing = store.action_get_by_idempotency(action['organization_id'], action['idempotency_key'])
    if existing is None:
        if decision.outcome == 'DENY':
            action['status'] = 'denied'
        elif decision.outcome == 'REQUIRE_APPROVAL':
            action['status'] = 'pending_approval'
        else:
            action['status'] = 'approved'
        store.action_insert(action)
        existing = store.action_get(action['organization_id'], action['action_id'])
    elif existing['action_digest'] != action['action_digest']:
        raise ValueError('idempotency key was already used for a different transfer')

    approval = store.approval_for_action(existing['organization_id'], existing['action_id'])
    if decision.outcome == 'REQUIRE_APPROVAL' and approval is None:
        approval = approval_make(existing, decision)
        store.approval_insert(approval)
        audit.emit(
            store, ctx, 'approval_requested', 'approval', approval['approval_id'], 'pending',
            decision.reason_code, {'action_id': existing['action_id'], 'action_digest': existing['action_digest']},
        )
    result = {
        'store': store,
        'provider': provider,
        'action': existing,
        'decision': decision,
        'approval': approval,
    }
    return result


def transfer_execute(ctx, action_id, action_digest):
    store = store_for_context(ctx)
    action = store.action_get(ctx.principal.organization_id, action_id)
    if action is None:
        raise ValueError('action not found')
    if action['action_digest'] != action_digest:
        raise ValueError('action digest does not match')
    if action['policy_version'] != POLICY_VERSION:
        store.action_status(ctx.principal.organization_id, action_id, 'approved', 'cancelled',
                            error_code='policy_stale', error_message='action policy version is stale')
        raise ValueError('action policy version is stale')
    if action.get('expires_at') and datetime.fromisoformat(action['expires_at']) <= datetime.now(timezone.utc):
        store.action_status(ctx.principal.organization_id, action_id, 'approved', 'cancelled',
                            error_code='action_expired', error_message='action expired before execution')
        raise ValueError('approved action is expired')
    approval = store.approval_for_action(ctx.principal.organization_id, action_id)
    if approval is None or approval['status'] != 'approved':
        raise ValueError('approved approval request is required')
    claimed = store.action_claim(ctx.principal.organization_id, action_id, action_digest)
    if not claimed:
        current = store.action_get(ctx.principal.organization_id, action_id)
        if current and current['status'] in ['submitted', 'succeeded']:
            return {'action': current, 'duplicate': True}
        raise ValueError('action could not be claimed for execution')

    provider = provider_for_context(ctx, store)
    audit.emit(store, ctx, 'effect_attempt', 'action', action_id, 'started', 'approved_action')
    try:
        args = action['normalized_arguments']
        screening = provider.screen_transfer(
            ctx.principal.organization_id, args['source_wallet_id'], args['amount'],
            args['asset'], args['chain'], args['destination'],
        )
        if screening['status'] != 'clear':
            raise ValueError('compliance screening is no longer clear')
        transaction = provider.submit_transfer(action)
    except Exception as exc:
        provider_error = exc.__class__.__name__
        store.action_result(ctx.principal.organization_id, action_id, False,
                            error_code='provider_error', error_message='provider request failed')
        audit.emit(store, ctx, 'effect_result', 'action', action_id, 'failed',
                   'provider_error', {'error_type': provider_error})
        raise ConnectionError('Circle provider request failed')
    store.action_result(ctx.principal.organization_id, action_id, True)
    audit.emit(store, ctx, 'effect_result', 'transaction', transaction['transaction_id'],
               'submitted', 'provider_accepted', {'action_id': action_id})
    result = {
        'action': store.action_get(ctx.principal.organization_id, action_id),
        'transaction': transaction,
        'duplicate': False,
    }
    return result
