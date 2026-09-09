#!/usr/bin/env python3
"""Synthetic-only acceptance/accounting contracts. No API or media reads."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('summary', ROOT/'scripts/summarize-sightengine-temporal.py')
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
AGG = S.get_aggregator()
MANIFEST = json.loads((ROOT/'eval/fixtures/sightengine-temporal-screen-v2.json').read_text())


def fixture(overrides=None):
    overrides = overrides or {}
    results = []
    operations = 0
    for i, case in enumerate(MANIFEST['cases']):
        mode = overrides.get(case['id'], 'positive' if case['label']=='ai' else 'negative')
        frames = [{'positionSeconds':j*.5,'aiGenerated':.9 if mode=='positive' else .1}
                  for j in range(math.ceil(case['media']['durationSeconds']/.5))]
        if mode == 'isolated': frames[0]['aiGenerated']=.9
        if mode == 'positive_and_isolated':
            for j in [0,1,5]: frames[j]['aiGenerated']=.9
        reported = 5*len(frames); operations += reported
        temporal = AGG.aggregate_evidence(frames,duration_seconds=case['media']['durationSeconds'],
                                           technical_complete=True,declared_interval_seconds=.5)
        results.append({'id':case['id'],'index':i,'mediaSha256':case['sha256'],'status':'completed',
            'response':{'kind':'response','evidence':{'schemaValid':True,'coverageComplete':True,
                         'frames':frames,'request':{'operations':reported}}},
            'temporal':temporal,'elapsedSeconds':1.0,'reportedOperationsObserved':operations,
            'accountingMayBeIncomplete':False,'transmissionMayBeUncertain':False})
    return {'results':results,'status':'completed','stopReason':None,'reportedOperationsObserved':operations}


class Contracts(unittest.TestCase):
    def test_perfect_pass_separate_denominators(self):
        s=S.analyze(MANIFEST,fixture(),AGG)
        self.assertTrue(s['passesFrozenGates'])
        self.assertEqual(s['publisherAssignedAi']['unconditionalRecall']['denominator'],12)
        self.assertEqual(s['documentedNegative']['parents'],6)
        self.assertEqual(s['receiptBackedSameParent']['total'],1)
        self.assertNotIn('accuracy',s)

    def test_quality_gate_not_hidden_by_overall_recall(self):
        c=[c for c in MANIFEST['cases'] if c['cohort']=='publisher_assigned_ai' and c['quality']=='original'][:2]
        s=S.analyze(MANIFEST,fixture({x['id']:'isolated' for x in c}),AGG)
        self.assertTrue(s['gates']['publisher_assigned_ai_recall'])
        self.assertFalse(s['gates']['publisher_assigned_ai_original'])
        self.assertEqual(s['publisherAssignedAi']['unconditionalRecall']['numerator'],10)

    def test_parent_abstentions_and_clear_coverage(self):
        c=[c for c in MANIFEST['cases'] if c['cohort']=='documented_negative' and c['parentId']=='NASA']
        s=S.analyze(MANIFEST,fixture({x['id']:'isolated' for x in c}),AGG)
        self.assertTrue(s['passesFrozenGates'])
        self.assertEqual(s['documentedNegative']['clearParents']['numerator'],5)
        c.append(next(c for c in MANIFEST['cases'] if c['cohort']=='documented_negative' and c['parentId']=='NOAA'))
        s=S.analyze(MANIFEST,fixture({x['id']:'isolated' for x in c}),AGG)
        self.assertFalse(s['gates']['negative_clear_parent_coverage'])
        self.assertFalse(s['gates']['negative_clear_file_coverage'])

    def test_positive_plus_isolated_remains_false_alert_and_unresolved(self):
        c=next(c for c in MANIFEST['cases'] if c['cohort']=='documented_negative')
        s=S.analyze(MANIFEST,fixture({c['id']:'positive_and_isolated'}),AGG)
        self.assertFalse(s['passesFrozenGates'])
        self.assertEqual(s['documentedNegative']['falseAlertFiles']['numerator'],1)
        self.assertEqual(s['documentedNegative']['isolatedAlerts'],1)
        self.assertTrue(next(r for r in s['cases'] if r['id']==c['id'])['reviewRequired'])

    def test_technical_stop_retains_full_denominator(self):
        r=fixture();first=r['results'][0]
        first['status']='stopped';first['accountingMayBeIncomplete']=True
        r['results']=[first]+[{'id':c['id'],'status':'not_attempted','reason':'synthetic stop'} for c in MANIFEST['cases'][1:]]
        r['status']='stopped';r['stopReason']='synthetic stop';r['reportedOperationsObserved']=first['reportedOperationsObserved']
        s=S.analyze(MANIFEST,r,AGG)
        self.assertFalse(s['passesFrozenGates']);self.assertEqual(s['overall']['total'],25)
        self.assertEqual(s['overall']['not_attempted'],24)

    def test_tampered_temporal_or_accounting_rejected(self):
        r=fixture();r['results'][0]['temporal']['verdict']='invented'
        with self.assertRaises(ValueError): S.analyze(MANIFEST,r,AGG)
        r=fixture();r['reportedOperationsObserved']+=1
        with self.assertRaises(ValueError): S.analyze(MANIFEST,r,AGG)

    def test_duplicate_or_missing_cases_rejected(self):
        r=fixture();r['results'][-1]=copy.deepcopy(r['results'][0])
        with self.assertRaises(ValueError): S.analyze(MANIFEST,r,AGG)
        r=fixture();r['results'].pop()
        with self.assertRaises(ValueError): S.analyze(MANIFEST,r,AGG)


if __name__=='__main__': unittest.main()
