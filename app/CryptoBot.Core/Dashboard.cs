using System.Text.Json;

namespace CryptoBot.Core;

public static class Dashboard
{
    static readonly object BacktestRef = new
    {
        trades = 251, win_rate_pct = 39.4, expectancy_pct = 1.814, profit_factor = 1.32, max_drawdown_pct = 15.5,
        period = "22/10/2024 – 14/11/2026",
    };

    public static string Build(BotState st, RunResult? snap, string? error)
    {
        double cap = st.InitialCapital;
        var data = new Dictionary<string, object?>
        {
            ["updated"] = Json.NowIso(), ["mode"] = st.Mode, ["start"] = st.Start, ["variant"] = D1.Name, ["rule"] = D1.RuleLabel,
            ["initial_capital"] = cap, ["equity"] = snap?.Equity ?? cap, ["realized"] = st.Trades.Sum(t => t.PnlUsdt),
            ["unrealized"] = snap?.Unrealized ?? 0.0, ["last_bar"] = snap?.LastBar, ["signals"] = snap?.Signals ?? [],
            ["positions"] = snap?.Positions ?? [],
            ["trades"] = st.Trades.OrderByDescending(t => t.ExitTime, StringComparer.Ordinal).ToList(),
            ["equity_curve"] = st.EquityCurve.Skip(Math.Max(0, st.EquityCurve.Count - 2000)).ToList(),
            ["metrics"] = Metrics.Compute(st.Trades), ["backtest"] = BacktestRef, ["symbols"] = st.Slots.Count,
            ["log"] = st.Log.Skip(Math.Max(0, st.Log.Count - 40)).Reverse().ToList(), ["error"] = error,
            ["radar"] = snap?.Radar ?? [], ["account"] = snap?.Account ?? (object)new { },
            ["shadow"] = Array.Empty<object>(), ["shadow_min_trades"] = 30,
            ["next_run_note"] = "07:05 hằng ngày (giờ VN)", ["paused"] = st.Paused == true,
        };
        return JsonSerializer.Serialize(data, Json.Options);
    }
}
