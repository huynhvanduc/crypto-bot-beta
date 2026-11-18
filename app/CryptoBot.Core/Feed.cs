using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed record Lot(string Symbol, string Source, double Qty, double Entry, double Cost);
public sealed record Trade(string Symbol, string Source, string ExitTime, double Entry, double Exit, double Pnl, double Pct);
public sealed record Fill(long Ms, string Side, string Symbol, double Price, double Quote, string Source);
public sealed record Snapshot(double Usdt, double Realized, List<Lot> Open, List<Trade> Closed, List<Fill> Fills, Dictionary<string, string> Reasons);

public static class Feed
{
    static string S(JsonNode? n) => n?.GetValue<string>() ?? "";
    static double D(JsonNode? n) => Binance.D(n);

    public static Snapshot Parse(string fills, string claude)
    {
        var f = JsonNode.Parse(fills)!;
        var rt = f["round_trips"]!;
        return new(D(f["usdt"]), D(rt["pnl_usdt"]),
            rt["open"]!.AsArray().Select(x => new Lot(S(x!["symbol"]), S(x["source"]), D(x["qty"]), D(x["entry_price"]), D(x["cost"]))).ToList(),
            rt["trades"]!.AsArray().Where(x => x!["pnl_usdt"] is not null)
                .Select(x => new Trade(S(x!["symbol"]), S(x["source"]), S(x["exit_time"]), D(x["entry_price"]), D(x["exit_price"]), D(x["pnl_usdt"]), D(x["return_pct"])))
                .OrderByDescending(t => t.ExitTime, StringComparer.Ordinal).Take(20).ToList(),
            f["fills"]!.AsArray().Take(20).Select(x => new Fill((long)D(x!["ms"]), S(x["side"]), S(x["symbol"]), D(x["price"]), D(x["quote"]), S(x["source"]))).ToList(),
            (JsonNode.Parse(claude)?["open"]?.AsArray() ?? []).ToDictionary(x => S(x!["symbol"]), x => S(x!["reason"])));
    }

    public static async Task<Snapshot> LoadAsync(HttpClient http, string baseUrl)
    {
        var t = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var fills = http.GetStringAsync($"{baseUrl}/fills.json?t={t}");
        string claude;
        try { claude = await http.GetStringAsync($"{baseUrl}/claude.json?t={t}"); }
        catch (HttpRequestException) { claude = "{}"; }
        return Parse(await fills, claude);
    }
}
