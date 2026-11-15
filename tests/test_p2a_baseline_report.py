import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from p2a_baseline_report import report


def row(ticker, day, label, status='labeled', exchange='HOSE'):
    outcome={'status':status,'endpoint_date':'2025-06-01','flat_band_pct':2.0,'method':'finfo adClose'}
    if status=='censored': outcome['reason']='missing_endpoint_adjusted_close'
    input_data=(f'BRIEF: Mã {ticker} tại {day}\nVERIFIED_DATA\n'+json.dumps({
        'ticker':ticker,'as_of':day,'source':{'ohlcv':f'daily_{exchange}'}}))
    return {'input':input_data,'metadata':{
        'kind':'bulk','exchange':exchange,'p2a_label_version':2,'p2a_label_status':status,
        'label':{'future_direction_120':label,'method':'finfo adClose',
                 'future_outcomes':{'120':outcome}}}}


class P2aBaselineReportTests(unittest.TestCase):
    def test_reports_only_data_baselines_and_censor_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'v2.jsonl'
            rows=[row('AAA','2024-01-02','UP'),row('BBB','2024-04-03','DOWN'),
                  row('CCC','2024-05-01',None,'censored')]
            path.write_text(''.join(json.dumps(item)+'\n' for item in rows))
            result=report([path])
        item=result['reports'][0]
        self.assertTrue(result['passes'])
        self.assertEqual(item['counts']['label_UP'],1)
        self.assertEqual(item['counts']['label_DOWN'],1)
        self.assertEqual(item['censored_by_exchange_reason'],
                         {'HOSE:missing_endpoint_adjusted_close':1})
        self.assertEqual(item['censored_by_ticker_reason'],
                         {'CCC:missing_endpoint_adjusted_close':1})
        self.assertFalse(item['model_evaluation_run'])

    def test_refuses_legacy_label_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'v1.jsonl'
            item=row('AAA','2024-01-02','UP'); item['metadata'].pop('p2a_label_version')
            path.write_text(json.dumps(item)+'\n')
            with self.assertRaisesRegex(ValueError,'refuses label version 1'):
                report([path])


if __name__=='__main__':
    unittest.main()
