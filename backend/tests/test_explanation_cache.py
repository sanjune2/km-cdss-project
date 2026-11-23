import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai import explanations as e


class ExplanationCacheTests(unittest.TestCase):
    def setUp(self):
        e._completion_cache.clear()
        self.addCleanup(e._completion_cache.clear)
        self.payload={'candidateId':10,'sources':{'s':'기침을 기록함'},'symptoms':['기침']}
        self.generated={'candidateId':10,'unexplainedSymptoms':[],
                        'sentences':[{'sentenceNo':1,'text':'원문에 기침이 있습니다.',
                                      'references':[{'sourceId':'s','quote':'기침'}]}]}

    def test_repeated_exact_request_uses_a_copy_and_source_change_misses(self):
        with patch.object(e,'complete_json',return_value=(self.generated,{'elapsedMs':100})) as model:
            first,_=e.chat(e.GENERATION,self.payload)
            second,metrics=e.chat(e.GENERATION,self.payload)
            self.assertTrue(metrics['cacheHit'])
            self.assertEqual(model.call_count,1)
            second['sentences'][0]['text']='client mutation'
            third,_=e.chat(e.GENERATION,self.payload)
            self.assertEqual(first,third)
            e.chat(e.GENERATION,{**self.payload,'sources':{'s':'원본이 바뀌어도 기침을 기록함'}})
            self.assertEqual(model.call_count,2)

    def test_invalid_quotes_are_never_cached(self):
        self.generated['sentences'][0]['references'][0]['quote']='invented'
        with patch.object(e,'complete_json',return_value=(self.generated,{})) as model:
            for _ in range(2):
                with self.assertRaises(e.Withhold):e.chat(e.GENERATION,self.payload)
            self.assertEqual(model.call_count,2)
        self.assertEqual(len(e._completion_cache),0)

    def test_cancelled_request_does_not_use_cached_result(self):
        with patch.object(e,'complete_json',return_value=(self.generated,{})):
            e.chat(e.GENERATION,self.payload)
            with self.assertRaises(e.ModelCancelled):
                e.chat(e.GENERATION,self.payload,cancelled=lambda:True)
