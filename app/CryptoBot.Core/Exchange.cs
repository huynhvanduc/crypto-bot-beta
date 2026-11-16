using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed record SymbolFilters(string Base, string Quote, string Step, double MinQty, string Tick, double MinNotional);

public sealed record OrderFill(double Commission, string CommissionAsset);

public sealed record Order(long OrderId, string Status, double ExecutedQty, double CumQuote, IReadOnlyList<OrderFill> Fills,
    string ClientOrderId = "", string Type = "")
{
    public static Order FromJson(JsonNode n) => new(
        n["orderId"]?.GetValue<long>() ?? 0,
        n["status"]?.GetValue<string>() ?? "",
        Num(n["executedQty"]),
        Num(n["cummulativeQuoteQty"]),
        (n["fills"] as JsonArray)?.Select(f => new OrderFill(Num(f!["commission"]), f!["commissionAsset"]?.GetValue<string>() ?? ""))
            .ToList() ?? [],
        n["clientOrderId"]?.GetValue<string>() ?? "",
        n["type"]?.GetValue<string>() ?? "");

    internal static double Num(JsonNode? v) => v is null ? 0 : v.GetValueKind() == System.Text.Json.JsonValueKind.String
        ? Json.D(v.GetValue<string>()) : v.GetValue<double>();
}

public sealed record MyTrade(string Symbol, long Id, long OrderId, double Price, double Qty, double QuoteQty, double Commission,
    string CommissionAsset, long Time, bool IsBuyer);

public interface IExchange
{
    bool IsTestnet { get; }
    Task SyncTimeAsync();
    Task<SymbolFilters> FiltersAsync(string symbol);
    Task<double> PriceAsync(string symbol);
    Task<double> FreeAsync(string asset);
    Task<Order> MarketBuyQuoteAsync(string symbol, double quoteAmount, string? tag = null);
    Task<Order> MarketSellAsync(string symbol, double qty, string? tag = null);
    Task<Order> StopLossSellAsync(string symbol, double qty, double stopPrice, string? tag = null);
    Task<Order> GetOrderAsync(string symbol, long orderId);
    Task CancelOrderAsync(string symbol, long orderId);
    Task<IReadOnlyList<MyTrade>> MyTradesAsync(string symbol, long? fromId = null, int limit = 1000);
}

public sealed class BinanceException(int status, JsonNode? payload, string raw) : Exception($"HTTP {status}: {raw}")
{
    public int Status { get; } = status;
    public JsonNode? Payload { get; } = payload;
    public string Raw { get; } = raw;
    public int? Code => Payload is JsonObject o && o["code"] is { } c ? c.GetValue<int>() : null;
    public bool IsRestrictedLocation => Status == 451;
}

public static class ExchangeMath
{
    static long _seq;

    public static string Sign(string secret, string query)
    {
        using var h = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        return Convert.ToHexStringLower(h.ComputeHash(Encoding.UTF8.GetBytes(query)));
    }

    public static string? ClientId(string? tag)
    {
        if (string.IsNullOrEmpty(tag)) return null;
        long n = Interlocked.Increment(ref _seq) - 1;
        return $"{tag}-{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}-{n % 1000}";
    }

    /// <summary>Làm tròn xuống theo bước giá/khối lượng, không dùng ký hiệu khoa học — giống round_step.</summary>
    public static string RoundStep(double value, string step)
    {
        var inv = CultureInfo.InvariantCulture;
        decimal dStep = decimal.Parse(step, NumberStyles.Float, inv) / 1.000000000000000000000000000000000m;
        decimal v = decimal.Parse(value.ToString("R", inv), NumberStyles.Float, inv);
        decimal q = Math.Floor(v / dStep) * dStep;
        int scale = dStep.Scale;
        return scale > 0 ? Math.Round(q, scale).ToString("F" + scale, inv) : Math.Truncate(q).ToString("F0", inv);
    }

    /// <summary>(số coin thực nhận, giá trung bình, phí quy ra USDT) — giống fill_summary.</summary>
    public static (double Qty, double Avg, double Fee) FillSummary(Order o, string baseAsset)
    {
        double qty = o.ExecutedQty, quote = o.CumQuote;
        double avg = qty != 0 ? quote / qty : 0.0;
        double feeBase = o.Fills.Where(f => f.CommissionAsset == baseAsset).Sum(f => f.Commission);
        double feeQuote = o.Fills.Where(f => f.CommissionAsset == "USDT").Sum(f => f.Commission);
        return (qty - feeBase, avg, feeQuote + feeBase * avg);
    }

    public static SymbolFilters ParseFilters(JsonNode info)
    {
        var f = (info["filters"] as JsonArray)!.ToDictionary(x => x!["filterType"]!.GetValue<string>(), x => x!);
        var notional = f.GetValueOrDefault("NOTIONAL") ?? f.GetValueOrDefault("MIN_NOTIONAL");
        return new SymbolFilters(
            info["baseAsset"]!.GetValue<string>(), info["quoteAsset"]!.GetValue<string>(),
            f["LOT_SIZE"]["stepSize"]!.GetValue<string>(), Order.Num(f["LOT_SIZE"]["minQty"]),
            f["PRICE_FILTER"]["tickSize"]!.GetValue<string>(),
            notional?["minNotional"] is { } mn ? Order.Num(mn) : 0);
    }
}

public sealed class BinanceClient : IExchange
{
    public const string TestnetUrl = "https://testnet.binance.vision";
    public const string LiveUrl = "https://api.binance.com";

    readonly HttpClient _http;
    readonly string _key, _secret;
    readonly Dictionary<string, SymbolFilters> _filters = new();
    long _offset;

    public string BaseUrl { get; }
    public string ApiKey => _key;
    public bool IsTestnet => BaseUrl.Contains("testnet");
    public bool HasKeys => _key.Length > 0 && _secret.Length > 0;
    public long TimeOffset => _offset;

    public BinanceClient(HttpClient http, string key, string secret, string? baseUrl = null)
    {
        _http = http;
        _key = key.Trim();
        _secret = secret.Trim();
        BaseUrl = (string.IsNullOrWhiteSpace(baseUrl) ? TestnetUrl : baseUrl.Trim()).TrimEnd('/');
    }

    public string SignWs(string query) => ExchangeMath.Sign(_secret, query);

    async Task<JsonNode?> RequestAsync(HttpMethod method, string path, IEnumerable<KeyValuePair<string, string?>>? prms = null,
        bool signed = false)
    {
        var list = (prms ?? []).Where(p => p.Value is not null).Select(p => $"{p.Key}={Uri.EscapeDataString(p.Value!)}").ToList();
        using var req = new HttpRequestMessage();
        if (signed)
        {
            if (!HasKeys) throw new InvalidOperationException("Thiếu khóa Binance (API key / secret) trong Cài đặt");
            list.Add($"timestamp={DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + _offset}");
            list.Add("recvWindow=10000");
            var q = string.Join("&", list);
            list = [q, $"signature={ExchangeMath.Sign(_secret, q)}"];
            req.Headers.Add("X-MBX-APIKEY", _key);
        }
        var qs = string.Join("&", list);
        req.Method = method;
        req.RequestUri = new Uri($"{BaseUrl}{path}" + (qs.Length > 0 ? "?" + qs : ""));
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        using var r = await _http.SendAsync(req, cts.Token).ConfigureAwait(false);
        var text = await r.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);
        JsonNode? data = null;
        try { data = JsonNode.Parse(text); } catch (System.Text.Json.JsonException) { }
        if ((int)r.StatusCode >= 400) throw new BinanceException((int)r.StatusCode, data, text);
        return data;
    }

    static KeyValuePair<string, string?> P(string k, object? v) =>
        new(k, v switch { null => null, IFormattable f => f.ToString(null, CultureInfo.InvariantCulture), _ => v.ToString() });

    public async Task SyncTimeAsync()
    {
        var server = (await RequestAsync(HttpMethod.Get, "/api/v3/time"))!["serverTime"]!.GetValue<long>();
        _offset = server - DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    }

    public async Task<SymbolFilters> FiltersAsync(string symbol)
    {
        if (!_filters.TryGetValue(symbol, out var f))
        {
            var info = (await RequestAsync(HttpMethod.Get, "/api/v3/exchangeInfo", [P("symbol", symbol)]))!["symbols"]![0]!;
            _filters[symbol] = f = ExchangeMath.ParseFilters(info);
        }
        return f;
    }

    public async Task<double> PriceAsync(string symbol) =>
        Order.Num((await RequestAsync(HttpMethod.Get, "/api/v3/ticker/price", [P("symbol", symbol)]))!["price"]);

    async Task<JsonArray> BalancesRawAsync() =>
        (JsonArray)(await RequestAsync(HttpMethod.Get, "/api/v3/account", [P("omitZeroBalances", "true")], signed: true))!["balances"]!;

    public async Task<double> FreeAsync(string asset)
    {
        foreach (var b in await BalancesRawAsync())
            if (b!["asset"]!.GetValue<string>() == asset) return Order.Num(b["free"]);
        return 0.0;
    }

    async Task<Order> OrderAsync(string? tag, params KeyValuePair<string, string?>[] prms) =>
        Order.FromJson((await RequestAsync(HttpMethod.Post, "/api/v3/order",
            [.. prms, P("newClientOrderId", ExchangeMath.ClientId(tag))], signed: true))!);

    public Task<Order> MarketBuyQuoteAsync(string symbol, double quoteAmount, string? tag = null) =>
        OrderAsync(tag, P("symbol", symbol), P("side", "BUY"), P("type", "MARKET"),
            P("quoteOrderQty", ExchangeMath.RoundStep(quoteAmount, "0.01")), P("newOrderRespType", "FULL"));

    public async Task<Order> MarketSellAsync(string symbol, double qty, string? tag = null)
    {
        var f = await FiltersAsync(symbol);
        return await OrderAsync(tag, P("symbol", symbol), P("side", "SELL"), P("type", "MARKET"),
            P("quantity", ExchangeMath.RoundStep(qty, f.Step)), P("newOrderRespType", "FULL"));
    }

    public async Task<Order> StopLossSellAsync(string symbol, double qty, double stopPrice, string? tag = null)
    {
        var f = await FiltersAsync(symbol);
        return await OrderAsync(tag, P("symbol", symbol), P("side", "SELL"), P("type", "STOP_LOSS"),
            P("quantity", ExchangeMath.RoundStep(qty, f.Step)), P("stopPrice", ExchangeMath.RoundStep(stopPrice, f.Tick)));
    }

    public async Task<Order> GetOrderAsync(string symbol, long orderId) =>
        Order.FromJson((await RequestAsync(HttpMethod.Get, "/api/v3/order", [P("symbol", symbol), P("orderId", orderId)], signed: true))!);

    public async Task CancelOrderAsync(string symbol, long orderId) =>
        await RequestAsync(HttpMethod.Delete, "/api/v3/order", [P("symbol", symbol), P("orderId", orderId)], signed: true);

    public async Task<IReadOnlyList<MyTrade>> MyTradesAsync(string symbol, long? fromId = null, int limit = 1000)
    {
        var arr = (JsonArray)(await RequestAsync(HttpMethod.Get, "/api/v3/myTrades",
            [P("symbol", symbol), P("fromId", fromId), P("limit", limit)], signed: true))!;
        return arr.Select(t => new MyTrade(t!["symbol"]!.GetValue<string>(), t["id"]!.GetValue<long>(), t["orderId"]!.GetValue<long>(),
            Order.Num(t["price"]), Order.Num(t["qty"]), Order.Num(t["quoteQty"]), Order.Num(t["commission"]),
            t["commissionAsset"]?.GetValue<string>() ?? "", t["time"]!.GetValue<long>(), t["isBuyer"]!.GetValue<bool>())).ToList();
    }
}
