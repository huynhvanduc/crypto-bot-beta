namespace CryptoBot.Core;

public sealed record MetricsResult(int Trades, double WinRatePct, double AvgWinPct, double AvgLossPct, double ExpectancyPct,
    double? ProfitFactor, double MaxDrawdownPct, double TotalReturnPct);

public static class Metrics
{
    public static List<double> PortfolioEquity(IReadOnlyList<Trade> trades)
    {
        var times = trades.Select(t => t.ExitTime).Distinct().OrderBy(t => t, StringComparer.Ordinal).ToList();
        var curves = new List<Dictionary<string, double>>();
        foreach (var g in trades.OrderBy(t => t.ExitTime, StringComparer.Ordinal).GroupBy(t => t.Symbol))
        {
            double eq = 1;
            var c = new Dictionary<string, double>();
            foreach (var t in g) { eq *= 1 + t.ReturnPct / 100; c[t.ExitTime] = eq; }
            curves.Add(c);
        }
        var last = curves.Select(_ => 1.0).ToArray();
        var outv = new List<double>();
        foreach (var t in times)
        {
            for (int i = 0; i < curves.Count; i++) if (curves[i].TryGetValue(t, out var v)) last[i] = v;
            outv.Add(last.Average());
        }
        return outv;
    }

    public static double MaxDrawdown(IEnumerable<double> equity)
    {
        double peak = 1, dd = 0;
        foreach (var e in equity.Prepend(1.0)) { peak = Math.Max(peak, e); dd = Math.Max(dd, 1 - e / peak); }
        return dd;
    }

    public static MetricsResult? Compute(IReadOnlyList<Trade> trades)
    {
        if (trades.Count == 0) return null;
        var r = trades.Select(t => t.ReturnPct / 100).ToArray();
        var wins = r.Where(x => x > 0).ToArray();
        var losses = r.Where(x => x <= 0).ToArray();
        double grossLoss = -losses.Sum();
        var eq = PortfolioEquity(trades);
        return new MetricsResult(r.Length, wins.Length * 100.0 / r.Length,
            wins.Length > 0 ? wins.Average() * 100 : 0, losses.Length > 0 ? losses.Average() * 100 : 0, r.Average() * 100,
            grossLoss > 0 ? wins.Sum() / grossLoss : null, MaxDrawdown(eq) * 100, (eq[^1] - 1) * 100);
    }
}
