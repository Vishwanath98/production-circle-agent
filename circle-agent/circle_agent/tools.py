import json

from decimal import Decimal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import interrupt

from agent_spine import audit
from agent_spine.actions import action_make, amount_str
from agent_spine.auth import require_scope
from agent_spine.context import context_from_config
from agent_spine.policy import POLICY_VERSION, action_evaluate
from agent_spine.tool_catalog import ToolCatalog

from circle_agent.rag_service import policy_search
from circle_agent.service import destination_validate, provider_for_context, store_for_context
from circle_agent.service import transfer_execute, transfer_propose
from circle_agent.x402_provider import payment_prepare, requirement_inspect


CORE_PROFILES = ['core-sim', 'rag-sim', 'mcp-sim', 'full-sim', 'full-testnet', 'x402-testnet']
RAG_PROFILES = ['rag-sim', 'full-sim', 'full-testnet', 'x402-testnet']
X402_PROFILES = ['x402-testnet']


@tool
def circle_policy_search(query: str, config: RunnableConfig) -> dict:
    """Search authorized Circle and compliance policy. Returns grounded citations or an explicit ungrounded result."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'policy:read')
    store = store_for_context(ctx)
    audit.emit(store, ctx, 'tool_intent', 'tool', 'circle_policy_search', 'started',
               safe_details={'query': query})
    result = policy_search(ctx, query)
    audit.emit(store, ctx, 'retrieval', 'policy', '', 'grounded' if result['grounded'] else 'ungrounded',
               'policy_search', {'citation_ids': [item['citation_id'] for item in result['citations']]})
    return result


@tool
def circle_wallet_balance(source_wallet_id: str, config: RunnableConfig) -> dict:
    """Read the authenticated organization's balance for a named Circle wallet."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'circle:read')
    store = store_for_context(ctx)
    provider = provider_for_context(ctx, store)
    action = action_make(
        ctx, 'wallet_balance', 'circle_wallet_balance', provider.name,
        {'source_wallet_id': source_wallet_id}, {'source_wallet_id': source_wallet_id},
        'low', POLICY_VERSION,
    )
    decision = action_evaluate(ctx.principal, action, resource_organization_id=ctx.principal.organization_id)
    audit.emit(store, ctx, 'authorization', 'wallet', source_wallet_id, decision.outcome,
               decision.reason_code, {'tool': 'circle_wallet_balance'})
    if decision.outcome != 'ALLOW':
        return {'status': 'denied', 'reason_code': decision.reason_code, 'message': decision.human_reason}
    result = provider.wallet_balance(ctx.principal.organization_id, source_wallet_id)
    return result


@tool
def circle_transfer_quote(source_wallet_id: str, amount: str, asset: str,
                          chain: str, destination: str, config: RunnableConfig) -> dict:
    """Validate and quote a USDC transfer without submitting a financial transaction."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'circle:read')
    store = store_for_context(ctx)
    provider = provider_for_context(ctx, store)
    wallet = store.wallet_get(ctx.principal.organization_id, source_wallet_id)
    if wallet is None:
        return {'status': 'not_found', 'message': 'source wallet not found'}
    if wallet['asset'] != asset or wallet['chain'] != chain:
        return {'status': 'denied', 'message': 'wallet asset or chain does not match the quote'}
    amount = amount_str(amount)
    if Decimal(amount) <= Decimal('0'):
        raise ValueError('amount must be greater than zero')
    destination = destination_validate(destination, chain)
    result = provider.transfer_quote(
        ctx.principal.organization_id, source_wallet_id, amount, asset, chain, destination,
    )
    result['status'] = 'quoted'
    return result


@tool
def circle_transaction_status(transaction_id: str, config: RunnableConfig) -> dict:
    """Read a tenant-scoped Circle transaction and its normalized asynchronous state."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'circle:read')
    store = store_for_context(ctx)
    provider = provider_for_context(ctx, store)
    result = provider.transaction_status(ctx.principal.organization_id, transaction_id)
    return result


@tool
def circle_request_transfer(source_wallet_id: str, amount: str, asset: str,
                            chain: str, destination: str, config: RunnableConfig,
                            idempotency_key: str = '', simulate_failure: bool = False,
                            simulate_status: str = '') -> dict:
    """Request a policy-controlled USDC transfer. Sensitive transfers pause for an authorized human decision before execution."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'circle:transfer:request')
    proposal = transfer_propose(
        ctx, source_wallet_id, amount, asset, chain, destination,
        idempotency_key=idempotency_key, simulate_failure=simulate_failure,
        simulate_status=simulate_status,
    )
    action = proposal['action']
    decision = proposal['decision']
    approval = proposal['approval']
    if decision.outcome == 'DENY' or action['status'] == 'denied':
        result = {
            'status': 'denied',
            'action_id': action['action_id'],
            'reason_code': decision.reason_code,
            'message': decision.human_reason,
        }
        return result

    if decision.outcome == 'REQUIRE_APPROVAL':
        if approval['status'] == 'pending':
            payload = {
                'type': 'approval_required',
                'approval_id': approval['approval_id'],
                'action_id': action['action_id'],
                'action_version': action['action_version'],
                'action_digest': action['action_digest'],
                'summary': 'Transfer %s %s on %s to %s' % (amount, asset, chain, destination),
                'arguments': action['redacted_arguments'],
                'risk_level': action['risk_level'],
                'policy_reason': decision.human_reason,
                'required_roles': approval['required_roles'],
                'expires_at': approval['expires_at'],
            }
            resume_value = interrupt(payload)
            if not isinstance(resume_value, dict) or resume_value.get('approval_id') != approval['approval_id']:
                raise ValueError('resume payload does not match the pending approval')

        store = store_for_context(ctx)
        approval = store.approval_get(ctx.principal.organization_id, approval['approval_id'])
        if approval['status'] == 'rejected':
            return {'status': 'rejected', 'action_id': action['action_id'], 'approval_id': approval['approval_id']}
        if approval['status'] != 'approved':
            return {'status': approval['status'], 'action_id': action['action_id'], 'approval_id': approval['approval_id']}

    result = transfer_execute(ctx, action['action_id'], action['action_digest'])
    transaction = result.get('transaction')
    response = {
        'status': 'submitted' if transaction else result['action']['status'],
        'action_id': action['action_id'],
        'duplicate': result['duplicate'],
        'transaction': transaction,
    }
    return response


@tool
def x402_inspect_payment(requirement_json: str, config: RunnableConfig) -> dict:
    """Validate an x402 payment requirement without signing or paying it."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'x402:read')
    requirement = json.loads(requirement_json)
    result = requirement_inspect(requirement)
    result['organization_id'] = ctx.principal.organization_id
    return result


@tool
def x402_request_payment(requirement_json: str, config: RunnableConfig) -> dict:
    """Request an x402 payment on an allowed testnet. Policy and authorized human approval run before Circle settlement."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'x402:pay:request')
    requirement = json.loads(requirement_json)
    payment = payment_prepare(ctx, requirement)
    inspected = payment['requirement']
    proposal = transfer_propose(
        ctx, payment['source_wallet_id'], inspected['amount'], inspected['asset'],
        payment['chain'], inspected['pay_to'], idempotency_key=payment['idempotency_key'],
    )
    action = proposal['action']
    decision = proposal['decision']
    approval = proposal['approval']
    if decision.outcome == 'DENY' or action['status'] == 'denied':
        return {
            'status': 'denied', 'action_id': action['action_id'],
            'reason_code': decision.reason_code, 'message': decision.human_reason,
            'requirement_digest': payment['requirement_digest'],
        }
    if approval['status'] == 'pending':
        payload = {
            'type': 'approval_required',
            'protocol': 'x402',
            'approval_id': approval['approval_id'],
            'action_id': action['action_id'],
            'action_version': action['action_version'],
            'action_digest': action['action_digest'],
            'requirement_digest': payment['requirement_digest'],
            'summary': 'x402 payment %s USDC for %s' % (inspected['amount'], inspected['resource']),
            'arguments': action['redacted_arguments'],
            'risk_level': action['risk_level'],
            'policy_reason': decision.human_reason,
            'required_roles': approval['required_roles'],
            'expires_at': approval['expires_at'],
        }
        resume_value = interrupt(payload)
        if not isinstance(resume_value, dict) or resume_value.get('approval_id') != approval['approval_id']:
            raise ValueError('resume payload does not match the pending x402 approval')
    store = store_for_context(ctx)
    approval = store.approval_get(ctx.principal.organization_id, approval['approval_id'])
    if approval['status'] != 'approved':
        return {'status': approval['status'], 'approval_id': approval['approval_id']}
    execution = transfer_execute(ctx, action['action_id'], action['action_digest'])
    result = {
        'status': 'submitted',
        'protocol': 'x402',
        'resource': inspected['resource'],
        'requirement_digest': payment['requirement_digest'],
        'action_id': action['action_id'],
        'transaction': execution.get('transaction'),
        'duplicate': execution['duplicate'],
    }
    return result


def catalog_build(extra_tools=None):
    catalog = ToolCatalog()
    read_meta = {
        'permission': 'circle:read', 'effect': 'read', 'risk': 'low',
        'provider': 'circle', 'timeout_seconds': 15, 'max_retries': 1,
    }
    catalog.register(circle_wallet_balance, read_meta, CORE_PROFILES)
    catalog.register(circle_transfer_quote, read_meta, CORE_PROFILES)
    catalog.register(circle_transaction_status, read_meta, CORE_PROFILES)
    catalog.register(circle_policy_search, {
        'permission': 'policy:read', 'effect': 'read', 'risk': 'low',
        'provider': 'rag', 'timeout_seconds': 15, 'max_retries': 1,
    }, RAG_PROFILES)
    catalog.register(circle_request_transfer, {
        'permission': 'circle:transfer:request', 'effect': 'financial', 'risk': 'high',
        'provider': 'circle', 'timeout_seconds': 120, 'max_retries': 0,
    }, CORE_PROFILES)
    catalog.register(x402_inspect_payment, {
        'permission': 'x402:read', 'effect': 'read', 'risk': 'medium',
        'provider': 'x402', 'timeout_seconds': 15, 'max_retries': 0,
    }, X402_PROFILES)
    catalog.register(x402_request_payment, {
        'permission': 'x402:pay:request', 'effect': 'financial', 'risk': 'high',
        'provider': 'x402', 'timeout_seconds': 120, 'max_retries': 0,
    }, X402_PROFILES)
    for item in extra_tools or []:
        catalog.register(item['tool'], item['metadata'], item['profiles'])
    return catalog
