namespace CryptoBot.Core;

/// <summary>Chỉ báo tính giống hệt pandas (ewm adjust=False, min_periods), kể cả thứ tự phép tính.</summary>
public static class Indicators
{
    /// <summary>pandas Series.ewm(com=..., adjust=False, min_periods=...).mean() — chép từ pandas/_libs/window/aggregations.pyx.</summary>
    static double[] EwmMean(double[] vals, double com, int minPeriods)
    {
        int n = vals.Length;
        var output = new double[n];
        if (n == 0) return output;
        double alpha = 1.0 / (1.0 + com);
        double oldWtFactor = 1.0 - alpha;
        double newWt = alpha; // adjust=False
        double weighted = vals[0];
        bool isObs = !double.IsNaN(weighted);
        int nobs = isObs ? 1 : 0;
        output[0] = nobs >= minPeriods ? weighted : double.NaN;
        double oldWt = 1.0;
        for (int i = 1; i < n; i++)
        {
            double cur = vals[i];
            isObs = !double.IsNaN(cur);
            nobs += isObs ? 1 : 0;
            if (!double.IsNaN(weighted))
            {
                // ignore_na=False
                oldWt *= oldWtFactor;
                if (isObs)
                {
                    if (weighted != cur)
                    {
                        weighted = oldWt * weighted + newWt * cur;
                        weighted /= oldWt + newWt;
                    }
                    oldWt = 1.0;
                }
            }
            else if (isObs)
            {
                weighted = cur;
            }
            output[i] = nobs >= minPeriods ? weighted : double.NaN;
        }
        return output;
    }

    /// <summary>s.ewm(span=period, adjust=False, min_periods=period).mean()</summary>
    public static double[] Ema(double[] close, int period) => EwmMean(close, (period - 1) / 2.0, period);

    /// <summary>ewm(alpha=1/period, ...) — pandas đổi alpha sang com = 1/alpha - 1 rồi tính lại alpha.</summary>
    static double[] Wilder(double[] x, int period)
    {
        double alpha = 1.0 / period;
        return EwmMean(x, 1.0 / alpha - 1.0, period);
    }

    public static double[] TrueRange(double[] high, double[] low, double[] close)
    {
        int n = close.Length;
        var tr = new double[n];
        for (int i = 0; i < n; i++)
        {
            double hl = high[i] - low[i];
            if (i == 0) { tr[i] = hl; continue; }
            double pc = close[i - 1];
            tr[i] = Math.Max(hl, Math.Max(Math.Abs(high[i] - pc), Math.Abs(low[i] - pc)));
        }
        return tr;
    }

    public static double[] Atr(double[] high, double[] low, double[] close, int period = 14) =>
        Wilder(TrueRange(high, low, close), period);
}
