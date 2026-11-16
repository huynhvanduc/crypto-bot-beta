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
        UserAppTheme = AppTheme.Dark;
        var shell = new Shell
        {
            BackgroundColor = T.Bg,
            Items =
            {
                new TabBar
                {
                    Items =
                    {
                        new ShellContent { Title = "Bot D1", Content = new OverviewPage() },
                        new ShellContent { Title = "Radar", Content = new RadarPage() },
                        new ShellContent { Title = "Lướt", Content = new ResearchPage() },
                        new ShellContent { Title = "Lịch sử", Content = new HistoryPage() },
                        new ShellContent { Title = "Cài đặt", Content = new SettingsPage() },
                    },
                },
            },
        };
        Shell.SetTabBarBackgroundColor(shell, Color.FromArgb("#0F1729"));
        Shell.SetTabBarTitleColor(shell, T.Green);
        Shell.SetTabBarUnselectedColor(shell, T.Muted);
        Shell.SetTabBarForegroundColor(shell, T.Green);
        Shell.SetBackgroundColor(shell, T.Bg);
        Shell.SetTitleColor(shell, T.Text);
        return new Window(shell);
    }
}

public static class BotHost
{
    static BotEngine? _engine;
    public static BotEngine Engine => _engine ??= new BotEngine(FileSystem.AppDataDirectory, LoadSettings());

    public static bool Enabled
    {
        get => Preferences.Get("enabled", true);
        set => Preferences.Set("enabled", value);
    }

    static string Get(string k, string def = "") => Task.Run(() => SecureStorage.GetAsync(k)).Result ?? def;

    public static BotSettings LoadSettings() => new(Get("key"), Get("secret"), Get("base", BinanceClient.TestnetUrl), Get("ntfy"),
        Get("gh_token"), Get("gh_repo", "huynhvanduc/crypto-bot-beta"));

    public static async Task SaveAsync(BotSettings s)
    {
        await SecureStorage.SetAsync("key", s.ApiKey);
        await SecureStorage.SetAsync("secret", s.ApiSecret);
        await SecureStorage.SetAsync("base", s.BaseUrl);
        await SecureStorage.SetAsync("ntfy", s.NtfyTopic);
        await SecureStorage.SetAsync("gh_token", s.GitHubToken);
        await SecureStorage.SetAsync("gh_repo", s.GitHubRepo);
        Engine.Settings = s;
        if (Engine.Running) { Engine.Stop(); Engine.Start(); }
    }
}
