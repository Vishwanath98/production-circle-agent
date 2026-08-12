#!/usr/bin/env python3

import json
import os
import sys

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

from agent_spine.store import Store

from circle_agent.rag_service import corpus_ingest


REQUESTER_SCOPES = ['agent:chat', 'circle:read', 'circle:transfer:request', 'policy:read', 'mcp:read',
                    'circle:testnet', 'x402:read', 'x402:pay:request', 'memory:read', 'memory:write']
REVIEWER_SCOPES = REQUESTER_SCOPES + ['circle:approval:decide', 'policy:write']


def parse_args(argv=None):
    agent_dir = os.path.abspath(os.path.dirname(__file__))
    repo_root = os.path.abspath(os.path.join(agent_dir, '..'))
    default_db = os.path.join(repo_root, '.local', 'data', 'circle.sqlite')
    parser = ArgumentParser(description='Seed the tenant-safe Circle local lab.',
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument('--db-path', default=os.environ.get('CIRCLE_DB_PATH', default_db))
    parser.add_argument('--rotate-credentials', action='store_true')
    return parser.parse_args(argv)


def seed_principal(store, organization_id, principal_id, display_name, roles, scopes,
                   rotate_credentials=False):
    store.principal_create(principal_id, display_name)
    store.membership_create(organization_id, principal_id, roles, scopes)
    active = store.credential_active_list(organization_id, principal_id)
    if active and not rotate_credentials:
        return '[existing credential retained; use --rotate-credentials to replace it]'
    if active:
        store.credential_revoke_all(organization_id, principal_id)
    token = store.credential_create(organization_id, principal_id)
    return token


def main(argv=None):
    args = parse_args(argv)
    store = Store(args.db_path)
    store.migrate()

    credentials = {}
    organizations = [
        ['org-acme', 'Acme Treasury'],
        ['org-globex', 'Globex Treasury'],
    ]
    for organization_id, name in organizations:
        store.organization_create(organization_id, name)
        requester_id = '%s-requester' % organization_id
        reviewer_id = '%s-reviewer' % organization_id
        credentials[requester_id] = seed_principal(
            store, organization_id, requester_id, '%s Requester' % name,
            ['requester'], REQUESTER_SCOPES, args.rotate_credentials,
        )
        credentials[reviewer_id] = seed_principal(
            store, organization_id, reviewer_id, '%s Reviewer' % name,
            ['reviewer'], REVIEWER_SCOPES, args.rotate_credentials,
        )
        store.wallet_upsert({
            'wallet_id': 'wallet-treasury',
            'organization_id': organization_id,
            'owner_principal_id': requester_id,
            'custody_type': 'developer-controlled',
            'provider': 'simulator',
            'provider_wallet_id': None,
            'address': '0x%s' % ('a' if organization_id == 'org-acme' else 'b') * 40,
            'chain': 'base',
            'asset': 'USDC',
            'balance': '1000',
            'status': 'active',
        })
        subscription_id = '00000000-0000-4000-8000-%012d' % (1 if organization_id == 'org-acme' else 2)
        store.webhook_subscription_upsert('circle', subscription_id, organization_id, 'testnet')

    corpus_dir = os.path.join(os.path.dirname(__file__), 'circle_agent', 'corpus')
    documents = corpus_ingest(store, corpus_dir)
    payload = {
        'database': os.path.abspath(args.db_path),
        'credentials': credentials,
        'policy_documents': len(documents),
        'warning': 'These credentials are local development secrets. They are shown once; do not commit them.',
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
