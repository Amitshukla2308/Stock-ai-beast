
import unittest
import pandas as pd
from datetime import datetime, time
from counterfactual_truth import TradeReplayer

class TestTruthEngine(unittest.TestCase):
    def setUp(self):
        # Mock 1-min Candle Data
        # Scenario: Entry at 100. SL 90. Target 120. Direction CALL.
        # Candle 1: 10:00 -> Open 100, High 105, Low 98, Close 102 (Nothing)
        # Candle 2: 10:01 -> Open 102, High 115, Low 101, Close 110 (Nothing)
        # Candle 3: 10:02 -> Open 110, High 119, Low 89, Close 95 (SL HIT!)
        # Candle 4: 10:03 -> Open 95, High 125, Low 90, Close 120 (Target hit AFTER SL)
        
        data = [
            {'timestamp': datetime(2025, 1, 1, 10, 0), 'open': 100, 'high': 105, 'low': 98, 'close': 102},
            {'timestamp': datetime(2025, 1, 1, 10, 1), 'open': 102, 'high': 115, 'low': 101, 'close': 110},
            {'timestamp': datetime(2025, 1, 1, 10, 2), 'open': 110, 'high': 119, 'low': 89, 'close': 95},
            {'timestamp': datetime(2025, 1, 1, 10, 3), 'open': 95, 'high': 125, 'low': 90, 'close': 120}
        ]
        self.df = pd.DataFrame(data)
        self.replayer = TradeReplayer(self.df)

    def test_sl_first_touch(self):
        """Verify SL is hit before Target in Candle 3"""
        start_time = datetime(2025, 1, 1, 10, 0)
        ts, price, pnl, result = self.replayer.replay(100, 90, 120, 'CALL', start_time)
        
        self.assertEqual(result, "SL_HIT")
        self.assertEqual(price, 90)
        self.assertEqual(pnl, -10)
        self.assertEqual(ts, datetime(2025, 1, 1, 10, 2))

    def test_target_hit(self):
        """Verify Target Hit scenario"""
        # Modify scenario: Candle 3 hits Target instead
        # Candle 3: High 125, Low 95 (Target 120 Hit)
        self.df.loc[2, 'high'] = 125
        self.df.loc[2, 'low'] = 95
        
        start_time = datetime(2025, 1, 1, 10, 0)
        ts, price, pnl, result = self.replayer.replay(100, 90, 120, 'CALL', start_time)
        
        self.assertEqual(result, "TARGET_HIT")
        self.assertEqual(price, 120)
        self.assertEqual(pnl, 20)

    def test_eod_exit(self):
        """Verify Exit at Session End if no level hit"""
        # All candles move sideways
        self.df['high'] = 105
        self.df['low'] = 95
        self.df['close'] = 100
        # Add EOD candle
        self.df.loc[4] = {'timestamp': datetime(2025, 1, 1, 15, 30), 'open': 100, 'high': 100, 'low': 100, 'close': 101}
        
        # Need to re-init replayer with new data
        replayer = TradeReplayer(self.df)
        
        start_time = datetime(2025, 1, 1, 10, 0)
        # SL 90, TGT 120 (Neither hit in range 95-105)
        ts, price, pnl, result = replayer.replay(100, 90, 120, 'CALL', start_time)
        
        self.assertEqual(result, "EOD_EXIT")
        self.assertEqual(price, 101)

if __name__ == '__main__':
    unittest.main()
