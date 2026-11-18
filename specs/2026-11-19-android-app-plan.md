# App Android viết lại — kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Viết lại `app/` thành app gọn để theo dõi lệnh và lời/lỗ, và đặt lệnh tay (mua kèm cắt lỗ trên sàn, bán) trên Binance Spot Testnet.

**Architecture:** `CryptoBot.Core` có 2 file:
- `Binance.cs`: client testnet ký HMAC, đặt lệnh, tính ATR, lấy giá công khai.
- `Feed.cs`: đọc `fills.json` và `claude.json` từ GitHub Pages.

`CryptoBot.App` (MAUI, Android) có 2 tab là Tổng quan và Cài đặt. Không có dịch vụ nền. Các lệnh app đang giữ lưu trong Preferences.

**Tech Stack:** .NET 9, MAUI Android (`net9.0-android`), System.Text.Json, xUnit.

## Global Constraints

- Code theo kiểu KISS: không comment, ngắn gọn, xóa toàn bộ code cũ không dùng.
- Chỉ dùng testnet `https://testnet.binance.vision`. Giá và nến lấy từ `https://data-api.binance.vision`.
- Dashboard mặc định là `https://huynhvanduc.github.io/crypto-bot-beta`.
- `newClientOrderId` = `app-<ms>`.
- Giá cắt lỗ = giá vào − 2×ATR(14, Wilder, nến 1h đã đóng). Dùng lệnh `STOP_LOSS`.
- Khóa SecureStorage `key` và `secret` giữ nguyên tên cũ, để key đã nhập ở app cũ vẫn dùng được.
- ApplicationId `com.cryptobot.d1` giữ nguyên, phiên bản tăng lên 2.0 / 2.

---

### Task 1: Core — Binance.cs, Feed.cs và test

**Files:**
- Create: `app/CryptoBot.Core/Binance.cs`, `app/CryptoBot.Core/Feed.cs`
- Create: `app/CryptoBot.Tests/CryptoBot.Tests.csproj`, `app/CryptoBot.Tests/CoreTests.cs`
- Delete: mọi file `.cs` còn lại trong `app/CryptoBot.Core/`

**Interfaces:**
- Produces:
  - `record Position(string Symbol, double Qty, double Entry, long StopId)`.
  - `class Binance(HttpClient, string key, string secret)`, gồm:
    - `HasKeys`;
    - `Task<(Position Pos, string? Warning)> BuyAsync(string symbol, double usdt)`;
    - `Task SellAsync(Position)`;
    - `Task<bool> ClosedAsync(Position)`.
  - Hàm static của `Binance`:
    - `D(JsonNode?)`;
    - `RoundStep(double, string)`;
    - `Atr(IReadOnlyList<(double H, double L, double C)>, int n = 14)`;
    - `Filled(JsonNode order, string baseAsset)`;
    - `PricesAsync(HttpClient, IEnumerable<string>)`.
  - `record Lot(Symbol, Source, Qty, Entry, Cost)`, `record Trade(Symbol, Source, ExitTime, Entry, Exit, Pnl, Pct)`, `record Fill(Ms, Side, Symbol, Price, Quote, Source)`, `record Snapshot(Usdt, Realized, Open, Closed, Fills, Reasons)`.
  - `Feed.Parse(string fills, string claude)`, `Feed.LoadAsync(HttpClient, string baseUrl)`.

- [ ] **Step 1: Tạo project test**

`app/CryptoBot.Tests/CryptoBot.Tests.csproj`:
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net9.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\CryptoBot.Core\CryptoBot.Core.csproj" />
  </ItemGroup>
</Project>
```

`app/CryptoBot.Tests/CoreTests.cs`:
```csharp
using System.Text.Json.Nodes;
using CryptoBot.Core;
using Xunit;

public class CoreTests
{
    [Theory]
    [InlineData(0.123456, "0.00100000", "0.123")]
    [InlineData(5.9, "1.00000000", "5")]
    [InlineData(1757.239, "0.01000000", "1757.23")]
    public void RoundStepFloors(double v, string step, string expected) => Assert.Equal(expected, Binance.RoundStep(v, step));

    [Fact]
    public void AtrIsWilderFromFirstRange()
    {
        Assert.Equal(2, Binance.Atr([(11, 9, 10), (11, 9, 10), (11, 9, 10)]), 9);
        Assert.Equal(2 + 1 / 14.0, Binance.Atr([(10, 8, 9), (12, 9, 11)]), 9);
    }

    [Fact]
    public void FilledSubtractsBaseFee()
    {
        var o = JsonNode.Parse("""{"executedQty":"1.0","cummulativeQuoteQty":"100","fills":[{"commission":"0.001","commissionAsset":"BTC"},{"commission":"0.1","commissionAsset":"USDT"}]}""")!;
        var (qty, avg) = Binance.Filled(o, "BTC");
        Assert.Equal(0.999, qty, 9);
        Assert.Equal(100, avg, 9);
    }

    [Fact]
    public void FeedParses()
    {
        var fills = """
        {"usdt":9511.76,"fills":[{"ms":2,"side":"BUY","symbol":"ETHUSDT","price":1757.2,"quote":99.98,"source":"ai"},
                                 {"ms":1,"side":"SELL","symbol":"BNBUSDT","price":582.49,"quote":5244.74,"source":"scalp"}],
         "round_trips":{"pnl_usdt":11.55,
           "open":[{"symbol":"ETHUSDT","source":"ai","qty":0.0569,"entry_price":1757.2,"cost":99.98,"entry_time":"t"}],
           "trades":[{"symbol":"XRPUSDT","source":"scalp","exit_time":"2026-11-15T01:00:00Z","entry_price":1,"exit_price":1.1,"pnl_usdt":10,"return_pct":10},
                     {"symbol":"SOLUSDT","source":"tay","exit_time":"2026-11-15T02:00:00Z","entry_price":null,"exit_price":70,"pnl_usdt":null,"return_pct":null},
                     {"symbol":"BNBUSDT","source":"scalp","exit_time":"2026-11-15T03:00:00Z","entry_price":2,"exit_price":1,"pnl_usdt":-5,"return_pct":-50}]}}
        """;
        var s = Feed.Parse(fills, """{"open":[{"symbol":"ETHUSDT","reason":"hồi"}]}""");
        Assert.Equal(9511.76, s.Usdt);
        Assert.Equal(11.55, s.Realized);
        Assert.Equal(new Lot("ETHUSDT", "ai", 0.0569, 1757.2, 99.98), s.Open.Single());
        Assert.Equal(["BNBUSDT", "XRPUSDT"], s.Closed.Select(t => t.Symbol));
        Assert.Equal(2, s.Fills.Count);
        Assert.Equal("hồi", s.Reasons["ETHUSDT"]);
        Assert.Empty(Feed.Parse(fills, "{}").Reasons);
    }
}
```

- [ ] **Step 2: Chạy test, phải fail vì chưa có code**

Run: `dotnet test app/CryptoBot.Tests`
Expected: lỗi biên dịch `The name 'Binance' does not exist`. Các file cũ của Core vẫn còn ở bước này.

- [ ] **Step 3: Xóa Core cũ, viết Binance.cs và Feed.cs**

```bash
git rm -q app/CryptoBot.Core/{Bars,BotEngine,Dashboard,Exchange,FillWatcher,Fills,Indicators,Json,LiveTrader,MarketData,Metrics,Research,Services,State,Strategy}.cs
```

`app/CryptoBot.Core/Binance.cs`:
```csharp
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
```

`app/CryptoBot.Core/Feed.cs`:
```csharp
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
```

- [ ] **Step 4: Chạy test, phải pass**

Run: `dotnet test app/CryptoBot.Tests`
Expected: `Passed!  - Failed: 0, Passed: 6`

- [ ] **Step 5: Commit**

```bash
git add -A app/CryptoBot.Core app/CryptoBot.Tests
git commit -m "App Android: Core mới (Binance testnet + Feed dashboard) và test"
```

### Task 2: App: 2 tab, bỏ dịch vụ nền, build APK

**Files:**
- Create: `app/CryptoBot.App/MainPage.cs`, `app/CryptoBot.App/SettingsPage.cs`
- Modify (ghi đè): `app/CryptoBot.App/App.cs`, `app/CryptoBot.App/Platforms/Android/Android.cs`, `app/CryptoBot.App/Platforms/Android/AndroidManifest.xml`, `app/CryptoBot.App/CryptoBot.App.csproj` (phiên bản)
- Delete: `app/CryptoBot.App/Pages.cs`

**Interfaces:**
- Consumes (Task 1): `Binance`, `Position`, `Feed.LoadAsync`, `Snapshot`, `Binance.PricesAsync`.
- Produces: `Host.Http`, `Host.Exchange`, `Host.Key`, `Host.Secret`, `Host.Dashboard`, `Host.Positions`, `Host.SaveAsync(key, secret, dashboard)`.

- [ ] **Step 1: Xóa Pages.cs, ghi đè App.cs**

```bash
git rm -q app/CryptoBot.App/Pages.cs
```

`app/CryptoBot.App/App.cs`:
```csharp
using System.Text.Json;
using CryptoBot.Core;

namespace CryptoBot.App;

public static class MauiProgram
{
    public static MauiApp CreateMauiApp() => MauiApp.CreateBuilder().UseMauiApp<App>().Build();
}

public class App : Application
{
    protected override Window CreateWindow(IActivationState? activationState)
    {
        UserAppTheme = AppTheme.Light;
        return new Window(new Shell
        {
            Items = { new TabBar { Items = {
                new ShellContent { Title = "Tổng quan", Content = new MainPage() },
                new ShellContent { Title = "Cài đặt", Content = new SettingsPage() } } } },
        });
    }
}

public static class Host
{
    public static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(20) };
    static Binance? _ex;

    static string Secure(string k) => Task.Run(() => SecureStorage.GetAsync(k)).Result ?? "";

    public static string Key => Secure("key");
    public static string Secret => Secure("secret");
    public static Binance Exchange => _ex ??= new(Http, Key, Secret);
    public static string Dashboard => Preferences.Get("dashboard", "https://huynhvanduc.github.io/crypto-bot-beta");

    public static List<Position> Positions
    {
        get => JsonSerializer.Deserialize<List<Position>>(Preferences.Get("positions", "[]")) ?? [];
        set => Preferences.Set("positions", JsonSerializer.Serialize(value));
    }

    public static async Task SaveAsync(string key, string secret, string dashboard)
    {
        await SecureStorage.SetAsync("key", key.Trim());
        await SecureStorage.SetAsync("secret", secret.Trim());
        Preferences.Set("dashboard", dashboard.Trim().TrimEnd('/'));
        _ex = null;
    }
}
```

- [ ] **Step 2: Viết SettingsPage.cs**

```csharp
namespace CryptoBot.App;

public class SettingsPage : ContentPage
{
    public SettingsPage()
    {
        Title = "Cài đặt";
        var key = new Entry { Placeholder = "API key testnet", Text = Host.Key };
        var secret = new Entry { Placeholder = "API secret testnet", Text = Host.Secret, IsPassword = true };
        var url = new Entry { Placeholder = "Địa chỉ dashboard", Text = Host.Dashboard, Keyboard = Keyboard.Url };
        var status = new Label();
        var save = new Button { Text = "Lưu" };
        save.Clicked += async (_, _) => { await Host.SaveAsync(key.Text ?? "", secret.Text ?? "", url.Text ?? ""); status.Text = "Đã lưu"; };
        Content = new ScrollView { Content = new VerticalStackLayout { Padding = 16, Spacing = 8, Children = {
            new Label { Text = "Key tạo ở testnet.binance.vision" }, key, secret,
            new Label { Text = "Dashboard" }, url, save, status } } };
    }
}
```

- [ ] **Step 3: Viết MainPage.cs**

```csharp
using System.Globalization;
using CryptoBot.Core;

namespace CryptoBot.App;

public class MainPage : ContentPage
{
    static readonly CultureInfo Vi = new("vi-VN");
    static readonly Color Green = Color.FromArgb("#1B7F3B"), Red = Color.FromArgb("#C0392B"), Gray = Color.FromArgb("#8A8984");
    static readonly Dictionary<string, string> Src = new() { ["ai"] = "Claude", ["tay"] = "Tay", ["scalp"] = "Lướt sóng", ["d1"] = "D1", ["nc"] = "Nghiên cứu" };
    static readonly string[] Coins = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "LTC", "DOT", "TRX", "ATOM", "UNI", "ETC",
        "BCH", "XLM", "FIL", "NEAR", "ALGO", "VET", "ICP", "AAVE", "SAND", "MANA", "AXS", "HBAR", "INJ", "GRT"];

    readonly VerticalStackLayout _body = new() { Padding = 14, Spacing = 6 };
    readonly Picker _coin = new() { ItemsSource = Coins, SelectedIndex = 0 };
    readonly Entry _usdt = new() { Text = "100", Keyboard = Keyboard.Numeric };
    readonly Button _buy = new() { Text = "Mua" };
    readonly Grid _buyRow;
    IDispatcherTimer? _timer;
    Snapshot? _snap;
    Dictionary<string, double> _px = [];
    string _loadErr = "", _msg = "";
    bool _msgErr, _busy;

    public MainPage()
    {
        Title = "Tổng quan";
        _buy.Clicked += async (_, _) => await Buy();
        _buyRow = Cols(_coin, _usdt, _buy);
        var refresh = new RefreshView { Content = new ScrollView { Content = _body } };
        refresh.Command = new Command(async () => { await Load(); refresh.IsRefreshing = false; });
        Content = refresh;
    }

    protected override void OnAppearing()
    {
        base.OnAppearing();
        _timer = Dispatcher.CreateTimer();
        _timer.Interval = TimeSpan.FromSeconds(15);
        _timer.Tick += async (_, _) => await Load();
        _timer.Start();
        _ = Load();
    }

    protected override void OnDisappearing()
    {
        _timer?.Stop();
        base.OnDisappearing();
    }

    async Task Load()
    {
        try
        {
            var mine = Host.Positions;
            if (Host.Exchange.HasKeys)
                foreach (var p in mine.ToList())
                    if (await Host.Exchange.ClosedAsync(p)) mine.Remove(p);
            Host.Positions = mine;
            _snap = await Feed.LoadAsync(Host.Http, Host.Dashboard);
            _px = await Binance.PricesAsync(Host.Http, _snap.Open.Select(o => o.Symbol).Concat(mine.Select(p => p.Symbol)));
            _loadErr = "";
        }
        catch (Exception e) { _loadErr = e.Message; }
        Render();
    }

    async Task Act(Func<Task<(string Msg, bool Err)>> action)
    {
        if (_busy) return;
        _busy = true;
        try { (_msg, _msgErr) = await action(); }
        catch (Exception e) { (_msg, _msgErr) = (e.Message, true); }
        finally { _busy = false; }
        await Load();
    }

    Task Buy() => Act(async () =>
    {
        var sym = Coins[_coin.SelectedIndex] + "USDT";
        if (!double.TryParse((_usdt.Text ?? "").Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var usdt) || usdt <= 0)
            return ("Số USDT không hợp lệ", true);
        if (Host.Positions.Any(p => p.Symbol == sym)) return ($"Đã có lệnh {Coins[_coin.SelectedIndex]} của app", true);
        var (pos, warn) = await Host.Exchange.BuyAsync(sym, usdt);
        Host.Positions = [.. Host.Positions, pos];
        return (warn ?? $"Đã mua {pos.Qty.ToString("0.######", Vi)} {Coin(sym)} giá {Px(pos.Entry)}", warn is not null);
    });

    Task Sell(Position p) => Act(async () =>
    {
        await Host.Exchange.SellAsync(p);
        Host.Positions = Host.Positions.Where(x => x.Symbol != p.Symbol).ToList();
        return ($"Đã bán {Coin(p.Symbol)}", false);
    });

    void Render()
    {
        _body.Clear();
        foreach (var (m, err) in new[] { (_loadErr, true), (_msg, _msgErr) })
            if (m.Length > 0) _body.Add(Text(m, err ? Red : Green));
        var s = _snap;
        var open = s?.Open.Select(o => (o, p: _px.GetValueOrDefault(o.Symbol))).ToList() ?? [];
        var openPnl = open.Where(x => x.p > 0).Sum(x => x.o.Qty * x.p - x.o.Cost);
        if (s is not null)
            _body.Add(Cols(Kpi("Số dư USDT", N(s.Usdt), null), Kpi("Đã chốt", Sgn(s.Realized), Pnl(s.Realized)),
                Kpi($"Đang mở {open.Count}", Sgn(openPnl), Pnl(openPnl))));

        _body.Add(Head("Mua"));
        _buy.IsEnabled = Host.Exchange.HasKeys;
        _body.Add(_buyRow);
        if (!Host.Exchange.HasKeys) _body.Add(Text("Nhập key ở Cài đặt", Gray));

        var mine = Host.Positions;
        if (mine.Count > 0)
        {
            _body.Add(Head("Lệnh của app"));
            foreach (var p in mine)
            {
                var px = _px.GetValueOrDefault(p.Symbol);
                var sell = new Button { Text = "Bán", IsEnabled = Host.Exchange.HasKeys };
                sell.Clicked += async (_, _) => await Sell(p);
                _body.Add(Cols(Text(Coin(p.Symbol) + (p.StopId == 0 ? " ⚠" : "")), Text(Px(p.Entry)),
                    Text(px > 0 ? Pct((px / p.Entry - 1) * 100) : "—", Pnl(px - p.Entry)), sell));
            }
        }
        if (s is null) return;

        _body.Add(Head("Đang mở"));
        foreach (var (o, p) in open.OrderBy(x => x.p > 0 ? x.p / x.o.Entry : 1))
        {
            var pnl = p > 0 ? o.Qty * p - o.Cost : 0;
            _body.Add(Cols(Text($"{Coin(o.Symbol)} · {Tag(o.Source)}"), Text(Px(o.Entry)), Text(p > 0 ? Px(p) : "—"),
                Text(p > 0 ? $"{Pct(pnl / o.Cost * 100)} {Sgn(pnl)}" : "—", Pnl(pnl))));
            if (o.Source == "ai" && s.Reasons.TryGetValue(o.Symbol, out var why)) _body.Add(Text("Claude: " + why, Gray));
        }

        _body.Add(Head("Đã đóng"));
        foreach (var t in s.Closed)
            _body.Add(Cols(Text($"{Coin(t.Symbol)} · {Tag(t.Source)}"), Text(Time(DateTimeOffset.Parse(t.ExitTime, CultureInfo.InvariantCulture))),
                Text($"{Px(t.Entry)} → {Px(t.Exit)}"), Text($"{Pct(t.Pct)} {Sgn(t.Pnl)}", Pnl(t.Pnl))));

        _body.Add(Head("Mua/bán gần đây"));
        foreach (var f in s.Fills)
            _body.Add(Cols(Text(Time(DateTimeOffset.FromUnixTimeMilliseconds(f.Ms))), Text(f.Side == "BUY" ? "Mua" : "Bán", f.Side == "BUY" ? Green : Red),
                Text($"{Coin(f.Symbol)} · {Tag(f.Source)}"), Text(Px(f.Price)), Text(N(f.Quote))));
    }

    static Label Text(string t, Color? c = null) => new() { Text = t, FontSize = 13, TextColor = c ?? Colors.Black, LineBreakMode = LineBreakMode.WordWrap };
    static Label Head(string t) => new() { Text = t, FontSize = 15, FontAttributes = FontAttributes.Bold, Margin = new(0, 10, 0, 0) };
    static View Kpi(string label, string value, Color? c) => new VerticalStackLayout { Children = { Text(label, Gray), new Label { Text = value, FontSize = 17, FontAttributes = FontAttributes.Bold, TextColor = c ?? Colors.Black } } };

    static Grid Cols(params View[] views)
    {
        var g = new Grid { ColumnSpacing = 6 };
        for (int i = 0; i < views.Length; i++)
        {
            g.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            g.Add(views[i], i);
        }
        return g;
    }

    static string Tag(string source) => Src.GetValueOrDefault(source, source);
    static string Coin(string s) => s.Replace("USDT", "");
    static string N(double v) => v.ToString("N2", Vi);
    static string Sgn(double v) => (v > 0 ? "+" : "") + N(v);
    static string Pct(double v) => (v > 0 ? "+" : "") + v.ToString("N2", Vi) + "%";
    static string Px(double v) => v.ToString(v >= 1000 ? "N2" : v >= 1 ? "0.####" : "0.######", Vi);
    static string Time(DateTimeOffset t) => t.ToOffset(TimeSpan.FromHours(7)).ToString("HH:mm dd/MM", Vi);
    static Color Pnl(double v) => v > 0 ? Green : v < 0 ? Red : Colors.Black;
}
```

- [ ] **Step 4: Ghi đè phần Android và tăng phiên bản**

`app/CryptoBot.App/Platforms/Android/Android.cs`:
```csharp
using Android.App;
using Android.Content.PM;
using Android.Runtime;

namespace CryptoBot.App;

[Application]
public class MainApplication(IntPtr handle, JniHandleOwnership own) : MauiApplication(handle, own)
{
    protected override MauiApp CreateMauiApp() => MauiProgram.CreateMauiApp();
}

[Activity(Theme = "@style/Maui.MainTheme.NoActionBar", MainLauncher = true, LaunchMode = LaunchMode.SingleTop,
    ConfigurationChanges = ConfigChanges.ScreenSize | ConfigChanges.Orientation | ConfigChanges.UiMode | ConfigChanges.ScreenLayout |
                           ConfigChanges.SmallestScreenSize | ConfigChanges.Density)]
public class MainActivity : MauiAppCompatActivity;
```

`app/CryptoBot.App/Platforms/Android/AndroidManifest.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application android:allowBackup="true" android:icon="@mipmap/appicon" android:roundIcon="@mipmap/appicon_round" android:supportsRtl="true" android:label="Crypto Bot" />
  <uses-permission android:name="android.permission.INTERNET" />
  <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
</manifest>
```

Trong `app/CryptoBot.App/CryptoBot.App.csproj`: đổi `<ApplicationDisplayVersion>1.0</ApplicationDisplayVersion>` thành `2.0` và `<ApplicationVersion>1</ApplicationVersion>` thành `2`.

- [ ] **Step 5: Build APK và chạy lại test**

Run: `dotnet publish app/CryptoBot.App -f net9.0-android -c Release` rồi `dotnet test app/CryptoBot.Tests`
Expected: build ra `app/CryptoBot.App/bin/Release/net9.0-android/publish/com.cryptobot.d1-Signed.apk` không lỗi, và test 6/6 pass.

- [ ] **Step 6: Commit**

```bash
git add -A app
git commit -m "App Android viết lại: Tổng quan (theo dõi + mua/bán tay kèm cắt lỗ) và Cài đặt; bỏ bot D1, lướt sóng, dịch vụ nền"
```

### Task 3: README

**Files:**
- Modify: `README.md` (mục Android)

- [ ] **Step 1: Thay đoạn mô tả `app/` trong mục Android**

Thay dòng bắt đầu bằng ``- `app/` là app .NET MAUI`` bằng:
```markdown
- `app/` là app .NET MAUI viết bằng C# để theo dõi lệnh (của Claude, Telegram và app), lời/lỗ, và đặt lệnh tay: mua theo USDT, kèm lệnh cắt lỗ đặt sẵn trên sàn ở giá vào − 2×ATR khung 1h. Dữ liệu lấy từ dashboard trên GitHub Pages; app không có dịch vụ chạy nền. Muốn nhận thông báo khớp lệnh thì dùng app ntfy, đăng ký topic có trong `docs/fills.json`. Build bằng `dotnet publish app/CryptoBot.App -f net9.0-android -c Release`, test bằng `dotnet test app/CryptoBot.Tests`.
```

- [ ] **Step 2: Commit và push**

```bash
git add README.md specs/2026-11-19-android-app-plan.md specs/2026-11-19-android-app-design.md
git commit -m "README: app Android mới"
git push
```
