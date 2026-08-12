from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import interrupt

from agent_spine.auth import require_scope
from agent_spine.context import context_from_config
from agent_spine.tenant_rag import search
from agent_spine.tool_catalog import ToolCatalog

from onboarding_agent.production_service import application_execute, application_propose, store_for_context


PROFILES = ['core-sim', 'rag-sim', 'mcp-sim', 'full-sim']


@tool
def onboarding_policy_search(query: str, config: RunnableConfig) -> dict:
    """Search authorized onboarding policy and return versioned citations or an explicit ungrounded result."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'policy:read')
    store = store_for_context(ctx)
    return search(store, ctx.principal.organization_id, query)


@tool
def onboarding_application_status(application_id: str, config: RunnableConfig) -> dict:
    """Read one onboarding application from the authenticated organization."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'onboarding:read')
    store = store_for_context(ctx)
    application = store.onboarding_application_get(ctx.principal.organization_id, application_id)
    if application is None:
        return {'status': 'not_found'}
    return application


@tool
def onboarding_submit_application(business_name: str, business_type: str, email: str,
                                  phone: str, use_case: str, monthly_volume: int,
                                  config: RunnableConfig, idempotency_key: str = '') -> dict:
    """Submit a tenant-scoped application. Account provisioning pauses for an authorized compliance decision."""
    ctx = context_from_config(config)
    require_scope(ctx.principal, 'onboarding:submit')
    proposal = application_propose(
        ctx, business_name, business_type, email, phone, use_case,
        monthly_volume, idempotency_key=idempotency_key,
    )
    action = proposal['action']
    application = proposal['application']
    decision = proposal['decision']
    approval = proposal['approval']
    if decision.outcome == 'DENY':
        return {'status': 'rejected', 'application_id': application['application_id'],
                'reason_code': decision.reason_code, 'message': decision.human_reason}
    if approval['status'] == 'pending':
        payload = {
            'type': 'approval_required', 'domain': 'onboarding',
            'approval_id': approval['approval_id'], 'action_id': action['action_id'],
            'action_version': action['action_version'], 'action_digest': action['action_digest'],
            'application_id': application['application_id'],
            'summary': 'Provision account for %s' % application['business_name'],
            'arguments': action['redacted_arguments'], 'risk_level': action['risk_level'],
            'policy_reason': decision.human_reason,
            'required_roles': approval['required_roles'], 'expires_at': approval['expires_at'],
        }
        resume_value = interrupt(payload)
        if not isinstance(resume_value, dict) or resume_value.get('approval_id') != approval['approval_id']:
            raise ValueError('resume payload does not match the onboarding approval')
    store = store_for_context(ctx)
    approval = store.approval_get(ctx.principal.organization_id, approval['approval_id'])
    if approval['status'] == 'rejected':
        store.onboarding_application_finalize(
            ctx.principal.organization_id, application['application_id'],
            'pending_review', 'rejected', None,
        )
        return {'status': 'rejected', 'application_id': application['application_id']}
    result = application_execute(ctx, action['action_id'], action['action_digest'])
    return {'status': 'approved', 'application': result['application'], 'duplicate': result['duplicate']}


def catalog_build(extra_tools=None):
    catalog = ToolCatalog()
    catalog.register(onboarding_application_status, {
        'permission': 'onboarding:read', 'effect': 'read', 'risk': 'low',
        'provider': 'local-onboarding', 'timeout_seconds': 10, 'max_retries': 1,
    }, PROFILES)
    catalog.register(onboarding_policy_search, {
        'permission': 'policy:read', 'effect': 'read', 'risk': 'low',
        'provider': 'rag', 'timeout_seconds': 15, 'max_retries': 1,
    }, ['rag-sim', 'full-sim'])
    catalog.register(onboarding_submit_application, {
        'permission': 'onboarding:submit', 'effect': 'account_provision', 'risk': 'high',
        'provider': 'local-onboarding', 'timeout_seconds': 60, 'max_retries': 0,
    }, PROFILES)
    for item in extra_tools or []:
        catalog.register(item['tool'], item['metadata'], item['profiles'])
    return catalog
