import os

from urllib.parse import urlparse


class ModelConfigurationError(Exception):
    pass


class ModelConfig:

    def __init__(self, provider, model, base_url='', api_key='', temperature=0.1,
                 timeout=120, max_retries=2, max_tokens=2048, default_headers=None):
        self.provider = provider
        self.model = model
        self.base_url = base_url or ''
        self.api_key = api_key or ''
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.max_tokens = int(max_tokens)
        self.default_headers = dict(default_headers or {})

    def safe_dict(self):
        data = {
            'provider': self.provider,
            'model': self.model,
            'base_url': self.base_url,
            'temperature': self.temperature,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
            'max_tokens': self.max_tokens,
            'default_headers': sorted(self.default_headers.keys()),
        }
        return data


def loopback_url(url):
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.hostname in ['127.0.0.1', '::1', 'localhost']


def config_from_env(provider=None, model=None, temperature=0.1, api_key=None):
    provider = provider or os.getenv('LLM_PROVIDER', 'openai')
    if provider == 'local':
        provider = 'openai'

    if provider == 'fake':
        config = ModelConfig('fake', model or 'agent-spine-fake', temperature=temperature)
        return config

    if provider == 'anthropic':
        config = ModelConfig(
            provider='anthropic',
            model=model or os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-5'),
            api_key=api_key or os.getenv('ANTHROPIC_API_KEY', ''),
            temperature=temperature,
            timeout=os.getenv('ANTHROPIC_TIMEOUT', '120'),
            max_retries=os.getenv('ANTHROPIC_MAX_RETRIES', '2'),
            max_tokens=os.getenv('ANTHROPIC_MAX_TOKENS', '2048'),
        )
        return config

    if provider != 'openai':
        raise ModelConfigurationError('LLM_PROVIDER must be openai, fake, or anthropic')

    base_url = os.getenv('OPENAI_BASE_URL') or os.getenv('LOCAL_LLM_BASE_URL') or ''
    openai_key = api_key or os.getenv('OPENAI_API_KEY') or os.getenv('LOCAL_LLM_API_KEY') or ''
    cf_token = os.getenv('CF_AIG_TOKEN', '')
    headers = {}
    if cf_token:
        headers = {
            'cf-aig-authorization': 'Bearer %s' % cf_token,
            'cf-aig-collect-log-payload': os.getenv('CF_AIG_COLLECT_LOG_PAYLOAD', 'false'),
            'Authorization': '',
        }
        openai_key = openai_key or 'cf-aig-gateway'
    if not openai_key and loopback_url(base_url):
        openai_key = 'local-development'
    if not openai_key:
        raise ModelConfigurationError('OPENAI_API_KEY is required for non-loopback OpenAI endpoints')

    config = ModelConfig(
        provider='openai',
        model=model or os.getenv('OPENAI_MODEL') or os.getenv('LOCAL_LLM_MODEL') or 'local-model',
        base_url=base_url,
        api_key=openai_key,
        temperature=temperature,
        timeout=os.getenv('OPENAI_TIMEOUT', '120'),
        max_retries=os.getenv('OPENAI_MAX_RETRIES', '2'),
        max_tokens=os.getenv('OPENAI_MAX_TOKENS', '2048'),
        default_headers=headers,
    )
    return config


def make_chat_model(config=None, callbacks=None):
    config = config or config_from_env()
    if config.provider == 'fake':
        from agent_spine.mock_llm import MockLLM
        return MockLLM()

    if config.provider == 'anthropic':
        from langchain_anthropic import ChatAnthropic
        if not config.api_key:
            raise ModelConfigurationError('ANTHROPIC_API_KEY is required')
        params = {
            'model': config.model,
            'api_key': config.api_key,
            'temperature': config.temperature,
            'timeout': config.timeout,
            'max_retries': config.max_retries,
            'max_tokens': config.max_tokens,
        }
        if callbacks:
            params['callbacks'] = callbacks
        model = ChatAnthropic(**params)
        return model

    from langchain_openai import ChatOpenAI

    params = {
        'model': config.model,
        'api_key': config.api_key,
        'temperature': config.temperature,
        'timeout': config.timeout,
        'max_retries': config.max_retries,
        'max_tokens': config.max_tokens,
    }
    if config.base_url:
        params['base_url'] = config.base_url
    if config.default_headers:
        params['default_headers'] = config.default_headers
    if callbacks:
        params['callbacks'] = callbacks
    model = ChatOpenAI(**params)
    return model


def make_llm(model=None, temperature=0.1, api_key=None, callbacks=None):
    config = config_from_env(model=model, temperature=temperature, api_key=api_key)
    llm = make_chat_model(config=config, callbacks=callbacks)
    return llm


def probe_model(model, tool=None):
    from langchain_core.messages import HumanMessage

    result = {
        'chat': False,
        'tool_binding': False,
        'tool_call': False,
        'usage_metadata': False,
        'errors': [],
    }
    try:
        response = model.invoke([HumanMessage(content='Reply with exactly OK.')])
        result['chat'] = bool(getattr(response, 'content', None))
        result['usage_metadata'] = bool(getattr(response, 'usage_metadata', None))
    except Exception as exc:
        result['errors'].append('chat: %s' % exc)

    if tool is not None:
        try:
            bound = model.bind_tools([tool])
            result['tool_binding'] = True
            prompt = 'Call the %s tool exactly once.' % tool.name
            response = bound.invoke([HumanMessage(content=prompt)])
            calls = getattr(response, 'tool_calls', None) or []
            result['tool_call'] = any(call.get('name') == tool.name for call in calls)
        except Exception as exc:
            result['errors'].append('tool_call: %s' % exc)

    return result
