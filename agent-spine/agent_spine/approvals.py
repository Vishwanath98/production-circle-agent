from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_spine.auth import utc_now
from agent_spine.policy import reviewer_authorize


def approval_make(action, decision, expires_minutes=30):
    requested_at = utc_now()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    approval = {
        'approval_id': 'apr_%s' % uuid4().hex,
        'action_id': action['action_id'],
        'action_version': action['action_version'],
        'action_digest': action['action_digest'],
        'organization_id': action['organization_id'],
        'status': 'pending',
        'required_roles': list(decision.required_reviewer_roles),
        'required_count': decision.required_approval_count,
        'requested_at': requested_at,
        'expires_at': expires_at.isoformat(),
    }
    return approval


def approval_decide(store, principal, approval_id, decision, action_digest, reason=''):
    if decision not in ['approve', 'reject']:
        raise ValueError('decision must be approve or reject')
    approval = store.approval_get(principal.organization_id, approval_id)
    if approval is None:
        raise ValueError('approval request not found')
    reviewer_authorize(principal, approval)
    result = store.approval_decide(
        organization_id=principal.organization_id,
        approval_id=approval_id,
        principal_id=principal.principal_id,
        decision=decision,
        reason=reason,
        action_digest=action_digest,
    )
    return result
