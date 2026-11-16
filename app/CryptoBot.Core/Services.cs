using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace CryptoBot.Core;

public sealed record BotSettings(string ApiKey = "", string ApiSecret = "", string BaseUrl = BinanceClient.TestnetUrl,
    string NtfyTopic = "", string GitHubToken = "", string GitHubRepo = "huynhvanduc/crypto-bot-beta")
{
    public bool IsTestnet => BaseUrl.Contains("testnet");
    public string Mode => IsTestnet ? "testnet" : "LIVE";
    public bool HasBinance => ApiKey.Length > 0 && ApiSecret.Length > 0;

    public BotSettings WithEnv(string text)
    {
        var d = new Dictionary<string, string>();
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.Trim();
            int i = line.IndexOf('=');
            if (line.Length == 0 || line.StartsWith('#') || i < 0) continue;
            d[line[..i].Trim()] = line[(i + 1)..].Trim().Trim('"');
        }
        string G(string k, string cur) => d.TryGetValue(k, out var v) && v.Length > 0 ? v : cur;
        return this with
        {
            ApiKey = G("BINANCE_API_KEY", ApiKey), ApiSecret = G("BINANCE_API_SECRET", ApiSecret),
            BaseUrl = G("BINANCE_BASE_URL", BaseUrl), NtfyTopic = G("NTFY_TOPIC", NtfyTopic),
            GitHubToken = G("GITHUB_TOKEN", GitHubToken), GitHubRepo = G("GITHUB_REPO", GitHubRepo),
        };
    }
}

public sealed class Ntfy(HttpClient http, string topic)
{
    public async Task PublishAsync(object payload)
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var body = new StringContent(JsonSerializer.Serialize(payload, Json.Options), Encoding.UTF8);
        (await http.PostAsync($"https://ntfy.sh/{topic}", body, cts.Token)).EnsureSuccessStatusCode();
    }
}

public sealed class GitHubPublisher(HttpClient http, string token, string repo)
{
    HttpRequestMessage Req(HttpMethod m, string url, object? body = null)
    {
        var r = new HttpRequestMessage(m, $"https://api.github.com/repos/{repo}{url}");
        r.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        r.Headers.UserAgent.ParseAdd("crypto-bot-app");
        r.Headers.Accept.ParseAdd("application/vnd.github+json");
        r.Headers.Add("X-GitHub-Api-Version", "2022-11-28");
        if (body is not null) r.Content = JsonContent.Create(body);
        return r;
    }

    public async Task<(bool Ok, string Why)> CanPushAsync()
    {
        using var r = await http.SendAsync(Req(HttpMethod.Put, "/contents/docs/data.json",
            new { message = "kiểm tra quyền", content = "", sha = new string('0', 40) }));
        return (int)r.StatusCode switch
        {
            409 or 422 => (true, $"ghi được vào {repo}"),
            401 => (false, "token sai hoặc đã hết hạn"),
            403 => (false, "token thiếu quyền Contents: Read and write"),
            404 => (false, "không thấy repo — sai tên repo hoặc token chưa chọn repo này"),
            var c => (false, $"HTTP {c}"),
        };
    }

    public async Task<string> PutAsync(string path, string content, string message)
    {
        for (int attempt = 0; ; attempt++)
        {
            string? sha = null;
            using (var g = await http.SendAsync(Req(HttpMethod.Get, $"/contents/{path}")))
            {
                if (g.IsSuccessStatusCode)
                {
                    var node = JsonNode.Parse(await g.Content.ReadAsStringAsync())!;
                    sha = node["sha"]!.GetValue<string>();
                    var b64 = node["content"]?.GetValue<string>()?.Replace("\n", "");
                    if (!string.IsNullOrEmpty(b64) && Encoding.UTF8.GetString(Convert.FromBase64String(b64)) == content)
                        return "Không có gì mới để đẩy lên.";
                }
            }
            using var p = await http.SendAsync(Req(HttpMethod.Put, $"/contents/{path}",
                new { message, content = Convert.ToBase64String(Encoding.UTF8.GetBytes(content)), sha }));
            if (p.IsSuccessStatusCode) return $"Đã đẩy {path} lên GitHub.";
            if (attempt == 0 && (int)p.StatusCode is 409 or 422) continue;
            throw new HttpRequestException($"GitHub {(int)p.StatusCode}: {await p.Content.ReadAsStringAsync()}");
        }
    }
}
