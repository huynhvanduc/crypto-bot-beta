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
