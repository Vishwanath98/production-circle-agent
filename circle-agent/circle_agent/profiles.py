PROFILES = {
    'core-sim': {
        'rag': False,
        'mcp': False,
        'provider': 'simulator',
        'x402': False,
    },
    'rag-sim': {
        'rag': True,
        'mcp': False,
        'provider': 'simulator',
        'x402': False,
    },
    'mcp-sim': {
        'rag': False,
        'mcp': True,
        'provider': 'simulator',
        'x402': False,
    },
    'full-sim': {
        'rag': True,
        'mcp': True,
        'provider': 'simulator',
        'x402': False,
    },
    'full-testnet': {
        'rag': True,
        'mcp': True,
        'provider': 'circle-testnet',
        'x402': False,
    },
    'x402-testnet': {
        'rag': True,
        'mcp': True,
        'provider': 'circle-testnet',
        'x402': True,
    },
}


LEGACY_PROFILES = {
    'base': 'core-sim',
    'rag': 'rag-sim',
    'mcp': 'mcp-sim',
}


def profile_get(name):
    name = LEGACY_PROFILES.get(name, name)
    profile = PROFILES.get(name)
    if profile is None:
        raise ValueError('unknown Circle profile: %s' % name)
    data = dict(profile)
    data['name'] = name
    return data


def profile_authorize(principal, name):
    from agent_spine.auth import require_scope

    profile = profile_get(name)
    if profile['rag']:
        require_scope(principal, 'policy:read')
    if profile['mcp']:
        require_scope(principal, 'mcp:read')
    if profile['provider'] == 'circle-testnet':
        require_scope(principal, 'circle:testnet')
    if profile['x402']:
        require_scope(principal, 'x402:pay:request')
    return profile['name']
