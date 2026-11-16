using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Channels;

namespace CryptoBot.Core;

public enum BotCommand { Run, Pause, Resume, CloseAll, Intraday }

public sealed class BotEngine
{
    public const double PushEvery = 60, BotRunEvery = 60;
    readonly string _dir;
    readonly HttpClient _http;
    readonly SemaphoreSlim _gate = new(1, 1);
    readonly object _logLock = new();
    BotSettings _settings;
    CancellationTokenSource? _cts;

    public BotState? State { get; private set; }
    public RunResult? Last { get; private set; }
    public string? LastError { get; private set; }
    public bool Busy { get; private set; }
    public bool Running => _cts is { IsCancellationRequested: false };
    public bool WsConnected { get; private set; }
    public FillWatcher? Watcher { get; private set; }
    readonly List<string> _engineLog = new();
    public string[] EngineLog { get { lock (_logLock) return _engineLog.ToArray(); } }
    public event Action? Changed;

    readonly SemaphoreSlim _researchGate = new(1, 1);
    public ResearchState Research { get; private set; }
    string ResearchPath => Path.Combine(_dir, "research.json");
    public string StatePath => Path.Combine(_dir, "state.json");
    public string FillsPath => Path.Combine(_dir, "fills.json");
    string LastDailyPath => Path.Combine(_dir, "last_daily");
    string DocsDir => Path.Combine(_dir, "docs");

    public BotEngine(string dataDir, BotSettings settings, HttpClient? http = null)
    {
        _dir = dataDir;
        _settings = settings;
        _http = http ?? new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        Directory.CreateDirectory(_dir);
        if (File.Exists(StatePath)) State = BotState.Parse(File.ReadAllText(StatePath));
        Research = ResearchReport.Load(ResearchPath);
    }

    public async Task SetResearchAsync(bool enabled)
    {
        if (enabled && !_settings.IsTestnet) throw new InvalidOperationException("Chế độ nghiên cứu chỉ chạy trên testnet");
        await _researchGate.WaitAsync();
        try
        {
            Research.Enabled = enabled;
            if (!enabled && Research.Positions.Count > 0) await new ResearchTrader(Exchange(), _http, Research, Log).CloseAllAsync();
            ResearchReport.Save(ResearchPath, Research);
            Log(enabled ? "BẬT chế độ nghiên cứu (tín hiệu C, giữ 10–30 phút, 100 USDT/lệnh, tối đa 500 USDT)" : "TẮT chế độ nghiên cứu");
        }
        finally { _researchGate.Release(); }
    }

    public const int IntradayMinutes = 15;
    public string? LastIntraday { get; private set; }
    long _intradaySlot;

    async Task IntradayLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            await Delay(30, ct);
            var now = DateTimeOffset.UtcNow;
            long slot = now.ToUnixTimeSeconds() / (IntradayMinutes * 60);
            if (!_settings.HasBinance || slot == _intradaySlot || Busy || LastDaily != now.ToString("yyyy-MM-dd")) continue;
            _intradaySlot = slot;
            try
            {
                await RunTraderAsync(BotCommand.Intraday);
                LastIntraday = Json.NowIso();
                Changed?.Invoke();
            }
            catch (Exception e) { Log($"Xét giá trong ngày lỗi: {e.Message}"); }
        }
    }

    async Task ResearchLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            await Delay(10, ct);
            if (!_settings.HasBinance || (!Research.Enabled && Research.Positions.Count == 0)) continue;
            if (!_settings.IsTestnet)
            {
                if (Research.Enabled) { Research.Enabled = false; ResearchReport.Save(ResearchPath, Research); Log("Sàn thật → tự TẮT chế độ nghiên cứu"); }
                continue;
            }
            await _researchGate.WaitAsync(ct);
            try
            {
                var ex = Exchange();
                await ex.SyncTimeAsync();
                if (await new ResearchTrader(ex, _http, Research, Log).TickAsync())
                {
                    ResearchReport.Save(ResearchPath, Research);
                    Changed?.Invoke();
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
            catch (Exception e) { Log($"Nghiên cứu lỗi: {e.Message}"); await Delay(30, ct); }
            finally { _researchGate.Release(); }
        }
    }

    public BotSettings Settings
    {
        get => _settings;
        set { _settings = value; Changed?.Invoke(); }
    }

    public string? LastDaily => File.Exists(LastDailyPath) ? File.ReadAllText(LastDailyPath).Trim() : null;

    public void Log(string msg)
    {
        var line = $"{Json.NowIso()} {msg}";
        lock (_logLock)
        {
            _engineLog.Add(line);
            if (_engineLog.Count > 300) _engineLog.RemoveRange(0, _engineLog.Count - 300);
            try { File.AppendAllText(Path.Combine(_dir, "engine.log"), line + "\n"); } catch { }
        }
        Changed?.Invoke();
    }

    BinanceClient Exchange() => new(_http, _settings.ApiKey, _settings.ApiSecret, _settings.BaseUrl);

    public async Task<string> RunTraderAsync(BotCommand cmd = BotCommand.Run)
    {
        if (!_settings.HasBinance) throw new InvalidOperationException("Chưa có khóa Binance — vào tab Cài đặt để dán khóa");
        await _gate.WaitAsync();
        Busy = true;
        Changed?.Invoke();
        try
        {
            var ex = Exchange();
            var st = File.Exists(StatePath) ? BotState.Parse(await File.ReadAllTextAsync(StatePath))
                : BotState.New(Config.Capital, Config.Symbols, _settings.Mode);
            if (st.Mode != _settings.Mode)
                throw new InvalidOperationException($"Trạng thái thuộc chế độ '{st.Mode}', cài đặt đang là '{_settings.Mode}'. Đổi sàn trong Cài đặt hoặc nhập state.json đúng chế độ.");
            var trader = new LiveTrader(ex, st, new MarketData(_http, _dir, Log), Log);
            RunResult? snap = null;
            string? error = null;
            try
            {
                if (cmd == BotCommand.CloseAll) await trader.CloseAllAsync();
                else if (cmd == BotCommand.Pause) trader.SetPaused(true);
                else if (cmd == BotCommand.Resume) trader.SetPaused(false);
                snap = cmd == BotCommand.Intraday ? await trader.IntradayAsync() : await trader.RunAsync();
            }
            catch (Exception e)
            {
                error = e is BinanceException { IsRestrictedLocation: true }
                    ? "Binance chặn vùng truy cập (HTTP 451) — kiểm tra mạng/VPN" : $"{e.GetType().Name}: {e.Message}";
                trader.Log($"LỖI: {error}");
            }
            Files.WriteAtomic(StatePath, st.ToJson());
            State = BotState.Parse(st.ToJson());
            if (snap is not null) Last = snap;
            LastError = error;
            var data = Dashboard.Build(st, snap, error);
            Files.WriteAtomic(Path.Combine(DocsDir, "data.json"), data);
            await PushAsync("docs/data.json", data, $"Cập nhật dashboard {Json.NowIso()}");
            if (error is not null) throw new BotRunException(error);
            return snap is null ? "" : $"Vốn {snap.Equity:N2} USDT | {snap.Positions.Count} lệnh mở | tín hiệu: {(snap.Signals.Count > 0 ? string.Join(", ", snap.Signals) : "không")}";
        }
        finally
        {
            Busy = false;
            _gate.Release();
            Changed?.Invoke();
        }
    }

    async Task<bool> PushAsync(string path, string content, string message)
    {
        if (string.IsNullOrWhiteSpace(_settings.GitHubToken)) return true;
        try { Log(await new GitHubPublisher(_http, _settings.GitHubToken, _settings.GitHubRepo).PutAsync(path, content, message)); return true; }
        catch (Exception e) { Log($"Đẩy GitHub lỗi: {e.Message}"); return false; }
    }

    public void ImportState(string text)
    {
        var st = BotState.Parse(text);
        if (st.Mode != _settings.Mode) throw new InvalidOperationException($"state.json thuộc chế độ '{st.Mode}', cài đặt đang là '{_settings.Mode}'");
        Files.WriteAtomic(StatePath, st.ToJson());
        State = st;
        Log($"Đã nhập state.json: {st.Positions.Count} lệnh mở, {st.Trades.Count} lệnh đã đóng");
    }

    public void ImportFills(string text)
    {
        var n = JsonNode.Parse(text)!;
        if (n["fills"] is not JsonArray) throw new InvalidOperationException("fills.json không đúng định dạng");
        Files.WriteAtomic(FillsPath, text);
        Watcher?.Load();
        Log($"Đã nhập fills.json: {((JsonArray)n["fills"]!).Count} lệnh khớp");
    }

    public void Start()
    {
        if (Running) return;
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        _ = Task.Run(() => DailyLoopAsync(ct));
        _ = Task.Run(() => WatchLoopAsync(ct));
        _ = Task.Run(() => ResearchLoopAsync(ct));
        _ = Task.Run(() => IntradayLoopAsync(ct));
        Log($"Bot bắt đầu ({_settings.Mode}); chạy D1 lúc 07:05 giờ VN mỗi ngày, chạy bù nếu lỡ");
    }

    public void Stop()
    {
        _cts?.Cancel();
        _cts = null;
        WsConnected = false;
        Log("Đã dừng bot");
    }

    async Task DailyLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            var now = DateTimeOffset.UtcNow;
            var today = now.ToString("yyyy-MM-dd");
            if (_settings.HasBinance && now.Hour * 100 + now.Minute >= 5 && LastDaily != today)
            {
                Log("Chạy bot D1 hằng ngày");
                try
                {
                    Log(await RunTraderAsync());
                    File.WriteAllText(LastDailyPath, today);
                }
                catch (Exception e)
                {
                    Log($"Bot D1 lỗi ({e.Message}); thử lại sau 9 phút");
                    await Delay(540, ct);
                }
            }
            await Delay(60, ct);
        }
    }

    static async Task Delay(double seconds, CancellationToken ct)
    {
        try { await Task.Delay(TimeSpan.FromSeconds(seconds), ct); } catch (OperationCanceledException) { }
    }

    string WsUrl(BinanceClient ex) => ex.IsTestnet ? "wss://ws-api.testnet.binance.vision/ws-api/v3" : "wss://ws-api.binance.com:443/ws-api/v3";

    async Task WatchLoopAsync(CancellationToken ct)
    {
        int delay = 5;
        double lastPush = 0, lastBot = 0;
        Task? pushTask = null, botTask = null;
        while (!ct.IsCancellationRequested)
        {
            if (!_settings.HasBinance) { await Delay(30, ct); continue; }
            var ex = Exchange();
            var topic = _settings.NtfyTopic.Trim();
            var ntfy = topic.Length > 0 ? new Ntfy(_http, topic) : null;
            var w = new FillWatcher(ex, m =>
            {
                if (ntfy is null) return;
                _ = ntfy.PublishAsync(m).ContinueWith(t => Log($"Gửi ntfy lỗi: {t.Exception?.GetBaseException().Message}"),
                    TaskContinuationOptions.OnlyOnFaulted);
            }, Config.Symbols, topic, FillsPath, () => State);
            w.Load();
            w.Dirty = true;
            Watcher = w;
            using var ws = new ClientWebSocket();
            try
            {
                await ex.SyncTimeAsync();
                int n = await w.BackfillAsync();
                Log($"Lấy bù {n} lệnh khớp; số dư USDT {w.Usdt:N2}");
                await ws.ConnectAsync(new Uri(WsUrl(ex)), ct);
                long ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + ex.TimeOffset;
                var q = $"apiKey={ex.ApiKey}&recvWindow=10000&timestamp={ts}";
                var sub = new JsonObject
                {
                    ["id"] = "sub", ["method"] = "userDataStream.subscribe.signature",
                    ["params"] = new JsonObject { ["apiKey"] = ex.ApiKey, ["recvWindow"] = 10000, ["timestamp"] = ts, ["signature"] = ex.SignWs(q) },
                };
                await ws.SendAsync(Encoding.UTF8.GetBytes(sub.ToJsonString()), WebSocketMessageType.Text, true, ct);
                var inbox = Channel.CreateUnbounded<string>();
                _ = ReceiveLoopAsync(ws, inbox.Writer, ct);
                var first = JsonNode.Parse(await inbox.Reader.ReadAsync(ct))!;
                if (first["status"]?.GetValue<int>() != 200)
                    throw new IOException($"Đăng ký nhận lệnh khớp bị từ chối: {first["error"]?.ToJsonString() ?? first.ToJsonString()}");
                WsConnected = true;
                Log("Đang nghe lệnh khớp qua WebSocket");
                delay = 5;
                while (!ct.IsCancellationRequested)
                {
                    var outv = new List<Fill>();
                    using (var wait = CancellationTokenSource.CreateLinkedTokenSource(ct))
                    {
                        wait.CancelAfter(500);
                        try
                        {
                            if (await inbox.Reader.WaitToReadAsync(wait.Token))
                                while (inbox.Reader.TryRead(out var msg)) outv.AddRange(w.Handle(JsonNode.Parse(msg)!));
                            else throw new IOException("WebSocket đã đóng");
                        }
                        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { }
                    }
                    foreach (var f in outv.Concat(w.Tick()))
                        Log($"KHỚP {f.Side} {Fmt.G(f.Qty)} {f.Symbol} @ {Fmt.G(f.Price)} ({f.Source}) → đã phát ntfy");
                    double now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                    if (w.Dirty && pushTask is not { IsCompleted: false } && now - lastPush >= PushEvery)
                    {
                        var data = w.Export();
                        Files.WriteAtomic(Path.Combine(DocsDir, "fills.json"), data);
                        lastPush = now;
                        pushTask = Task.Run(async () =>
                        {
                            if (!await PushAsync("docs/fills.json", data, $"Lệnh khớp {Json.NowIso()}")) w.Dirty = true;
                        });
                    }
                    if (w.BotStopFilled && botTask is not { IsCompleted: false } && now - lastBot >= BotRunEvery)
                    {
                        w.BotStopFilled = false;
                        lastBot = now;
                        Log("Stop của bot D1 vừa khớp → chạy bot để chốt sổ");
                        botTask = Task.Run(async () =>
                        {
                            try { Log(await RunTraderAsync()); } catch (Exception e) { Log($"Chạy bot lỗi: {e.Message}"); }
                        });
                    }
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
            catch (Exception e)
            {
                WsConnected = false;
                Log($"Mất kết nối ({e.GetType().Name}: {e.Message}); nối lại sau {delay} giây");
                await Delay(delay, ct);
                delay = Math.Min(delay * 2, 60);
            }
            finally
            {
                WsConnected = false;
                try { if (ws.State == WebSocketState.Open) await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None); } catch { }
            }
        }
    }

    static async Task ReceiveLoopAsync(ClientWebSocket ws, ChannelWriter<string> outw, CancellationToken ct)
    {
        var buf = new byte[64 * 1024];
        var sb = new MemoryStream();
        try
        {
            while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
            {
                var r = await ws.ReceiveAsync(buf, ct);
                if (r.MessageType == WebSocketMessageType.Close) break;
                sb.Write(buf, 0, r.Count);
                if (!r.EndOfMessage) continue;
                outw.TryWrite(Encoding.UTF8.GetString(sb.ToArray()));
                sb.SetLength(0);
            }
        }
        catch { }
        finally { outw.TryComplete(); }
    }

    public async Task<List<(string Name, bool Ok, string Detail)>> CheckAsync()
    {
        var res = new List<(string, bool, string)>();
        try
        {
            var ex = Exchange();
            await ex.SyncTimeAsync();
            res.Add(("Binance", true, $"USDT {await ex.FreeAsync("USDT"):N2} ({_settings.Mode})"));
        }
        catch (Exception e) { res.Add(("Binance", false, e.Message)); }
        if (_settings.NtfyTopic.Length > 0)
        {
            try
            {
                await new Ntfy(_http, _settings.NtfyTopic).PublishAsync(new { v = 1, kind = "test", msg = "Kiểm tra từ app" });
                res.Add(("ntfy", true, "đã gửi tin thử"));
            }
            catch (Exception e) { res.Add(("ntfy", false, e.Message)); }
        }
        else res.Add(("ntfy", false, "chưa có NTFY_TOPIC"));
        if (_settings.GitHubToken.Length > 0)
        {
            try
            {
                var (ok, why) = await new GitHubPublisher(_http, _settings.GitHubToken, _settings.GitHubRepo).CanPushAsync();
                res.Add(("GitHub", ok, why));
            }
            catch (Exception e) { res.Add(("GitHub", false, e.Message)); }
        }
        else res.Add(("GitHub", false, "chưa có token (dashboard web sẽ không cập nhật)"));
        return res;
    }
}

public sealed class BotRunException(string message) : Exception(message);
