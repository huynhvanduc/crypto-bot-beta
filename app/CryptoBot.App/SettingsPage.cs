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
