import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai.symptom_context import analyze_symptoms, find_mentions
from ai.runtime import diseases_for

DATA = {'keywords':[{'term':'기침','DIS_UNIQN':1},{'term':'열','DIS_UNIQN':2}]}


class SymptomContextTests(unittest.TestCase):
    def test_reviewed_strength_negation_keeps_affirmed(self):
        result = analyze_symptoms('기침이 심하지는 않아요.',DATA)
        self.assertEqual(result['affirmedTerms'],['기침'])
        self.assertEqual(result['mentions'][0]['assertion'],'AFFIRMED')

    def test_simple_presence_negation_never_enters_embedding(self):
        data = {**DATA,'embedder':Mock()}
        result = analyze_symptoms('기침은 전혀 없어요.',data)
        self.assertEqual(result['mentions'][0]['assertion'],'NEGATED')
        self.assertEqual(diseases_for('기침은 전혀 없어요.',data,result),[])
        data['embedder'].encode_query.assert_not_called()

    def test_mixed_mentions_use_only_current_patient_affirmed(self):
        decisions=[{'mentionId':'M1','context':'PATIENT_SYMPTOM','assertion':'NEGATED','experiencer':'SELF','temporality':'CURRENT'},
                   {'mentionId':'M2','context':'PATIENT_SYMPTOM','assertion':'AFFIRMED','experiencer':'SELF','temporality':'CURRENT'}]
        with patch('ai.explanations.complete_json',return_value=({'decisions':decisions,'additionalSymptoms':[]},{})):
            result=analyze_symptoms('기침은 없고 열은 있어요.',DATA)
        self.assertEqual(result['affirmedTerms'],['열'])
        self.assertEqual([row['usedInSearch'] for row in result['mentions']],[False,True])

    def test_others_past_uncertain_and_non_symptom_do_not_support_search(self):
        for override in [{'experiencer':'OTHER'},{'temporality':'PAST'},{'assertion':'UNCERTAIN'},
                         {'context':'NON_SYMPTOM','assertion':'UNASSESSED'}]:
            decision={'mentionId':'M1','context':'PATIENT_SYMPTOM','assertion':'AFFIRMED','experiencer':'SELF','temporality':'CURRENT',**override}
            with self.subTest(override=override),patch('ai.explanations.complete_json',return_value=({'decisions':[decision],'additionalSymptoms':[]},{})):
                self.assertEqual(analyze_symptoms('이 문장의 기침 표현을 확인합니다.',DATA)['affirmedTerms'],[])

    def test_model_failure_and_malformed_ids_require_review(self):
        for returned in [OSError('unavailable'), ({'decisions':[]},{}),
                         ({'decisions':[{'mentionId':'invented'}]}, {})]:
            with patch('ai.explanations.complete_json',side_effect=returned if isinstance(returned,Exception) else None,
                       return_value=returned):
                result=analyze_symptoms('기침인지 모르겠어요.',DATA)
            self.assertEqual(result['affirmedTerms'],[])
            self.assertTrue(result['reviewRequired'])

    def test_no_registered_expression_is_explicit_review(self):
        with patch('ai.explanations.complete_json',side_effect=OSError('unavailable')):
            self.assertTrue(analyze_symptoms('등록되지 않은 표현',DATA)['reviewRequired'])

    def test_unregistered_affirmed_symptom_can_still_use_semantic_search(self):
        additional={'sourceText':'가래','context':'PATIENT_SYMPTOM','assertion':'AFFIRMED','experiencer':'SELF','temporality':'CURRENT'}
        with patch('ai.explanations.complete_json',return_value=({'decisions':[],'additionalSymptoms':[additional]},{})):
            result=analyze_symptoms('가래가 있어요.',DATA)
        self.assertEqual(result['searchTerms'],['가래'])
        self.assertEqual(result['affirmedTerms'],[])

    def test_additional_symptoms_cannot_reintroduce_negated_registered_term(self):
        decision={'mentionId':'M1','context':'PATIENT_SYMPTOM','assertion':'NEGATED','experiencer':'SELF','temporality':'CURRENT'}
        extra={**{k:v for k,v in decision.items() if k!='mentionId'},'sourceText':'기침','assertion':'AFFIRMED'}
        with patch('ai.explanations.complete_json',return_value=({'decisions':[decision],'additionalSymptoms':[extra]},{})):
            result=analyze_symptoms('기침은 없다고 해요.',DATA)
        self.assertEqual(result['searchTerms'],[])
        self.assertTrue(result['reviewRequired'])

    def test_uncertain_simple_phrase_is_not_unassessed_or_negated(self):
        result=analyze_symptoms('기침인지 모르겠어요.',DATA)
        self.assertEqual(result['mentions'][0]['assertion'],'UNCERTAIN')
        self.assertEqual(result['searchTerms'],[])

    def test_inconsistent_mention_does_not_discard_a_separate_valid_symptom(self):
        bad={'mentionId':'M1','context':'NON_SYMPTOM','assertion':'NEGATED','experiencer':'SELF','temporality':'CURRENT'}
        valid={'sourceText':'가래가 있어요','context':'PATIENT_SYMPTOM','assertion':'AFFIRMED','experiencer':'SELF','temporality':'CURRENT'}
        with patch('ai.explanations.complete_json',return_value=({'decisions':[bad],'additionalSymptoms':[valid]},{})):
            result=analyze_symptoms('기침은 없지만 가래가 있어요.',DATA)
        self.assertEqual(result['searchTerms'],['가래가 있어요'])
        self.assertEqual(result['affirmedTerms'],[])
        self.assertTrue(result['reviewRequired'])

    def test_ambiguous_repeated_unregistered_span_requires_review(self):
        extra={'sourceText':'가래','context':'PATIENT_SYMPTOM','assertion':'AFFIRMED','experiencer':'SELF','temporality':'CURRENT'}
        with patch('ai.explanations.complete_json',return_value=({'decisions':[],'additionalSymptoms':[extra]},{})):
            result=analyze_symptoms('어머니의 가래와 제 가래는 달라요.',DATA)
        self.assertEqual(result['searchTerms'],[])
        self.assertTrue(result['reviewRequired'])

    def test_source_spans_and_longest_registered_expression(self):
        text='밤 기침이 나요. 기침도 있어요.'
        mentions=find_mentions(text,[{'term':'기침'},{'term':'밤 기침'}])
        self.assertEqual([text[r['start']:r['end']] for r in mentions],['밤 기침','기침'])

    def test_keyword_and_semantic_paths_share_positive_terms(self):
        data={**DATA,'diseases':[{'DIS_UNIQN':1,'ATT_DIS_NM':'가'},{'DIS_UNIQN':2,'ATT_DIS_NM':'나'}],
              'chunks':[],'matrix':None,'embedder':Mock()}
        with patch('ai.runtime.search_semantic',return_value=[]):
            rows=diseases_for('기침이 심하지는 않아요.',data)
        self.assertEqual([row['id'] for row in rows],[1])
        data['embedder'].encode_query.assert_called_once_with('기침')


if __name__=='__main__':
    unittest.main()
