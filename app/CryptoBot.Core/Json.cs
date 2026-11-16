using System.Globalization;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace CryptoBot.Core;

public static partial class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static readonly JsonSerializerOptions Indented = new(Options) { WriteIndented = true };

    /// <summary>Python json.dumps ghi -Infinity/NaN không có ngoặc kép; đổi sang dạng System.Text.Json đọc được.</summary>
    public static string FixPythonLiterals(string text) => PyLiteral().Replace(text, "$1\"$2\"$3");

    [GeneratedRegex(@"(:\s*)(-?Infinity|NaN)(\s*[,}\]])")]
    private static partial Regex PyLiteral();

    public static string NowIso(DateTimeOffset? now = null) =>
        (now ?? DateTimeOffset.UtcNow).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);

    /// <summary>Giống pandas Timestamp.isoformat() cho mốc UTC: 2026-11-15T00:00:00+00:00.</summary>
    public static string PdIso(DateTimeOffset t) =>
        t.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture);

    public static DateTimeOffset ParseTime(string s) =>
        DateTimeOffset.Parse(s, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);

    public static double D(string s) => double.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture);
}

public static class Fmt
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    /// <summary>Giống định dạng Python "{x:.6g}" / "{x:g}".</summary>
    public static string G(double x)
    {
        if (double.IsNegativeInfinity(x)) return "-inf";
        if (double.IsPositiveInfinity(x)) return "inf";
        if (double.IsNaN(x)) return "nan";
        return x.ToString("G6", Inv).Replace('E', 'e');
    }

    public static string F2(double x) => x.ToString("F2", Inv);
    public static string Signed2(double x) => (x >= 0 ? "+" : "") + x.ToString("F2", Inv);
}
