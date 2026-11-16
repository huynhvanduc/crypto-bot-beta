using System.Text.Json;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed record FillMessage(int V, string Kind, Fill Fill, double? Usdt);

public sealed class FillWatcher(IExchange ex, Action<FillMessage> publish, IEnumerable<string> symbols, string topic, string fillsPath,
    Func<BotState?> state, Func<double>? clock = null)
{
    public const double BalanceWait = 0.5;
    public const int Keep = 200;
    readonly List<string> _symbols = symbols.ToList();
    readonly Func<double> _clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
    readonly Dictionary<(string, long), (string Cid, string Type)> _orderInfo = new();
    List<(double At, Fill F)> _pending = new();

    public List<Fill> FillList { get; private set; } = new();
    public double? Usdt { get; private set; }
    public bool Dirty { get; set; }
    public bool BotStopFilled { get; set; }

    sealed record Stored(List<Fill> Fills, double? Usdt);

    public void Load()
    {
        if (!File.Exists(fillsPath)) return;
        var d = JsonSerializer.Deserialize<Stored>(File.ReadAllText(fillsPath), Json.Options);
        FillList = d?.Fills ?? new();
        Usdt = d?.Usdt;
    }

    void Save() => Files.WriteAtomic(fillsPath, JsonSerializer.Serialize(new Stored(FillList, Usdt), Json.Options));

    public string Export()
    {
        Dirty = false;
        var recent = FillList.Skip(Math.Max(0, FillList.Count - Keep)).Reverse().ToList();
        return JsonSerializer.Serialize(new
        {
            updated = Fills.IsoMs(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), topic, usdt = Usdt, fills = recent,
            round_trips = Fills.Compute(FillList),
        }, Json.Options);
    }

    public HashSet<long> BotOrderIds() =>
        state()?.Positions.Values.Where(p => p.StopOrderId is not null).Select(p => p.StopOrderId!.Value).ToHashSet() ?? new();

    long StartMs() => state()?.Start is { Length: > 0 } s ? Json.ParseTime(s).ToUnixTimeMilliseconds() : 0;

    public async Task<int> BackfillAsync()
    {
        var bot = BotOrderIds();
        long start = StartMs();
        var add = new List<Fill>();
        foreach (var sym in _symbols.Concat(FillList.Select(f => f.Symbol)).Distinct().Order(StringComparer.Ordinal))
        {
            var known = FillList.Where(f => f.Symbol == sym).Select(f => f.TradeId).ToList();
            foreach (var t in await ex.MyTradesAsync(sym, known.Count > 0 ? known.Max() + 1 : null))
            {
                if (known.Count == 0 && t.Time < start) continue;
                var k = (sym, t.OrderId);
                if (!_orderInfo.TryGetValue(k, out var info))
                {
                    var o = await ex.GetOrderAsync(sym, t.OrderId);
                    _orderInfo[k] = info = (o.ClientOrderId, o.Type);
                }
                add.Add(Fills.FromRest(t, info.Cid, info.Type, bot));
            }
        }
        Usdt = await ex.FreeAsync("USDT");
        int before = FillList.Count;
        FillList = Fills.Merge(FillList, add);
        int added = FillList.Count - before;
        if (added > 0) { Dirty = true; Save(); }
        return added;
    }

    public async Task<List<Fill>> PollAsync()
    {
        var known = FillList.Select(f => f.Key).ToHashSet();
        await BackfillAsync();
        var fresh = FillList.Where(f => !known.Contains(f.Key)).ToList();
        foreach (var f in fresh)
        {
            publish(new FillMessage(1, "fill", f, Usdt));
            if (f.Source == "d1" && f.Type == "STOP_LOSS") BotStopFilled = true;
        }
        return fresh;
    }

    public List<Fill> Handle(JsonNode frame)
    {
        if (frame["event"] is not JsonObject ev) return [];
        var kind = ev["e"]?.GetValue<string>();
        if (kind == "eventStreamTerminated") throw new IOException("Sàn đã ngắt luồng sự kiện");
        if (kind == "executionReport")
        {
            var f = Fills.FromEvent(ev, BotOrderIds());
            if (f is not null)
            {
                _pending.Add((_clock() + BalanceWait, f));
                if (f.Source == "d1" && ev["o"]?.GetValue<string>() == "STOP_LOSS" && ev["X"]?.GetValue<string>() == "FILLED")
                    BotStopFilled = true;
            }
            return [];
        }
        if (kind == "outboundAccountPosition")
        {
            foreach (var b in ev["B"] as JsonArray ?? [])
                if (b!["a"]?.GetValue<string>() == "USDT") Usdt = Order.Num(b["f"]) + Order.Num(b["l"]);
            return Flush(true);
        }
        return [];
    }

    public List<Fill> Tick() => Flush(false);

    List<Fill> Flush(bool everything)
    {
        double now = _clock();
        var due = _pending.Where(p => everything || p.At <= now).Select(p => p.F).ToList();
        _pending = _pending.Where(p => !(everything || p.At <= now)).ToList();
        var known = FillList.Select(f => f.Key).ToHashSet();
        var outv = due.Where(f => !known.Contains(f.Key)).GroupBy(f => f.Key).Select(g => g.Last()).ToList();
        if (outv.Count == 0) return [];
        FillList = Fills.Merge(FillList, outv);
        foreach (var f in outv) publish(new FillMessage(1, "fill", f, Usdt));
        Dirty = true;
        Save();
        return outv;
    }
}
