using System.Globalization;
using CryptoBot.Core;
using Microsoft.Maui.Controls.Shapes;

namespace CryptoBot.App;

static class T
{
    public static readonly Color Bg = Color.FromArgb("#0B1220"), Card = Color.FromArgb("#131C2E"), Card2 = Color.FromArgb("#1B2740"),
        Line = Color.FromArgb("#24324D"), Text = Color.FromArgb("#E6EAF2"), Muted = Color.FromArgb("#8A97AD"),
        Green = Color.FromArgb("#22C55E"), Red = Color.FromArgb("#EF4444"), Amber = Color.FromArgb("#F59E0B"), Blue = Color.FromArgb("#3B82F6");
}

static class Ui
{
    public static readonly CultureInfo Vi = new("vi-VN");

    public static Label L(string text = "", double size = 13, bool bold = false, Color? color = null) => new()
    {
        Text = text, FontSize = size, FontAttributes = bold ? FontAttributes.Bold : FontAttributes.None, TextColor = color ?? T.Text,
        LineBreakMode = LineBreakMode.WordWrap,
    };

    public static Label Muted(string text, double size = 12) => L(text, size, color: T.Muted);

    public static Button B(string text, Func<Task> act, Color? bg = null, bool enabled = true)
    {
        var b = new Button
        {
            Text = text, BackgroundColor = enabled ? bg ?? T.Card2 : T.Line, TextColor = enabled ? Colors.White : T.Muted, FontSize = 14,
            FontAttributes = FontAttributes.Bold, CornerRadius = 12, HeightRequest = 48, Padding = new Thickness(8, 0), IsEnabled = enabled,
        };
        b.Clicked += async (_, _) =>
        {
            b.IsEnabled = false;
            try { await act(); }
            catch (Exception e) { await Shell.Current.DisplayAlert("Lỗi", e.Message, "OK"); }
            finally { b.IsEnabled = true; }
        };
        return b;
    }

    public static Border Card(View content, Color? bg = null, double pad = 14) => new()
    {
        Content = content, BackgroundColor = bg ?? T.Card, Padding = pad, StrokeThickness = 0, StrokeShape = new RoundRectangle { CornerRadius = 14 },
    };

    public static Border Pill(string text, Color color) => new()
    {
        Content = L(text, 12, true, color), BackgroundColor = color.WithAlpha(0.16f), Padding = new Thickness(10, 4), StrokeThickness = 0,
        StrokeShape = new RoundRectangle { CornerRadius = 20 }, HorizontalOptions = LayoutOptions.Start,
    };

    public static View Stat(string label, string value, Color? color = null) => new VerticalStackLayout
    {
        Spacing = 2, Children = { Muted(label, 11), L(value, 16, true, color) },
    };

    public static Grid Grid2(params View[] views)
    {
        var g = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Star) }, ColumnSpacing = 10, RowSpacing = 10 };
        for (int i = 0; i < views.Length; i++)
        {
            if (i % 2 == 0) g.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            g.Add(views[i], i % 2, i / 2);
        }
        return g;
    }

    public static Grid Row(View left, View right, double gap = 8)
    {
        var g = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }, ColumnSpacing = gap };
        g.Add(left, 0);
        right.VerticalOptions = LayoutOptions.Center;
        g.Add(right, 1);
        return g;
    }

    public static HorizontalStackLayout H(params View[] v)
    {
        var h = new HorizontalStackLayout { Spacing = 8 };
        foreach (var x in v) { x.VerticalOptions = LayoutOptions.Center; h.Add(x); }
        return h;
    }

    public static Label Section(string text) => L(text, 15, true).Also(l => l.Margin = new Thickness(2, 6, 0, 0));

    public static Color PnL(double v) => v >= 0 ? T.Green : T.Red;
    public static string N(double v, int d = 2) => v.ToString("N" + d, Vi);
    public static string Pct(double v) => (v >= 0 ? "+" : "") + v.ToString("N2", Vi) + "%";
    public static string Px(double v) => v >= 100 ? v.ToString("N2", Vi) : v >= 1 ? v.ToString("N4", Vi) : v.ToString("0.######", Vi);
    public static string Coin(string s) => s.Replace("USDT", "");

    public static string Local(string? iso, string fmt = "dd/MM HH:mm")
    {
        if (string.IsNullOrEmpty(iso)) return "—";
        try { return Json.ParseTime(iso).ToOffset(TimeSpan.FromHours(7)).ToString(fmt, Vi); } catch { return iso; }
    }
}

public abstract class BotPage : ContentPage
{
    protected BotEngine E => BotHost.Engine;
    protected readonly VerticalStackLayout Body = new() { Padding = new Thickness(14, 12, 14, 24), Spacing = 10 };
    IDispatcherTimer? _timer;
    bool _dirty;
    DateTime _last;

    protected BotPage(string title, bool scroll = true)
    {
        Title = title;
        BackgroundColor = T.Bg;
        Shell.SetBackgroundColor(this, T.Bg);
        Shell.SetTitleColor(this, T.Text);
        Shell.SetForegroundColor(this, T.Text);
        Content = new ScrollView { Content = Body };
    }

    protected abstract void Render();

    void OnChanged() => _dirty = true;

    protected override void OnAppearing()
    {
        base.OnAppearing();
        E.Changed += OnChanged;
        _timer = Dispatcher.CreateTimer();
        _timer.Interval = TimeSpan.FromSeconds(1);
        _timer.Tick += (_, _) =>
        {
            if (!_dirty && DateTime.UtcNow - _last < TimeSpan.FromSeconds(5)) return;
            Draw();
        };
        _timer.Start();
        Draw();
    }

    protected void Draw()
    {
        _dirty = false;
        _last = DateTime.UtcNow;
        Render();
    }

    protected override void OnDisappearing()
    {
        E.Changed -= OnChanged;
        _timer?.Stop();
        base.OnDisappearing();
    }

    protected Task RunAsync(BotCommand cmd) => Task.Run(async () =>
    {
        var msg = await E.RunTraderAsync(cmd);
        if (msg.Length > 0) E.Log(msg);
    });
}

public class OverviewPage : BotPage
{
    public OverviewPage() : base("Bot D1") { }

    protected override void Render()
    {
        var st = E.State;
        var snap = E.Last;
        bool paused = st?.Paused == true, keys = E.Settings.HasBinance;
        Body.Clear();

        var (text, color) = !keys ? ("Chưa có khóa API", T.Amber)
            : !E.Running ? ("Bot đã tắt", T.Red)
            : E.LastError is not null ? ("Lỗi lần chạy gần nhất", T.Red)
            : paused ? ("Tạm dừng mua mới", T.Amber)
            : ("Đang chạy", T.Green);
        Body.Add(Ui.H(Ui.Pill("● " + text, color), Ui.Pill(E.Settings.Mode, T.Blue),
            Ui.Pill(E.Running ? (E.WsConnected ? "WS ✓" : "WS …") : "WS ✗", E.WsConnected ? T.Green : T.Muted)));

        double cap = st?.InitialCapital ?? Config.Capital;
        double realized = st?.Trades.Sum(t => t.PnlUsdt) ?? 0;
        double equity = snap?.Equity ?? cap + realized;
        double chg = (equity / cap - 1) * 100;
        Body.Add(Ui.Card(new VerticalStackLayout
        {
            Spacing = 12,
            Children =
            {
                new VerticalStackLayout
                {
                    Spacing = 0,
                    Children = { Ui.Muted("Vốn bot D1 (USDT)"), Ui.H(Ui.L(Ui.N(equity), 30, true), Ui.L(Ui.Pct(chg), 15, true, Ui.PnL(chg))) },
                },
                Ui.Grid2(
                    Ui.Stat("Đã chốt", Ui.N(realized), Ui.PnL(realized)),
                    Ui.Stat("Chưa chốt", Ui.N(snap?.Unrealized ?? 0), Ui.PnL(snap?.Unrealized ?? 0)),
                    Ui.Stat("USDT trên sàn", snap?.Account.Usdt is { } u ? Ui.N(u) : "—"),
                    Ui.Stat("Lệnh đang mở", (st?.Positions.Count ?? 0).ToString())),
            },
        }));

        Body.Add(Ui.Card(new VerticalStackLayout
        {
            Spacing = 4,
            Children =
            {
                Ui.Row(Ui.L("Lịch chạy D1", 13, true), Ui.L($"07:05 + mỗi {BotEngine.IntradayMinutes} phút", 13, true, T.Blue)),
                Ui.Muted($"Xét giá trong ngày gần nhất: {Ui.Local(E.LastIntraday, "HH:mm")} — mua ngay khi giá vượt đỉnh 20 ngày và trên EMA200"),
                Ui.Muted($"Lần gần nhất {Ui.Local(st?.LastRun)} · đã chạy hôm nay: {(E.LastDaily == DateTime.UtcNow.ToString("yyyy-MM-dd") ? "có" : "chưa")}"),
                Ui.Muted($"Nến ngày đã xử lý: {Ui.Local(st?.LastBar, "dd/MM/yyyy")}"),
            },
        }, pad: 12));

        if (E.LastError is not null) Body.Add(Ui.Card(Ui.L(E.LastError, 12, color: T.Red), T.Red.WithAlpha(0.12f), 12));
        if (snap is null && keys) Body.Add(Ui.Muted("Chưa có giá mới từ lúc mở app — bấm \"Chạy ngay\"."));

        Body.Add(Ui.Grid2(
            Ui.B(E.Busy ? "Đang xử lý…" : "↻ Chạy ngay", () => RunAsync(BotCommand.Run), T.Blue, !E.Busy && keys),
            Ui.B(paused ? "Tiếp tục mua" : "Tạm dừng mua", () => RunAsync(paused ? BotCommand.Resume : BotCommand.Pause),
                paused ? T.Green : T.Amber, !E.Busy && keys),
            Ui.B("Bán hết", async () =>
            {
                if (!await DisplayAlert("Bán hết?", "Bán market TOÀN BỘ lệnh D1 đang mở và tạm dừng mua mới.", "Tiếp", "Hủy")) return;
                if (!await DisplayAlert("Xác nhận lần 2", "Chắc chắn bán hết ngay bây giờ?", "BÁN HẾT", "Hủy")) return;
                await RunAsync(BotCommand.CloseAll);
            }, T.Red, !E.Busy && keys),
            Ui.B(E.Running ? "Tắt bot" : "Bật bot", async () =>
            {
                var ctx = Platform.AppContext;
                if (E.Running)
                {
                    if (!await DisplayAlert("Tắt bot?", "Bot sẽ không tự mua bán và không nghe lệnh khớp. Lệnh stop trên sàn vẫn giữ.", "Tắt", "Hủy")) return;
                    BotHost.Enabled = false;
                    BotService.Stop(ctx);
                }
                else
                {
                    BotHost.Enabled = true;
                    BotService.Start(ctx);
                }
                Draw();
            }, E.Running ? T.Card2 : T.Green)));

        var views = snap?.Positions ?? st?.Positions.Select(kv => new PositionView(kv.Key, kv.Value.EntryTime, kv.Value.EntryPrice,
            kv.Value.EntryPrice, kv.Value.Qty, kv.Value.Stop, kv.Value.BarsHeld, 0, 0, 0)).ToList() ?? [];
        Body.Add(Ui.Section($"Lệnh đang mở ({views.Count})"));
        if (views.Count == 0)
            Body.Add(Ui.Card(Ui.Muted("Chưa có lệnh. Bot chỉ mua khi giá đóng cửa ngày vượt đỉnh 20 ngày và nằm trên EMA200 — xem tab Radar."), pad: 12));
        foreach (var p in views)
            Body.Add(Ui.Card(new VerticalStackLayout
            {
                Spacing = 8,
                Children =
                {
                    Ui.Row(Ui.L(Ui.Coin(p.Symbol), 17, true), Ui.L($"{Ui.Pct(p.PnlPct)}  {Ui.N(p.PnlUsdt)}", 14, true, Ui.PnL(p.PnlPct))),
                    Ui.Grid2(Ui.Stat("Giá vào", Ui.Px(p.EntryPrice)), Ui.Stat("Giá hiện tại", Ui.Px(p.Price)),
                        Ui.Stat("Stop", $"{Ui.Px(p.Stop)} ({Ui.Pct(p.RiskPct)})", T.Amber), Ui.Stat("Đã giữ", $"{p.Days} ngày")),
                },
            }, pad: 12));
    }
}

public class RadarPage : BotPage
{
    public RadarPage() : base("Radar tín hiệu D1") { }

    protected override void Render()
    {
        Body.Clear();
        var rows = E.Last?.Radar;
        Body.Add(Ui.Row(Ui.Muted("Mua khi giá ĐÓNG CỬA ngày > đỉnh 20 ngày và > EMA200."),
            Ui.B(E.Busy ? "…" : "↻", () => RunAsync(BotCommand.Run), T.Blue, !E.Busy && E.Settings.HasBinance).Also(b => b.WidthRequest = 56)));
        if (rows is null)
        {
            Body.Add(Ui.Card(Ui.Muted("Chưa có radar — bấm ↻ (lần đầu tải lịch sử nến mất vài phút)."), pad: 12));
            return;
        }
        int near = rows.Count(r => r.AboveEma && r.Status != "Đang giữ");
        Body.Add(Ui.H(Ui.Pill($"{rows.Count(r => r.Status == "Đang giữ")} đang giữ", T.Green), Ui.Pill($"{near} trên EMA200", T.Amber),
            Ui.Pill($"{rows.Count - near} xu hướng giảm", T.Muted)));
        foreach (var r in rows)
        {
            var c = r.Status == "Đang giữ" || r.Status.StartsWith("Đủ") ? T.Green : r.AboveEma ? T.Amber : T.Muted;
            string tag = r.Status == "Đang giữ" ? "Đang giữ" : r.Status.StartsWith("Đủ") ? "Đủ điều kiện" : r.AboveEma ? "Chờ breakout" : "Dưới EMA200";
            Body.Add(Ui.Card(new VerticalStackLayout
            {
                Spacing = 6,
                Children =
                {
                    Ui.Row(Ui.H(Ui.L(Ui.Coin(r.Symbol), 16, true), Ui.Pill(tag, c)), Ui.L(r.GapPct <= 0 ? "đạt" : $"còn {Ui.Pct(r.GapPct)}", 14, true, c)),
                    new ProgressBar { Progress = Math.Clamp(1 - r.GapPct / 50, 0.02, 1), ProgressColor = c, BackgroundColor = T.Line, HeightRequest = 6 },
                    Ui.Muted($"Giá {Ui.Px(r.Price)} · Đỉnh 20N {Ui.Px(r.Breakout)} · EMA200 {Ui.Px(r.Ema200)}", 11),
                },
            }, pad: 12));
        }
    }
}

public class ResearchPage : BotPage
{
    public ResearchPage() : base("Lướt sóng (nghiên cứu)") { }

    protected override void Render()
    {
        var r = E.Research;
        Body.Clear();
        Body.Add(Ui.H(Ui.Pill(r.Enabled ? "● Đang nghiên cứu" : r.Positions.Count > 0 ? "● Đã tắt · chờ bán" : "● Đã tắt", r.Enabled ? T.Green : T.Muted),
            Ui.Pill("testnet", T.Blue), Ui.Pill($"{r.Positions.Count}/5 lệnh", T.Amber)));
        if (!E.Settings.IsTestnet) Body.Add(Ui.Card(Ui.L("Đang ở sàn thật — chế độ nghiên cứu không chạy.", 12, color: T.Red), T.Red.WithAlpha(0.12f), 12));
        Body.Add(Ui.B(r.Enabled ? "Tắt nghiên cứu (bán lệnh đang mở)" : "Bật nghiên cứu", async () =>
        {
            if (!r.Enabled && !await DisplayAlert("Bật nghiên cứu?",
                    "Lướt sóng 10–30 phút trên TESTNET (tiền ảo), 100 USDT/lệnh, tối đa 500 USDT. Backtest 2 năm của kiểu này lỗ ~−0,31%/lệnh sau phí — đây là để đo thực tế, không phải để kiếm lời.",
                    "Bật", "Hủy")) return;
            await Task.Run(() => E.SetResearchAsync(!r.Enabled));
            Draw();
        }, r.Enabled ? T.Red : T.Green));
        if (r.Note is { Length: > 21 } note) Body.Add(Ui.Muted($"{Ui.Local(note[..20], "HH:mm")} · {note[21..]}"));

        var s = ResearchReport.Stats(r.Trades);
        Body.Add(Ui.Card(new VerticalStackLayout
        {
            Spacing = 12,
            Children =
            {
                Ui.Grid2(
                    Ui.Stat("Số lệnh", s?.Trades.ToString() ?? "0"),
                    Ui.Stat("Tỷ lệ thắng", s is null ? "—" : $"{s.WinPct:N0}%"),
                    Ui.Stat("TB / lệnh (sau phí)", s is null ? "—" : Ui.Pct(s.AvgNetPct), s is null ? null : Ui.PnL(s.AvgNetPct)),
                    Ui.Stat("Tổng (USDT)", s is null ? "—" : Ui.N(s.TotalNetUsdt), s is null ? null : Ui.PnL(s.TotalNetUsdt))),
                Ui.Muted(s is null ? "Backtest đối chiếu: thắng 17% · TB −0,31%/lệnh"
                    : $"Giữ TB {s.AvgMinutes:N1} phút · lệch giá vào {s.AvgSlipBps:+0.0;-0.0} bps · backtest: thắng 17%, TB −0,31%/lệnh", 11),
            },
        }));
        Body.Add(Ui.Card(Ui.Muted("BTC, ETH, BNB, SOL, XRP · vào khi nến 5 phút có dòng tiền mua > +0,3 và tăng, coin và BTC trên EMA200 khung 1h · " +
                                  "stop 1,5×ATR, từ phút 10 stop nâng theo giá, bán ở phút 30 · phí 0,1%/chiều như sàn thật.", 11), pad: 12));

        long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        Body.Add(Ui.Section($"Đang giữ ({r.Positions.Count})"));
        foreach (var p in r.Positions.Values)
        {
            double min = (now - p.EntryMs) / 60000.0;
            Body.Add(Ui.Card(new VerticalStackLayout
            {
                Spacing = 6,
                Children =
                {
                    Ui.Row(Ui.L(Ui.Coin(p.Symbol), 16, true), Ui.L($"{min:N0}/30 phút", 13, true, T.Amber)),
                    new ProgressBar { Progress = Math.Clamp(min / 30, 0, 1), ProgressColor = T.Amber, BackgroundColor = T.Line, HeightRequest = 6 },
                    Ui.Muted($"Vào {Ui.Px(p.Entry)} · stop {Ui.Px(p.Stop)} · đỉnh {Ui.Px(p.Peak)} · {Ui.N(p.Cost)} USDT", 11),
                },
            }, pad: 12));
        }
        Body.Add(Ui.Section("Lệnh đã đóng"));
        if (r.Trades.Count == 0) Body.Add(Ui.Muted("Chưa có."));
        foreach (var t in r.Trades.AsEnumerable().Reverse().Take(100))
            Body.Add(Ui.Card(new VerticalStackLayout
            {
                Spacing = 4,
                Children =
                {
                    Ui.Row(Ui.L(Ui.Coin(t.Symbol), 15, true), Ui.L($"{Ui.Pct(t.NetPct)}  {Ui.N(t.NetUsdt)}", 14, true, Ui.PnL(t.NetPct))),
                    Ui.Muted($"{Ui.Px(t.EntryPrice)} → {Ui.Px(t.ExitPrice)} · {t.Minutes:N1} phút · {t.Reason} · trước phí {Ui.Pct(t.GrossPct)}", 11),
                    Ui.Muted($"{Ui.Local(t.EntryTime, "dd/MM HH:mm")} → {Ui.Local(t.ExitTime, "HH:mm")}", 11),
                },
            }, pad: 12));
    }
}

public class HistoryPage : BotPage
{
    bool _fills;

    public HistoryPage() : base("Lịch sử") { }

    protected override void Render()
    {
        Body.Clear();
        Body.Add(Ui.Grid2(
            Ui.B("Lệnh D1 đã đóng", () => { _fills = false; Draw(); return Task.CompletedTask; }, _fills ? T.Card2 : T.Blue),
            Ui.B("Lệnh khớp", () => { _fills = true; Draw(); return Task.CompletedTask; }, _fills ? T.Blue : T.Card2)));
        if (_fills)
        {
            var fills = E.Watcher?.FillList ?? [];
            if (fills.Count == 0) Body.Add(Ui.Muted("Chưa có lệnh khớp."));
            foreach (var f in fills.AsEnumerable().Reverse().Take(150))
                Body.Add(Ui.Card(new VerticalStackLayout
                {
                    Spacing = 4,
                    Children =
                    {
                        Ui.Row(Ui.H(Ui.Pill(f.Side == "BUY" ? "MUA" : "BÁN", f.Side == "BUY" ? T.Green : T.Red), Ui.L(Ui.Coin(f.Symbol), 15, true)),
                            Ui.L($"{Ui.N(f.Quote)} USDT", 13, true)),
                        Ui.Muted($"{f.Qty:G6} @ {Ui.Px(f.Price)} · {f.Type} · nguồn {f.Source} · {Ui.Local(f.Time, "dd/MM HH:mm:ss")}", 11),
                    },
                }, pad: 12));
            return;
        }
        var trades = E.State?.Trades.OrderByDescending(t => t.ExitTime, StringComparer.Ordinal).ToList() ?? [];
        if (trades.Count == 0) { Body.Add(Ui.Card(Ui.Muted("Bot D1 chưa đóng lệnh nào."), pad: 12)); return; }
        var m = Metrics.Compute(trades)!;
        Body.Add(Ui.Card(Ui.Grid2(Ui.Stat("Số lệnh", m.Trades.ToString()), Ui.Stat("Tỷ lệ thắng", $"{m.WinRatePct:N1}%"),
            Ui.Stat("TB / lệnh", Ui.Pct(m.ExpectancyPct), Ui.PnL(m.ExpectancyPct)), Ui.Stat("Sụt vốn tối đa", $"{m.MaxDrawdownPct:N1}%", T.Amber))));
        foreach (var t in trades)
            Body.Add(Ui.Card(new VerticalStackLayout
            {
                Spacing = 4,
                Children =
                {
                    Ui.Row(Ui.L(Ui.Coin(t.Symbol), 15, true), Ui.L($"{Ui.Pct(t.ReturnPct)}  {Ui.N(t.PnlUsdt)}", 14, true, Ui.PnL(t.PnlUsdt))),
                    Ui.Muted($"{Ui.Px(t.EntryPrice)} → {Ui.Px(t.ExitPrice)} · {t.Days} ngày · {t.Reason}", 11),
                    Ui.Muted($"{Ui.Local(t.EntryTime, "dd/MM/yy")} → {Ui.Local(t.ExitTime, "dd/MM/yy")}", 11),
                },
            }, pad: 12));
    }
}

public class SettingsPage : BotPage
{
    readonly Entry _key = E1("BINANCE_API_KEY", true), _secret = E1("BINANCE_API_SECRET", true), _ntfy = E1("NTFY_TOPIC (cbb-…)"),
        _gh = E1("GitHub token (github_pat_…)", true), _repo = E1("chủ/repo");
    readonly Switch _live = new() { OnColor = T.Red, ThumbColor = Colors.White };
    readonly Label _check = Ui.L("", 12), _battery = Ui.L("", 13, true), _log = Ui.L("", 11, color: T.Muted).Also(l => l.FontFamily = "monospace");

    static Entry E1(string ph, bool pwd = false) => new()
    {
        Placeholder = ph, IsPassword = pwd, TextColor = T.Text, PlaceholderColor = T.Muted, BackgroundColor = T.Card2, FontSize = 13,
    };

    public SettingsPage() : base("Cài đặt")
    {
        View Field(string name, Entry e) => new VerticalStackLayout
        {
            Spacing = 4,
            Children =
            {
                Ui.Muted(name, 11),
                Ui.Row(e, Ui.B("Dán", async () => e.Text = (await Clipboard.GetTextAsync())?.Trim() ?? e.Text).Also(b => { b.HeightRequest = 40; b.WidthRequest = 64; })),
            },
        };
        Body.Add(Ui.Section("Khóa API"));
        Body.Add(Ui.Card(new VerticalStackLayout
        {
            Spacing = 12,
            Children =
            {
                Field("Binance API key", _key), Field("Binance API secret", _secret),
                Ui.Row(new VerticalStackLayout { Children = { Ui.L("Sàn thật (tiền thật)", 13, true), Ui.Muted("Tắt = testnet", 11) } }, _live),
                Field("NTFY_TOPIC", _ntfy), Field("GitHub token (Contents: Read and write)", _gh), Field("GitHub repo", _repo),
                Ui.Muted("Token: github.com → Settings → Developer settings → Fine-grained tokens → chỉ chọn repo trên, quyền Contents: Read and write.", 11),
                Ui.B("Dán cả file .env", async () =>
                {
                    var text = await Clipboard.GetTextAsync();
                    if (string.IsNullOrWhiteSpace(text)) { await DisplayAlert("Clipboard trống", "Chép nội dung file .env rồi bấm lại.", "OK"); return; }
                    Load(Current().WithEnv(text));
                }),
                Ui.Grid2(Ui.B("Lưu", SaveAsync, T.Green), Ui.B("Kiểm tra kết nối", async () =>
                {
                    await SaveAsync();
                    _check.Text = "Đang kiểm tra…";
                    var res = await Task.Run(E.CheckAsync);
                    _check.Text = string.Join("\n", res.Select(r => $"{(r.Ok ? "✓" : "✗")} {r.Name}: {r.Detail}"));
                }, T.Blue)),
                _check,
            },
        }));
        Body.Add(Ui.Section("Chuyển dữ liệu từ laptop"));
        Body.Add(Ui.Card(Ui.Grid2(Ui.B("Nhập state.json", () => ImportAsync(E.ImportState)), Ui.B("Nhập fills.json", () => ImportAsync(E.ImportFills))), pad: 12));
        Body.Add(Ui.Section("Chạy nền"));
        Body.Add(Ui.Card(new VerticalStackLayout
        {
            Spacing = 10,
            Children =
            {
                _battery,
                Ui.Muted("OPPO/ColorOS: Cài đặt ứng dụng → Crypto Bot → Pin → Cho phép hoạt động nền, và bật Tự khởi chạy để bot chạy lại sau khi khởi động máy.", 11),
                Ui.Grid2(Ui.B("Pin không giới hạn", () => { Battery.AskUnrestricted(); return Task.CompletedTask; }),
                    Ui.B("Cài đặt ứng dụng", () => { Battery.OpenAppSettings(); return Task.CompletedTask; })),
            },
        }));
        Body.Add(Ui.Section("Nhật ký"));
        Body.Add(Ui.Card(_log, pad: 12));
    }

    protected override void OnAppearing()
    {
        Load(E.Settings);
        base.OnAppearing();
    }

    void Load(BotSettings s)
    {
        _key.Text = s.ApiKey; _secret.Text = s.ApiSecret; _ntfy.Text = s.NtfyTopic; _gh.Text = s.GitHubToken; _repo.Text = s.GitHubRepo;
        _live.IsToggled = !s.IsTestnet;
    }

    BotSettings Current() => new((_key.Text ?? "").Trim(), (_secret.Text ?? "").Trim(),
        _live.IsToggled ? BinanceClient.LiveUrl : BinanceClient.TestnetUrl, (_ntfy.Text ?? "").Trim(), (_gh.Text ?? "").Trim(),
        (_repo.Text ?? "").Trim());

    async Task SaveAsync()
    {
        var s = Current();
        if (!s.IsTestnet && E.Settings.IsTestnet &&
            !await DisplayAlert("Chuyển sang sàn THẬT?", "Bot sẽ đặt lệnh bằng TIỀN THẬT. Trạng thái testnet hiện tại sẽ không dùng được.", "Đồng ý", "Hủy"))
        {
            _live.IsToggled = false;
            return;
        }
        await BotHost.SaveAsync(s);
        await DisplayAlert("Đã lưu", "Khóa được lưu mã hóa trong điện thoại (Android Keystore).", "OK");
    }

    async Task ImportAsync(Action<string> import)
    {
        var f = await FilePicker.PickAsync();
        if (f is null) return;
        using var s = await f.OpenReadAsync();
        import(await new StreamReader(s).ReadToEndAsync());
        await DisplayAlert("Đã nhập", f.FileName, "OK");
    }

    protected override void Render()
    {
        bool ok = Battery.IsUnrestricted;
        _battery.Text = ok ? "✓ Pin: không hạn chế" : "⚠ Pin đang bị tối ưu — máy có thể tắt bot khi tắt màn hình";
        _battery.TextColor = ok ? T.Green : T.Amber;
        var lines = E.EngineLog.TakeLast(80).Reverse().Concat(new[] { "— nhật ký bot D1 —" })
            .Concat(E.State?.Log.TakeLast(40).AsEnumerable().Reverse() ?? []);
        _log.Text = string.Join("\n", lines);
    }
}

static class Ext
{
    public static T Also<T>(this T x, Action<T> a) { a(x); return x; }
}
