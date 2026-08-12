from langchain_core.tools import BaseTool


REQUIRED_METADATA = ['permission', 'effect', 'risk', 'provider', 'timeout_seconds', 'max_retries']


class ToolCatalog:

    def __init__(self):
        self.entries = {}

    def register(self, tool, metadata, profiles):
        if not isinstance(tool, BaseTool):
            raise TypeError('registered tool must be a LangChain BaseTool')
        if tool.name in self.entries:
            raise ValueError('duplicate tool name: %s' % tool.name)
        for key in REQUIRED_METADATA:
            if key not in metadata:
                raise ValueError('tool %s is missing metadata: %s' % (tool.name, key))
        if tool.args_schema is None:
            raise ValueError('tool %s has no argument schema' % tool.name)
        entry = {
            'tool': tool,
            'metadata': dict(metadata),
            'profiles': list(profiles),
        }
        self.entries[tool.name] = entry
        return tool

    def tools(self, profile):
        tools = []
        for entry in self.entries.values():
            if profile in entry['profiles']:
                tools.append(entry['tool'])
        return tools

    def manifest(self):
        rows = []
        names = sorted(self.entries.keys())
        for name in names:
            entry = self.entries[name]
            row = {
                'name': name,
                'description': entry['tool'].description,
                'input_schema': entry['tool'].args_schema.model_json_schema(),
                'metadata': dict(entry['metadata']),
                'profiles': list(entry['profiles']),
            }
            rows.append(row)
        return rows
