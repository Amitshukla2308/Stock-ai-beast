"""
Atlas 64D Feature Calculators - GPU (cuDF) Implementation
Offloads Group I-V calculations to VRAM for massive backtest speedup.
"""
import cudf
import cupy as cp
import numpy as np
import pandas as pd

class AtlasFeaturesGPU:
    
    @staticmethod
    def calculate_all(df_cpu):
        """
        Master wrapper to calc all 64 dims on GPU.
        Input: pandas DataFrame
        Output: pandas DataFrame (for compatibility with current pipeline)
        """
        # 1. Robust Type Cleaning for cuDF
        df_clean = df_cpu.copy()
        
        for col in df_clean.columns:
            dtype = df_clean[col].dtype
            
            # A. Handle Datetime/Timezone columns
            if pd.api.types.is_datetime64_any_dtype(dtype):
                df_clean[col] = df_clean[col].dt.tz_localize(None)
            
            # B. Handle "Object" columns that are likely dates or strings
            elif dtype == 'object':
                # If it's a timestamp string or object, try converting to datetime
                if 'time' in col.lower() or 'date' in col.lower() or 'ts' in col.lower():
                    try:
                        df_clean[col] = pd.to_datetime(df_clean[col]).dt.tz_localize(None)
                    except:
                        # If conversion fails, it's just a string, cuDF doesn't need it for math
                        df_clean.drop(columns=[col], inplace=True)
                else:
                    # Generic object (categorical/string) - cuDF math can't use it
                    df_clean.drop(columns=[col], inplace=True)

        # 2. Move to GPU
        gdf = cudf.from_pandas(df_clean)
        
        # 2. Compute Groups
        gdf = AtlasFeaturesGPU._calculate_physics(gdf)     # X01-X10
        gdf = AtlasFeaturesGPU._calculate_statistics(gdf)  # X11-X20
        gdf = AtlasFeaturesGPU._calculate_momentum(gdf)    # X21-X35
        gdf = AtlasFeaturesGPU._calculate_volatility(gdf)  # X36-X45
        gdf = AtlasFeaturesGPU._calculate_volume(gdf)      # X46-X55
        gdf = AtlasFeaturesGPU._calculate_external(gdf)    # X56-X64
        
        # 3. Pull back to CPU
        return gdf.to_pandas()

    @staticmethod
    def _calculate_physics(gdf):
        # ATR logic on GPU
        h_l = gdf['high'] - gdf['low']
        h_pc = (gdf['high'] - gdf['close'].shift(1)).abs()
        l_pc = (gdf['low'] - gdf['close'].shift(1)).abs()
        tr = cudf.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        gdf['atr'] = tr.rolling(14).mean()
        
        atr = gdf['atr'].fillna(1.0).replace(0, 1.0)
        close = gdf['close']
        
        # X01-X03: Distances
        gdf['X01_Pivot_Dist'] = (close - gdf['pivot']) / atr if 'pivot' in gdf.columns else 0.0
        gdf['X02_VWAP_Dist'] = (close - gdf['vwap']) / atr if 'vwap' in gdf.columns else 0.0
        gdf['X03_DayOpen_Bias'] = (close - gdf['daily_open']) / atr if 'daily_open' in gdf.columns else 0.0
        
        # X04: Momentum 1H
        gdf['X04_Mom_1H'] = (close - close.shift(12)) / atr
        
        # X05: Price Pressure
        range_hl = gdf['high'] - gdf['low']
        gdf['X05_Price_Pressure'] = ((close - gdf['low']) - (gdf['high'] - close)) / range_hl.replace(0, 1.0)
        
        # X06: Squeeze
        atr_20 = gdf['atr'].rolling(20).mean()
        gdf['X06_Squeeze'] = cp.log(atr.values / atr_20.fillna(1.0).values)
        
        # X07: Efficiency
        net_move = (close - close.shift(12)).abs()
        gross_move = (close - close.shift(1)).abs().rolling(12).sum()
        gdf['X07_Efficiency'] = net_move / gross_move.replace(0, 1.0)
        
        # X08: Internal Strength
        is_green = (close > gdf['open']).astype(int)
        green_count = is_green.rolling(12).sum()
        gdf['X08_Internal_Strength'] = (green_count / 12.0 - 0.5) * 2.0
        
        # X09: Vol Trend
        atr_50 = gdf['atr'].rolling(50).mean()
        gdf['X09_Vol_Trend'] = (atr_20 - atr_50) / atr_50.replace(0, 1.0)
        
        # X10: Acceleration
        vel = close - close.shift(3)
        acc = vel - vel.shift(3)
        gdf['X10_Acceleration'] = acc / atr
        
        return gdf

    @staticmethod
    def _calculate_statistics(gdf):
        close = gdf['close']
        atr = gdf['atr'].fillna(1.0).replace(0, 1.0)
        
        # X11: Log Returns
        gdf['X11_Log_Ret'] = cp.log(close.values / close.shift(1).bfill().values)
        
        # X12-X14: Distribution (Algebraic Moments for Skew/Kurt)
        n = 20
        roll = close.rolling(n)
        mean = roll.mean()
        std = roll.std().replace(0, 1.0)
        
        # X12: Z-Score
        gdf['X12_ZScore'] = (close - mean) / std
        
        # X13: Skewness (Algebraic Proxy: 3rd Moment)
        # skew = mean((x - mu)^3) / sigma^3
        # (x-mu)^3 = x^3 - 3mu x^2 + 3mu^2 x - mu^3
        sum_x = roll.sum()
        sum_x2 = (close**2).rolling(n).sum()
        sum_x3 = (close**3).rolling(n).sum()
        
        m3 = (sum_x3 - 3*mean*sum_x2 + 3*(mean**2)*sum_x - n*(mean**3)) / n
        gdf['X13_Skew'] = m3 / (std**3)
        
        # X14: Kurtosis (Algebraic Proxy: 4th Moment)
        # kurt = mean((x - mu)^4) / sigma^4 - 3
        sum_x4 = (close**4).rolling(n).sum()
        m4 = (sum_x4 - 4*mean*sum_x3 + 6*(mean**2)*sum_x2 - 4*(mean**3)*sum_x + n*(mean**4)) / n
        gdf['X14_Kurt'] = m4 / (std**4) - 3.0
        
        # X15: Chop Index
        r_max = gdf['high'].rolling(14).max()
        r_min = gdf['low'].rolling(14).min()
        r_sum_tr = gdf['atr'].rolling(14).sum() * 14
        range_hl = r_max - r_min
        gdf['X15_Chop_Index'] = cp.log10(r_sum_tr.values / range_hl.replace(0, 1.0).values) / cp.log10(14)
        
        # X16: Autocorr (Correlation with Lag-1)
        # Algebraic Corr: [sum(xy) - n*mx*my] / [(n-1)*sx*sy]
        c_p = close
        c_l = close.shift(1).bfill()
        sum_cl = c_l.rolling(n).sum()
        sum_cpcl = (c_p * c_l).rolling(n).sum()
        std_l = c_l.rolling(n).std().replace(0, 1.0)
        
        # We reuse mean and std from c_p (X12-X14 section)
        gdf['X16_Autocorr'] = (sum_cpcl - n*mean*(sum_cl/n)) / ((n-1)*std*std_l)
        
        # X17: Bar Density
        gdf['X17_Bar_Density'] = (gdf['high'] - gdf['low']) / atr
        
        # X18: IQR Norm (Proxy: 1.35 * Sigma for normal dist parity)
        gdf['X18_IQR_Norm'] = (1.3489 * roll.std()) / atr
        
        # X19: MAD Norm (Proxy: 0.67 * Sigma)
        gdf['X19_MAD_Norm'] = (0.6745 * roll.std()) / atr
        
        # X20: Entropy
        gdf['X20_Entropy'] = 0.0
        
        return gdf

    @staticmethod
    def _calculate_momentum(gdf):
        close = gdf['close']
        high = gdf['high']
        low = gdf['low']
        atr = gdf['atr'].fillna(1.0).replace(0, 1.0)
        
        # X21: ROC
        gdf['X21_ROC'] = close.pct_change(12) * 100
        
        # X22: MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        gdf['X22_MACD_Hist'] = (macd - signal) / atr
        
        # X23-X25: Oscillators
        tp = (high + low + close) / 3
        sma = tp.rolling(20).mean()
        mad = (tp - sma).abs().rolling(20).mean()
        gdf['X23_CCI'] = (tp - sma) / (0.015 * mad.replace(0, 1.0))
        
        # CMO
        diff = close.diff()
        pos = diff.clip(lower=0).rolling(14).sum()
        neg = (-diff.clip(upper=0)).rolling(14).sum()
        gdf['X24_CMO'] = (pos - neg) / (pos + neg).replace(0, 1.0)
        
        # Stoch (X25)
        ll = low.rolling(14).min()
        hh = high.rolling(14).max()
        gdf['X25_StochK'] = (close - ll) / (hh - ll).replace(0, 1.0)
        
        # X26: AO
        mp = (high + low) / 2
        gdf['X26_AO'] = (mp.rolling(5).mean() - mp.rolling(34).mean()) / atr
        
        # X27-X35: Momentum Tail
        gdf['X27_TRIX'] = close.ewm(span=12).mean().ewm(span=12).mean().ewm(span=12).mean().pct_change() * 100
        gdf['X28_KST_Proxy'] = close.pct_change(10) + close.pct_change(15)*2 + close.pct_change(20)*3 + close.pct_change(30)*4
        
        # X29-X30: ADX Logic
        up = high.diff().fillna(0)
        down = (-low.diff()).fillna(0)
        pdm = ((up > down) & (up > 0)).astype(cp.float32) * up
        mdm = ((down > up) & (down > 0)).astype(cp.float32) * down
        
        pdm_roll = pdm.rolling(14).mean()
        mdm_roll = mdm.rolling(14).mean()
        
        pdi = pdm_roll / atr
        mdi = mdm_roll / atr
        dx = (pdi - mdi).abs() / (pdi + mdi).replace(0, 1.0)
        gdf['X29_ADX'] = dx.rolling(14).mean()
        gdf['X30_DI_Spread'] = pdi - mdi
        
        gdf['X31_ROC_Accel'] = gdf['X21_ROC'].diff()
        gdf['X32_WillR'] = (gdf['X25_StochK'] - 1) * 100
        gdf['X33_StochD'] = gdf['X25_StochK'].rolling(3).mean()
        gdf['X34_EMA200_Dist'] = (close - close.ewm(span=200).mean()) / atr
        gdf['X35_Mom_Div'] = gdf['X21_ROC'] - gdf['X21_ROC'].rolling(10).mean()
        
        return gdf

    @staticmethod
    def _calculate_volatility(gdf):
        close = gdf['close']
        high = gdf['high']
        low = gdf['low']
        atr = gdf['atr'].fillna(1.0).replace(0, 1.0)
        
        # X36: ATR Ratio
        gdf['X36_ATR_Ratio'] = atr / atr.rolling(50).mean().replace(0, 1.0)
        
        # X37-X38: Advanced Vol
        log_hl = cp.log(high.values / low.replace(0, 0.01).values)
        log_co = cp.log(close.values / gdf['open'].replace(0, 0.01).values)
        gk = 0.5 * log_hl**2 - (2*cp.log(2) - 1) * log_co**2
        gdf['X37_GK_Vol'] = cudf.Series(gk).rolling(14).mean()
        
        park = (1.0 / (4 * cp.log(2))) * log_hl**2
        gdf['X38_Park_Vol'] = cudf.Series(park).rolling(14).mean()
        
        # X39-X40: BB
        std = close.rolling(20).std()
        mid = close.rolling(20).mean()
        upper = mid + 2*std
        lower = mid - 2*std
        gdf['X39_BB_Width'] = (upper - lower) / mid.replace(0, 1.0)
        gdf['X40_BB_PctB'] = (close - lower) / (upper - lower).replace(0, 1.0)
        
        # X41-X45: Vol Tail
        gdf['X41_Kelt_Pos'] = (close - close.ewm(span=20).mean()) / (2 * atr).replace(0, 1.0)
        gdf['X42_Donch_Pos'] = (close - low.rolling(20).min()) / (high.rolling(20).max() - low.rolling(20).min()).replace(0, 1.0)
        
        ret = cp.log(close.values / close.shift(1).bfill().values)
        hv10 = cudf.Series(ret).rolling(10).std()
        hv100 = cudf.Series(ret).rolling(100).std()
        gdf['X43_VRP_Proxy'] = hv10 / hv100.replace(0, 1.0)
        
        roll_max = close.rolling(14).max()
        drawdown = (close - roll_max) / roll_max * 100
        gdf['X44_Ulcer_Idx'] = cp.sqrt((drawdown**2).rolling(14).mean().values)
        
        hl_ema = (high - low).ewm(span=10).mean()
        gdf['X45_Chaikin_Vol'] = hl_ema.pct_change(10) * 100
        
        return gdf

    @staticmethod
    def _calculate_volume(gdf):
        vol = gdf['volume'].replace(0, 1.0)
        close = gdf['close']
        high = gdf['high']
        low = gdf['low']
        atr = gdf['atr'].fillna(1.0).replace(0, 1.0)
        
        # X46: MFI
        tp = (high + low + close) / 3
        raw_flow = tp * vol
        flow_sign = cp.sign(tp.diff().fillna(0).values)
        pos_flow = cudf.Series(raw_flow.values * (flow_sign > 0).astype(int)).rolling(14).sum()
        neg_flow = cudf.Series(raw_flow.values * (flow_sign < 0).astype(int)).rolling(14).sum()
        gdf['X46_MFI'] = 100 - (100 / (1 + pos_flow / neg_flow.replace(0, 1.0)))
        
        # X47: OBV Slope
        obv = (cp.sign(close.diff().fillna(0).values) * vol.values).cumsum()
        gdf['X47_OBV_Slope'] = (cudf.Series(obv).diff(20) / (vol.rolling(20).mean() * 20)).replace(0, 1.0)
        
        # X48: CMF
        mfm = ((close - low) - (high - close)) / (high - low).replace(0, 1.0)
        gdf['X48_CMF'] = (mfm * vol).rolling(20).sum() / vol.rolling(20).sum().replace(0, 1.0)
        
        # X49: Vol ZScore
        gdf['X49_Vol_ZScore'] = (vol - vol.rolling(20).mean()) / vol.rolling(20).std().replace(0, 1.0)
        
        # X50-X55: Volume Tail
        fi_raw = vol * close.diff()
        gdf['X50_Force_Idx'] = fi_raw.ewm(span=13).mean() / (atr * vol.rolling(20).mean()).replace(0, 1.0)
        dist = ((high + low) / 2).diff()
        box_ratio = vol / (high - low).replace(0, 1.0)
        gdf['X51_EOM'] = (dist / box_ratio.replace(0, 1.0)).rolling(14).mean() * 1e6
        gdf['X52_VWMA_Diff'] = ((close * vol).rolling(20).sum() / vol.rolling(20).sum().replace(0, 1.0) - close.rolling(20).mean()) / atr
        gdf['X53_ADL_Flow'] = mfm
        gdf['X54_Vol_ROC'] = vol.pct_change(12) * 100
        gdf['X55_V_Trend'] = vol.ewm(span=12).mean().pct_change(5) * 100
        
        return gdf

    @staticmethod
    def _calculate_external(gdf):
        # In BacktestMode, 'vix' and 'daily_open' are added to the pre-process DF
        # Group VI (External Attributes)
        vix = gdf['vix'] if 'vix' in gdf.columns else cudf.Series([12.0] * len(gdf))
        atr = gdf['atr'].fillna(1.0).replace(0, 1.0)
        
        gdf['X56_VIX_Level'] = vix
        gdf['X57_VIX_Delta'] = vix.diff()
        v_roll = vix.rolling(50)
        gdf['X58_VIX_ZScore'] = (vix - v_roll.mean()) / v_roll.std().replace(0, 1.0)
        
        # X59: Nifty-VIX Corr (Algebraic)
        n_corr = 20
        c_p = gdf['close']
        v_p = vix
        
        c_mean = c_p.rolling(n_corr).mean()
        c_std = c_p.rolling(n_corr).std().replace(0, 1.0)
        v_mean = v_p.rolling(n_corr).mean()
        v_std = v_p.rolling(n_corr).std().replace(0, 1.0)
        
        sum_cv = (c_p * v_p).rolling(n_corr).sum()
        
        gdf['X59_NIFTY_VIX_Corr'] = (sum_cv - n_corr*c_mean*v_mean) / ((n_corr-1)*c_std*v_std)
        gdf['X60_Expiry_Prox'] = 0.0 # Static until Option Chain integrated
        
        # X61: Session Progress
        if 'timestamp' in gdf.columns:
            ts = gdf['timestamp'].dt
            hours = ts.hour + ts.minute / 60.0
            gdf['X61_Session_Prog'] = (hours - 9.25) / 6.25
        else:
            gdf['X61_Session_Prog'] = 0.5
            
        gdf['X62_Gap_Size'] = (gdf['open'] - gdf['close'].shift(1)) / atr
        color = cp.sign((gdf['close'] - gdf['open']).values)
        gdf['X63_Color_Persist'] = cudf.Series(color).rolling(5).sum()
        gdf['X64_Range_Ratio'] = (gdf['high'] - gdf['low']) / atr
        
        return gdf
