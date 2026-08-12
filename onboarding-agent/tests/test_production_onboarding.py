import json
import os
import tempfile
import threading
import unittest

import requests

from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from agent_spine.approvals import approval_decide
from agent_spine.auth import Principal
from agent_spine.context import RuntimeContext
from agent_spine.mock_llm import MockLLM
from agent_spine.store import Store

from onboarding_agent.production import build_agent, resume, run_message
from onboarding_agent.production_api import OnboardingApplication, OnboardingHttpServer
from onboarding_agent.production_service import application_propose
from onboarding_agent.production_tools import catalog_build


class ProductionOnboardingTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'onboarding.sqlite')
        self.store = Store(self.db_path)
        self.store.migrate()
        for organization_id in ['org-one', 'org-two']:
            self.store.organization_create(organization_id, organization_id)
            self.store.principal_create('%s-applicant' % organization_id, 'Applicant')
            self.store.principal_create('%s-reviewer' % organization_id, 'Reviewer')
            self.store.membership_create(
                organization_id, '%s-applicant' % organization_id, ['applicant'],
                ['agent:chat', 'onboarding:read', 'onboarding:submit', 'policy:read'],
            )
            self.store.membership_create(
                organization_id, '%s-reviewer' % organization_id, ['compliance'],
                ['onboarding:read', 'onboarding:approval:decide', 'policy:read'],
            )
        self.applicant = Principal(
            'org-one-applicant', 'org-one', 'Applicant', ['applicant'],
            ['agent:chat', 'onboarding:read', 'onboarding:submit', 'policy:read'],
        )
        self.reviewer = Principal(
            'org-one-reviewer', 'org-one', 'Reviewer', ['compliance'],
            ['onboarding:read', 'onboarding:approval:decide', 'policy:read'],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def context(self, organization='org-one', thread='thread-one'):
        principal = self.applicant
        if organization == 'org-two':
            principal = Principal(
                'org-two-applicant', 'org-two', 'Other', ['applicant'],
                ['agent:chat', 'onboarding:read', 'onboarding:submit', 'policy:read'],
            )
        return RuntimeContext('req', 'run', thread, principal, 'onboarding', 'test',
                              'core-sim', db_path=self.db_path)

    def test_tools_are_native_and_runtime_context_is_hidden(self):
        tools = catalog_build().tools('core-sim')
        submit = [item for item in tools if item.name == 'onboarding_submit_application'][0]
        self.assertTrue(all(isinstance(item, BaseTool) for item in tools))
        self.assertNotIn('config', submit.args)

    def test_application_requires_human_approval_then_provisions_once(self):
        ctx = self.context()
        graph = build_agent('core-sim', model=MockLLM(), checkpointer_override=MemorySaver())
        message = json.dumps({
            'action': 'submit', 'business_name': 'Acme Logistics',
            'business_type': 'LLC', 'email': 'ops@acme.example',
            'phone': '+15555550100', 'use_case': 'Transactional delivery alerts',
            'monthly_volume': 50000,
        })
        first = run_message(ctx, message, graph=graph)
        pending = first['__interrupt__'][0].value
        approval = self.store.approval_get('org-one', pending['approval_id'])

        approval_decide(self.store, self.reviewer, approval['approval_id'], 'approve',
                        approval['action_digest'], 'KYB reviewed')
        second = resume(ctx, {'approval_id': approval['approval_id']}, graph=graph)
        application = self.store.onboarding_application_get('org-one', pending['application_id'])
        action = self.store.action_get('org-one', approval['action_id'])

        self.assertEqual(application['status'], 'approved')
        self.assertTrue(application['account_id'].startswith('AC'))
        self.assertEqual(action['status'], 'succeeded')
        self.assertGreaterEqual(len(second['messages']), 4)

    def test_restricted_use_case_denies_without_approval(self):
        proposal = application_propose(
            self.context(), 'Risky LLC', 'LLC', 'ops@risky.example', '+15555550100',
            'Bulk gambling promotional spam', 10000,
        )
        self.assertEqual(proposal['decision'].outcome, 'DENY')
        self.assertEqual(proposal['application']['status'], 'rejected')
        self.assertIsNone(proposal['approval'])

    def test_same_application_id_is_not_visible_cross_tenant(self):
        proposal = application_propose(
            self.context(), 'Acme Logistics', 'LLC', 'ops@acme.example', '+15555550100',
            'Transactional delivery alerts', 10000,
        )
        application_id = proposal['application']['application_id']
        self.assertIsNotNone(self.store.onboarding_application_get('org-one', application_id))
        self.assertIsNone(self.store.onboarding_application_get('org-two', application_id))

    def test_authenticated_http_chat_uses_production_graph(self):
        token = self.store.credential_create('org-one', 'org-one-applicant')
        checkpoint_db = os.path.join(self.temp_dir.name, 'checkpoints.sqlite')
        app = OnboardingApplication(self.db_path, checkpoint_db, model=MockLLM())
        server = OnboardingHttpServer(('127.0.0.1', 0), app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = 'http://127.0.0.1:%s' % server.server_address[1]
        headers = {'Authorization': 'Bearer %s' % token}
        message = json.dumps({
            'action': 'submit', 'business_name': 'Acme Logistics',
            'business_type': 'LLC', 'email': 'ops@acme.example',
            'phone': '+15555550100', 'use_case': 'Transactional delivery alerts',
            'monthly_volume': 50000,
        })
        try:
            response = requests.post(
                '%s/chat' % base_url,
                json={'thread_id': 'http-thread', 'profile': 'core-sim', 'message': message},
                headers=headers, timeout=5,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'approval_required')
            self.assertEqual(response.json()['approval']['domain'], 'onboarding')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
