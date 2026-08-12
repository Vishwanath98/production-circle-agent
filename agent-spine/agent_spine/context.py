from agent_spine.auth import AuthenticationError, Principal, utc_now


class RuntimeContext:

    def __init__(self, request_id, run_id, thread_id, principal, agent_name,
                 agent_version, profile, trace_metadata=None, db_path=''):
        self.request_id = str(request_id)
        self.run_id = str(run_id)
        self.thread_id = str(thread_id)
        self.principal = principal
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.profile = profile
        self.trace_metadata = dict(trace_metadata or {})
        self.db_path = db_path or ''

    def to_dict(self):
        data = {
            'request_id': self.request_id,
            'run_id': self.run_id,
            'thread_id': self.thread_id,
            'principal': self.principal.to_dict(),
            'agent_name': self.agent_name,
            'agent_version': self.agent_version,
            'profile': self.profile,
            'trace_metadata': dict(self.trace_metadata),
            'db_path': self.db_path,
        }
        return data


def config_make(ctx):
    configurable = {
        'thread_id': ctx.thread_id,
        'runtime_context': ctx.to_dict(),
    }
    metadata = dict(ctx.trace_metadata)
    metadata.update({
        'request_id': ctx.request_id,
        'run_id': ctx.run_id,
        'thread_id': ctx.thread_id,
        'organization_id': ctx.principal.organization_id,
        'principal_id': ctx.principal.principal_id,
        'agent_name': ctx.agent_name,
        'agent_version': ctx.agent_version,
        'profile': ctx.profile,
    })
    config = {
        'configurable': configurable,
        'metadata': metadata,
    }
    return config


def context_from_config(config):
    configurable = (config or {}).get('configurable', {})
    data = configurable.get('runtime_context')
    if not data:
        raise AuthenticationError('authenticated runtime context is required')
    principal_data = data.get('principal') or {}
    if not principal_data.get('principal_id') or not principal_data.get('organization_id'):
        raise AuthenticationError('runtime principal is incomplete')
    principal = Principal(
        principal_id=principal_data['principal_id'],
        organization_id=principal_data['organization_id'],
        display_name=principal_data.get('display_name', ''),
        roles=principal_data.get('roles', []),
        scopes=principal_data.get('scopes', []),
        auth_method=principal_data.get('auth_method', ''),
        credential_id=principal_data.get('credential_id', ''),
        authenticated_at=principal_data.get('authenticated_at') or utc_now(),
    )
    ctx = RuntimeContext(
        request_id=data['request_id'],
        run_id=data['run_id'],
        thread_id=data['thread_id'],
        principal=principal,
        agent_name=data['agent_name'],
        agent_version=data['agent_version'],
        profile=data['profile'],
        trace_metadata=data.get('trace_metadata'),
        db_path=data.get('db_path', ''),
    )
    return ctx
