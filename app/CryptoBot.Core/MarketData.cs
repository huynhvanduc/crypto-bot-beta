using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed class MarketData(HttpClient http, string dataDir, Action<string>? progress = null) : IMarketData
{
    public const string PublicApi = "https://data-api.binance.vision/api/v3";
    static readonly long StartMs = new DateTimeOffset(2020, 1, 1, 0, 0, 0, TimeSpan.Zero).ToUnixTimeMilliseconds();
    const long HourMs = 3_600_000, DayMs = 86_400_000;

    sealed class Store
    {
        public long LastOpenMs { get; set; } = -1;
        public List<double[]> Daily { get; set; } = new();
        public List<double[]> Tail { get; set; } = new();
    }

    static Bar ToBar(double[] r) => new((long)r[0], r[1], r[2], r[3], r[4], r[5]);
    static double[] FromBar(Bar b) => [b.OpenMs, b.Open, b.High, b.Low, b.Close, b.Volume];

    string PathOf(string sym) => Path.Combine(dataDir, "bars", $"{sym}_1d.json");

    async Task<List<Bar>> FetchAsync(string sym, long startMs, long nowMs)
    {
        var rows = new List<Bar>();
        long cursor = startMs;
        while (true)
        {
            JsonArray? batch = null;
            for (int attempt = 0; ; attempt++)
            {
                try
                {
                    var txt = await http.GetStringAsync($"{PublicApi}/klines?symbol={sym}&interval=1h&startTime={cursor}&limit=1000");
                    batch = JsonNode.Parse(txt) as JsonArray;
                    break;
                }
                catch (HttpRequestException) when (attempt < 4) { await Task.Delay(1000 << attempt); }
            }
            if (batch is null || batch.Count == 0) break;
            foreach (var k in batch)
            {
                long closeMs = k![6]!.GetValue<long>();
                if (closeMs >= nowMs) continue;
                rows.Add(new Bar(k[0]!.GetValue<long>(), P(k[1]), P(k[2]), P(k[3]), P(k[4]), P(k[5])));
            }
            cursor = batch[^1]![0]!.GetValue<long>() + 1;
            if (batch.Count < 1000) break;
            await Task.Delay(200);
        }
        return rows;
    }

    static double P(JsonNode? n) => double.Parse(n!.GetValue<string>(), NumberStyles.Float, CultureInfo.InvariantCulture);

    static long DayOf(long ms) => ms - ((ms % DayMs) + DayMs) % DayMs;

    public async Task<DailySeries> DailyAsync(string symbol)
    {
        var path = PathOf(symbol);
        var st = File.Exists(path) ? JsonSerializer.Deserialize<Store>(await File.ReadAllTextAsync(path), Json.Options)! : new Store();
        long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        if (st.LastOpenMs < 0) progress?.Invoke($"Tải lịch sử nến {symbol} từ 2020 (lần đầu)…");
        var fresh = await FetchAsync(symbol, st.LastOpenMs < 0 ? StartMs : st.LastOpenMs + 1, now);
        if (fresh.Count > 0)
        {
            var tail = st.Tail.Select(ToBar).Concat(fresh).ToList();
            st.LastOpenMs = tail[^1].OpenMs;
            long lastDay = DayOf(tail[^1].OpenMs);
            st.Daily.AddRange(DailyAggregator.Aggregate(tail.Where(b => DayOf(b.OpenMs) < lastDay)).Select(FromBar));
            st.Tail = tail.Where(b => DayOf(b.OpenMs) == lastDay).Select(FromBar).ToList();
            Files.WriteAtomic(path, JsonSerializer.Serialize(st, Json.Options));
        }
        var bars = st.Daily.Select(ToBar).Concat(DailyAggregator.Aggregate(st.Tail.Select(ToBar))).ToList();
        return new DailySeries(bars);
    }

    public async Task<Dictionary<string, double>> AllPricesAsync()
    {
        var arr = JsonNode.Parse(await http.GetStringAsync($"{PublicApi}/ticker/price")) as JsonArray ?? [];
        return arr.ToDictionary(x => x!["symbol"]!.GetValue<string>(), x => P(x!["price"]));
    }
}
