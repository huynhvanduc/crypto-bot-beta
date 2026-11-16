namespace CryptoBot.Core;

public readonly record struct Bar(long OpenMs, double Open, double High, double Low, double Close, double Volume)
{
    public DateTimeOffset Time => DateTimeOffset.FromUnixTimeMilliseconds(OpenMs);
}

public static class DailyAggregator
{
    const long DayMs = 86_400_000;

    /// <summary>
    /// Gộp nến 1h thành nến ngày UTC, chỉ giữ ngày đủ 24 nến — giống bot.data.resample_ohlc(df, "1d").
    /// Đầu vào phải sắp theo thời gian, không trùng.
    /// </summary>
    public static List<Bar> Aggregate(IEnumerable<Bar> hourly)
    {
        var outBars = new List<Bar>();
        long day = long.MinValue;
        int count = 0;
        double o = 0, h = 0, l = 0, c = 0, v = 0;
        foreach (var b in hourly)
        {
            long d = Math.DivRem(b.OpenMs, DayMs, out long rem) * DayMs;
            if (rem < 0) d -= DayMs;
            if (d != day)
            {
                if (count == 24) outBars.Add(new Bar(day, o, h, l, c, v));
                day = d; count = 0;
                o = b.Open; h = b.High; l = b.Low; v = 0;
            }
            h = Math.Max(h, b.High);
            l = Math.Min(l, b.Low);
            c = b.Close;
            v += b.Volume;
            count++;
        }
        if (count == 24) outBars.Add(new Bar(day, o, h, l, c, v));
        return outBars;
    }
}
