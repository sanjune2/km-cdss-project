import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai.local_completion import server_completion


class LocalCompletionTests(unittest.TestCase):
    def test_rejects_external_hosts_credentials_and_redirect_targets(self):
        for url in ['https://127.0.0.1','http://external.example','http://user:pass@localhost','http://localhost/path']:
            with self.subTest(url=url),self.assertRaises(ValueError):
                server_completion(url,'prompt',{},lambda:False,limit=100,timeout=10)

    def request(self,events,cancelled=lambda:False):
        response=MagicMock()
        response.iter_lines.return_value=['data: '+json.dumps(row) for row in events]
        with patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.stream.return_value.__enter__.return_value=response
            result=server_completion('http://127.0.0.1:8091','prompt',{},cancelled,limit=100,timeout=10)
            self.assertFalse(client.call_args.kwargs['trust_env'])
            self.assertFalse(client.call_args.kwargs['follow_redirects'])
        return result

    def test_complete_stream_returns_json(self):
        result,_=self.request([{'content':'{"ok":true}','stop':False},{'content':'','stop':True,'stop_type':'eos'}])
        self.assertEqual(result,{'ok':True})

    def test_truncated_stream_is_not_success(self):
        for events in [[{'content':'{}','stop':False}], [{'content':'{}','stop':True,'stop_type':'limit'}]]:
            with self.assertRaises(ValueError): self.request(events)

    def test_cancellation_closes_stream(self):
        with self.assertRaises(InterruptedError):
            self.request([{'content':'{}','stop':True,'stop_type':'eos'}],lambda:True)
