using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.OS;
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
public class MainActivity : MauiAppCompatActivity
{
    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        if (OperatingSystem.IsAndroidVersionAtLeast(33)) RequestPermissions([Android.Manifest.Permission.PostNotifications], 1);
        AutoImport(GetExternalFilesDir("import")?.AbsolutePath);
        if (BotHost.Enabled) BotService.Start(this);
    }

    static void AutoImport(string? dir)
    {
        if (dir is null) return;
        var e = BotHost.Engine;
        void Take(string name, Action<string> act)
        {
            var p = Path.Combine(dir, name);
            if (!File.Exists(p)) return;
            try { act(File.ReadAllText(p)); }
            catch (Exception ex) { e.Log($"Tự nhập {name} lỗi: {ex.Message}"); }
            finally { File.Delete(p); }
        }
        Take("bot.env", t =>
        {
            Task.Run(() => BotHost.SaveAsync(e.Settings.WithEnv(t))).Wait();
            e.Log("Đã tự nhập khóa từ bot.env");
        });
        Take("state.json", e.ImportState);
        Take("fills.json", e.ImportFills);
    }
}

[Register("com.cryptobot.d1.BotService")]
public class BotService : Service
{
    const string Channel = "bot";
    PowerManager.WakeLock? _wl;

    public static void Start(Context c) => c.StartForegroundService(new Intent(c, typeof(BotService)));
    public static void Stop(Context c) => c.StopService(new Intent(c, typeof(BotService)));

    public override IBinder? OnBind(Intent? intent) => null;

    public override StartCommandResult OnStartCommand(Intent? intent, StartCommandFlags flags, int startId)
    {
        var nm = (NotificationManager)GetSystemService(NotificationService)!;
        nm.CreateNotificationChannel(new NotificationChannel(Channel, "Bot đang chạy", NotificationImportance.Low));
        var open = PendingIntent.GetActivity(this, 0, new Intent(this, typeof(MainActivity)), PendingIntentFlags.Immutable);
        var n = new Notification.Builder(this, Channel).SetContentTitle("Crypto Bot đang chạy")
            .SetContentText("D1 lúc 07:05 mỗi ngày · nghe lệnh khớp").SetSmallIcon(Resource.Mipmap.appicon)
            .SetContentIntent(open).SetOngoing(true).Build();
        if (OperatingSystem.IsAndroidVersionAtLeast(34)) StartForeground(1, n, ForegroundService.TypeSpecialUse);
        else StartForeground(1, n);
        _wl ??= ((PowerManager)GetSystemService(PowerService)!).NewWakeLock(WakeLockFlags.Partial, "cryptobot:bot");
        if (!_wl.IsHeld) _wl.Acquire();
        BotHost.Engine.Start();
        return StartCommandResult.Sticky;
    }

    public override void OnDestroy()
    {
        BotHost.Engine.Stop();
        if (_wl?.IsHeld == true) _wl.Release();
        base.OnDestroy();
    }
}

[Register("com.cryptobot.d1.BootReceiver")]
public class BootReceiver : BroadcastReceiver
{
    public override void OnReceive(Context? context, Intent? intent)
    {
        if (context is not null && intent?.Action == Intent.ActionBootCompleted && BotHost.Enabled) BotService.Start(context);
    }
}

public static class Battery
{
    public static void AskUnrestricted()
    {
        var c = Platform.AppContext;
        var i = new Intent(Android.Provider.Settings.ActionRequestIgnoreBatteryOptimizations,
            Android.Net.Uri.Parse("package:" + c.PackageName));
        i.AddFlags(ActivityFlags.NewTask);
        c.StartActivity(i);
    }

    public static void OpenAppSettings()
    {
        var c = Platform.AppContext;
        var i = new Intent(Android.Provider.Settings.ActionApplicationDetailsSettings, Android.Net.Uri.Parse("package:" + c.PackageName));
        i.AddFlags(ActivityFlags.NewTask);
        c.StartActivity(i);
    }

    public static bool IsUnrestricted =>
        ((PowerManager)Platform.AppContext.GetSystemService(Context.PowerService)!).IsIgnoringBatteryOptimizations(Platform.AppContext.PackageName);
}
