from agent_spine.auth import AuthorizationError, require_organization, require_scope


POLICY_VERSION = 'onboarding-policy-1'
RESTRICTED_USE_CASES = ['spam', 'adult', 'gambling', 'political', 'fraud']


class OnboardingDecision:

    def __init__(self, outcome, reason_code, human_reason, permission='', roles=None):
        self.outcome = outcome
        self.reason_code = reason_code
        self.human_reason = human_reason
        self.required_permission = permission
        self.required_reviewer_roles = list(roles or [])
        self.required_approval_count = 1 if roles else 0
        self.policy_version = POLICY_VERSION
        self.evidence = []
        self.expires_at = ''


def application_evaluate(principal, action, resource_organization_id):
    try:
        require_organization(principal, resource_organization_id)
        require_scope(principal, 'onboarding:submit')
    except AuthorizationError as exc:
        return OnboardingDecision('DENY', 'unauthorized', str(exc), 'onboarding:submit')
    arguments = action['normalized_arguments']
    use_case = arguments['use_case'].lower()
    for restricted in RESTRICTED_USE_CASES:
        if restricted in use_case:
            return OnboardingDecision(
                'DENY', 'restricted_use_case',
                'The application includes a restricted use case: %s.' % restricted,
                'onboarding:submit',
            )
    if int(arguments['monthly_volume']) <= 0:
        return OnboardingDecision('DENY', 'invalid_volume', 'Monthly volume must be positive.',
                                  'onboarding:submit')
    if float(arguments['verification_score']) < 0.4:
        return OnboardingDecision('DENY', 'verification_failed',
                                  'Business verification did not meet the minimum threshold.',
                                  'onboarding:submit')
    if arguments.get('policy_required') and not arguments.get('policy_grounded'):
        return OnboardingDecision('DENY', 'policy_ungrounded',
                                  'No authorized onboarding policy grounded the application.',
                                  'onboarding:submit')
    return OnboardingDecision(
        'REQUIRE_APPROVAL', 'account_provisioning',
        'A compliance reviewer must approve account provisioning.',
        'onboarding:submit', ['reviewer', 'compliance', 'admin'],
    )
