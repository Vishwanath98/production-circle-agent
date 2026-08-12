from agent_spine.auth import AuthorizationError, require_organization, require_scope


POLICY_VERSION = 'circle-action-policy-1'
SUPPORTED_CHAINS = ['arbitrum', 'base', 'ethereum', 'polygon', 'solana']
SUPPORTED_ASSETS = ['USDC']


class PolicyDecision:

    def __init__(self, outcome, reason_code, human_reason, required_permission='',
                 required_reviewer_roles=None, required_approval_count=0,
                 evidence=None, expires_at=''):
        self.outcome = outcome
        self.reason_code = reason_code
        self.human_reason = human_reason
        self.required_permission = required_permission
        self.required_reviewer_roles = list(required_reviewer_roles or [])
        self.required_approval_count = int(required_approval_count or 0)
        self.policy_version = POLICY_VERSION
        self.evidence = list(evidence or [])
        self.expires_at = expires_at

    def to_dict(self):
        data = {
            'outcome': self.outcome,
            'reason_code': self.reason_code,
            'human_reason': self.human_reason,
            'required_permission': self.required_permission,
            'required_reviewer_roles': list(self.required_reviewer_roles),
            'required_approval_count': self.required_approval_count,
            'policy_version': self.policy_version,
            'evidence': list(self.evidence),
            'expires_at': self.expires_at,
        }
        return data


def allow(reason_code, human_reason, permission='', evidence=None):
    return PolicyDecision('ALLOW', reason_code, human_reason, permission, evidence=evidence)


def deny(reason_code, human_reason, permission='', evidence=None):
    return PolicyDecision('DENY', reason_code, human_reason, permission, evidence=evidence)


def require_approval(reason_code, human_reason, permission, roles, count=1, evidence=None):
    return PolicyDecision('REQUIRE_APPROVAL', reason_code, human_reason, permission,
                          required_reviewer_roles=roles, required_approval_count=count,
                          evidence=evidence)


def action_evaluate(principal, action, resource_organization_id=None):
    if resource_organization_id:
        try:
            require_organization(principal, resource_organization_id)
        except AuthorizationError:
            return deny('tenant_mismatch', 'The resource is outside the authenticated organization.')

    action_type = action['action_type']
    arguments = action['normalized_arguments']

    if action_type in ['wallet_balance', 'transaction_status', 'policy_search', 'transfer_quote']:
        scope = 'circle:read'
        try:
            require_scope(principal, scope)
        except AuthorizationError:
            return deny('missing_scope', 'The principal cannot read Circle resources.', scope)
        return allow('authorized_read', 'The read is authorized.', scope)

    if action_type != 'transfer':
        return deny('unknown_action', 'The requested action is not recognized.')

    scope = 'circle:transfer:request'
    try:
        require_scope(principal, scope)
    except AuthorizationError:
        return deny('missing_scope', 'The principal cannot request transfers.', scope)

    if arguments.get('asset') not in SUPPORTED_ASSETS:
        return deny('unsupported_asset', 'The requested asset is not supported.', scope)
    if arguments.get('chain') not in SUPPORTED_CHAINS:
        return deny('unsupported_chain', 'The requested chain is not supported.', scope)
    if arguments.get('compliance_status') in ['denied', 'sanctioned']:
        return deny('compliance_denied', 'Compliance screening denied the transfer.', scope)
    if arguments.get('compliance_status') not in ['clear']:
        return deny('compliance_uncertain', 'Compliance screening did not produce a clear result.', scope)
    if arguments.get('policy_required') and not arguments.get('policy_grounded'):
        return deny('policy_ungrounded', 'No authorized policy evidence grounded the transfer.', scope)
    if arguments.get('balance_ok') is not True:
        return deny('insufficient_balance', 'The source wallet does not have sufficient funds.', scope)

    return require_approval(
        'financial_effect',
        'An authorized reviewer must approve this financial effect.',
        scope,
        ['reviewer', 'admin'],
        count=1,
        evidence=arguments.get('policy_evidence', []),
    )


def reviewer_authorize(principal, approval):
    allowed_scope = False
    for scope in ['approval:decide', 'circle:approval:decide', 'onboarding:approval:decide']:
        if principal.has_scope(scope):
            allowed_scope = True
            break
    if not allowed_scope:
        raise AuthorizationError('an approval decision scope is required')
    require_organization(principal, approval['organization_id'])
    required_roles = approval.get('required_roles', [])
    allowed = False
    for role in required_roles:
        if principal.has_role(role):
            allowed = True
            break
    if not allowed:
        raise AuthorizationError('reviewer role is not authorized for this approval')
    return True
