"""Nhật ký lệnh tay: bối cảnh thị trường lúc vào/ra, lý do, kết quả — dữ liệu để phân tích và viết chiến lược sau."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pandas as pd
import requests

from .config import Config
from .data import PUBLIC_API
from .indicators import atr, ema, rsi

REAL_FEE_RT_PCT = 0.2          # phí thật Binance spot 0,1 %/chiều; testnet không thu phí
MIN_USDT, MAX_USDT, DEFAULT_USDT = 10.0, 1000.0, 100.0
SYMBOLS = Config().symbols


def parse_buy(text: str, symbols=SYMBOLS) -> tuple[str, float, str] | str:
    """'/mua sol 200 lý do…' → ('SOLUSDT', 200.0, 'lý do…'); sai thì trả chuỗi báo lỗi."""
    parts = text.split(maxsplit=3)
    if len(parts) < 2:
        return "Cú pháp: /mua <coin> [USDT] [lý do], ví dụ: /mua SOL 200 phá đỉnh 1h, volume lớn"
    sym = parts[1].upper()
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    if sym not in symbols:
        return f"Không hỗ trợ {sym}. Coin được dùng: {' '.join(s[:-4] for s in symbols)}"
    usdt = DEFAULT_USDT
    if len(parts) >= 3:
        try:
            usdt = float(parts[2].replace(",", ""))
        except ValueError:
            return "Không đọc được số USDT. Cú pháp: /mua <coin> [USDT] [lý do]"
    if not MIN_USDT <= usdt <= MAX_USDT:
        return f"Không mua: số USDT phải từ {MIN_USDT:g} đến {MAX_USDT:g}."
    return sym, usdt, parts[3].strip() if len(parts) == 4 else ""


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100


def features(tf: dict, btc_1h) -> dict:
    """Bối cảnh từ nến ĐÃ ĐÓNG. tf = {'5m','15m','1h'}: mỗi cái có open/high/low/close/volume."""
    m5, m15, h1, btc = (pd.DataFrame(x).reset_index(drop=True) for x in (tf["5m"], tf["15m"], tf["1h"], btc_1h))
    c5, c1 = m5["close"], h1["close"]
    last5, last1 = c5.iloc[-1], c1.iloc[-1]
    e20_1h, e50_1h, e200_1h = (ema(c1, n).iloc[-1] for n in (20, 50, 200))
    day = h1.iloc[-24:]
    lo, hi = day["low"].min(), day["high"].max()
    btc_e200 = ema(btc["close"], 200).iloc[-1]
    return {
        "price": float(last5),
        "ret_15m_pct": _pct(last5, c5.iloc[-4]),
        "ret_1h_pct": _pct(last5, c5.iloc[-13]),
        "ret_4h_pct": _pct(last1, c1.iloc[-5]),
        "ret_24h_pct": _pct(last1, c1.iloc[-25]),
        "rsi_5m": float(rsi(c5, 14).iloc[-1]),
        "rsi_15m": float(rsi(m15["close"], 14).iloc[-1]),
        "rsi_1h": float(rsi(c1, 14).iloc[-1]),
        "dist_ema20_5m_pct": _pct(last5, ema(c5, 20).iloc[-1]),
        "dist_ema20_1h_pct": _pct(last1, e20_1h),
        "dist_ema200_1h_pct": _pct(last1, e200_1h),
        "above_ema200_1h": bool(last1 > e200_1h),
        "ema20_gt_ema50_1h": bool(e20_1h > e50_1h),
        "atr_pct_5m": float(atr(m5, 14).iloc[-1] / last5 * 100),
        "atr_pct_1h": float(atr(h1, 14).iloc[-1] / last1 * 100),
        "vol_ratio_5m": float(m5["volume"].iloc[-1] / m5["volume"].iloc[-21:-1].mean()),
        "range_pos_24h": float((last1 - lo) / (hi - lo)) if hi > lo else 0.5,
        "btc_ret_1h_pct": _pct(btc["close"].iloc[-1], btc["close"].iloc[-2]),
        "btc_above_ema200_1h": bool(btc["close"].iloc[-1] > btc_e200),
    }


def _klines(symbol: str, interval: str, get=requests.get, **params) -> list:
    r = get(f"{PUBLIC_API}/klines", params={"symbol": symbol, "interval": interval, **params}, timeout=20)
    r.raise_for_status()
    return r.json()


def _closed(rows: list) -> dict:
    rows = rows[:-1]
    return {k: [float(x[i]) for x in rows] for k, i in
            (("open", 1), ("high", 2), ("low", 3), ("close", 4), ("volume", 5))}


def snapshot(symbol: str, get=requests.get) -> dict:
    """Bối cảnh thị trường thật (không phải testnet) ngay lúc này."""
    tf = {iv: _closed(_klines(symbol, iv, get, limit=n)) for iv, n in (("5m", 101), ("15m", 101), ("1h", 301))}
    btc = _closed(_klines("BTCUSDT", "1h", get, limit=301))
    f = features(tf, btc)
    r = get(f"{PUBLIC_API}/ticker/price", params={"symbol": symbol}, timeout=20)
    r.raise_for_status()
    f["price"] = float(r.json()["price"])
    f["hour_utc"] = time.gmtime().tm_hour
    f["weekday"] = time.gmtime().tm_wday
    return f


def excursion(klines: list, entry: float) -> tuple[float, float]:
    """(lãi cao nhất %, lỗ sâu nhất %) trong lúc giữ, theo high/low nến 1 phút."""
    hi = max(float(k[2]) for k in klines)
    lo = min(float(k[3]) for k in klines)
    return _pct(hi, entry), _pct(lo, entry)


def market_excursion(symbol: str, start_s: float, end_s: float, entry: float, get=requests.get):
    k = _klines(symbol, "1m", get, startTime=int(start_s * 1000), endTime=int(end_s * 1000), limit=1000)
    return excursion(k, entry) if k else (0.0, 0.0)


def write_row(path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, header = [], []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            header, rows = list(r.fieldnames or []), list(r)
    new_cols = [k for k in row if k not in header]
    if rows and not new_cols:
        with path.open("a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=header).writerow(row)
        return
    header += new_cols
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows + [row])


def _load(path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
    if not df.empty:
        ret = df["ret_market_pct"] if "ret_market_pct" in df else df["ret_testnet_pct"]
        df["net_pct"] = (ret - REAL_FEE_RT_PCT).round(4)
    return df


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades": 0}
    net = df["net_pct"]
    return {"trades": len(df), "win_rate_pct": round(float((net > 0).mean() * 100), 1),
            "avg_net_pct": round(float(net.mean()), 4), "sum_net_pct": round(float(net.sum()), 4),
            "avg_minutes": round(float(df["minutes"].mean()), 1)}


def summary(path) -> str:
    s = stats(_load(path))
    if not s["trades"]:
        return "Chưa có lệnh tay nào đã đóng."
    return (f"{s['trades']} lệnh | thắng {s['win_rate_pct']:.0f}% (sau phí thật) | "
            f"lãi TB {s['avg_net_pct']:+.2f}%/lệnh sau phí thật {REAL_FEE_RT_PCT:g}% | "
            f"giữ TB {s['avg_minutes']:.0f} phút")


DOC_COLS = ["symbol", "entry_time", "exit_time", "minutes", "usdt", "reason", "exit_how", "ret_market_pct",
            "net_pct", "mfe_pct", "mae_pct", "e_rsi_5m", "e_rsi_1h", "e_vol_ratio_5m", "e_ret_1h_pct",
            "e_above_ema200_1h", "e_btc_above_ema200_1h"]


def export_docs(trader, path="docs/manual.json") -> dict:
    """Nhật ký lệnh tay cho dashboard GitHub Pages (công khai — không chứa khóa hay số dư)."""
    df = _load(trader.journal)
    closed = []
    if not df.empty:
        cols = [c for c in DOC_COLS if c in df]
        sub = df[cols].astype(object).where(df[cols].notna(), None)
        closed = sorted(sub.to_dict("records"), key=lambda r: str(r["exit_time"]), reverse=True)
    out = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fee_rt_pct": REAL_FEE_RT_PCT,
        "stats": stats(df),
        "open": [{"symbol": s, "entry": p["entry"], "usdt": round(p["cost"], 2), "stop": p["stop"],
                  "time": p.get("time"), "reason": p.get("reason", ""),
                  "market_entry": (p.get("ctx") or {}).get("price")} for s, p in trader.pos.items()],
        "closed": closed,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    text = json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return json.loads(text)
