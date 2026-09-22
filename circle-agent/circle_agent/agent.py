import json
import os
import re

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command

from agent_spine import checkpointer
from agent_spine.context import config_make
from agent_spine.model import make_chat_model

from circle_agent.profiles import profile_get
from circle_agent.state import CircleState
from circle_agent.tools import catalog_build


AGENT_VERSION = 'circle-production-lab-1'

SYSTEM_PROMPT = """
You are a Circle USDC operations agent. Use tools instead of guessing about
wallets, transactions, policy, or transfer results. Never claim a financial
effect completed until the tool returns a submitted or final transaction.
Respect authorization and approval results. Cite policy sources returned by
the policy search tool. Use Circle MCP documentation tools for current product
capabilities, supported networks, and SDK implementation details, never for
wallet balances or transaction state. Do not ask for secrets, private keys,
entity secrets, or API tokens. Keep financial amounts and transaction states exact.
""".strip()


def deterministic_tool_call(message, profile):
    content = message.content if hasattr(message, 'content') else str(message)
    data = None
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        action = data.get('action') or data.get('type')
        if action == 'balance':
            return 'circle_wallet_balance', {'source_wallet_id': data.get('source_wallet_id', 'wallet-treasury')}
        if action == 'status':
            return 'circle_transaction_status', {'transaction_id': data.get('transaction_id', '')}
        if action == 'policy':
            return 'circle_policy_search', {'query': data.get('query', '')}
        if action == 'transfer':
            args = {
                'source_wallet_id': data.get('source_wallet_id', 'wallet-treasury'),
                'amount': str(data.get('amount') or data.get('amount_usdc') or '0'),
                'asset': data.get('asset', 'USDC'),
                'chain': data.get('chain', 'base'),
                'destination': data.get('destination') or data.get('recipient_address') or '',
                'idempotency_key': data.get('idempotency_key', ''),
                'simulate_failure': bool(data.get('simulate_failure', False)),
                'simulate_status': data.get('simulate_status', ''),
            }
            return 'circle_request_transfer', args

    lower = content.lower()
    if 'policy' in lower or 'travel rule' in lower:
        return 'circle_policy_search', {'query': content}
    if 'balance' in lower:
        return 'circle_wallet_balance', {'source_wallet_id': 'wallet-treasury'}
    amount_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(?:usdc)?', lower)
    address_match = re.search(r'0x[0-9a-fA-F]{40}', content)
    if amount_match and address_match:
        args = {
            'source_wallet_id': 'wallet-treasury',
            'amount': amount_match.group(1),
            'asset': 'USDC',
            'chain': 'base',
            'destination': address_match.group(0),
        }
        return 'circle_request_transfer', args
    return None, None


class AssistantNode:

    def __init__(self, model, tools, profile):
        self.model = model
        self.tools = tools
        self.profile = profile
        self.bound_model = model.bind_tools(tools) if hasattr(model, 'bind_tools') else None

    def __call__(self, state):
        messages = state.get('messages', [])
        last = messages[-1] if messages else HumanMessage(content='')
        if isinstance(last, ToolMessage):
            content = last.content
            tool_failed = getattr(last, 'status', '') == 'error'
            try:
                data = json.loads(content)
                content = json.dumps(data, indent=2, sort_keys=True)
            except (ValueError, TypeError):
                pass
            response = AIMessage(content=content)
            status = 'error' if tool_failed else 'ok'
            return {'messages': [response], 'final': {'assistant_message': content, 'status': status}}

        if self.bound_model is not None:
            prompt_messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
            response = self.bound_model.invoke(prompt_messages)
            return {'messages': [response]}

        tool_name, args = deterministic_tool_call(last, self.profile)
        if tool_name:
            call = {'name': tool_name, 'args': args, 'id': 'call_%s' % uuid4().hex, 'type': 'tool_call'}
            response = AIMessage(content='', tool_calls=[call])
            return {'messages': [response]}
        response = AIMessage(content='Please provide a wallet balance, policy, transaction status, or USDC transfer request.')
        return {'messages': [response], 'final': {'assistant_message': response.content, 'status': 'ok'}}


def route_after_assistant(state):
    route = tools_condition(state)
    return route


def build_agent(profile='core-sim', model=None, checkpointer_override=None,
                checkpoint_db=None, ephemeral=False, extra_tools=None):
    profile_data = profile_get(profile)
    profile_name = profile_data['name']
    catalog = catalog_build(extra_tools=extra_tools)
    tools = catalog.tools(profile_name)
    model = model or make_chat_model()
    assistant = AssistantNode(model, tools, profile_name)

    if checkpointer_override is not None:
        saver = checkpointer_override
    else:
        if checkpoint_db is None:
            agent_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            checkpoint_db = checkpointer.default_db_path(agent_root)
        saver = checkpointer.get_checkpointer(checkpoint_db, ephemeral=ephemeral)

    graph = StateGraph(CircleState)
    graph.add_node('assistant', assistant)
    graph.add_node('tools', ToolNode(tools))
    graph.add_edge(START, 'assistant')
    graph.add_conditional_edges('assistant', route_after_assistant, ['tools', END])
    graph.add_edge('tools', 'assistant')
    compiled = graph.compile(checkpointer=saver)
    return compiled


def run_message(ctx, message, model=None, graph=None):
    graph = graph or build_agent(profile=ctx.profile, model=model)
    config = config_make(ctx)
    result = graph.invoke({'messages': [HumanMessage(content=message)]}, config=config)
    return result_with_interrupts(graph, config, result)


def resume(ctx, resume_value, model=None, graph=None):
    graph = graph or build_agent(profile=ctx.profile, model=model)
    config = config_make(ctx)
    result = graph.invoke(Command(resume=resume_value), config=config)
    return result_with_interrupts(graph, config, result)


def result_with_interrupts(graph, config, result):
    if result.get('__interrupt__'):
        return result
    snapshot = graph.get_state(config)
    interrupts = []
    for task in snapshot.tasks:
        for item in task.interrupts:
            interrupts.append(item)
    if interrupts:
        result = dict(result)
        result['__interrupt__'] = interrupts
    return result
