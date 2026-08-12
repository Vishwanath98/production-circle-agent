import json
import os

from functools import partial

from pydantic import create_model

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from agent_spine.auth import require_scope
from agent_spine.context import context_from_config
from agent_spine.mcp_client import MCPToolClient


JSON_TYPES = {
    'string': str,
    'number': float,
    'integer': int,
    'boolean': bool,
    'array': list,
    'object': dict,
}


class MCPToolCall:

    def __init__(self, client, remote_name, permission):
        self.client = client
        self.remote_name = remote_name
        self.permission = permission

    def call(self, config, arguments):
        ctx = context_from_config(config)
        require_scope(ctx.principal, self.permission)
        return self.client.call(self.remote_name, arguments)


def mcp_tool_invoke(caller, config: RunnableConfig, **kwargs):
    return caller.call(config, kwargs)


class MCPGateway:

    def __init__(self, config_path):
        self.config_path = os.path.abspath(config_path)
        self.clients = []
        self.adapters = []

    def load(self):
        with open(self.config_path, 'rt') as f:
            config = json.load(f)
        servers = config.get('servers') or []
        base_dir = os.path.dirname(self.config_path)
        for server in servers:
            if not server.get('enabled', False):
                continue
            command = server.get('command')
            args = list(server.get('args') or [])
            cwd = server.get('cwd') or base_dir
            if cwd.startswith('.'):
                cwd = os.path.abspath(os.path.join(base_dir, cwd))
            if command == '${PYTHON}':
                command = os.sys.executable
            resolved_args = []
            for value in args:
                if value.startswith('./'):
                    value = os.path.abspath(os.path.join(base_dir, value))
                resolved_args.append(value)
            client = MCPToolClient(
                timeout=float(server.get('timeout_seconds', 15)), command=command,
                args=resolved_args, cwd=cwd, env=dict(server.get('environment') or {}),
            )
            self.clients.append(client)
            available = client.describe_tools()
            allowed = server.get('allowed_tools') or []
            for specification in available:
                if specification.name not in allowed:
                    continue
                adapter = tool_adapter(server, client, specification)
                self.adapters.append(adapter)
        return list(self.adapters)

    def close(self):
        for client in self.clients:
            client.close()
        self.clients = []
        self.adapters = []


def schema_model(name, schema):
    fields = {}
    required = schema.get('required') or []
    properties = schema.get('properties') or {}
    for field_name, field_schema in properties.items():
        python_type = JSON_TYPES.get(field_schema.get('type'), object)
        default = ... if field_name in required else field_schema.get('default', None)
        fields[field_name] = (python_type, default)
    model_name = '%sInput' % ''.join(part.title() for part in name.split('_'))
    return create_model(model_name, **fields)


def tool_adapter(server, client, specification):
    namespace = server['name'].replace('-', '_')
    public_name = 'mcp_%s_%s' % (namespace, specification.name)
    args_schema = schema_model(public_name, specification.input_schema)
    permission = server.get('permission', 'mcp:read')
    caller = MCPToolCall(client, specification.name, permission)
    invoke = partial(mcp_tool_invoke, caller)
    metadata = {
        'permission': permission,
        'effect': 'read',
        'risk': server.get('risk', 'medium'),
        'provider': 'mcp:%s' % server['name'],
        'timeout_seconds': server.get('timeout_seconds', 15),
        'max_retries': 0,
        'remote_tool': specification.name,
    }
    tool = StructuredTool(
        name=public_name,
        description=specification.description or 'MCP tool %s' % specification.name,
        args_schema=args_schema,
        func=invoke,
        metadata=metadata,
    )
    item = {
        'tool': tool,
        'metadata': metadata,
        'profiles': list(server.get('profiles') or []),
    }
    return item
