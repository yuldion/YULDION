"""Explicit chat-completion endpoint; no provider or model downloads selected by default."""
import json
import os
import math
from urllib.parse import urlparse
from urllib.request import Request
from urllib.error import HTTPError, URLError
from .errors import InferenceFailure

def generate(config, messages):
    if "provider" in config:
        from .providers import validate_provider
        validate_provider(config)
    timeout=config.get('request_timeout_seconds',60)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=180:
        raise ValueError('request_timeout_seconds must be in 1..180')
    endpoint = config['endpoint']
    url = urlparse(endpoint)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError('Endpoint must not contain credentials, query or fragment')
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('Use HTTPS or an explicit loopback HTTP model endpoint')
    model = config['model']
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Explicit model ID required')
    headers = {'Content-Type': 'application/json'}
    if config.get('api_key_env'):
        headers['Authorization'] = 'Bearer ' + os.environ[config['api_key_env']]
    response_format = {'type': 'json_object'}
    mode=config.get('response_format_mode','json_schema')
    if mode not in ('json_schema','json_object'):
        raise ValueError('Unsupported response_format_mode')
    if config.get('response_schema') is not None and mode=='json_schema':
        response_format = {'type':'json_schema', 'json_schema':{
            'name':'actor_response','strict':True,'schema':config['response_schema']}}
    request = Request(endpoint, data=json.dumps({'model': model, 'messages': messages,
        'temperature': 0.2, 'max_tokens': config.get('max_output_tokens',1800), 'response_format': response_format}).encode(), headers=headers)
    # No redirects: never forward an authorization header to another host.
    from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    handlers=[NoRedirect()]
    if config.get('provider')=='local':handlers.insert(0,ProxyHandler({}))
    try:
        with build_opener(*handlers).open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        retry=None
        try:retry=max(0,min(300,float(error.headers.get('Retry-After',''))))
        except (ValueError,TypeError,AttributeError):pass
        error.close()
        raise InferenceFailure('http',error.code,retry) from None
    except TimeoutError:
        raise InferenceFailure('timeout') from None
    except URLError as error:
        raise InferenceFailure('timeout' if isinstance(error.reason,TimeoutError) else 'connection') from None
    if len(raw) > 1024 * 1024:
        raise ValueError('Model response too large')
    packet = json.loads(raw)
    text = packet['choices'][0]['message']['content']
    return json.loads(text), {'requested_model': model, 'reported_model': packet.get('model'),
                              'usage': packet.get('usage'), 'raw_content': text}
