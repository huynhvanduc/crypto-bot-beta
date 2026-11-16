namespace CryptoBot.Core;

public interface IMarketData
{
    Task<DailySeries> DailyAsync(string symbol);
    Task<Dictionary<string, double>> AllPricesAsync();
}

public sealed record PositionView(string Symbol, string EntryTime, double EntryPrice, double Price, double Qty, double Stop, int Days,
    double PnlPct, double PnlUsdt, double RiskPct);

public sealed record RadarRow(string Symbol, double Price, double Breakout, double Ema200, double GapPct, bool AboveEma, string Status);

public sealed record AccountInfo(double? Usdt, bool Ok, string? Error = null);

public sealed record RunResult(double Equity, double Unrealized, List<PositionView> Positions, string LastBar, List<string> Signals,
    List<string> Entered, List<RadarRow> Radar, AccountInfo Account);

public sealed class LiveTrader(IExchange ex, BotState st, IMarketData md, Action<string>? print = null)
{
    public const string OrderTag = "d1";
    readonly List<string> _symbols = st.Slots.Keys.ToList();

    public void Log(string msg)
    {
        var line = $"{Json.NowIso()} {msg}";
        print?.Invoke(line);
        st.Log.Add(line);
        if (st.Log.Count > 200) st.Log.RemoveRange(0, st.Log.Count - 200);
    }

    async Task CloseAsync(string sym, Order order, string reason)
    {
        var pos = st.Positions[sym];
        st.Positions.Remove(sym);
        var f = await ex.FiltersAsync(sym);
        var (qty, avg, fee) = ExchangeMath.FillSummary(order, f.Base);
        double proceeds = qty * avg - fee;
        st.Slots[sym] = st.Slots[sym] - pos.Cost + proceeds;
        double ret = proceeds / pos.Cost - 1;
        st.Trades.Add(new Trade
        {
            Symbol = sym, EntryTime = pos.EntryTime, ExitTime = Json.NowIso(), EntryPrice = pos.EntryPrice, ExitPrice = avg,
            Qty = pos.Qty, ReturnPct = ret * 100, PnlUsdt = proceeds - pos.Cost, Reason = reason, Days = pos.BarsHeld,
        });
        st.LastExitBar[sym] = pos.LastBarDone;
        Log($"THOÁT {sym} @ {Fmt.G(avg)} ({reason}) {Fmt.Signed2(ret * 100)}%");
    }

    async Task SellAsync(string sym, string reason) =>
        await CloseAsync(sym, await ex.MarketSellAsync(sym, st.Positions[sym].Qty, OrderTag), reason);

    async Task PlaceStopAsync(string sym, Position pos)
    {
        try
        {
            pos.StopOrderId = (await ex.StopLossSellAsync(sym, pos.Qty, pos.Stop, OrderTag)).OrderId;
        }
        catch (BinanceException e)
        {
            Log($"Không đặt được stop {sym} ({e.Raw}); bán market");
            await SellAsync(sym, "stop");
        }
    }

    public async Task ReconcileAsync()
    {
        foreach (var sym in st.Positions.Keys.ToList())
        {
            var pos = st.Positions[sym];
            if (pos.StopOrderId is not { } oid) { await PlaceStopAsync(sym, pos); continue; }
            Order o;
            try { o = await ex.GetOrderAsync(sym, oid); }
            catch (BinanceException) { o = new Order(oid, "NOT_FOUND", 0, 0, []); }
            if (o.Status == "FILLED") await CloseAsync(sym, o, "stop");
            else if (o.Status is "CANCELED" or "EXPIRED" or "REJECTED" or "NOT_FOUND")
            {
                var f = await ex.FiltersAsync(sym);
                if (await ex.FreeAsync(f.Base) < pos.Qty * 0.5)
                {
                    double px = await ex.PriceAsync(sym);
                    await CloseAsync(sym, new Order(oid, "FILLED", pos.Qty, pos.Qty * px, []), "mất (sàn reset)");
                }
                else
                {
                    Log($"Lệnh stop {sym} ở trạng thái {o.Status}; đặt lại");
                    await PlaceStopAsync(sym, pos);
                }
            }
        }
    }

    async Task UpdateStopsAsync(Dictionary<string, DailySeries> bars)
    {
        foreach (var sym in st.Positions.Keys.ToList())
        {
            var pos = st.Positions[sym];
            var df = bars[sym];
            var done = Json.ParseTime(pos.LastBarDone);
            double oldStop = pos.Stop;
            bool any = false;
            for (int i = 0; i < df.Count; i++)
            {
                if (df.Time[i] <= done) continue;
                any = true;
                pos.BarsHeld++;
                pos.Hh = Math.Max(pos.Hh, df.High[i]);
                pos.Stop = Math.Max(pos.Stop, pos.Hh - D1.TrailAtr * pos.Atr);
                pos.LastBarDone = Json.PdIso(df.Time[i]);
            }
            if (!any) continue;
            if (pos.BarsHeld >= D1.MaxBars)
            {
                await ex.CancelOrderAsync(sym, pos.StopOrderId!.Value);
                await SellAsync(sym, "hết 240 ngày");
            }
            else if (pos.Stop > oldStop)
            {
                await ex.CancelOrderAsync(sym, pos.StopOrderId!.Value);
                Log($"Nâng stop {sym}: {Fmt.G(oldStop)} → {Fmt.G(pos.Stop)}");
                await PlaceStopAsync(sym, pos);
            }
        }
    }

    public async Task<int> CloseAllAsync(string reason = "bán tay")
    {
        await ex.SyncTimeAsync();
        await ReconcileAsync();
        int n = 0;
        foreach (var sym in st.Positions.Keys.ToList())
        {
            var pos = st.Positions[sym];
            if (pos.StopOrderId is { } oid)
            {
                try { await ex.CancelOrderAsync(sym, oid); }
                catch (BinanceException e) { Log($"Hủy stop {sym} lỗi ({e.Raw}); vẫn bán"); }
            }
            await SellAsync(sym, reason);
            n++;
        }
        st.Paused = true;
        Log($"ĐÃ BÁN HẾT {n} lệnh và TẠM DỪNG bot (bấm Tiếp tục để bật lại)");
        return n;
    }

    public void SetPaused(bool paused)
    {
        st.Paused = paused;
        Log(paused ? "TẠM DỪNG bot: không mua mới, lệnh đang mở vẫn giữ stop" : "BẬT LẠI bot");
    }

    async Task<List<string>> EnterAsync(Dictionary<string, DailySeries> bars, DateTimeOffset lastBar)
    {
        var entered = new List<string>();
        if (st.Paused == true) { Log("Bot đang tạm dừng: bỏ qua mọi tín hiệu mua"); return entered; }
        foreach (var sym in _symbols)
        {
            if (st.Positions.ContainsKey(sym) || Config.Unsupported.Contains(sym)) continue;
            var df = bars[sym];
            if (df.IsEmpty || df.LastTime != lastBar || !df.Signal[^1]) continue;
            if (await BuyAsync(sym, df, lastBar, "")) entered.Add(sym);
        }
        return entered;
    }

    bool ExitedSince(string sym, DateTimeOffset lastBar) =>
        st.LastExitBar.GetValueOrDefault(sym) is { Length: > 0 } le && Json.ParseTime(le) >= lastBar;

    async Task<bool> BuyAsync(string sym, DailySeries df, DateTimeOffset lastBar, string why)
    {
        if (ExitedSince(sym, lastBar)) return false;
        double atr = df.Atr[^1];
        double quote = st.Slots[sym];
        var f = await ex.FiltersAsync(sym);
        if (quote < Math.Max(f.MinNotional, 5) * 1.5) { Log($"Bỏ qua {sym}: vốn phần này quá nhỏ ({Fmt.F2(quote)} USDT)"); return false; }
        var order = await ex.MarketBuyQuoteAsync(sym, quote * 0.995, OrderTag);
        var (qty, avg, fee) = ExchangeMath.FillSummary(order, f.Base);
        double cost = order.CumQuote + (order.Fills.Count > 0 && order.Fills[0].CommissionAsset == "USDT" ? fee : 0);
        var pos = new Position
        {
            EntryTime = Json.NowIso(), SignalBar = Json.PdIso(lastBar), EntryPrice = avg, Qty = qty, Cost = cost, Atr = atr,
            Stop = avg - D1.SlAtr * atr, LastBarDone = Json.PdIso(lastBar),
        };
        st.Positions[sym] = pos;
        Log($"VÀO {sym} @ {Fmt.G(avg)}, {Fmt.G(qty)} coin ({Fmt.F2(cost)} USDT), stop {Fmt.G(pos.Stop)}{why}");
        await PlaceStopAsync(sym, pos);
        return true;
    }

    public async Task<RunResult> IntradayAsync()
    {
        await ex.SyncTimeAsync();
        await ReconcileAsync();
        var bars = new Dictionary<string, DailySeries>();
        foreach (var s in _symbols) bars[s] = await md.DailyAsync(s);
        var lastBar = bars.Values.Where(d => !d.IsEmpty).Max(d => d.LastTime);
        var prices = await md.AllPricesAsync();
        var entered = new List<string>();
        foreach (var sym in _symbols)
        {
            if (st.Paused == true || st.Positions.ContainsKey(sym) || Config.Unsupported.Contains(sym)) continue;
            var df = bars[sym];
            if (df.Count <= D1.DonchianN || df.LastTime != lastBar || double.IsNaN(df.Atr[^1]) || !prices.TryGetValue(sym, out var px)) continue;
            double level = df.High[^D1.DonchianN..].Max();
            if (px <= level || px <= df.Ema[^1]) continue;
            if (await BuyAsync(sym, df, lastBar, $" — trong ngày: giá {Fmt.G(px)} vượt đỉnh 20 ngày {Fmt.G(level)}")) entered.Add(sym);
        }
        var (equity, unreal, positions) = await SnapshotAsync(bars);
        st.LastRun = Json.NowIso();
        AccountInfo account;
        try { account = new AccountInfo(ex.IsTestnet ? await ex.FreeAsync("USDT") : null, true); }
        catch (Exception e) { account = new AccountInfo(null, false, e.Message[..Math.Min(200, e.Message.Length)]); }
        return new RunResult(equity, unreal, positions, Json.PdIso(lastBar), entered, entered, await RadarAsync(bars), account);
    }

    async Task<(double Equity, double Unreal, List<PositionView> Positions)> SnapshotAsync(Dictionary<string, DailySeries> bars)
    {
        var positions = new List<PositionView>();
        double unreal = 0, equity = 0;
        foreach (var sym in _symbols)
        {
            double slot = st.Slots[sym];
            if (!st.Positions.TryGetValue(sym, out var pos)) { equity += slot; continue; }
            double px;
            try { px = await ex.PriceAsync(sym); } catch { px = bars[sym].Close[^1]; }
            double value = pos.Qty * px * (1 - D1.Fee);
            equity += slot - pos.Cost + value;
            unreal += value - pos.Cost;
            positions.Add(new PositionView(sym, pos.EntryTime, pos.EntryPrice, px, pos.Qty, pos.Stop, pos.BarsHeld,
                (value / pos.Cost - 1) * 100, value - pos.Cost, (pos.Stop / px - 1) * 100));
        }
        return (equity, unreal, positions);
    }

    async Task<List<RadarRow>> RadarAsync(Dictionary<string, DailySeries> bars)
    {
        Dictionary<string, double> prices;
        try { prices = await md.AllPricesAsync(); } catch { prices = new(); }
        var rows = new List<RadarRow>();
        foreach (var sym in _symbols)
        {
            var df = bars[sym];
            if (df.Count < D1.DonchianN || Config.Unsupported.Contains(sym)) continue;
            double level = df.High[^D1.DonchianN..].Max();
            double ema = df.Ema[^1];
            double px = prices.TryGetValue(sym, out var p) ? p : df.Close[^1];
            double need = Math.Max(level, ema);
            string status = st.Positions.ContainsKey(sym) ? "Đang giữ"
                : px > need ? "Đủ điều kiện — bot mua ở lần xét 15 phút tới"
                : px <= ema ? "Dưới EMA200 (xu hướng giảm)"
                : "Chờ breakout";
            rows.Add(new RadarRow(sym, px, level, ema, (need / px - 1) * 100, px > ema, status));
        }
        return rows.OrderBy(r => r.Status == "Đang giữ").ThenBy(r => r.GapPct).ToList();
    }

    public async Task<RunResult> RunAsync()
    {
        await ex.SyncTimeAsync();
        await ReconcileAsync();
        var bars = new Dictionary<string, DailySeries>();
        foreach (var s in _symbols) bars[s] = await md.DailyAsync(s);
        var lastBar = bars.Values.Where(d => !d.IsEmpty).Max(d => d.LastTime);
        bool newDay = st.LastBar is null || Json.ParseTime(st.LastBar) < lastBar;
        var entered = new List<string>();
        if (newDay)
        {
            await UpdateStopsAsync(bars);
            entered = await EnterAsync(bars, lastBar);
            st.LastBar = Json.PdIso(lastBar);
            Log($"Đã xử lý nến ngày {lastBar:yyyy-MM-dd}: {entered.Count} lệnh mới");
        }
        else Log($"Nến ngày {lastBar:yyyy-MM-dd} đã xử lý trước đó; chỉ đối chiếu lệnh và cập nhật giá");
        var signals = _symbols.Where(s => !bars[s].IsEmpty && bars[s].LastTime == lastBar && bars[s].Signal[^1]).ToList();
        var (equity, unreal, positions) = await SnapshotAsync(bars);
        st.EquityCurve.Add(new EquityPoint(Json.NowIso(), Math.Round(equity, 2)));
        st.LastRun = Json.NowIso();
        AccountInfo account;
        try { account = new AccountInfo(ex.IsTestnet ? await ex.FreeAsync("USDT") : null, true); }
        catch (Exception e) { account = new AccountInfo(null, false, e.Message[..Math.Min(200, e.Message.Length)]); }
        return new RunResult(equity, unreal, positions, Json.PdIso(lastBar), signals, entered, await RadarAsync(bars), account);
    }
}

public static class Config
{
    public const double Capital = 10_000.0;
    public static readonly string[] AllSymbols =
    [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT",
        "DOTUSDT", "TRXUSDT", "ATOMUSDT", "UNIUSDT", "ETCUSDT", "BCHUSDT", "XLMUSDT", "FILUSDT", "NEARUSDT", "ALGOUSDT",
        "VETUSDT", "ICPUSDT", "AAVEUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "HBARUSDT", "INJUSDT", "GRTUSDT", "EOSUSDT",
    ];
    public static readonly HashSet<string> Unsupported = ["EOSUSDT"];
    public static string[] Symbols => AllSymbols.Where(s => !Unsupported.Contains(s)).ToArray();
}
