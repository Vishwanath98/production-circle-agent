#!/usr/bin/env python3

import json
import os
import sys

from argparse import ArgumentParser

from agent_spine.store import Store
from agent_spine.tenant_rag import corpus_ingest


def parse_args(argv=None):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    parser = ArgumentParser(description='Seed the production Onboarding local lab.')
    parser.add_argument('--db-path', default=os.path.join(repo_root, '.local', 'data', 'onboarding.sqlite'))
    parser.add_argument('--rotate-credentials', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    store = Store(args.db_path)
    store.migrate()
    store.organization_create('org-onboarding-acme', 'Acme Messaging')
    credentials = {}
    principals = [
        ['applicant', ['applicant'], ['agent:chat', 'onboarding:read', 'onboarding:submit', 'policy:read', 'mcp:read']],
        ['reviewer', ['compliance'], ['agent:chat', 'onboarding:read', 'onboarding:approval:decide',
                                     'policy:read', 'policy:write']],
    ]
    for suffix, roles, scopes in principals:
        principal_id = 'onboarding-%s' % suffix
        store.principal_create(principal_id, 'Onboarding %s' % suffix.title())
        store.membership_create('org-onboarding-acme', principal_id, roles, scopes)
        active = store.credential_active_list('org-onboarding-acme', principal_id)
        if active and not args.rotate_credentials:
            token = '[existing credential retained; use --rotate-credentials to replace it]'
        else:
            if active:
                store.credential_revoke_all('org-onboarding-acme', principal_id)
            token = store.credential_create('org-onboarding-acme', principal_id)
        credentials[principal_id] = token
    corpus_dir = os.path.join(os.path.dirname(__file__), 'onboarding_agent', 'corpus')
    documents = corpus_ingest(store, corpus_dir, actor_id='onboarding-system')
    print(json.dumps({'database': os.path.abspath(args.db_path), 'credentials': credentials,
                      'policy_documents': len(documents)}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
