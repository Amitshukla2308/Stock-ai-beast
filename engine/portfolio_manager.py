"""
Portfolio Manager for LiveEngine
Tracks capital, positions, PnL, and generates performance reports
"""
import json
from datetime import datetime
from data.database import get_connection

# Instrument Constants
LOT_SIZES = {
    "BANKNIFTY": 15,
    "NIFTY": 25,
    "FINNIFTY": 25
}
OPTION_PREMIUM_MULTIPLIER = 0.6  # Avg factor to convert index points to option premium

class PortfolioManager:
    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {symbol: {'qty': int, 'avg_price': float, 'side': str}}
        self.trades = []  # All closed trades
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        
        print(f"💼 Portfolio Initialized: ₹{initial_capital:,.0f}")
    
    def process_fill(self, order_type, symbol, quantity, price, side):
        """
        Process filled order (BUY/SELL)
        order_type: 'ENTRY' or 'EXIT'
        """
        if order_type == 'ENTRY':
            # Opening position - calculate premium cost
            lot_size = LOT_SIZES.get(symbol, LOT_SIZES["BANKNIFTY"])
            cost = price * OPTION_PREMIUM_MULTIPLIER * lot_size * quantity
            if self.cash < cost:
                return {'status': 'REJECTED', 'reason': 'Insufficient Capital'}
            
            self.cash -= cost
            self.positions[symbol] = {
                'qty': quantity,
                'entry_price': price,  # Store index price for PnL calc
                'side': side,
                'entry_time': datetime.now()
            }
            print(f"   💼 Position Opened: {symbol} | Cash Remaining: ₹{self.cash:,.0f}")
            return {'status': 'FILLED'}
        
        elif order_type == 'EXIT':
            # Closing position
            if symbol not in self.positions:
                return {'status': 'REJECTED', 'reason': 'No open position'}
            
            pos = self.positions[symbol]
            
            # Convert index points to option premium
            # Entry/exit prices are Bank Nifty index values, not actual option premiums
            point_movement = (price - pos['entry_price']) if pos['side'] == 'CALL' else (pos['entry_price'] - price)
            
            # Premium PnL = Point Movement × Premium Multiplier × Lot Size × Quantity
            lot_size = LOT_SIZES.get(symbol, LOT_SIZES["BANKNIFTY"])
            pnl = point_movement * OPTION_PREMIUM_MULTIPLIER * lot_size * quantity
            
            # Update cash (using premium-adjusted values)
            revenue = price * OPTION_PREMIUM_MULTIPLIER * lot_size * quantity
            self.cash += revenue
            
            self.total_pnl += pnl
            
            # Track win/loss
            if pnl > 0:
                self.winning_trades += 1
            elif pnl < 0:
                self.losing_trades += 1
            
            # Log trade
            trade_record = {
                **pos,
                'exit_price': price,
                'exit_time': datetime.now(),
                'pnl': pnl,
                'symbol': symbol,
                'qty': quantity
            }
            self.trades.append(trade_record)
            
            # Remove position
            del self.positions[symbol]
            
            print(f"   💼 Position Closed: {symbol} | PnL: ₹{pnl:+,.0f} | Total: ₹{self.total_pnl:+,.0f}")
            return {'status': 'FILLED', 'pnl': pnl}
    
    def get_summary(self):
        """Generate portfolio performance summary"""
        total_trades = len(self.trades)
        win_rate = (self.winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        current_value = self.cash + sum(
            pos['qty'] * pos['entry_price'] for pos in self.positions.values()
        )
        
        return {
            'initial_capital': self.initial_capital,
            'current_cash': self.cash,
            'current_value': current_value,
            'total_pnl': self.total_pnl,
            'pnl_pct': (self.total_pnl / self.initial_capital) * 100,
            'total_trades': total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': win_rate,
            'open_positions': len(self.positions)
        }
    
    def print_final_report(self):
        """Print detailed end-of-simulation report"""
        summary = self.get_summary()
        
        print("\n" + "="*60)
        print("📊 FINAL PERFORMANCE REPORT")
        print("="*60)
        print(f"Initial Capital:     ₹{summary['initial_capital']:>12,.0f}")
        print(f"Final Cash:          ₹{summary['current_cash']:>12,.0f}")
        print(f"Current Value:       ₹{summary['current_value']:>12,.0f}")
        print("-"*60)
        print(f"Total P&L:           ₹{summary['total_pnl']:>12,+.2f}")
        print(f"Return %:            {summary['pnl_pct']:>13.2f}%")
        print("-"*60)
        print(f"Total Trades:        {summary['total_trades']:>14}")
        print(f"Winners:             {summary['winning_trades']:>14}")
        print(f"Losers:              {summary['losing_trades']:>14}")
        print(f"Win Rate:            {summary['win_rate']:>13.1f}%")
        print(f"Open Positions:      {summary['open_positions']:>14}")
        print("="*60 + "\n")
        
        # Save to DB
        self._save_summary_to_db(summary)
        
        return summary
    
    def _save_summary_to_db(self, summary):
        """Save final summary to database"""
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_summary (
                timestamp TIMESTAMP,
                initial_capital FLOAT,
                final_cash FLOAT,
                final_value FLOAT,
                total_pnl FLOAT,
                return_pct FLOAT,
                total_trades INT,
                winning_trades INT,
                losing_trades INT,
                win_rate FLOAT
            )
        """)
        
        conn.execute("""
            INSERT INTO simulation_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            summary['initial_capital'],
            summary['current_cash'],
            summary['current_value'],
            summary['total_pnl'],
            summary['pnl_pct'],
            summary['total_trades'],
            summary['winning_trades'],
            summary['losing_trades'],
            summary['win_rate']
        ))
        conn.close()
        print("✅ Performance summary saved to database")
