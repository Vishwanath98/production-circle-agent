import hashlib
import json
import re

from datetime import datetime, timezone
from uuid import uuid4

from agent_spine import audit
from agent_spine.actions import action_make
from agent_spine.approvals import approval_make
from agent_spine.store import Store
from agent_spine.tenant_rag import search

from onboarding_agent.production_policy import POLICY_VERSION, application_evaluate


EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def store_for_context(ctx):
    if not ctx.db_path:
        raise ValueError('runtime context has no durable database path')
    store = Store(ctx.db_path)
    store.migrate()
    return store


def verification_score(business_name, email):
    if not EMAIL.match(email or ''):
        return '0.2'
    lower = business_name.lower()
    if any(value in lower for value in ['fake', 'test', 'temporary']):
        return '0.3'
    return '0.85'


def idempotency_make(ctx, values, client_key=''):
    if client_key:
        return client_key
    data = dict(values)
    data['organization_id'] = ctx.principal.organization_id
    data['principal_id'] = ctx.principal.principal_id
    data['thread_id'] = ctx.thread_id
    payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return 'onboarding_%s' % hashlib.sha256(payload.encode('utf-8')).hexdigest()


def application_propose(ctx, business_name, business_type, email, phone,
                        use_case, monthly_volume, idempotency_key=''):
    store = store_for_context(ctx)
    values = {
        'business_name': business_name.strip(), 'business_type': business_type.strip(),
        'email': email.strip().lower(), 'phone': phone.strip(),
        'use_case': use_case.strip(), 'monthly_volume': int(monthly_volume),
    }
    for name in ['business_name', 'business_type', 'email', 'phone', 'use_case']:
        if not values[name]:
            raise ValueError('%s is required' % name)
    values['verification_score'] = verification_score(values['business_name'], values['email'])
    values['risk'] = []
    if values['monthly_volume'] > 1000000:
        values['risk'].append('high_volume')
    policy_required = ctx.profile in ['rag-sim', 'full-sim']
    policy_result = {'grounded': False, 'citations': []}
    if policy_required:
        query = 'A2P messaging business verification compliance %s %s monthly message volume %s onboarding KYB' % (
            values['business_type'], values['use_case'], values['monthly_volume'],
        )
        policy_result = search(store, ctx.principal.organization_id, query, k=4)
    values['policy_required'] = policy_required
    values['policy_grounded'] = bool(policy_result['grounded'])
    values['policy_evidence'] = [
        {'citation_id': item['citation_id'], 'source': item['source'],
         'version': item['version'], 'score': item['score']}
        for item in policy_result['citations']
    ]
    stable_key = idempotency_make(ctx, values, client_key=idempotency_key)
    action = action_make(
        ctx, 'account_provision', 'onboarding_submit_application', 'local-onboarding',
        {}, values, 'high', POLICY_VERSION, idempotency_key=stable_key,
    )
    decision = application_evaluate(ctx.principal, action, ctx.principal.organization_id)
    existing = store.action_get_by_idempotency(ctx.principal.organization_id, stable_key)
    if existing is None:
        action['status'] = 'denied' if decision.outcome == 'DENY' else 'pending_approval'
        store.action_insert(action)
        existing = store.action_get(ctx.principal.organization_id, action['action_id'])
        application_id = 'app_%s' % uuid4().hex
        store.onboarding_application_insert({
            'application_id': application_id,
            'organization_id': ctx.principal.organization_id,
            'principal_id': ctx.principal.principal_id,
            'action_id': existing['action_id'],
            'business_name': values['business_name'], 'business_type': values['business_type'],
            'email': values['email'], 'phone': values['phone'], 'use_case': values['use_case'],
            'monthly_volume': values['monthly_volume'],
            'verification_score': values['verification_score'], 'risk': values['risk'],
            'recommended_decision': 'approve' if decision.outcome != 'DENY' else 'reject',
            'status': 'rejected' if decision.outcome == 'DENY' else 'pending_review',
        })
    elif existing['action_digest'] != action['action_digest']:
        raise ValueError('idempotency key was already used for a different application')
    application = store.onboarding_application_by_action(
        ctx.principal.organization_id, existing['action_id'],
    )
    approval = store.approval_for_action(ctx.principal.organization_id, existing['action_id'])
    if decision.outcome == 'REQUIRE_APPROVAL' and approval is None:
        approval = approval_make(existing, decision)
        store.approval_insert(approval)
    audit.emit(store, ctx, 'onboarding_policy', 'application', application['application_id'],
               decision.outcome, decision.reason_code,
               {'action_id': existing['action_id'], 'action_digest': existing['action_digest']})
    return {'store': store, 'action': existing, 'application': application,
            'approval': approval, 'decision': decision}


def application_execute(ctx, action_id, action_digest):
    store = store_for_context(ctx)
    action = store.action_get(ctx.principal.organization_id, action_id)
    if action is None or action['action_digest'] != action_digest:
        raise ValueError('approved onboarding action does not match')
    if action['policy_version'] != POLICY_VERSION:
        store.action_status(ctx.principal.organization_id, action_id, 'approved', 'cancelled',
                            error_code='policy_stale', error_message='action policy version is stale')
        raise ValueError('onboarding action policy version is stale')
    if action.get('expires_at') and datetime.fromisoformat(action['expires_at']) <= datetime.now(timezone.utc):
        store.action_status(ctx.principal.organization_id, action_id, 'approved', 'cancelled',
                            error_code='action_expired', error_message='action expired before execution')
        raise ValueError('approved onboarding action is expired')
    approval = store.approval_for_action(ctx.principal.organization_id, action_id)
    if approval is None or approval['status'] != 'approved':
        raise ValueError('approved approval request is required')
    if not store.action_claim(ctx.principal.organization_id, action_id, action_digest):
        application = store.onboarding_application_by_action(ctx.principal.organization_id, action_id)
        if application and application['status'] == 'approved':
            return {'application': application, 'duplicate': True}
        raise ValueError('onboarding action could not be claimed')
    application = store.onboarding_application_by_action(ctx.principal.organization_id, action_id)
    account_seed = '%s:%s' % (ctx.principal.organization_id, action['idempotency_key'])
    account_id = 'AC%s' % hashlib.sha256(account_seed.encode('utf-8')).hexdigest()[:16].upper()
    changed = store.onboarding_application_finalize(
        ctx.principal.organization_id, application['application_id'],
        'pending_review', 'approved', account_id,
    )
    if not changed:
        raise ValueError('onboarding application could not be finalized')
    store.action_status(ctx.principal.organization_id, action_id, 'executing', 'succeeded')
    application = store.onboarding_application_get(
        ctx.principal.organization_id, application['application_id'],
    )
    audit.emit(store, ctx, 'account_provisioned', 'application', application['application_id'],
               'succeeded', 'approved_action', {'account_id': account_id})
    return {'application': application, 'duplicate': False}
