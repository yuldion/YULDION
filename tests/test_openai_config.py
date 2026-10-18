import json
from unittest import TestCase
from unittest.mock import patch
from yuldion.inference import generate

class OpenAIConfigTest(TestCase):
    def test_json_mode_does_not_send_local_tuple_schema(self):
        packet={'model':'test','choices':[{'message':{'content':'{}'}}]}
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps(packet).encode()
            generate({'endpoint':'https://api.openai.com/v1/chat/completions','model':'test',
                      'response_format_mode':'json_object','response_schema':{'prefixItems':[]}},[])
            body=json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertEqual(body['response_format'],{'type':'json_object'})
