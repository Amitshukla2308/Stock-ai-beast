
import sqlite3
import json
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bootstrap_gen")

def generate_unbiased_bootstrap():
    db_path = Path("data/trading.db")
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    logger.info("Querying 2021-2024 trade outcomes for bootstrap...")
    # Query all trades (real + counterfactual) before 2025
    query = "SELECT regime, direction, pnl_points, mfe, mae FROM trades WHERE entry_time < '2025-01-01'"
    cursor = conn.execute(query)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        logger.warning("No historical trades found before 2025.")
        return

    # Grouping logic
    stats = {}
    for row in rows:
        regime = row['regime']
        if not regime or ':' not in regime:
            continue
            
        direction = row['direction']
        pnl = row['pnl_points'] if row['pnl_points'] is not None else 0.0
        mfe = row['mfe'] if row['mfe'] is not None else 0.0
        mae = row['mae'] if row['mae'] is not None else 0.0
        
        if regime not in stats:
            stats[regime] = {'LONG': [], 'SHORT': []}
        
        # In the context of NIFTY, 'CALL' is Long and 'PUT' is Short
        bias = 'LONG' if direction in ['CALL', 'BUY_CALL'] else 'SHORT'
        stats[regime][bias].append({
            'win': 1 if pnl > 0 else 0,
            'pnl': pnl,
            'mfe': mfe,
            'mae': mae
        })

    long_edges = []
    short_edges = []

    for regime, biases in stats.items():
        try:
            c15, c5 = map(int, regime.split(':'))
        except ValueError:
            continue

        # Process Long
        if biases['LONG']:
            count = len(biases['LONG'])
            win_rate = sum(t['win'] for t in biases['LONG']) / count
            long_edges.append({
                "cluster_15m": c15,
                "cluster_5m": c5,
                "count": count,
                "win_rate_long": win_rate,
                "avg_mfe_long": sum(t['mfe'] for t in biases['LONG']) / count,
                "avg_mae_long": sum(t['mae'] for t in biases['LONG']) / count,
                "expectancy_long": sum(t['pnl'] for t in biases['LONG']) / count
            })

        # Process Short
        if biases['SHORT']:
            count = len(biases['SHORT'])
            win_rate = sum(t['win'] for t in biases['SHORT']) / count
            short_edges.append({
                "cluster_15m": c15,
                "cluster_5m": c5,
                "count": count,
                "win_rate_short": win_rate,
                "avg_mfe_short": sum(t['mfe'] for t in biases['SHORT']) / count,
                "avg_mae_short": sum(t['mae'] for t in biases['SHORT']) / count,
                "expectancy_short": sum(t['pnl'] for t in biases['SHORT']) / count
            })

    output = {
        "metadata": {
            "total_rows": len(rows),
            "description": "Rigorous Unbiased Bootstrap 2021-2024",
            "timestamp": "2026-01-28"
        },
        "long_edges": long_edges,
        "short_edges": short_edges
    }

    output_path = Path("atlas/models/confluence_map_2021_2024.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=4)
        
    logger.info(f"Successfully generated {output_path} with {len(long_edges)} long and {len(short_edges)} short edges.")

if __name__ == "__main__":
    generate_unbiased_bootstrap()
