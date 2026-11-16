using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace CryptoBot.Core;

public sealed class Position
{
    public string EntryTime { get; set; } = "";
    public string SignalBar { get; set; } = "";
    public double EntryPrice { get; set; }
    public double Qty { get; set; }
    public double Cost { get; set; }
    public double Atr { get; set; }
    public double Hh { get; set; } = double.NegativeInfinity;
    public double Stop { get; set; }
    public int BarsHeld { get; set; }
    public string LastBarDone { get; set; } = "";
    public long? StopOrderId { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class Trade
{
    public string Symbol { get; set; } = "";
    public string EntryTime { get; set; } = "";
    public string ExitTime { get; set; } = "";
    public double EntryPrice { get; set; }
    public double ExitPrice { get; set; }
    public double Qty { get; set; }
    public double ReturnPct { get; set; }
    public double PnlUsdt { get; set; }
    public string Reason { get; set; } = "";
    public int Days { get; set; }
}

public sealed record EquityPoint(string T, double Equity);

public sealed class BotState
{
    public string Mode { get; set; } = "";
    public string Start { get; set; } = "";
    public double InitialCapital { get; set; }
    public string Variant { get; set; } = "";
    public Dictionary<string, double> Slots { get; set; } = new();
    public Dictionary<string, Position> Positions { get; set; } = new();
    public List<Trade> Trades { get; set; } = new();
    public Dictionary<string, string?> LastExitBar { get; set; } = new();
    public string? LastBar { get; set; }
    public List<EquityPoint> EquityCurve { get; set; } = new();
    public List<string> Log { get; set; } = new();
    public JsonObject SimOrders { get; set; } = new();
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public string? LastRun { get; set; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public bool? Paused { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }

    public static BotState New(double capital, IReadOnlyList<string> symbols, string mode) => new()
    {
        Mode = mode, Start = Json.NowIso(), InitialCapital = capital, Variant = D1.Name,
        Slots = symbols.ToDictionary(s => s, _ => capital / symbols.Count),
    };

    public static BotState Parse(string text) =>
        JsonSerializer.Deserialize<BotState>(Json.FixPythonLiterals(text), Json.Options) ?? throw new JsonException("state.json rỗng");

    public string ToJson() => JsonSerializer.Serialize(this, Json.Indented);
}

public static class Files
{
    public static void WriteAtomic(string path, string text)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var tmp = path + ".tmp";
        File.WriteAllText(tmp, text);
        File.Move(tmp, path, true);
    }
}
