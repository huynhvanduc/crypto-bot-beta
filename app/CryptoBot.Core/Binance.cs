using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed record Position(string Symbol, double Qty, double Entry, long StopId);

public sealed class BinanceException(string message) : Exception(message);

public sealed class Binance(HttpClient http, string key, string secret)
{
    public const string Testnet = "https://testnet.binance.vision";
    public const string Public = "https://data-api.binance.vision";
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    readonly Dictionary<string, (string Base, string Step, string Tick)> _filters = [];
    long? _offset;

    public bool HasKeys => key.Length > 0 && secret.Length > 0;

    public static double D(JsonNode? n) => n is null ? 0
        : n.GetValueKind() == JsonValueKind.String ? double.Parse(n.GetValue<string>(), Inv) : n.GetValue<double>();

    public static string RoundStep(double value, string step)
    {
        var s = decimal.Parse(step, NumberStyles.Float, Inv) / 1.000000000000000000000000000000000m;
        return (Math.Floor((decimal)value / s) * s).ToString("F" + s.Scale, Inv);
    }

    public static double Atr(IReadOnlyList<(double H, double L, double C)> b, int n = 14)
    {
        double atr = b[0].H - b[0].L;
        for (int i = 1; i < b.Count; i++)
            atr += (Math.Max(b[i].H - b[i].L, Math.Max(Math.Abs(b[i].H - b[i - 1].C), Math.Abs(b[i].L - b[i - 1].C))) - atr) / n;
        return atr;
    }

    public static (double Qty, double Avg) Filled(JsonNode o, string baseAsset)
    {
        double qty = D(o["executedQty"]);
        double fee = o["fills"]!.AsArray().Where(f => f!["commissionAsset"]!.GetValue<string>() == baseAsset).Sum(f => D(f!["commission"]));
        return (qty - fee, D(o["cummulativeQuoteQty"]) / qty);
    }

    public static async Task<Dictionary<string, double>> PricesAsync(HttpClient http, IEnumerable<string> symbols)
    {
        var list = symbols.Distinct().ToList();
        if (list.Count == 0) return [];
        var url = $"{Public}/api/v3/ticker/price?symbols={Uri.EscapeDataString(JsonSerializer.Serialize(list))}";
        return JsonNode.Parse(await http.GetStringAsync(url))!.AsArray().ToDictionary(x => x!["symbol"]!.GetValue<string>(), x => D(x!["price"]));
    }

    async Task<JsonNode> Send(HttpMethod method, string path, string query, bool signed = true)
    {
        if (signed)
        {
            _offset ??= (long)D((await Send(HttpMethod.Get, "/api/v3/time", "", false))["serverTime"]) - DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            query += $"{(query.Length > 0 ? "&" : "")}timestamp={DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + _offset}&recvWindow=10000";
            query += "&signature=" + Convert.ToHexStringLower(HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), Encoding.UTF8.GetBytes(query)));
        }
        using var req = new HttpRequestMessage(method, $"{Testnet}{path}{(query.Length > 0 ? "?" + query : "")}");
        if (signed) req.Headers.Add("X-MBX-APIKEY", key);
        using var r = await http.SendAsync(req);
        var text = await r.Content.ReadAsStringAsync();
        if (!r.IsSuccessStatusCode) throw new BinanceException($"Sàn báo lỗi {(int)r.StatusCode}: {text}");
        return JsonNode.Parse(text)!;
    }

    async Task<(string Base, string Step, string Tick)> Filters(string symbol)
    {
        if (_filters.TryGetValue(symbol, out var f)) return f;
        var s = (await Send(HttpMethod.Get, "/api/v3/exchangeInfo", $"symbol={symbol}", false))["symbols"]![0]!;
        var fl = s["filters"]!.AsArray().ToDictionary(x => x!["filterType"]!.GetValue<string>(), x => x!);
        return _filters[symbol] = (s["baseAsset"]!.GetValue<string>(), fl["LOT_SIZE"]["stepSize"]!.GetValue<string>(), fl["PRICE_FILTER"]["tickSize"]!.GetValue<string>());
    }

    Task<JsonNode> Order(string query) =>
        Send(HttpMethod.Post, "/api/v3/order", $"{query}&newClientOrderId=app-{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}");

    async Task<List<(double H, double L, double C)>> Hourly(string symbol) =>
        JsonNode.Parse(await http.GetStringAsync($"{Public}/api/v3/klines?symbol={symbol}&interval=1h&limit=100"))!.AsArray()
            .SkipLast(1).Select(k => (D(k![2]), D(k[3]), D(k[4]))).ToList();

    public async Task<(Position Pos, string? Warning)> BuyAsync(string symbol, double usdt)
    {
        var f = await Filters(symbol);
        var (qty, entry) = Filled(await Order($"symbol={symbol}&side=BUY&type=MARKET&quoteOrderQty={RoundStep(usdt, "0.01")}&newOrderRespType=FULL"), f.Base);
        try
        {
            var stop = entry - 2 * Atr(await Hourly(symbol));
            var o = await Order($"symbol={symbol}&side=SELL&type=STOP_LOSS&quantity={RoundStep(qty, f.Step)}&stopPrice={RoundStep(stop, f.Tick)}");
            return (new(symbol, qty, entry, (long)D(o["orderId"])), null);
        }
        catch (Exception e)
        {
            return (new(symbol, qty, entry, 0), $"Chưa đặt được cắt lỗ — bán tay khi cần ({e.Message})");
        }
    }

    public async Task SellAsync(Position p)
    {
        var f = await Filters(p.Symbol);
        if (p.StopId > 0)
            try { await Send(HttpMethod.Delete, "/api/v3/order", $"symbol={p.Symbol}&orderId={p.StopId}"); }
            catch (BinanceException) { }
        await Order($"symbol={p.Symbol}&side=SELL&type=MARKET&quantity={RoundStep(p.Qty, f.Step)}");
    }

    public async Task<bool> ClosedAsync(Position p) => p.StopId > 0 &&
        (await Send(HttpMethod.Get, "/api/v3/order", $"symbol={p.Symbol}&orderId={p.StopId}"))["status"]!.GetValue<string>() is "FILLED" or "CANCELED" or "EXPIRED";
}
