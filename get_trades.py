import duckdb
import json
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Fetch trades for a specific backtest session.")
    parser.add_argument("session_id", help="The Session ID (e.g., BACKTEST_20260117_150509)")
    args = parser.parse_args()

    try:
        # Connect to DB (Read Only to prevent locks)
        conn = duckdb.connect('data/trading.db', read_only=True)
        
        # Parameterized query to prevent injection (though low risk here)
        query = "SELECT * FROM simulation_trades WHERE session_id = ? ORDER BY entry_time ASC"
        df = conn.execute(query, [args.session_id]).fetchdf()
        
        # Custom JSON serializer for datetime objects
        def default(o):
            if hasattr(o, 'isoformat'):
                return o.isoformat()
            return str(o)

        if df.empty:
            print(json.dumps({"message": f"No trades found for session: {args.session_id}"}, indent=2))
        else:
            # Convert to dict and dump
            records = df.to_dict(orient='records')
            print(json.dumps(records, default=default, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
    finally:
        try: conn.close()
        except: pass

if __name__ == "__main__":
    main()
