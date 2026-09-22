import json
import os
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.tools import tool

from agent_spine import audit
from agent_spine.actions import action_make, amount_str
from agent_spine.approvals import approval_decide, approval_make
from agent_spine.auth import AuthenticationError, AuthorizationError, Principal, resolve_principal
from agent_spine.checkpointer import default_db_path, get_checkpointer
from agent_spine.context import RuntimeContext, config_make, context_from_config
from agent_spine.mcp_gateway import MCPGateway
from agent_spine.model import config_from_env
from agent_spine.policy import POLICY_VERSION, action_evaluate
from agent_spine.store import Store
from agent_spine.tool_catalog import ToolCatalog


@tool
def foundation_echo(account_id: str) -> dict:
    """Return the supplied account identifier."""
    result = {'account_id': account_id}
    return result


def principal_requester():
    principal = Principal(
        'principal-requester', 'org-one', 'Requester', ['requester'],
        ['circle:read', 'circle:transfer:request'],
    )
    return principal


def runtime_context(principal=None, db_path=''):
    principal = principal or principal_requester()
    ctx = RuntimeContext(
        request_id='req-one', run_id='run-one', thread_id='thread-one',
        principal=principal, agent_name='circle', agent_version='test',
        profile='core-sim', trace_metadata={'suite': 'foundation'}, db_path=db_path,
    )
    return ctx


class FoundationTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'foundation.sqlite')
        self.store = Store(self.db_path)
        self.store.migrate()
        self.store.organization_create('org-one', 'Organization One')
        self.store.organization_create('org-two', 'Organization Two')
        self.store.principal_create('principal-requester', 'Requester')
        self.store.principal_create('principal-reviewer', 'Reviewer')
        self.store.principal_create('principal-other', 'Other Tenant')
        self.store.membership_create(
            'org-one', 'principal-requester', ['requester'],
            ['circle:read', 'circle:transfer:request'],
        )
        self.store.membership_create(
            'org-one', 'principal-reviewer', ['reviewer'],
            ['circle:read', 'circle:approval:decide'],
        )
        self.store.membership_create(
            'org-two', 'principal-other', ['reviewer'],
            ['circle:read', 'circle:approval:decide'],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_hashed_token_resolves_and_plaintext_is_not_stored(self):
        token = self.store.credential_create('org-one', 'principal-requester')

        principal = resolve_principal(self.store, token)
        credential_id = token.split('.', 1)[0][4:]
        row = self.store.credential_get(credential_id)

        self.assertEqual(principal.organization_id, 'org-one')
        self.assertEqual(principal.principal_id, 'principal-requester')
        self.assertNotEqual(row['secret_hash'], token)
        self.assertNotIn(token, dict(row).values())

    def test_expired_and_revoked_tokens_are_rejected(self):
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        expired = self.store.credential_create('org-one', 'principal-requester', expires_at=expired_at)
        active = self.store.credential_create('org-one', 'principal-requester')

        with self.assertRaises(AuthenticationError):
            resolve_principal(self.store, expired)

        credential_id = active.split('.', 1)[0][4:]
        self.store.credential_revoke(credential_id)
        with self.assertRaises(AuthenticationError):
            resolve_principal(self.store, active)

    def test_thread_lookup_is_tenant_scoped(self):
        self.store.thread_upsert('org-one', 'principal-requester', 'same-id', 'core-sim')

        own = self.store.thread_get('org-one', 'same-id')
        foreign = self.store.thread_get('org-two', 'same-id')

        self.assertIsNotNone(own)
        self.assertIsNone(foreign)

    def test_runtime_context_round_trip(self):
        ctx = runtime_context(db_path=self.db_path)

        restored = context_from_config(config_make(ctx))

        self.assertEqual(restored.thread_id, ctx.thread_id)
        self.assertEqual(restored.principal.organization_id, 'org-one')
        self.assertEqual(restored.db_path, self.db_path)

    def test_transfer_policy_requires_approval(self):
        ctx = runtime_context(db_path=self.db_path)
        arguments = {
            'amount': amount_str('125.00'),
            'asset': 'USDC',
            'chain': 'base',
            'compliance_status': 'clear',
            'balance_ok': True,
        }
        action = action_make(
            ctx, 'transfer', 'circle_request_transfer', 'simulator',
            {'source_wallet_id': 'wallet-one'}, arguments, 'high', POLICY_VERSION,
        )

        decision = action_evaluate(ctx.principal, action, resource_organization_id='org-one')

        self.assertEqual(decision.outcome, 'REQUIRE_APPROVAL')
        self.assertEqual(decision.required_reviewer_roles, ['reviewer', 'admin'])

    def test_approval_is_tenant_scoped_and_authorized(self):
        ctx = runtime_context(db_path=self.db_path)
        arguments = {
            'amount': '125', 'asset': 'USDC', 'chain': 'base',
            'compliance_status': 'clear', 'balance_ok': True,
        }
        action = action_make(
            ctx, 'transfer', 'circle_request_transfer', 'simulator',
            {'source_wallet_id': 'wallet-one'}, arguments, 'high', POLICY_VERSION,
        )
        decision = action_evaluate(ctx.principal, action, resource_organization_id='org-one')
        action['status'] = 'pending_approval'
        self.store.action_insert(action)
        approval = approval_make(action, decision)
        self.store.approval_insert(approval)

        foreign = Principal(
            'principal-other', 'org-two', 'Other Tenant', ['reviewer'],
            ['circle:approval:decide'],
        )
        reviewer = Principal(
            'principal-reviewer', 'org-one', 'Reviewer', ['reviewer'],
            ['circle:approval:decide'],
        )

        with self.assertRaises(ValueError):
            approval_decide(self.store, foreign, approval['approval_id'], 'approve', action['action_digest'])

        result = approval_decide(
            self.store, reviewer, approval['approval_id'], 'approve', action['action_digest'], 'approved for test',
        )
        stored_action = self.store.action_get('org-one', action['action_id'])

        self.assertEqual(result['status'], 'approved')
        self.assertEqual(stored_action['status'], 'approved')

    def test_action_digest_rejects_idempotency_reuse(self):
        ctx = runtime_context(db_path=self.db_path)
        first = action_make(
            ctx, 'transfer', 'circle_request_transfer', 'simulator', {},
            {'amount': '10'}, 'high', POLICY_VERSION, idempotency_key='same-key',
        )
        second = action_make(
            ctx, 'transfer', 'circle_request_transfer', 'simulator', {},
            {'amount': '11'}, 'high', POLICY_VERSION, idempotency_key='same-key',
        )
        self.store.action_insert(first)

        with self.assertRaises(ValueError):
            self.store.action_insert(second)

    def test_action_claim_is_exactly_once(self):
        ctx = runtime_context(db_path=self.db_path)
        action = action_make(
            ctx, 'transfer', 'circle_request_transfer', 'simulator', {},
            {'amount': '10'}, 'high', POLICY_VERSION,
        )
        action['status'] = 'approved'
        self.store.action_insert(action)

        first = self.store.action_claim('org-one', action['action_id'], action['action_digest'])
        second = self.store.action_claim('org-one', action['action_id'], action['action_digest'])

        self.assertTrue(first)
        self.assertFalse(second)

    def test_audit_redacts_secret_fields(self):
        ctx = runtime_context(db_path=self.db_path)
        audit.emit(
            self.store, ctx, 'tool_intent', 'wallet', 'wallet-one', 'allowed',
            safe_details={'api_token': 'do-not-store', 'amount': '10'},
        )

        event = self.store.audit_list('org-one', 'thread-one')[0]

        self.assertEqual(event['safe_details']['api_token'], '[REDACTED]')
        self.assertEqual(event['safe_details']['amount'], '10')

    def test_audit_events_are_tenant_scoped(self):
        ctx = runtime_context(db_path=self.db_path)
        audit.emit(self.store, ctx, 'authorization', 'wallet', 'wallet-one', 'allowed', 'scope_granted')

        own = self.store.audit_list('org-one', 'thread-one')
        foreign = self.store.audit_list('org-two', 'thread-one')

        self.assertEqual(len(own), 1)
        self.assertEqual(foreign, [])

    def test_tool_catalog_requires_metadata_and_exposes_manifest(self):
        catalog = ToolCatalog()
        metadata = {
            'permission': 'circle:read',
            'effect': 'read',
            'risk': 'low',
            'provider': 'local',
            'timeout_seconds': 5,
            'max_retries': 0,
        }

        catalog.register(foundation_echo, metadata, ['core-sim'])
        manifest = catalog.manifest()

        self.assertEqual(catalog.tools('core-sim')[0].name, 'foundation_echo')
        self.assertEqual(manifest[0]['metadata']['effect'], 'read')

    def test_durable_checkpointer_and_local_default_path(self):
        db_path = os.path.join(self.temp_dir.name, 'checkpoints.sqlite')

        saver = get_checkpointer(db_path)
        default_path = default_db_path(os.path.join(self.temp_dir.name, 'circle-agent'))

        self.assertEqual(saver.__class__.__name__, 'SqliteSaver')
        self.assertIn(os.path.join('.local', 'data'), default_path)

    def test_openai_loopback_configuration_uses_local_placeholder_key(self):
        env = {
            'LLM_PROVIDER': 'openai',
            'OPENAI_BASE_URL': 'http://127.0.0.1:1234/v1',
            'OPENAI_MODEL': 'local-test-model',
            'OPENAI_API_KEY': '',
            'LOCAL_LLM_API_KEY': '',
            'CF_AIG_TOKEN': '',
        }
        with patch.dict(os.environ, env, clear=False):
            config = config_from_env()

        self.assertEqual(config.provider, 'openai')
        self.assertEqual(config.model, 'local-test-model')
        self.assertEqual(config.api_key, 'local-development')

    def test_mcp_gateway_loads_allowlisted_streamable_http_tools(self):
        config_path = os.path.join(self.temp_dir.name, 'mcp.json')
        config = {
            'servers': [{
                'name': 'circle-docs',
                'enabled': True,
                'url': 'https://api.circle.com/v1/codegen/mcp',
                'allowed_tools': ['search_circle_documentation'],
                'profiles': ['full-sim'],
                'permission': 'mcp:read',
                'timeout_seconds': 30,
            }],
        }
        with open(config_path, 'wt') as f:
            json.dump(config, f)
        specification = SimpleNamespace(
            name='search_circle_documentation',
            description='Search Circle documentation.',
            input_schema={
                'type': 'object',
                'properties': {'query': {'type': 'string'}},
                'required': ['query'],
            },
        )
        client = SimpleNamespace(describe_tools=lambda: [specification], close=lambda: None)

        with patch('agent_spine.mcp_gateway.MCPToolClient', return_value=client) as client_class:
            tools = MCPGateway(config_path).load()

        call = client_class.call_args.kwargs
        self.assertEqual(call['url'], 'https://api.circle.com/v1/codegen/mcp')
        self.assertEqual(call['command'], None)
        self.assertEqual(tools[0]['tool'].name, 'mcp_circle_docs_search_circle_documentation')
        self.assertEqual(tools[0]['profiles'], ['full-sim'])


if __name__ == '__main__':
    unittest.main()
