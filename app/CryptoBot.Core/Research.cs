using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed class ResearchPosition
{
    public string Symbol { get; set; } = "";
    public double Qty { get; set; }
    public double Entry { get; set; }
    public double Cost { get; set; }
    public double RefPrice { get; set; }
    public double Atr { get; set; }
    public double Stop { get; set; }
    public double Peak { get; set; }
    public string EntryTime { get; set; } = "";
    public long EntryMs { get; set; }
}

public sealed class ResearchTrade
{
    public string Symbol { get; set; } = "";
    public string EntryTime { get; set; } = "";
    public string ExitTime { get; set; } = "";
    public double EntryPrice { get; set; }
    public double ExitPrice { get; set; }
    public double Qty { get; set; }
    public double Minutes { get; set; }
    public string Reason { get; set; } = "";
    public double GrossPct { get; set; }
    public double NetPct { get; set; }
    public double NetUsdt { get; set; }
    public double SlipBps { get; set; }
}

public sealed class ResearchState
{
    public bool Enabled { get; set; }
    public Dictionary<string, ResearchPosition> Positions { get; set; } = new();
    public List<ResearchTrade> Trades { get; set; } = new();
    public long LastBarMs { get; set; }
    public string? Note { get; set; }
}

public sealed class ResearchTrader(IExchange ex, HttpClient http, ResearchState st, Action<string> log)
{
    public static readonly string[] Symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"];
    public const double PerTrade = 100, Budget = 500, Fee = 0.001, StopAtr = 1.5, MinTarget = 0.006, FlowMin = 0.3;
    public const int TrailAfterMin = 10, MaxHoldMin = 30;
    public const string Tag = "nc";
    const long FiveMin = 300_000, HourMs = 3_600_000;
    readonly Dictionary<string, (long Hour, bool Up)> _regime = new();

    sealed record K(long Open, double O, double H, double L, double C, double V, double TakerBuy);

    async Task<List<K>> KlinesAsync(string sym, string interval, int limit, long nowMs)
    {
        var arr = JsonNode.Parse(await http.GetStringAsync($"{MarketData.PublicApi}/klines?symbol={sym}&interval={interval}&limit={limit}"))!.AsArray();
        static double P(JsonNode? n) => double.Parse(n!.GetValue<string>(), CultureInfo.InvariantCulture);
        return arr.Where(k => k![6]!.GetValue<long>() < nowMs)
            .Select(k => new K(k![0]!.GetValue<long>(), P(k[1]), P(k[2]), P(k[3]), P(k[4]), P(k[5]), P(k[9]))).ToList();
    }

    async Task<bool> UpAsync(string sym, bool btc, long nowMs)
    {
        long hour = nowMs / HourMs;
        if (_regime.TryGetValue(sym + btc, out var c) && c.Hour == hour) return c.Up;
        var h = await KlinesAsync(sym, "1h", 1000, nowMs);
        var close = h.Select(k => k.C).ToArray();
        var e200 = Indicators.Ema(close, 200);
        bool up = close.Length > 200 && close[^1] > e200[^1] && (btc || Indicators.Ema(close, 50)[^1] > e200[^1]);
        _regime[sym + btc] = (hour, up);
        return up;
    }

    public async Task<bool> TickAsync()
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        bool changed = false;
        foreach (var p in st.Positions.Values.ToList())
        {
            double px = await ex.PriceAsync(p.Symbol);
            double minutes = (now - p.EntryMs) / 60_000.0;
            p.Peak = Math.Max(p.Peak, px);
            if (minutes >= TrailAfterMin) p.Stop = Math.Max(p.Stop, p.Peak - StopAtr * p.Atr);
            if (px <= p.Stop) { await CloseAsync(p, "stop"); changed = true; }
            else if (minutes >= MaxHoldMin) { await CloseAsync(p, $"hết {MaxHoldMin} phút"); changed = true; }
        }
        long bar = now / FiveMin * FiveMin - FiveMin;
        if (!st.Enabled || bar <= st.LastBarMs || now - (bar + FiveMin) < 3000) return changed;
        st.LastBarMs = bar;
        if (!await UpAsync("BTCUSDT", true, now)) { st.Note = $"{Json.NowIso()} BTC dưới EMA200 khung 1h → không vào lệnh"; return true; }
        int found = 0;
        foreach (var sym in Symbols)
        {
            if (st.Positions.ContainsKey(sym)) continue;
            if ((st.Positions.Count + 1) * PerTrade > Budget) break;
            var k5 = await KlinesAsync(sym, "5m", 100, now);
            if (k5.Count < 30 || k5[^1].Open != bar) continue;
            var last = k5[^1];
            double flow = last.V > 0 ? (2 * last.TakerBuy - last.V) / last.V : 0;
            if (!(flow > FlowMin && last.C > last.O)) continue;
            var atr = Indicators.Atr(k5.Select(k => k.H).ToArray(), k5.Select(k => k.L).ToArray(), k5.Select(k => k.C).ToArray())[^1];
            if (double.IsNaN(atr) || 3 * atr / last.C < MinTarget) continue;
            if (!await UpAsync(sym, false, now)) continue;
            if (await ex.FreeAsync("USDT") < PerTrade * 1.5) { log("Nghiên cứu: USDT trên sàn thấp, ngừng mua"); break; }
            await EnterAsync(sym, last.C, atr, flow);
            found++;
        }
        st.Note = $"{Json.NowIso()} đã xét nến 5 phút {DateTimeOffset.FromUnixTimeMilliseconds(bar).ToOffset(TimeSpan.FromHours(7)):HH:mm}: " +
                  (found > 0 ? $"vào {found} lệnh" : "chưa có tín hiệu");
        return true;
    }

    async Task EnterAsync(string sym, double refPx, double atr, double flow)
    {
        var f = await ex.FiltersAsync(sym);
        var o = await ex.MarketBuyQuoteAsync(sym, PerTrade, Tag);
        var (qty, avg, _) = ExchangeMath.FillSummary(o, f.Base);
        long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        st.Positions[sym] = new ResearchPosition
        {
            Symbol = sym, Qty = qty, Entry = avg, Cost = o.CumQuote, RefPrice = refPx, Atr = atr, Stop = avg - StopAtr * atr, Peak = avg,
            EntryTime = Json.NowIso(), EntryMs = now,
        };
        log($"Nghiên cứu VÀO {sym} @ {Fmt.G(avg)} (dòng tiền {flow:+0.00}, stop {Fmt.G(avg - StopAtr * atr)})");
    }

    async Task CloseAsync(ResearchPosition p, string reason)
    {
        var f = await ex.FiltersAsync(p.Symbol);
        var o = await ex.MarketSellAsync(p.Symbol, p.Qty, Tag);
        var (_, avg, _) = ExchangeMath.FillSummary(o, f.Base);
        st.Positions.Remove(p.Symbol);
        double net = avg * (1 - Fee) / (p.Entry * (1 + Fee)) - 1;
        var t = new ResearchTrade
        {
            Symbol = p.Symbol, EntryTime = p.EntryTime, ExitTime = Json.NowIso(), EntryPrice = p.Entry, ExitPrice = avg, Qty = p.Qty,
            Minutes = Math.Round((DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - p.EntryMs) / 60_000.0, 1), Reason = reason,
            GrossPct = (avg / p.Entry - 1) * 100, NetPct = net * 100, NetUsdt = net * p.Cost, SlipBps = (p.Entry / p.RefPrice - 1) * 1e4,
        };
        st.Trades.Add(t);
        log($"Nghiên cứu THOÁT {p.Symbol} @ {Fmt.G(avg)} ({reason}, {t.Minutes:0.#} phút) {Fmt.Signed2(t.NetPct)}% sau phí");
    }

    public async Task CloseAllAsync()
    {
        foreach (var p in st.Positions.Values.ToList()) await CloseAsync(p, "tắt nghiên cứu");
    }
}

public sealed record ResearchStats(int Trades, double WinPct, double AvgNetPct, double TotalNetUsdt, double AvgSlipBps, double AvgMinutes);

public static class ResearchReport
{
    public static ResearchStats? Stats(IReadOnlyList<ResearchTrade> t) => t.Count == 0 ? null
        : new(t.Count, t.Count(x => x.NetPct > 0) * 100.0 / t.Count, t.Average(x => x.NetPct), t.Sum(x => x.NetUsdt),
            t.Average(x => x.SlipBps), t.Average(x => x.Minutes));

    public static ResearchState Load(string path) =>
        File.Exists(path) ? JsonSerializer.Deserialize<ResearchState>(File.ReadAllText(path), Json.Options) ?? new() : new();

    public static void Save(string path, ResearchState s) => Files.WriteAtomic(path, JsonSerializer.Serialize(s, Json.Options));
}
