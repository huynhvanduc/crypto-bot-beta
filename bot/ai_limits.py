"""Giới hạn cứng cho chế độ Claude tự giao dịch: Claude không vượt được dù prompt nói gì."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

VN = timezone(timedelta(hours=7))


class Limits(NamedTuple):
    max_usdt: float      # tối đa USDT mỗi lệnh
    max_open: int        # tối đa số lệnh mở cùng lúc
    max_day_loss: float  # dừng mua khi lỗ đã chốt trong ngày (giờ VN) chạm mức này


def vn_date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(VN).date().isoformat()


def today_vn() -> str:
    return datetime.now(VN).date().isoformat()


def day_loss(journal: Path, fee_pct: float, today: str) -> float:
    """Lỗ đã chốt trong ngày `today` (giờ VN), sau phí thật; trả về số dương, 0 nếu đang lãi."""
    if not Path(journal).exists():
        return 0.0
    total = 0.0
    with open(journal, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("exit_time") and vn_date(r["exit_time"]) == today:
                total += float(r["usdt"]) * (float(r["ret_market_pct"]) - fee_pct) / 100
    return max(0.0, -total)


def check(lim: Limits, n_open: int, usdt: float, loss_today: float) -> str | None:
    """None nếu được mua; ngược lại là lý do từ chối."""
    if not 0 < usdt <= lim.max_usdt:
        return f"TỪ CHỐI: mỗi lệnh phải trong (0, {lim.max_usdt:g}] USDT, yêu cầu {usdt:g}."
    if n_open >= lim.max_open:
        return f"TỪ CHỐI: đã có {n_open} lệnh mở, tối đa {lim.max_open}."
    if loss_today >= lim.max_day_loss:
        return f"TỪ CHỐI: hôm nay đã lỗ {loss_today:.2f} USDT, chạm mức dừng {lim.max_day_loss:g} USDT."
    return None
