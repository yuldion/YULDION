"""Explicit chat-completion endpoint; no provider or model downloads selected by default."""
import json
import os
from urllib.parse import urlparse
from urllib.request import Request

def generate(config, messages):
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
    request = Request(endpoint, data=json.dumps({'model': model, 'messages': messages,
        'temperature': 0.2, 'max_tokens': 1800, 'response_format': {'type': 'json_object'}}).encode(), headers=headers)
    # No redirects: never forward an authorization header to another host.
    from urllib.request import build_opener, HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with build_opener(NoRedirect()).open(request, timeout=60) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Model response too large')
    packet = json.loads(raw)
    text = packet['choices'][0]['message']['content']
    return json.loads(text), {'requested_model': model, 'reported_model': packet.get('model'),
                              'usage': packet.get('usage'), 'raw_content': text}
