"""Mục đích: tính verified snapshot và signal-text bằng indicators.py, không gọi model."""
import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verified_indicators', ROOT / 'inputs/indicators.py')
ind = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ind)
MISSING = 'không có số liệu'


def load(name):
    return json.loads((ROOT / 'inputs' / name).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def date_of(row):
    t = row.get('date', row.get('time'))
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
    if '-' in t and len(t.split('-')[0]) != 4:
        return datetime.strptime(t, '%d-%m-%Y').date().isoformat()
    return t[:10]


def rows_for(ticker, as_of=None):
    rows = load('bot-data/stocks_vnstock.json')[ticker]
    return sorted([dict(r, date=date_of(r)) for r in rows if as_of is None or date_of(r) <= as_of], key=lambda r: r['date'])


def finite(x):
    return round(float(x), 6) if np.isfinite(x) else MISSING


def build(ticker, as_of=None):
    rows = rows_for(ticker, as_of)
    if len(rows) < 200:
        raise ValueError('Cần ít nhất 200 phiên OHLCV để có MA200')
    a = ind.compute_all(rows)
    c = a['close']; last = rows[-1]; day = last['date']
    macd = ind.ema(c, 12) - ind.ema(c, 26)
    values = {k: finite(a[k][-1]) for k in ['ma20','ma50','ma200','rsi14','macd_hist','atr14','boll_mid','boll_up','boll_lo','obv']}
    values.update(macd=finite(macd[-1]), macd_signal=finite(ind.ema(macd, 9)[-1]), ema12=finite(ind.ema(c, 12)[-1]), ema26=finite(ind.ema(c, 26)[-1]))
    price = {'unit':'nghìn VND/cổ phiếu; volume: cổ phiếu','ohlcv':{k:last[k] for k in ['open','high','low','close','volume']},'change_pct_1d':finite((c[-1]/c[-2]-1)*100),'high_close_150':finite(max(c[-150:])),'low_close_150':finite(min(c[-150:])),'from_peak_pct':finite((c[-1]/max(c[-150:])-1)*100),'from_bottom_pct':finite((c[-1]/min(c[-150:])-1)*100),'support_low_20':finite(min(r['low'] for r in rows[-20:]))}
    state = a['state']
    state = {k:(finite(v) if isinstance(v,float) else v) for k,v in state.items()}
    flows = {side:{'year_ytd_ty':MISSING,'last20_ty':MISSING,'last5_ty':MISSING} for side in ['foreign','proprietary']}
    flow_source = MISSING
    if ticker == 'VCB' and day == '2026-11-06':
        v = load('vcb_test.json')
        for side,key in [('foreign','foreign_last5'),('proprietary','proprietary_last5')]:
            selected = sorted([r for r in v[key] if date_of(r) <= day],key=date_of)
            if len(selected) == 5:
                flows[side]['last5_ty'] = round(sum(r['net_value_ty'] for r in selected), 3)
        flow_source = 'inputs/vcb_test.json: net_value_ty; chỉ 5 phiên, không thay cho 20 phiên/YTD'
    fundamentals = {k:MISSING for k in ['lnst_yoy_pct','roe_trailing4q_pct','pe','pb','ranking_score']}
    macro = {'cpi_yoy_pct':MISSING,'fed_rate_pct':MISSING,'position_size':MISSING,'source':MISSING}
    monthly = load('bot-data/macro_monthly.json')
    if monthly['fetched'][:10] <= day:
        macro.update(cpi_yoy_pct=float(monthly['cpi_yoy_pct'].replace(',','.')),source='inputs/bot-data/macro_monthly.json; fetched='+monthly['fetched'])
        if macro['cpi_yoy_pct'] > 4.5:
            macro['position_size'] = 'HALF_OR_LESS; CPI cao, Fed không có số liệu'
    reasons = ['Thiếu LNST YoY/ROE trailing/PE/PB: không đủ bằng chứng BCTC','Thiếu khối ngoại YTD và 20 phiên: không đủ căn cứ xếp hạng']
    if macro['fed_rate_pct'] == MISSING:
        reasons.append('Thiếu Fed: không xác nhận vị thế đầy đủ')
    lines = []
    for name,key in [('MA20','ma20'),('MA50','ma50'),('MA200','ma200')]:
        lines.append(f'{name}: {"TRÊN" if c[-1]>values[key] else "DƯỚI"} (giá {finite(c[-1])}; trung bình {values[key]}; so sánh giá đóng cửa)')
    lines.append(f'RSI: {"ĐÁY SÂU" if values["rsi14"]<35 else "CHƯA QUÁ BÁN"} ({values["rsi14"]}; Wilder từ toàn bộ lịch sử đến ngày phân tích)')
    lines.append(f'MACD: {"ĐẢO DƯƠNG" if state["flip_now"] else "CHƯA ĐẢO DƯƠNG"} (hist {values["macd_hist"]}; hist trước {finite(a["macd_hist"][-2])}; xác nhận cần âm sang dương)')
    for name,key in [('ATR','atr14'),('OBV','obv'),('BOLLINGER','boll_mid')]:
        lines.append(f'{name}: QUAN SÁT ({values[key]}; Python tính từ OHLCV)')
    for side,label in [('foreign','KHỐI NGOẠI'),('proprietary','TỰ DOANH')]:
        val=flows[side]['last5_ty']
        direction = MISSING if val == MISSING else ('SELL/âm' if val<0 else 'BUY/dương' if val>0 else 'TRUNG TÍNH')
        lines.append(f'{label}: {direction} (5 phiên {val} tỷ; 20 phiên {MISSING}; YTD {MISSING})')
    result={'ticker':ticker,'as_of':day,'source':{'ohlcv':'inputs/bot-data/stocks_vnstock.json','ohlcv_sha256':digest(rows),'indicator_module_sha256':hashlib.sha256((ROOT/'inputs/indicators.py').read_bytes()).hexdigest(),'row_count':len(rows),'flow':flow_source},'price':price,'indicators':values,'state':state,'flows':flows,'fundamentals':fundamentals,'macro':macro,'abstain_reasons':reasons,'signal_text':'\n'.join(lines),'allowed_enums':{'recommendation':['BUY','WAIT','REDUCE','ABSTAIN'],'confidence':['LOW','MEDIUM','HIGH'],'direction':['UP','DOWN','FLAT','UNKNOWN']}}
    result['input_data_hash']=digest(result)
    return result


def prompt(snapshot):
    system=(ROOT/'p0/system_prompt.txt').read_text()
    table='\n'.join(f'{key}: {value}' for key,value in snapshot['indicators'].items())
    user='BRIEF: Phân tích mã '+snapshot['ticker']+' tại '+snapshot['as_of']+'. Chỉ dùng VERIFIED_DATA.\nBẢNG TÓM TẮT (Python):\n'+table+'\nVERIFIED_DATA\n'+json.dumps(snapshot,ensure_ascii=False,allow_nan=False)+'\nEND_VERIFIED_DATA\nLANGUAGE: tiếng Việt, kết luận trước, trả JSON theo system.'
    return [{'role':'system','content':system},{'role':'user','content':user}]


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--ticker',default='VCB');p.add_argument('--as-of');p.add_argument('--output',required=True);args=p.parse_args()
    out=Path(args.output).resolve()
    if not out.is_relative_to(ROOT):raise ValueError('Output phải trong workdir')
    out.write_text(json.dumps(build(args.ticker,args.as_of),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('snapshot_written',str(out))
