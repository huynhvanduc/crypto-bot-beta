namespace CryptoBot.Core;

/// <summary>Biến thể D1 đang chạy thật: Donchian 20 + EMA200, stop đầu 2×ATR, trailing 3×ATR, tối đa 240 nến.</summary>
public static class D1
{
    public const string Name = "D1 Donchian20, trailing rộng";
    public const int DonchianN = 20;
    public const int EmaTrend = 200;
    public const int AtrPeriod = 14;
    public const double SlAtr = 2;
    public const double TrailAtr = 3;
    public const int MaxBars = 240;
    public const double Fee = 0.001;
    public static string RuleLabel => $"Trailing {TrailAtr:g}×ATR, SL đầu {SlAtr:g}×ATR, tối đa {MaxBars} nến";

    /// <summary>close > max(high của 20 nến trước) và close > EMA200 và có ATR — giống donchian_signals.</summary>
    public static bool[] Signals(double[] high, double[] close, double[] ema, double[] atr, int n = DonchianN)
    {
        var sig = new bool[close.Length];
        for (int i = n; i < close.Length; i++)
        {
            double prior = double.MinValue;
            for (int j = i - n; j < i; j++) prior = Math.Max(prior, high[j]);
            sig[i] = close[i] > prior && close[i] > ema[i] && !double.IsNaN(atr[i]);
        }
        return sig;
    }

    public static double NetReturn(double entry, double exit, double fee = Fee) => exit * (1 - fee) / (entry * (1 + fee)) - 1;

    public readonly record struct ExitResult(int ExitIdx, double ExitPrice, string Barrier);

    /// <summary>Giống bot.exits.trailing_stop.</summary>
    public static ExitResult? TrailingStop(double[] o, double[] h, double[] l, double[] c, int entryIdx, double entryPrice,
        double atrValue, double slAtr = SlAtr, double trailAtr = TrailAtr, int maxBars = MaxBars)
    {
        double stop = entryPrice - slAtr * atrValue;
        double hh = double.NegativeInfinity;
        int last = entryIdx + maxBars - 1;
        bool incomplete = last >= c.Length;
        int end = Math.Min(last, c.Length - 1);
        for (int j = entryIdx; j <= end; j++)
        {
            if (o[j] <= stop) return new ExitResult(j, o[j], "stop");
            if (l[j] <= stop) return new ExitResult(j, stop, "stop");
            hh = Math.Max(hh, h[j]);
            stop = Math.Max(stop, hh - trailAtr * atrValue);
        }
        if (incomplete) return null;
        return new ExitResult(last, c[last], "time");
    }

    public sealed record BacktestTrade(DateTimeOffset SignalTime, DateTimeOffset EntryTime, DateTimeOffset ExitTime,
        double EntryPrice, double ExitPrice, string Barrier, int BarsHeld, double ReturnPct);

    /// <summary>Giống bot.variants.backtest_variant(df, cfg, D1).</summary>
    public static List<BacktestTrade> Backtest(DailySeries s)
    {
        var trades = new List<BacktestTrade>();
        int busyUntil = -1;
        for (int i = 0; i < s.Count; i++)
        {
            if (!s.Signal[i] || i <= busyUntil) continue;
            int entryIdx = i + 1;
            if (entryIdx >= s.Count) break;
            double entry = s.Open[entryIdx];
            var res = TrailingStop(s.Open, s.High, s.Low, s.Close, entryIdx, entry, s.Atr[i]);
            if (res is null) break;
            var r = res.Value;
            double ret = NetReturn(entry, r.ExitPrice);
            trades.Add(new BacktestTrade(s.Time[i], s.Time[entryIdx], s.Time[r.ExitIdx], entry, r.ExitPrice, r.Barrier,
                r.ExitIdx - entryIdx + 1, ret * 100));
            busyUntil = r.ExitIdx;
        }
        return trades;
    }
}

/// <summary>Nến ngày đã kèm EMA200, ATR và tín hiệu D1 (tương đương add_indicators + signals).</summary>
public sealed class DailySeries
{
    public DateTimeOffset[] Time { get; }
    public double[] Open { get; }
    public double[] High { get; }
    public double[] Low { get; }
    public double[] Close { get; }
    public double[] Ema { get; }
    public double[] Atr { get; }
    public bool[] Signal { get; }
    public int Count => Close.Length;
    public bool IsEmpty => Count == 0;
    public DateTimeOffset LastTime => Time[^1];

    public DailySeries(IReadOnlyList<Bar> bars)
    {
        Time = bars.Select(b => b.Time).ToArray();
        Open = bars.Select(b => b.Open).ToArray();
        High = bars.Select(b => b.High).ToArray();
        Low = bars.Select(b => b.Low).ToArray();
        Close = bars.Select(b => b.Close).ToArray();
        Ema = Indicators.Ema(Close, D1.EmaTrend);
        Atr = Indicators.Atr(High, Low, Close, D1.AtrPeriod);
        Signal = D1.Signals(High, Close, Ema, Atr);
    }
}
