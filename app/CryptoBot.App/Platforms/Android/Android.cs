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
