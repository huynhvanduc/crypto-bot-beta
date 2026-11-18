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
