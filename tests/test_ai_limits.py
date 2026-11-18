from bot.ai_limits import Limits, check, day_loss


def write(tmp_path, rows):
    p = tmp_path / "j.csv"
    p.write_text("symbol,exit_time,usdt,ret_market_pct\n" + "".join(f"{r}\n" for r in rows), encoding="utf-8")
    return p


def test_check_allows_within_limits():
    assert check(Limits(200, 5, 150), n_open=4, usdt=200, loss_today=149.9) is None


def test_check_blocks_each_limit():
    lim = Limits(200, 5, 150)
    assert "200" in check(lim, n_open=0, usdt=200.01, loss_today=0)
    assert "5" in check(lim, n_open=5, usdt=100, loss_today=0)
    assert "150" in check(lim, n_open=0, usdt=100, loss_today=150)
    assert check(lim, n_open=0, usdt=0, loss_today=0)


def test_day_loss_counts_only_today_vn_after_fee(tmp_path):
    j = write(tmp_path, [
        "BTCUSDT,2026-11-19T02:00:00Z,200,-2.0",   # 09:00 19-11 giờ VN: -2% - 0.2% = -4.4 USDT
        "ETHUSDT,2026-11-19T03:00:00Z,100,1.2",    # +1.0 USDT
        "SOLUSDT,2026-11-18T16:59:00Z,200,-5.0",   # 23:59 18-11 giờ VN: hôm trước, bỏ qua
    ])
    assert abs(day_loss(j, fee_pct=0.2, today="2026-11-19") - 3.4) < 1e-9


def test_day_loss_profit_or_missing_file_is_zero(tmp_path):
    assert day_loss(write(tmp_path, ["BTCUSDT,2026-11-19T02:00:00Z,200,3.0"]), 0.2, "2026-11-19") == 0
    assert day_loss(tmp_path / "none.csv", 0.2, "2026-11-19") == 0
