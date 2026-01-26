"""
Atlas 64D Feature Calculators
Group I: Core Physics (Dimensions 1-10)
Group II: Statistical (11-20)
Group III: Momentum (21-35)
Group IV: Volatility (36-45)
Group V: Volume (46-55)
Group VI: External (56-64)
"""
import numpy as np
import pandas as pd
from scipy.stats import entropy

class AtlasFeatures:
    
    @staticmethod
    def calculate_core_physics(df, context_df=None):
        """
        Calculates Dimensions 1-10 (Core Physics).
        Assumes df has ['close', 'open', 'high', 'low', 'volume', 'atr', 'pivot', 'vwap', 'daily_open']
        """
        # Ensure ATR is present (it's the denominator for everything)
        if 'atr' not in df.columns:
            # Simple ATR calculation if missing
            h_l = df['high'] - df['low']
            h_pc = (df['high'] - df['close'].shift(1)).abs()
            l_pc = (df['low'] - df['close'].shift(1)).abs()
            tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
            df['atr'] = tr.rolling(14).mean()
        
        atr = df['atr'].replace(0, 1.0) # Avoid div/0
        close = df['close']
        
        # 1. Pivot Distance
        # (Close - Pivot) / ATR
        # Feature: X01_Pivot_Dist
        if 'pivot' in df.columns:
            df['X01_Pivot_Dist'] = (close - df['pivot']) / atr
        else:
            df['X01_Pivot_Dist'] = 0.0
            
        # 2. VWAP Distance
        # (Close - VWAP) / ATR
        # Feature: X02_VWAP_Dist
        if 'vwap' in df.columns:
            df['X02_VWAP_Dist'] = (close - df['vwap']) / atr
        else:
            df['X02_VWAP_Dist'] = 0.0
            
        # 3. Daily Open Bias
        # (Close - DailyOpen) / ATR
        # Feature: X03_DayOpen_Bias
        if 'daily_open' in df.columns:
            df['X03_DayOpen_Bias'] = (close - df['daily_open']) / atr
        else:
            df['X03_DayOpen_Bias'] = 0.0
            
        # 4. Momentum (1hr)
        # (Close - Close_1hr) / ATR
        # Assuming 5m bars -> 1hr = 12 bars
        # Feature: X04_Mom_1H
        df['X04_Mom_1H'] = (close - close.shift(12)) / atr
        
        # 5. Price Pressure (Money Flow Multiplier / CLV)
        # ((C - L) - (H - C)) / (H - L)
        # Feature: X05_Price_Pressure
        range_hl = df['high'] - df['low']
        # Handle zero range
        mfm = ((close - df['low']) - (df['high'] - close)) / range_hl
        mfm = mfm.fillna(0.0) # Div by 0
        df['X05_Price_Pressure'] = mfm
        
        # 6. Squeeze Metric
        # log(ATR / ATR_20)
        # Feature: X06_Squeeze
        atr_20 = df['atr'].rolling(20).mean()
        df['X06_Squeeze'] = np.log(atr / atr_20.replace(0, 1.0))
        
        # 7. Efficiency Ratio (Kaufman)
        # Net_Move / Gross_Move (over 12 bars/1hr)
        # Feature: X07_Efficiency
        n = 12
        net_move = (close - close.shift(n)).abs()
        gross_move = (close - close.shift(1)).abs().rolling(n).sum()
        er = net_move / gross_move
        df['X07_Efficiency'] = er.fillna(0.0)
        
        # 8. Internal Strength Proxy
        # Win/Loss Ratio of recent bars (12 bars)
        # Count Green vs Red? Or Sum of Gains vs Sum of Losses (RSI-like)?
        # Plan says: "Win/Loss ratio of recent bars"
        # Let's use: (Count_Green / n) - 0.5 * 2 => -1 to 1
        # Feature: X08_Internal_Strength
        is_green = (close > df['open']).astype(int)
        green_count = is_green.rolling(12).sum()
        df['X08_Internal_Strength'] = (green_count / 12.0 - 0.5) * 2.0
        
        # 9. Volatility Trend
        # (ATR_20 - ATR_50) / ATR_50
        # Feature: X09_Vol_Trend
        atr_50 = df['atr'].rolling(50).mean()
        df['X09_Vol_Trend'] = (atr_20 - atr_50) / atr_50.replace(0, 1.0)
        
        # 10. Acceleration
        # 2nd derivative of price change
        # (Vel_Now - Vel_Prev)
        # Vel = Close - Close_3
        # Feature: X10_Acceleration
        vel = close - close.shift(3)
        acc = vel - vel.shift(3)
        df['X10_Acceleration'] = acc / atr
        
        return df

    @staticmethod
    def calculate_statistics(df):
        """
        Calculates Dimensions 11-20 (Statistical).
        """
        close = df['close']
        returns = np.log(close / close.shift(1))
        
        # 11. Log Returns
        # Feature: X11_Log_Ret
        df['X11_Log_Ret'] = returns
        
        # 12. Rolling Z-Score (20 period)
        # Feature: X12_ZScore
        roll = close.rolling(20)
        df['X12_ZScore'] = (close - roll.mean()) / roll.std()
        
        # 13. Rolling Skewness (20 period)
        # Feature: X13_Skew
        # Note: Requires min periods
        df['X13_Skew'] = roll.skew()
        
        # 14. Rolling Kurtosis (20 period)
        # Feature: X14_Kurt
        df['X14_Kurt'] = roll.kurt()
        
        # 15. Hurst Exponent (Approx via RS analysis or simplified proxy)
        # True Hurst is slow. Using simple Fractal Dimension proxy or VR
        # Simplified proxy: log(High-Low range / ATR) ? 
        # Better: use a Fractal Efficiency check or Volatility Ratio
        # For speed: Volatility Ratio (parkinson / close-to-close)
        # Feature: X15_Hurst_Proxy
        # Actually, let's stick to the Plan's intent: Trend Persistence.
        # VR = Variance(n) / (n * Variance(1))
        # Feature: X15_Hurst_Proxy (VR)
        ret_var_n = close.diff(10).var()
        ret_var_1 = close.diff(1).var()
        # Rolling calc is expensive. Let's use Efficiency Ratio as fractal proxy?
        # Let's use: (Rolling Max - Min) / Sum(Abs Diff)
        # This is Choppiness Index inverted.
        r_max = df['high'].rolling(14).max()
        r_min = df['low'].rolling(14).min()
        r_sum_tr = df['atr'].rolling(14).sum() * 14 # Approx sum TR
        # Chop = log10(Sum TR / Range) / log10(n)
        # Hurst ~ 0.5 + (0.5 - Chop/100) ? 
        # Let's just calculate Choppiness Index (0-100)
        # X15: 0=Trend, 100=Chop
        chop_num = r_sum_tr
        chop_den = (r_max - r_min)
        df['X15_Chop_Index'] = np.where(chop_den == 0, 0, np.log10(chop_num / chop_den) / np.log10(14))
        
        # 16. Autocorrelation (Lag 1)
        # Feature: X16_Autocorr
        # Rolling 20 autocorrelation
        df['X16_Autocorr'] = returns.rolling(20).apply(lambda x: x.autocorr(lag=1), raw=False)
        
        # 17. Price Density
        # Touches in range.
        # Approx: (High - Low) / ATR (Bar Magnitude)
        # Feature: X17_Bar_Density
        df['X17_Bar_Density'] = (df['high'] - df['low']) / df['atr']
        
        # 18. IQR (Normalized by ATR)
        # Feature: X18_IQR_Norm
        q75 = roll.quantile(0.75)
        q25 = roll.quantile(0.25)
        df['X18_IQR_Norm'] = (q75 - q25) / df['atr']
        
        # 19. MAD (Median Abs Deviation)
        # Feature: X19_MAD_Norm
        med = roll.median()
        mad = (close - med).abs().rolling(20).median()
        df['X19_MAD_Norm'] = mad / df['atr']
        
        # 20. Entropy
        # Feature: X20_Entropy
        # Rolling entropy of discretized returns
        def calc_ent(x):
            counts, _ = np.histogram(x, bins=5)
            return entropy(counts + 1e-9)
        
        df['X20_Entropy'] = returns.rolling(20).apply(calc_ent, raw=True)
        
        return df

    @staticmethod
    def calculate_momentum(df):
        """
        Calculates Dimensions 21-35 (Momentum).
        """
        close = df['close']
        high = df['high']
        low = df['low']
        
        # 21. ROC (Rate of Change)
        df['X21_ROC'] = close.pct_change(12) * 100
        
        # 22. MACD Histogram (Proxy)
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        df['X22_MACD_Hist'] = (macd - signal) / df['atr'] # Normalized
        
        # 23. CCI
        tp = (high + low + close) / 3
        sma = tp.rolling(20).mean()
        mad = (tp - sma).abs().rolling(20).mean()
        df['X23_CCI'] = (tp - sma) / (0.015 * mad)
        
        # 24. CMO (Chande Momentum)
        # (Su - Sd) / (Su + Sd)
        diff = close.diff()
        pos = diff.where(diff > 0, 0).rolling(14).sum()
        neg = -diff.where(diff < 0, 0).rolling(14).sum()
        df['X24_CMO'] = (pos - neg) / (pos + neg)
        
        # 25. SMI (Stochastic Momentum) - Simplified as %K
        # (C - Ln) / (Hn - Ln)
        ll = low.rolling(14).min()
        hh = high.rolling(14).max()
        df['X25_StochK'] = (close - ll) / (hh - ll)
        
        # 26. Awesome Oscillator
        mp = (high + low) / 2
        ao = mp.rolling(5).mean() - mp.rolling(34).mean()
        df['X26_AO'] = ao / df['atr']
        
        # 27. TRIX (Proxy: Rate of Change of EMA)
        # True TRIX is Triple EMA ROC. 
        e1 = close.ewm(span=12).mean()
        e2 = e1.ewm(span=12).mean()
        e3 = e2.ewm(span=12).mean()
        df['X27_TRIX'] = e3.pct_change() * 100
        
        # 28. KST (Proxy: Sum of ROCs)
        r1 = close.pct_change(10)
        r2 = close.pct_change(15)
        r3 = close.pct_change(20)
        r4 = close.pct_change(30)
        df['X28_KST_Proxy'] = (r1 + r2*2 + r3*3 + r4*4)
        
        # 29. ADX Strength
        # Complex to calc manually vectorised efficiently.
        # Proxy: rolling mean of abs(high-low) / atr? No.
        # Let's use High-Low correlation with ATR?
        # Let's use PDI/MDI logic simplified.
        up = high.diff()
        down = -low.diff()
        pdm = np.where((up > down) & (up > 0), up, 0)
        mdm = np.where((down > up) & (down > 0), down, 0)
        
        # Need to roll this...
        pdm_roll = pd.Series(pdm).rolling(14).mean()
        mdm_roll = pd.Series(mdm).rolling(14).mean()
        atr = df['atr']
        
        pdi = pdm_roll / atr
        mdi = mdm_roll / atr
        dx = (pdi - mdi).abs() / (pdi + mdi)
        df['X29_ADX'] = dx.rolling(14).mean()
        
        # 30. DI Spread
        df['X30_DI_Spread'] = pdi - mdi
        
        # 31. Velocity Change (Acceleration)
        # Already X10? 
        # Plan says: "Acceleration of price movement."
        # Keep consistent. Use ROC change.
        df['X31_ROC_Accel'] = df['X21_ROC'].diff()
        
        # 32. Williams %R
        # Similar to Stoch, but (Hn - C) / (Hn - Ln) * -100
        # We calculated StochK (X25). W%R = (X25 - 1) * 100
        df['X32_WillR'] = (df['X25_StochK'] - 1) * 100
        
        # 33. Stochastic %D (SMA of %K)
        df['X33_StochD'] = df['X25_StochK'].rolling(3).mean()
        
        # 34. Price Stretch (Dist from EMA 200)
        ema200 = close.ewm(span=200).mean()
        df['X34_EMA200_Dist'] = (close - ema200) / df['atr']
        
        # 35. Momentum Divergence
        # ROC of Price vs ROC of RSI?
        # Let's use ROC(Price) - ROC(SmoothedPrice)
        df['X35_Mom_Div'] = df['X21_ROC'] - df['X21_ROC'].rolling(10).mean()
        
        return df

    @staticmethod
    def calculate_volatility(df):
        """
        Calculates Dimensions 36-45 (Volatility & Risk).
        """
        close = df['close']
        high = df['high']
        low = df['low']
        atr = df['atr']
        
        # 36. ATR Ratio
        # ATR / ATR(50)
        df['X36_ATR_Ratio'] = atr / atr.rolling(50).mean().replace(0, 1.0)
        
        # 37. Garman-Klass Volatility (proxy)
        # 0.5 * ln(H/L)^2 - (2ln2 - 1) * ln(C/O)^2
        # Feature: X37_GK_Vol
        log_hl = np.log(high / low.replace(0, 0.01))
        log_co = np.log(close / df['open'].replace(0, 0.01))
        gk = 0.5 * log_hl**2 - (2*np.log(2) - 1) * log_co**2
        df['X37_GK_Vol'] = gk.rolling(14).mean()
        
        # 38. Parkinson Volatility
        # 1 / (4ln2) * ln(H/L)^2
        # Feature: X38_Park_Vol
        park = (1.0 / (4 * np.log(2))) * log_hl**2
        df['X38_Park_Vol'] = park.rolling(14).mean()
        
        # 39. BB Width
        # (Upper - Lower) / Mid
        std = close.rolling(20).std()
        mid = close.rolling(20).mean()
        upper = mid + 2*std
        lower = mid - 2*std
        df['X39_BB_Width'] = (upper - lower) / mid.replace(0, 1.0)
        
        # 40. BB %B
        # (Price - Lower) / (Upper - Lower)
        df['X40_BB_PctB'] = (close - lower) / (upper - lower).replace(0, 1.0)
        
        # 41. Keltner Channel Position
        # (Price - EMA20) / (2 * ATR)
        ema20 = close.ewm(span=20).mean()
        df['X41_Kelt_Pos'] = (close - ema20) / (2 * atr).replace(0, 1.0)
        
        # 42. Donchian Position
        # (Price - LowN) / (HighN - LowN)
        dn_low = low.rolling(20).min()
        dn_high = high.rolling(20).max()
        df['X42_Donch_Pos'] = (close - dn_low) / (dn_high - dn_low).replace(0, 1.0)
        
        # 43. Volatility Risk Premium (VRP Proxy)
        # Realized Vol (Hist) vs Implied Vol (VIX)?
        # We don't have VIX in this method yet (it's in Group VI).
        # Let's use HV_Short vs HV_Long
        # HV(10) / HV(100)
        ret = np.log(close / close.shift(1))
        hv10 = ret.rolling(10).std()
        hv100 = ret.rolling(100).std()
        df['X43_VRP_Proxy'] = hv10 / hv100.replace(0, 1.0)
        
        # 44. Ulcer Index
        # Sqrt(Mean(Pct_Drawdown^2))
        roll_max = close.rolling(14).max()
        drawdown = (close - roll_max) / roll_max * 100
        sq_dd = drawdown ** 2
        df['X44_Ulcer_Idx'] = np.sqrt(sq_dd.rolling(14).mean())
        
        # 45. Chaikin Volatility
        # ROC(EMA(High-Low))
        hl_ema = (high - low).ewm(span=10).mean()
        df['X45_Chaikin_Vol'] = hl_ema.pct_change(10) * 100
        
        return df

    @staticmethod
    def calculate_volume(df):
        """
        Calculates Dimensions 46-55 (Volume & Conviction).
        """
        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']
        
        # Ensure vol is not zero
        vol = vol.replace(0, 1.0)
        
        # 46. MFI (Money Flow Index)
        # Volume-weighted RSI
        tp = (high + low + close) / 3
        raw_flow = tp * vol
        flow_sign = np.sign(tp.diff())
        pos_flow = (raw_flow * np.where(flow_sign > 0, 1, 0)).rolling(14).sum()
        neg_flow = (raw_flow * np.where(flow_sign < 0, 1, 0)).rolling(14).sum()
        mfi = 100 - (100 / (1 + pos_flow / neg_flow.replace(0, 1.0)))
        df['X46_MFI'] = mfi
        
        # 47. OBV Slope
        # Slope of OBV over 20 bars / AvgVolume
        obv = (np.sign(close.diff()) * vol).cumsum()
        obv_slope = obv.diff(20)
        avg_vol = vol.rolling(20).mean()
        df['X47_OBV_Slope'] = obv_slope / (avg_vol * 20).replace(0, 1.0)
        
        # 48. CMF (Chaikin Money Flow)
        # Sum(MFM * Vol) / Sum(Vol)
        mfm = ((close - low) - (high - close)) / (high - low).replace(0, 1.0)
        mf_vol = mfm * vol
        df['X48_CMF'] = mf_vol.rolling(20).sum() / vol.rolling(20).sum().replace(0, 1.0)
        
        # 49. Volume Z-Score
        # (Vol - Mean) / Std
        df['X49_Vol_ZScore'] = (vol - vol.rolling(20).mean()) / vol.rolling(20).std().replace(0, 1.0)
        
        # 50. Force Index
        # Vol * (Close - PrevClose)
        # Normalized by ATR * AvgVol to scale
        fi_raw = vol * close.diff()
        fi_ema = fi_raw.ewm(span=13).mean()
        # Normalize
        df['X50_Force_Idx'] = fi_ema / (df['atr'] * vol.rolling(20).mean()).replace(0, 1.0)
        
        # 51. Ease of Movement (EOM)
        # ((H+L)/2 - Prev) / (Vol / (H-L))
        dist = ((high + low) / 2).diff()
        box_ratio = vol / (high - low).replace(0, 1.0)
        eom = dist / box_ratio.replace(0, 1.0)
        df['X51_EOM'] = eom.rolling(14).mean() * 1e6 # Scale up
        
        # 52. VWMA-SMA Spread
        vwma = (close * vol).rolling(20).sum() / vol.rolling(20).sum().replace(0, 1.0)
        sma = close.rolling(20).mean()
        df['X52_VWMA_Diff'] = (vwma - sma) / df['atr']
        
        # 53. ADL (Accumulation Distribution Line)
        # MFM * Vol + PrevADL (Already used logic in CMF, but raw line)
        # Use simple MFM as per previous plan adjustment or raw ADL slope?
        # Plan says: "Volume flow relative to candle close."
        # Feature: X53_ADL_Flow - Use MFM directly for simplicity here
        df['X53_ADL_Flow'] = mfm 
        
        # 54. Volume ROC
        df['X54_Vol_ROC'] = vol.pct_change(12) * 100
        
        # 55. V-ROC Momentum (Accel of Volume)
        # ROC of Trend of Volume
        df['X55_V_Trend'] = vol.ewm(span=12).mean().pct_change(5) * 100
        
        return df

    @staticmethod
    def calculate_external(df):
        """
        Calculates Dimensions 56-64 (External & Structural).
        Assumes df has ['vix', 'date', 'time'] or passed in context?
        We will rely on whatever column we have. If missing, 0.
        """
        # Close/Open might be needed for gaps
        
        # 56. India VIX Level
        if 'vix' in df.columns:
            df['X56_VIX_Level'] = df['vix']
        else:
            df['X56_VIX_Level'] = 12.0 # Default fallback
            
        # 57. VIX Delta
        if 'vix' in df.columns:
            df['X57_VIX_Delta'] = df['vix'].diff()
        else:
            df['X57_VIX_Delta'] = 0.0
            
        # 58. VIX Z-Score
        if 'vix' in df.columns:
            v_roll = df['vix'].rolling(50)
            df['X58_VIX_ZScore'] = (df['vix'] - v_roll.mean()) / v_roll.std().replace(0, 1.0)
        else:
            df['X58_VIX_ZScore'] = 0.0
            
        # 59. Nifty-VIX Correlation
        if 'vix' in df.columns:
            df['X59_NIFTY_VIX_Corr'] = df['close'].rolling(20).corr(df['vix'])
        else:
            df['X59_NIFTY_VIX_Corr'] = 0.0
            
        # 60. Time-to-Expiry
        # Placeholder (Needs Option Chain context). 0 for now.
        df['X60_Expiry_Prox'] = 0.0
        
        # 61. Session Progress
        # Normalized time 0 to 1
        # timestamp presumed
        if 'timestamp' in df.columns:
            # Approx logic: (Hour - 9) / 6
            hours = df['timestamp'].dt.hour + df['timestamp'].dt.minute / 60.0
            df['X61_Session_Prog'] = (hours - 9.25) / 6.25 # 9:15 to 15:30 = 6.25h
        else:
             df['X61_Session_Prog'] = 0.5
        
        # 62. Opening Gap Size
        # (Open - PrevClose) / ATR
        df['X62_Gap_Size'] = (df['open'] - df['close'].shift(1)) / df['atr']
        
        # 63. Bar Color Persistence
        # 1 if G, -1 if R. Rolling Sum.
        color = np.sign(df['close'] - df['open'])
        df['X63_Color_Persist'] = color.rolling(5).sum()
        
        # 64. Range Expansion Ratio
        # (High-Low) / ATR
        df['X64_Range_Ratio'] = (df['high'] - df['low']) / df['atr']
        
        return df

    @classmethod
    def calculate_all(cls, df):
        """Master wrapper to calc all 64 dims"""
        df = cls.calculate_core_physics(df)
        df = cls.calculate_statistics(df)
        df = cls.calculate_momentum(df)
        df = cls.calculate_volatility(df)
        df = cls.calculate_volume(df)
        df = cls.calculate_external(df)
        return df

