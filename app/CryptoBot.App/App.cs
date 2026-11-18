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
