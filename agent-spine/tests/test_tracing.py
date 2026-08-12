import unittest

from unittest.mock import patch

from langsmith import Client
from langsmith import tracing_context

from agent_spine import events
from agent_spine.serve import response_body


def account_check(account_id):
    rv = {'account_id': account_id, 'status': 'active'}
    return rv


class InternalTracingTest(unittest.TestCase):

    def test_logic_tool_is_traced_but_not_registered_as_an_llm_tool(self):
        client = Client(
            api_url='https://scrimmage.example.com/api/langsmith',
            api_key='test-key',
            auto_batch_tracing=False,
        )
        traced_check = events.logic_tool(account_check)

        with patch.object(Client, 'create_run', autospec=True) as create_run:
            with patch.object(Client, 'update_run', autospec=True) as update_run:
                with tracing_context(enabled=True, client=client):
                    result = traced_check('acct-1')

        self.assertEqual(result, {'account_id': 'acct-1', 'status': 'active'})
        self.assertTrue(callable(traced_check))
        self.assertFalse(hasattr(traced_check, 'invoke'))
        self.assertFalse(hasattr(traced_check, 'args_schema'))
        create_kwargs = create_run.call_args.kwargs
        self.assertEqual(create_kwargs['name'], 'account_check')
        self.assertEqual(create_kwargs['run_type'], 'tool')
        self.assertEqual(create_kwargs['trace_id'], create_kwargs['id'])
        self.assertTrue(create_kwargs['dotted_order'])
        update_run.assert_called_once()

    def test_legacy_event_buffer_stays_empty(self):
        events.enable()
        events.emit('tool', 'account_check', account_id='acct-1')

        self.assertEqual(events.events(), [])

    def test_http_response_omits_internal_agent_state(self):
        result = {
            'final': {
                'assistant_message': 'Account is active.',
                'status': 'ok',
                'tool_call': None,
                'usage': {'total_tokens': 12},
                'decision': 'active',
                'events': [{'name': 'account_check'}],
                'turns': [{'role': 'assistant'}],
            },
            'events': [{'name': 'duplicate'}],
            'turns': [{'role': 'user'}],
        }

        body = response_body(result)

        self.assertEqual(body['assistant_message'], 'Account is active.')
        self.assertEqual(body['decision'], 'active')
        self.assertNotIn('events', body)
        self.assertNotIn('turns', body)


if __name__ == '__main__':
    unittest.main()
