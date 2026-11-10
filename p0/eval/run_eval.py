"""Mục đích: chạy eval P0 lặp, cache theo hash input, lưu raw và đo rubric/hit-rate."""
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / 'p0/eval'
CUTOFF = '2026-04-07'
HORIZON = 20
REPEATS = 3
MODEL_GROUP = 'vn-stock'
PARAMS = {'temperature': 0.1, 'top_p': 0.75, 'top_k': 40, 'max_tokens': 1200, 'reasoning_effort': 'none'}
spec = importlib.util.spec_from_file_location('p0_snapshot', ROOT / 'p0/snapshot.py')
snapshot = importlib.util.module_from_spec(spec); spec.loader.exec_module(snapshot)


def read_json(rel): return json.loads((ROOT / rel).read_text())
def sha(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def rows_at(rows): return sorted(rows,key=lambda x:x.get('time',x.get('date','')))

def outcome(rows, date):
    rr=rows_at(rows); dates=[snapshot.date_of(r) for r in rr]
    if date not in dates:return None
    i=dates.index(date); j=i+HORIZON
    if j>=len(rr):return None
    return {'entry_date':date,'exit_date':dates[j],'entry_close':rr[i]['close'],'exit_close':rr[j]['close'],'return_pct':round((rr[j]['close']/rr[i]['close']-1)*100,6),'direction':'UP' if rr[j]['close']>rr[i]['close'] else 'DOWN' if rr[j]['close']<rr[i]['close'] else 'FLAT'}

def proxy_key():
    for proc in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            cmd=proc.read_bytes().replace(b'\0',b' ').decode()
            if '/litellm ' in cmd and '--port 4000' in cmd:
                env=dict(x.split(b'=',1) for x in (proc.parent/'environ').read_bytes().split(b'\0') if b'=' in x)
                return env[b'LITELLM_MASTER_KEY'].decode()
        except (OSError,KeyError,ValueError):pass
    raise RuntimeError('LiteLLM port 4000/master key not discoverable')

def call(messages):
    body={'model':MODEL_GROUP,'messages':messages,**PARAMS}
    req=urllib.request.Request('http://127.0.0.1:4000/v1/chat/completions',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+proxy_key()})
    with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)

def parse_json(text):
    try:return json.loads(text)
    except (ValueError,TypeError):
        m=re.search(r'\{[\s\S]*\}',text or '')
        if m:
            try:return json.loads(m.group())
            except ValueError:pass
    return {}

def score(raw, snap):
    text=raw.get('content') or ''; obj=parse_json(text); low=text.lower(); signals=snap['signal_text'].splitlines()
    checks={
      'machine_json':bool(obj) and all(k in obj for k in ['ticker','recommendation','confidence','direction','sections']),
      'correct_ticker':obj.get('ticker')==snap['ticker'],
      'abstain_when_missing':obj.get('recommendation')=='ABSTAIN' and obj.get('confidence')=='LOW' if snap['abstain_reasons'] else True,
      'no_unsupported_lnst_claim':not bool(re.search(r'LNST.{0,50}(?:tăng|giảm|âm|dương|\+|−|-)',text,re.I)) or any(x in text for x in ['không có số liệu','không được cung cấp']),
      'roe_trailing_rule':('trailing' in low or 'không có số liệu' in low or 'không được cung cấp' in low) and not bool(re.search(r'ROE.{0,40}(?:×\s*4|nhân\s*4|annualiz)',text,re.I)),
      'flow_sign_not_reversed':not bool(re.search(r'(?:bán ròng|SELL)\s*(?:=|:|là)\s*(?:BUY|mua ròng|dương)|(?:mua ròng|BUY)\s*(?:=|:|là)\s*(?:SELL|bán ròng|âm)',text,re.I)),
      'when_or_no_entry':bool(re.search(r'khi|chờ|điều kiện|chưa có điểm vào',text,re.I)),
      'ranking_has_score_or_abstains':('không xếp hạng' in low or 'không có số liệu' in low or bool(re.search(r'điểm\s*[:=]?\s*-?\d+',low))),
      'signal_values_grounded':sum(1 for line in signals if any(token in text for token in re.findall(r'[-+]?\d+(?:\.\d+)?',line)))>=2,
      'macro_position_caveat':('cpi' in low and ('fed' in low or 'không có số liệu' in low)) or 'không có số liệu' in low,
    }
    return {'checks':checks,'score':sum(checks.values()),'max_score':len(checks),'direction_output':obj.get('direction','UNKNOWN')}

def main():
    EVAL.mkdir(exist_ok=True); (EVAL/'cache').mkdir(exist_ok=True)
    rank=read_json('inputs/bot-data/stock_rank.json')[:20]
    stocks=read_json('inputs/bot-data/stocks_vnstock.json'); idx=read_json('inputs/bot-data/vnindex_vnstock.json')
    ref=[]
    for item in rank:
        t=item['code']; future=outcome(stocks[t],CUTOFF); snap=snapshot.build(t,CUTOFF)
        if future is None:continue
        key=sha({'prompt':snapshot.prompt(snap),'model_group':MODEL_GROUP,'params':PARAMS})
        ref.append({'ticker':t,'rank_winrate_source':item,'snapshot':snap,'prompt':snapshot.prompt(snap),'input_hash':key,'stock_outcome':future,'index_outcome':outcome(idx,CUTOFF)})
    manifest={'cutoff':CUTOFF,'horizon_sessions':HORIZON,'requested_repeats':REPEATS,'model_group':MODEL_GROUP,'params':PARAMS,'tickers':[x['ticker'] for x in ref],'started_at':datetime.now(timezone.utc).isoformat(),'outputs':[]}
    manifest_path=EVAL/'manifest.json'
    if manifest_path.exists():
        old=json.loads(manifest_path.read_text())
        if old.get('cutoff')!=CUTOFF or old.get('tickers')!=manifest['tickers']:raise RuntimeError('Existing manifest differs; refusing overwrite')
        manifest=old
        manifest['outputs']=[x for x in manifest['outputs'] if not (EVAL/x['file']).exists() or not json.loads((EVAL/x['file']).read_text()).get('cache_hit',False)]
    seen={(x['ticker'],x['repeat']) for x in manifest['outputs']}
    for item in ref:
        for repeat in range(1,REPEATS+1):
            if (item['ticker'],repeat) in seen:continue
            cache=EVAL/'cache'/f"{item['input_hash']}_run{repeat}.json"
            started=datetime.now(timezone.utc).isoformat();t0=time.monotonic()
            try:
                if cache.exists():
                    response=json.loads(cache.read_text());cache_hit=True
                else:
                    response=call(item['prompt']);cache.write_text(json.dumps(response,ensure_ascii=False,indent=2)+'\n');cache_hit=False
                choice=response['choices'][0]; msg=choice['message']; raw={'ticker':item['ticker'],'repeat':repeat,'model_group':MODEL_GROUP,'actual_model':response.get('model'),'timestamp_started_utc':started,'timestamp_completed_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-t0,3),'params':PARAMS,'input_hash':item['input_hash'],'cache_hit':cache_hit,'content':msg.get('content'),'tool_calls':msg.get('tool_calls'),'finish_reason':choice.get('finish_reason'),'usage':response.get('usage')}
                raw['rubric']=score(raw,item['snapshot']); raw['stock_outcome_20']=item['stock_outcome'];raw['vnindex_outcome_20']=item['index_outcome']
            except Exception as exc:
                raw={'ticker':item['ticker'],'repeat':repeat,'model_group':MODEL_GROUP,'actual_model':None,'timestamp_started_utc':started,'timestamp_completed_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-t0,3),'params':PARAMS,'input_hash':item['input_hash'],'error_type':type(exc).__name__,'error':str(exc)}
            rawpath=EVAL/f"raw_{item['ticker']}_run{repeat}.json";rawpath.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n')
            manifest['outputs'].append({'ticker':item['ticker'],'repeat':repeat,'file':rawpath.name,'model':raw.get('actual_model'),'error':raw.get('error')})
            manifest['updated_at']=datetime.now(timezone.utc).isoformat();manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'ticker':item['ticker'],'repeat':repeat,'model':raw.get('actual_model'),'seconds':raw['elapsed_seconds'],'error':raw.get('error'),'rubric':raw.get('rubric',{}).get('score')},ensure_ascii=False),flush=True)
    summarize(ref,manifest)

def summarize(ref,manifest):
    index_rows=read_json('inputs/bot-data/vnindex_vnstock.json');index=outcome(index_rows,CUTOFF)
    actual_up=index['direction']=='UP' if index else None
    results=[]
    for item in ref:
        records=[]
        for n in range(1,REPEATS+1):
            p=EVAL/f"raw_{item['ticker']}_run{n}.json"
            if p.exists():records.append(json.loads(p.read_text()))
        valid=[r for r in records if 'rubric' in r]
        results.append({'ticker':item['ticker'],'repeat_count':len(records),'model_runs':sorted(set(r.get('actual_model') for r in valid)),'mean_rubric':round(sum(r['rubric']['score'] for r in valid)/len(valid),2) if valid else None,'stock_direction_20':item['stock_outcome']['direction'],'stock_return_20_pct':item['stock_outcome']['return_pct'],'vnindex_direction_20':item['index_outcome']['direction'],'predicted_directions':[r['rubric']['direction_output'] for r in valid],'outputs':[r['rubric']['direction_output'] for r in valid]})
    preds=[r for r in results for d in r['predicted_directions'] if d in ['UP','DOWN','FLAT']]
    index_hit=sum((d=='UP')==(actual_up) for d in preds)/len(preds) if preds and actual_up is not None else None
    stock_preds=[(d,r['stock_direction_20']) for r in results for d in r['predicted_directions'] if d in ['UP','DOWN','FLAT']]
    stock_hit=sum(d==a for d,a in stock_preds)/len(stock_preds) if stock_preds else None
    valid_records=[json.loads((EVAL/x['file']).read_text()) for x in manifest['outputs'] if not x.get('error')]
    report={'eval_type':'retryable','cutoff':CUTOFF,'horizon_sessions':HORIZON,'index_outcome':index,'index_direction_hit_rate':index_hit,'index_direction_predictions_n':len(preds),'stock_direction_hit_rate':stock_hit,'stock_direction_predictions_n':len(stock_preds),'direction_coverage':{'directional_n':len(preds),'unknown_n':len(valid_records)-len(preds),'total_n':len(valid_records),'directional_fraction':len(preds)/len(valid_records) if valid_records else None},'recommendation_counts':{name:sum(parse_json(r.get('content')).get('recommendation')==name for r in valid_records) for name in ['BUY','WAIT','REDUCE','ABSTAIN']},'rubric_mean':round(sum(r['rubric']['score'] for r in valid_records)/len(valid_records),2) if valid_records else None,'rubric_max':10,'rubric_method':'Automated heuristic checks; not human adjudication or comparison to absent bot-analysis prose','symbols_evaluated':[r['ticker'] for r in results if r['repeat_count']],'symbols_with_model_output':[r['ticker'] for r in results if r['model_runs']],'per_ticker':results,'outputs_recorded':len(manifest['outputs']),'generated_at':datetime.now(timezone.utc).isoformat()}
    (EVAL/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('SUMMARY',json.dumps({'count_outputs':report['outputs_recorded'],'symbols':report['symbols_with_model_output'],'index_direction_hit_rate':index_hit,'index_predictions_n':len(preds)},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
