"""Explicit interpretation backends. Credentials are references, never config values."""
import math
import os
import re
from urllib.parse import urlsplit

OPENAI_ENDPOINT = 'https://api.openai.com/v1/chat/completions'
LOCAL_ENDPOINT = 'http://127.0.0.1:8080/v1/chat/completions'


def validate_provider(options):
    provider = options.get('provider')
    if provider not in ('openai', 'local'):
        raise ValueError('provider must be openai or local')
    allowed = {'provider','endpoint','model','api_key_env','response_format_mode',
               'request_timeout_seconds','response_schema'}
    if set(options)-allowed:
        raise ValueError('Unknown provider option; credentials belong in environment variables')
    model = options.get('model')
    if not isinstance(model,str) or not model.strip():
        raise ValueError('Explicit served model ID required')
    endpoint = options.get('endpoint','')
    url = urlsplit(endpoint)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError('Endpoint cannot embed credentials, query or fragment')
    if provider == 'openai':
        if endpoint != OPENAI_ENDPOINT:
            raise ValueError('OpenAI provider uses only the official HTTPS endpoint')
        env = options.get('api_key_env','')
        if not isinstance(env,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',env):
            raise ValueError('api_key_env must name an environment variable')
        if options.get('response_format_mode') != 'json_object':
            raise ValueError('OpenAI port uses JSON mode with Python contract validation')
    else:
        if (url.scheme != 'http' or url.hostname not in ('127.0.0.1','localhost','::1')
                or url.path != '/v1/chat/completions'):
            raise ValueError('Local provider requires a loopback HTTP chat-completions endpoint; use an SSH tunnel for remote hosts')
        if options.get('api_key_env'):
            raise ValueError('Local mode never attaches external API credentials')
        if options.get('response_format_mode') not in ('json_schema','json_object'):
            raise ValueError('Invalid local response format')
    timeout = options.get('request_timeout_seconds',120)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=180:
        raise ValueError('request_timeout_seconds must be in 1..180')
    return options


def provider_options(provider, model=None, endpoint=None, api_key_env='OPENAI_API_KEY'):
    if provider not in ('openai','local'):
        raise ValueError('Unknown interpretation provider')
    options = {'provider':provider,
               'endpoint':endpoint or (OPENAI_ENDPOINT if provider=='openai' else LOCAL_ENDPOINT),
               'model':model or ('gpt-4.1' if provider=='openai' else 'yuldion-qwen3-8b'),
               'response_format_mode':'json_object' if provider=='openai' else 'json_schema',
               'request_timeout_seconds':120}
    if provider == 'openai': options['api_key_env'] = api_key_env
    return validate_provider(options)


def authentication_ready(options):
    validate_provider(options)
    return options['provider']=='local' or bool(os.environ.get(options['api_key_env']))
