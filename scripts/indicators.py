"""Chi bao ky thuat P1 — port tu bot LightVela 1 (signal_engine.py).

Nguon: /home/agentuser/vnstock_system/scripts/signal_engine.py (bot Hermes,
LightVela 1), da backtest 1.995 phien VN-Index + 29 ma (2018-2026).
Danh gia day du: bot-lightvela1/EVALUATION.md.

Thay doi so voi ban goc:
- KHONG doc file, KHONG dung duong dan cung: moi ham nhan mang gia/OHLCV
  lam tham so. (Ban goc co loi: __main__ tim data o HERE/scripts trong khi
  data o ../data, chay ra NOTHING.)
- Them ham tien ich nhan OHLCV dang list-of-dict (dinh dang dataset
  train_2014_2026_*.json: {date, open, high, low, close, volume}).

Cong thuc:
- RSI(14): Wilder smoothing (giong spec P1).
- MACD: EMA12 - EMA26, hist = MACD - EMA9(MACD).
- Tin hieu day/dinh (da backtest, win 86%/120 phien o chi so):
  day sau = RSI14 < 35 HOAC giam >=10% tu dinh 150 phien (trong 20 phien);
  xac nhan = MACD hist dao am -> duong;
  dinh = RSI > 70 VA gia >15% tren MA150 (chi giam ty trong, KHONG short).
"""
import numpy as np


# ---------- Chi bao co ban ----------
def ema(x, s):
    """EMA(s). x: array-like gia dong."""
    x = np.asarray(x, float)
    a = 2 / (s + 1)
    o = np.zeros(len(x))
    if len(x) == 0:
        return o
    o[0] = x[0]
    for i in range(1, len(x)):
        o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o


def sma(x, w):
    """SMA(w). Tra NaN cho w-1 diem dau."""
    x = np.asarray(x, float)
    o = np.full(len(x), np.nan)
    for i in range(w - 1, len(x)):
        o[i] = x[i - w + 1:i + 1].mean()
    return o


def rsi(close, n=14):
    """RSI(n), Wilder smoothing. Tra NaN cho n diem dau."""
    close = np.asarray(close, float)
    d = np.diff(close)
    g = np.where(d > 0, d, 0.)
    l = np.where(d < 0, -d, 0.)
    ag, al = g[:n].mean(), l[:n].mean()
    out = [np.nan] * n
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + l[i]) / n
        out.append(100 - 100 / (1 + (ag / al if al else 100)))
    return np.concatenate([[np.nan], out])


def macd_hist(close, fast=12, slow=26, sig=9):
    """MACD histogram: (EMA12 - EMA26) - EMA9(MACD)."""
    close = np.asarray(close, float)
    macd = ema(close, fast) - ema(close, slow)
    return macd - ema(macd, sig)


def atr(high, low, close, n=14):
    """ATR(n) — True Range lam muot Wilder."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    out = np.full(len(close), np.nan)
    if len(tr) < n:
        return out
    a = tr[:n].mean()
    out[n] = a
    for i in range(n + 1, len(close)):
        a = (a * (n - 1) + tr[i - 1]) / n
        out[i] = a
    return out


def bollinger(close, w=20, k=2.0):
    """Bollinger Bands: tra (mid, upper, lower)."""
    close = np.asarray(close, float)
    mid = sma(close, w)
    upper = np.full(len(close), np.nan)
    lower = np.full(len(close), np.nan)
    for i in range(w - 1, len(close)):
        sd = close[i - w + 1:i + 1].std(ddof=0)
        upper[i] = mid[i] + k * sd
        lower[i] = mid[i] - k * sd
    return mid, upper, lower


def obv(close, volume):
    """On-Balance Volume."""
    close = np.asarray(close, float)
    volume = np.asarray(volume, float)
    o = np.zeros(len(close))
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            o[i] = o[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            o[i] = o[i - 1] - volume[i]
        else:
            o[i] = o[i - 1]
    return o


# ---------- Tin hieu day/dinh (da backtest) ----------
def signals(close, n_lookback=20, rsi_th=35, dd_th=-0.10, dd_window=150,
            hold=120):
    """Tra (sig_idx, top_idx, state) — giong signal_engine.goc.

    sig_idx: index cac phien co tin hieu day (day sau + MACD flip), gop
    tin hieu cach nhau <10 phien. top_idx: index cac phien canh bao dinh.
    state: trang thai phien cuoi (rsi, hist, dd, deep_now, flip_now, top_now).
    """
    c = np.asarray(close, float)
    n = len(c)
    h = macd_hist(c)
    r = rsi(c)
    ma150 = sma(c, 150)

    def deep(i):
        seg_r = r[max(0, i - n_lookback):i]
        r_ok = len(seg_r) > 0 and not np.isnan(seg_r.min()) \
            and seg_r.min() < rsi_th
        dd_ok = False
        if i >= dd_window:
            lo = c[max(0, i - n_lookback):i].min()
            hi = c[max(0, i - dd_window - n_lookback):i - n_lookback].max()
            dd_ok = lo / hi - 1 <= dd_th
        return bool(r_ok or dd_ok)

    def flip(i):
        return bool(h[i] > 0 and h[i - 1] <= 0)

    def top(i):
        return bool((not np.isnan(r[i]) and r[i] > 70) and
                    (not np.isnan(ma150[i]) and c[i] / ma150[i] - 1 > 0.15))

    raw = [i for i in range(n_lookback, n - hold) if flip(i) and deep(i)]
    sig = []
    last = -100
    for i in raw:
        if i - last > 10:
            sig.append(i)
        last = i
    tops = [i for i in range(150, n) if top(i)]
    i = n - 1
    state = {
        'close': float(c[i]), 'rsi': float(r[i]), 'hist': float(h[i]),
        'dd_from_150_high': float(c[i] / c[-dd_window:].max() - 1),
        'deep_now': bool(deep(i)), 'flip_now': bool(flip(i)),
        'top_now': bool(top(i)),
    }
    return sig, tops, state


def winrate(close, sig, hold=120):
    """Win-rate sau 20/60/120 phien cho danh sach index tin hieu."""
    close = np.asarray(close, float)
    res = {}
    for per in (20, 60, hold):
        rr = [(close[x + per] / close[x] - 1) * 100
              for x in sig if x + per < len(close)]
        if rr:
            res[per] = {'win%': round(100 * sum(1 for q in rr if q > 0) / len(rr)),
                        'avg%': round(float(np.mean(rr)), 1), 'n': len(rr)}
    return res


# ---------- Tien ich: OHLCV dang list-of-dict ----------
def closes_from_ohlcv(rows):
    """Lay mang close tu list {date, open, high, low, close, volume}."""
    return np.array([r['close'] for r in rows], float)


def compute_all(rows):
    """Tinh toan bo chi bao P1 cho 1 ma (rows: list OHLCV dict).
    Tra dict cac array (cung do dai voi rows)."""
    close = np.array([r['close'] for r in rows], float)
    high = np.array([r['high'] for r in rows], float)
    low = np.array([r['low'] for r in rows], float)
    vol = np.array([r['volume'] for r in rows], float)
    ma20, ma50, ma200 = sma(close, 20), sma(close, 50), sma(close, 200)
    mid, up, lo = bollinger(close)
    sig, tops, state = signals(close)
    return {
        'close': close, 'ma20': ma20, 'ma50': ma50, 'ma200': ma200,
        'rsi14': rsi(close), 'macd_hist': macd_hist(close),
        'boll_mid': mid, 'boll_up': up, 'boll_lo': lo,
        'atr14': atr(high, low, close), 'obv': obv(close, vol),
        'signal_idx': sig, 'top_idx': tops, 'state': state,
    }
