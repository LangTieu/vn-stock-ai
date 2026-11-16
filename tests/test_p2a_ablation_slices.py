import json
import sys
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from p2a_ablation_slices import make_slices
from p2a_relabel import row_identity


def v2row(ticker,as_of,label,endpoint):
    payload={'ticker':ticker,'as_of':as_of,'source':{'ohlcv':'daily_HOSE'}}
    return {'input':f'BRIEF: Mã {ticker} tại {as_of}\nVERIFIED_DATA\n'+json.dumps(payload),
            'metadata':{'kind':'bulk','exchange':'HOSE','market_as_of':as_of,
             'p2a_label_version':2,'p2a_label_status':'labeled',
             'label':{'future_direction_120':label,'method':'real adjusted close',
                      'future_outcomes':{'120':{'endpoint_date':endpoint,'flat_band_pct':2.0}}}}}


class AblationSliceTests(unittest.TestCase):
    def test_uses_disjoint_train_period_before_2024_validation_not_external_holdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'v2_train.jsonl';rows=[]
            start=date(2023,1,1)
            for i in range(80):
                day=start+timedelta(days=i)
                rows.append(v2row(f'T{i:03}','%s'%day.isoformat(),'UP',
                                  (day+timedelta(days=120)).isoformat()))
                rows.append(v2row(f'D{i:03}',day.isoformat(),'DOWN',
                                  (day+timedelta(days=120)).isoformat()))
            val_start=date(2024,1,2)
            for i in range(40):
                day=val_start+timedelta(days=i)
                rows.append(v2row(f'V{i:03}',day.isoformat(),'UP',
                                  (day+timedelta(days=120)).isoformat()))
                rows.append(v2row(f'W{i:03}',day.isoformat(),'DOWN',
                                  (day+timedelta(days=120)).isoformat()))
            source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            result=make_slices(source,root/'out',2024,train_per_class=32,validation_per_class=16)
            self.assertTrue(result['passes'])
            self.assertTrue(result['actual_split']['train_target_before_validation_as_of'])
            self.assertEqual(result['train_sample']['class_counts'],{'UP':32,'DOWN':32})
            self.assertEqual(result['validation_sample']['class_counts'],{'UP':16,'DOWN':16})
            self.assertFalse(result['external_holdout_used_for_selection'])
            train_dates=[json.loads(x)['metadata']['label']['future_outcomes']['120']['endpoint_date']
                         for x in (root/'out/train-v2.jsonl').read_text().splitlines()]
            val_dates=[row_identity(json.loads(x))[2].isoformat() for x in
                       (root/'out/validation-v2.jsonl').read_text().splitlines()]
            self.assertLess(max(train_dates),min(val_dates))


if __name__=='__main__':unittest.main()
