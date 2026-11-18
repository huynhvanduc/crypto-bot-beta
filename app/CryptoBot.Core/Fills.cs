using System.Globalization;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed record Fill(long TradeId, long OrderId, string ClientId, string Symbol, string Side, string Type, double Qty, double Price,
    double Quote, double Fee, string FeeAsset, string Time, long Ms, string Source)
{
    public (string, long) Key => (Symbol, TradeId);
}

public sealed record RoundTrip(string Symbol, string Source, string ExitTime, double ExitPrice, string? EntryTime, double Qty,
    double? EntryPrice, double? PnlUsdt, double? ReturnPct);

public sealed record OpenLot(string Symbol, string Source, double Qty, double EntryPrice, double Cost, string EntryTime);

public sealed record RoundTrips(List<RoundTrip> Trades, List<OpenLot> Open, double PnlUsdt, int Count);

public static class Fills
{
    public static string IsoMs(long ms) =>
        DateTimeOffset.FromUnixTimeMilliseconds(ms).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);

    public static string Classify(string? clientId, long orderId, IReadOnlySet<long> botOrderIds)
    {
        var cid = clientId ?? "";
        if (cid.StartsWith("d1-") || botOrderIds.Contains(orderId)) return "d1";
        if (cid.StartsWith("scalp-")) return "scalp";
        if (cid.StartsWith("nc-")) return "nc";
        if (cid.StartsWith("ai-")) return "ai";
        return "tay";
    }

    static Fill Make(string symbol, long tradeId, long orderId, string? clientId, string side, string type, double qty, double price,
        double quote, double fee, string? feeAsset, long ms, IReadOnlySet<long> bot) =>
        new(tradeId, orderId, clientId ?? "", symbol, side, type, qty, price, quote, fee, feeAsset ?? "", IsoMs(ms), ms,
            Classify(clientId, orderId, bot));

    static string S(JsonNode? n) => n?.GetValue<string>() ?? "";

    public static Fill? FromEvent(JsonNode ev, IReadOnlySet<long>? bot = null)
    {
        if (S(ev["e"]) != "executionReport" || S(ev["x"]) != "TRADE") return null;
        return Make(S(ev["s"]), ev["t"]!.GetValue<long>(), ev["i"]!.GetValue<long>(), ev["c"]?.GetValue<string>(), S(ev["S"]), S(ev["o"]),
            Order.Num(ev["l"]), Order.Num(ev["L"]), Order.Num(ev["Y"]), Order.Num(ev["n"]), ev["N"]?.GetValue<string>(),
            ev["T"]!.GetValue<long>(), bot ?? new HashSet<long>());
    }

    public static Fill FromRest(MyTrade t, string? clientId, string orderType, IReadOnlySet<long>? bot = null) =>
        Make(t.Symbol, t.Id, t.OrderId, clientId, t.IsBuyer ? "BUY" : "SELL", orderType, t.Qty, t.Price, t.QuoteQty, t.Commission,
            t.CommissionAsset, t.Time, bot ?? new HashSet<long>());

    public static List<Fill> Merge(IEnumerable<Fill> fills, IEnumerable<Fill> add)
    {
        var outv = fills.ToList();
        var seen = outv.Select(f => f.Key).ToHashSet();
        foreach (var f in add) if (seen.Add(f.Key)) outv.Add(f);
        return outv.OrderBy(f => f.Ms).ThenBy(f => f.TradeId).ToList();
    }

    sealed class Agg
    {
        public required string Symbol, Source, Side, Time;
        public long Ms;
        public double Qty, Quote, FeeBase, FeeUsdt;
    }

    sealed class Lot
    {
        public double Qty, Cost, Price;
        public required string Time, Source;
    }

    static string BaseOf(string s) => s.EndsWith("USDT") ? s[..^4] : s;

    public static RoundTrips Compute(IReadOnlyList<Fill> fills)
    {
        var orders = new Dictionary<(string, long), Agg>();
        foreach (var f in fills.OrderBy(f => f.Ms).ThenBy(f => f.TradeId))
        {
            if (f.Source == "d1") continue;
            if (!orders.TryGetValue((f.Symbol, f.OrderId), out var o))
                orders[(f.Symbol, f.OrderId)] = o = new Agg { Symbol = f.Symbol, Source = f.Source, Side = f.Side, Time = f.Time, Ms = f.Ms };
            o.Qty += f.Qty;
            o.Quote += f.Quote;
            if (f.FeeAsset == BaseOf(f.Symbol)) o.FeeBase += f.Fee;
            else if (f.FeeAsset == "USDT") o.FeeUsdt += f.Fee;
        }
        var lots = new Dictionary<string, List<Lot>>();
        var trades = new List<RoundTrip>();
        foreach (var o in orders.Values.OrderBy(o => o.Ms))
        {
            double price = o.Quote / o.Qty;
            if (o.Side == "BUY")
            {
                if (!lots.TryGetValue(o.Symbol, out var l)) lots[o.Symbol] = l = new();
                l.Add(new Lot { Qty = o.Qty - o.FeeBase, Cost = o.Quote + o.FeeUsdt, Price = price, Time = o.Time, Source = o.Source });
                continue;
            }
            double eps = o.Qty * 1e-9;
            double netPerCoin = (o.Quote - o.FeeUsdt - o.FeeBase * price) / o.Qty;
            double left = o.Qty, mq = 0, mcost = 0, mgross = 0;
            string? first = null;
            var queue = lots.GetValueOrDefault(o.Symbol) ?? new();
            while (left > eps && queue.Count > 0)
            {
                var lot = queue[0];
                double take = Math.Min(left, lot.Qty), unit = lot.Cost / lot.Qty;
                mq += take; mcost += take * unit; mgross += take * lot.Price;
                first ??= lot.Time;
                lot.Qty -= take; lot.Cost -= take * unit; left -= take;
                if (lot.Qty <= eps) queue.RemoveAt(0);
            }
            if (mq > eps)
            {
                double pnl = mq * netPerCoin - mcost;
                trades.Add(new RoundTrip(o.Symbol, o.Source, o.Time, price, first, mq, mgross / mq, pnl, pnl / mcost * 100));
            }
            if (left > eps) trades.Add(new RoundTrip(o.Symbol, o.Source, o.Time, price, null, left, null, null, null));
        }
        var open = lots.SelectMany(kv => kv.Value.Select(l => new OpenLot(kv.Key, l.Source, l.Qty, l.Price, l.Cost, l.Time))).ToList();
        var done = trades.Where(t => t.PnlUsdt is not null).Select(t => t.PnlUsdt!.Value).ToList();
        trades.Reverse();
        return new RoundTrips(trades, open, done.Sum(), done.Count);
    }
}
