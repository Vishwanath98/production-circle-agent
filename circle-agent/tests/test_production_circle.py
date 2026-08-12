import base64
import json
import os
import tempfile
import threading
import unittest

from unittest.mock import patch

import requests

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from agent_spine.approvals import approval_decide
from agent_spine.actions import action_make
from agent_spine.auth import Principal
from agent_spine.context import RuntimeContext
from agent_spine.mock_llm import MockLLM
from agent_spine.mcp_gateway import MCPGateway
from agent_spine.policy import POLICY_VERSION
from agent_spine.store import Store

from circle_agent.agent import build_agent, resume, run_message
from circle_agent.api import CircleApplication, CircleHttpServer
from circle_agent.circle_provider import CircleTestnetProvider, uuid_v4_for_key
from circle_agent.rag_service import document_ingest, policy_search
from circle_agent.service import transfer_propose
from circle_agent.tools import catalog_build
from circle_agent.webhooks import CircleWebhookVerifier, webhook_process
from circle_agent.x402_provider import payment_prepare, requirement_inspect


class FakeCircleGateway:

    def wallet_balances(self, provider_wallet_id):
        return {'data': {'tokenBalances': [{'amount': '50', 'token': {'symbol': 'USDC'}}]}}

    def submit_transfer(self, provider_wallet_id, token_id, amount, destination,
                        idempotency_key, request_id):
        self.last_idempotency_key = idempotency_key
        return {'data': {'id': '11111111-1111-4111-8111-111111111111', 'state': 'INITIATED'}}

    def transaction(self, provider_reference, request_id):
        return {'data': {'transaction': {'id': provider_reference, 'state': 'CONFIRMED'}}}


class ProductionCircleTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'circle.sqlite')
        self.store = Store(self.db_path)
        self.store.migrate()
        for organization_id in ['org-one', 'org-two']:
            self.store.organization_create(organization_id, organization_id)
            requester_id = '%s-requester' % organization_id
            reviewer_id = '%s-reviewer' % organization_id
            self.store.principal_create(requester_id, 'Requester')
            self.store.principal_create(reviewer_id, 'Reviewer')
            self.store.membership_create(
                organization_id, requester_id, ['requester'],
                ['agent:chat', 'circle:read', 'circle:transfer:request', 'policy:read',
                 'mcp:read', 'x402:read', 'x402:pay:request'],
            )
            self.store.membership_create(
                organization_id, reviewer_id, ['reviewer'],
                ['agent:chat', 'circle:read', 'circle:approval:decide', 'policy:read'],
            )
            self.store.wallet_upsert({
                'wallet_id': 'wallet-treasury', 'organization_id': organization_id,
                'owner_principal_id': requester_id, 'custody_type': 'developer-controlled',
                'provider': 'simulator', 'provider_wallet_id': None,
                'address': '0x%s' % ('a' if organization_id == 'org-one' else 'b') * 40,
                'chain': 'base', 'asset': 'USDC',
                'balance': '1000' if organization_id == 'org-one' else '7', 'status': 'active',
            })
        self.requester = Principal(
            'org-one-requester', 'org-one', 'Requester', ['requester'],
            ['agent:chat', 'circle:read', 'circle:transfer:request', 'policy:read',
             'mcp:read', 'x402:read', 'x402:pay:request'],
        )
        self.reviewer = Principal(
            'org-one-reviewer', 'org-one', 'Reviewer', ['reviewer'],
            ['agent:chat', 'circle:read', 'circle:approval:decide', 'policy:read'],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def context(self, thread_id='thread-one', profile='core-sim'):
        return RuntimeContext(
            'request-one', 'run-one', thread_id, self.requester,
            'circle', 'test', profile, db_path=self.db_path,
        )

    def test_native_tools_and_model_schema_hide_runtime_config(self):
        catalog = catalog_build()
        tools = catalog.tools('core-sim')
        transfer = [item for item in tools if item.name == 'circle_request_transfer'][0]

        self.assertTrue(all(isinstance(item, BaseTool) for item in tools))
        self.assertNotIn('config', transfer.args)
        self.assertEqual(transfer.metadata, None)
        manifest = [item for item in catalog.manifest() if item['name'] == 'circle_request_transfer'][0]
        self.assertEqual(manifest['metadata']['effect'], 'financial')

    def test_hitl_resume_executes_once_and_preserves_thread_state(self):
        ctx = self.context()
        graph = build_agent('core-sim', model=MockLLM(), checkpointer_override=MemorySaver())
        message = json.dumps({
            'action': 'transfer', 'source_wallet_id': 'wallet-treasury', 'amount': '10',
            'asset': 'USDC', 'chain': 'base', 'destination': '0x' + 'c' * 40,
        })
        first = run_message(ctx, message, graph=graph)
        pending = first['__interrupt__'][0].value
        approval = self.store.approval_get('org-one', pending['approval_id'])

        approval_decide(
            self.store, self.reviewer, approval['approval_id'], 'approve',
            approval['action_digest'], 'approved test payment',
        )
        second = resume(ctx, {'approval_id': approval['approval_id']}, graph=graph)
        action = self.store.action_get('org-one', approval['action_id'])
        duplicate_attempt = self.store.action_claim('org-one', action['action_id'], action['action_digest'])

        self.assertEqual(action['status'], 'submitted')
        self.assertFalse(duplicate_attempt)
        self.assertEqual(self.store.wallet_get('org-one', 'wallet-treasury')['balance'], '989.99')
        self.assertGreaterEqual(len(second['messages']), 4)

    def test_insufficient_balance_denies_without_approval_or_effect(self):
        foreign = Principal(
            'org-two-requester', 'org-two', 'Requester', ['requester'],
            ['circle:read', 'circle:transfer:request'],
        )
        ctx = RuntimeContext('r', 'run', 't', foreign, 'circle', 'test', 'core-sim', db_path=self.db_path)
        proposal = transfer_propose(
            ctx, 'wallet-treasury', '10', 'USDC', 'base', '0x' + 'd' * 40,
        )

        self.assertEqual(proposal['action']['status'], 'denied')
        self.assertEqual(proposal['decision'].reason_code, 'insufficient_balance')
        self.assertIsNone(proposal['approval'])
        self.assertEqual(self.store.wallet_get('org-two', 'wallet-treasury')['balance'], '7')

    def test_provider_failure_is_failed_not_simulated_success(self):
        ctx = self.context(thread_id='failure-thread')
        graph = build_agent('core-sim', model=MockLLM(), checkpointer_override=MemorySaver())
        message = json.dumps({
            'action': 'transfer', 'source_wallet_id': 'wallet-treasury', 'amount': '10',
            'asset': 'USDC', 'chain': 'base', 'destination': '0x' + 'c' * 40,
            'simulate_failure': True,
        })
        first = run_message(ctx, message, graph=graph)
        pending = first['__interrupt__'][0].value
        approval = self.store.approval_get('org-one', pending['approval_id'])
        approval_decide(self.store, self.reviewer, approval['approval_id'], 'approve',
                        approval['action_digest'], 'exercise provider failure')
        second = resume(ctx, {'approval_id': approval['approval_id']}, graph=graph)
        action = self.store.action_get('org-one', approval['action_id'])

        self.assertEqual((second.get('final') or {}).get('status'), 'error')
        self.assertEqual(action['status'], 'failed')
        self.assertEqual(self.store.wallet_get('org-one', 'wallet-treasury')['balance'], '1000')

    def test_wallet_and_rag_are_hard_tenant_scoped(self):
        document_ingest(
            self.store, 'org-one', 'private-one.md', '1',
            '# Secret\nAcme launch codename is ORCHID.', 'org-one-reviewer',
        )
        one = policy_search(self.context(), 'Acme ORCHID launch')
        other_principal = Principal('org-two-requester', 'org-two', 'Other', ['requester'], ['policy:read'])
        other_ctx = RuntimeContext('r2', 'run2', 't2', other_principal, 'circle', 'test',
                                   'rag-sim', db_path=self.db_path)
        two = policy_search(other_ctx, 'Acme ORCHID launch')

        self.assertTrue(one['grounded'])
        self.assertEqual(one['citations'][0]['organization_id'], 'org-one')
        self.assertFalse(two['grounded'])
        self.assertEqual(self.store.wallet_get('org-one', 'wallet-treasury')['balance'], '1000')
        self.assertEqual(self.store.wallet_get('org-two', 'wallet-treasury')['balance'], '7')

    def test_rag_profile_pins_authorized_policy_evidence_into_action(self):
        document_ingest(
            self.store, 'org-one', 'transfer-policy.md', '7',
            '# USDC transfers\nUSDC transfer compliance requires balance review and human approval on Base.',
            'org-one-reviewer',
        )
        proposal = transfer_propose(
            self.context(profile='rag-sim'), 'wallet-treasury', '10', 'USDC',
            'base', '0x' + 'd' * 40,
        )
        arguments = proposal['action']['normalized_arguments']

        self.assertEqual(proposal['decision'].outcome, 'REQUIRE_APPROVAL')
        self.assertTrue(arguments['policy_grounded'])
        self.assertEqual(arguments['policy_evidence'][0]['version'], '7')

    def test_explicit_memory_is_principal_scoped_and_soft_deletable(self):
        memory_id = self.store.memory_add(
            'org-one', 'org-one-requester', 'thread-one', 'user_note',
            'Use the treasury wallet.', 'private', 'user_explicit',
        )
        own = self.store.memory_list('org-one', 'org-one-requester')
        other_principal = self.store.memory_list('org-one', 'org-one-reviewer')
        other_tenant = self.store.memory_list('org-two', 'org-two-requester')

        self.assertEqual([item['memory_id'] for item in own], [memory_id])
        self.assertEqual(other_principal, [])
        self.assertEqual(other_tenant, [])
        self.assertTrue(self.store.memory_delete('org-one', 'org-one-requester', memory_id))
        self.assertEqual(self.store.memory_list('org-one', 'org-one-requester'), [])

    def test_circle_sdk_adapter_uses_uuid_v4_and_normalized_status(self):
        self.store.wallet_upsert({
            'wallet_id': 'wallet-circle', 'organization_id': 'org-one',
            'owner_principal_id': 'org-one-requester', 'custody_type': 'developer-controlled',
            'provider': 'circle-testnet', 'provider_wallet_id': 'provider-wallet',
            'address': '0x' + 'e' * 40, 'chain': 'base', 'asset': 'USDC',
            'balance': '50', 'status': 'active',
        })
        gateway = FakeCircleGateway()
        provider = CircleTestnetProvider(self.store, gateway=gateway)
        arguments = {
                'source_wallet_id': 'wallet-circle', 'amount': '5', 'asset': 'USDC',
                'chain': 'base', 'destination': '0x' + 'f' * 40,
        }
        action = action_make(
            self.context(profile='full-testnet'), 'transfer', 'circle_request_transfer',
            'circle-testnet', {'source_wallet_id': 'wallet-circle'}, arguments,
            'high', POLICY_VERSION, idempotency_key='stable-key',
        )
        action['status'] = 'approved'
        self.store.action_insert(action)
        with patch.dict(os.environ, {'CIRCLE_TESTNET_USDC_TOKEN_ID': 'token-usdc'}, clear=False):
            transaction = provider.submit_transfer(action)
            final = provider.transaction_status('org-one', transaction['transaction_id'])

        self.assertEqual(gateway.last_idempotency_key, uuid_v4_for_key('stable-key'))
        self.assertEqual(gateway.last_idempotency_key[14], '4')
        self.assertEqual(final['normalized_status'], 'confirmed')

    def test_mcp_v2_gateway_is_allowlisted_namespaced_and_authorized(self):
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mcp_servers.json'))
        gateway = MCPGateway(config_path)
        try:
            items = gateway.load()
            names = [item['tool'].name for item in items]
            self.assertEqual(names, [
                'mcp_circle_risk_validate_address',
                'mcp_circle_risk_sanctions_screen',
                'mcp_circle_risk_chain_analytics',
            ])
            ctx = self.context(profile='mcp-sim')
            result = items[0]['tool'].invoke(
                {'address': '0x' + 'a' * 40, 'chain': 'base'},
                config={'configurable': {'thread_id': ctx.thread_id,
                                          'runtime_context': ctx.to_dict()}},
            )
            self.assertTrue(result['valid'])

            denied = Principal('denied', 'org-one', 'Denied', ['requester'], [])
            denied_ctx = RuntimeContext('r', 'run', 't', denied, 'circle', 'test',
                                        'mcp-sim', db_path=self.db_path)
            with self.assertRaises(Exception):
                items[0]['tool'].invoke(
                    {'address': '0x' + 'a' * 40, 'chain': 'base'},
                    config={'configurable': {'thread_id': 't',
                                              'runtime_context': denied_ctx.to_dict()}},
                )
        finally:
            gateway.close()

    def test_webhook_signature_mapping_and_deduplication(self):
        subscription_id = '00000000-0000-4000-8000-000000000001'
        self.store.webhook_subscription_upsert('circle', subscription_id, 'org-one')
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_der = private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_text = base64.b64encode(public_der).decode('ascii')
        payload = {
            'subscriptionId': subscription_id,
            'notificationId': 'notification-one',
            'notificationType': 'transactions.outbound',
            'notification': {'id': 'unknown-provider-transaction', 'state': 'CONFIRMED'},
        }
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        signature = private_key.sign(body, ec.ECDSA(hashes.SHA256()))
        signature_text = base64.b64encode(signature).decode('ascii')
        verifier = CircleWebhookVerifier(key_resolver=lambda key_id: public_text)

        first = webhook_process(self.store, body, signature_text, 'key-one', verifier)
        second = webhook_process(self.store, body, signature_text, 'key-one', verifier)

        self.assertEqual(first['status'], 'processed')
        self.assertEqual(second['status'], 'duplicate')
        with self.assertRaises(ValueError):
            webhook_process(self.store, body + b' ', signature_text, 'key-one', verifier)

    def test_x402_is_testnet_only_and_uses_stable_requirement_digest(self):
        requirement = {
            'scheme': 'exact', 'network': 'eip155:84532', 'asset': 'USDC',
            'amount': '1.25', 'resource': 'https://merchant.example/data',
            'pay_to': '0x' + 'c' * 40, 'source_wallet_id': 'wallet-treasury',
        }
        first = payment_prepare(self.context(profile='x402-testnet'), requirement)
        second = payment_prepare(self.context(profile='x402-testnet'), requirement)

        self.assertEqual(first['chain'], 'base')
        self.assertEqual(first['idempotency_key'], second['idempotency_key'])
        with self.assertRaises(ValueError):
            requirement_inspect(dict(requirement, network='eip155:8453'))

    def test_http_session_chat_and_cross_tenant_thread_denial(self):
        token = self.store.credential_create('org-one', 'org-one-requester')
        checkpoint_db = os.path.join(self.temp_dir.name, 'checkpoints.sqlite')
        app = CircleApplication(self.db_path, checkpoint_db, model=MockLLM())
        server = CircleHttpServer(('127.0.0.1', 0), app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = 'http://127.0.0.1:%s' % server.server_address[1]
        session = requests.Session()
        try:
            login = session.post('%s/api/v1/sessions' % base_url, json={'token': token}, timeout=5)
            self.assertEqual(login.status_code, 201)
            csrf = login.json()['csrf_token']
            headers = {'X-CSRF-Token': csrf}
            created = session.post(
                '%s/api/v1/threads' % base_url,
                json={'profile': 'core-sim', 'title': 'Balance'}, headers=headers, timeout=5,
            )
            thread_id = created.json()['thread_id']
            response = session.post(
                '%s/api/v1/threads/%s/messages' % (base_url, thread_id),
                json={'profile': 'core-sim', 'message': '{"action":"balance"}'},
                headers=headers, timeout=5,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('1000', response.json()['message'])

            self.store.thread_upsert('org-two', 'org-two-requester', 'foreign-thread', 'core-sim')
            hidden = session.get('%s/api/v1/threads/foreign-thread/messages' % base_url, timeout=5)
            self.assertEqual(hidden.status_code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
