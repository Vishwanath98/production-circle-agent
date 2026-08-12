import json
import os

from typing import Annotated, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command

from agent_spine import checkpointer
from agent_spine.context import config_make
from agent_spine.model import make_chat_model

from onboarding_agent.production_tools import catalog_build


AGENT_VERSION = 'onboarding-production-lab-1'
PROFILES = ['core-sim', 'rag-sim', 'mcp-sim', 'full-sim']
SYSTEM_PROMPT = """
You are a business onboarding agent. Use tools for applications, policy, and
status. Do not invent approval, account, or verification results. Never request
passwords, API tokens, or private identity secrets. Account provisioning may
pause for an authorized human review. Cite policy sources returned by tools.
""".strip()


class OnboardingState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    final: dict


def profile_validate(profile):
    if profile not in PROFILES:
        raise ValueError('unknown onboarding profile: %s' % profile)
    return profile


def profile_authorize(principal, profile):
    from agent_spine.auth import require_scope

    profile = profile_validate(profile)
    if profile in ['rag-sim', 'full-sim']:
        require_scope(principal, 'policy:read')
    if profile in ['mcp-sim', 'full-sim']:
        require_scope(principal, 'mcp:read')
    return profile


def deterministic_tool_call(message):
    content = message.content if hasattr(message, 'content') else str(message)
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        data = None
    if not isinstance(data, dict):
        return None, None
    action = data.get('action') or data.get('type')
    if action == 'policy':
        return 'onboarding_policy_search', {'query': data.get('query', '')}
    if action == 'status':
        return 'onboarding_application_status', {'application_id': data.get('application_id', '')}
    if action == 'submit':
        args = {
            'business_name': data.get('business_name', ''),
            'business_type': data.get('business_type', ''),
            'email': data.get('email', ''),
            'phone': data.get('phone', ''),
            'use_case': data.get('use_case', ''),
            'monthly_volume': int(data.get('monthly_volume', 0)),
            'idempotency_key': data.get('idempotency_key', ''),
        }
        return 'onboarding_submit_application', args
    return None, None


class AssistantNode:

    def __init__(self, model, tools):
        self.model = model
        self.tools = tools
        self.bound_model = model.bind_tools(tools) if hasattr(model, 'bind_tools') else None

    def __call__(self, state):
        messages = state.get('messages', [])
        last = messages[-1] if messages else HumanMessage(content='')
        if isinstance(last, ToolMessage):
            content = last.content
            tool_failed = getattr(last, 'status', '') == 'error'
            try:
                content = json.dumps(json.loads(content), indent=2, sort_keys=True)
            except (ValueError, TypeError):
                pass
            status = 'error' if tool_failed else 'ok'
            return {'messages': [AIMessage(content=content)],
                    'final': {'assistant_message': content, 'status': status}}
        if self.bound_model is not None:
            response = self.bound_model.invoke([SystemMessage(content=SYSTEM_PROMPT)] + messages)
            return {'messages': [response]}
        tool_name, args = deterministic_tool_call(last)
        if tool_name:
            call = {'name': tool_name, 'args': args, 'id': 'call_%s' % uuid4().hex,
                    'type': 'tool_call'}
            return {'messages': [AIMessage(content='', tool_calls=[call])]}
        content = 'Provide an onboarding application, policy query, or application ID.'
        return {'messages': [AIMessage(content=content)],
                'final': {'assistant_message': content, 'status': 'ok'}}


def build_agent(profile='core-sim', model=None, checkpointer_override=None,
                checkpoint_db=None, ephemeral=False, extra_tools=None):
    profile = profile_validate(profile)
    tools = catalog_build(extra_tools=extra_tools).tools(profile)
    model = model or make_chat_model()
    saver = checkpointer_override
    if saver is None:
        agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        checkpoint_db = checkpoint_db or checkpointer.default_db_path(agent_dir)
        saver = checkpointer.get_checkpointer(checkpoint_db, ephemeral=ephemeral)
    graph = StateGraph(OnboardingState)
    graph.add_node('assistant', AssistantNode(model, tools))
    graph.add_node('tools', ToolNode(tools))
    graph.add_edge(START, 'assistant')
    graph.add_conditional_edges('assistant', tools_condition, ['tools', END])
    graph.add_edge('tools', 'assistant')
    return graph.compile(checkpointer=saver)


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


def run_message(ctx, message, graph=None, model=None):
    graph = graph or build_agent(ctx.profile, model=model)
    config = config_make(ctx)
    result = graph.invoke({'messages': [HumanMessage(content=message)]}, config=config)
    return result_with_interrupts(graph, config, result)


def resume(ctx, resume_value, graph=None, model=None):
    graph = graph or build_agent(ctx.profile, model=model)
    config = config_make(ctx)
    result = graph.invoke(Command(resume=resume_value), config=config)
    return result_with_interrupts(graph, config, result)
