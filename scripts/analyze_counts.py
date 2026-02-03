
import pandas as pd
import json

def analyze_trades():
    try:
        with open('session_trades.json', 'r') as f:
            trades = json.load(f)
            
        df = pd.DataFrame(trades)
        print(f"📉 Total Exported: {len(df)}")
        
        if 'exit_reason' in df.columns:
            print("\n🚪 Exit Reason Breakdown:")
            counts = df['exit_reason'].value_counts()
            for reason, count in counts.items():
                print(f" - {reason}: {count}")
                
        if 'status' in df.columns:
            print("\n📊 Status Breakdown:")
            counts = df['status'].value_counts()
            for status, count in counts.items():
                print(f" - {status}: {count}")

        # Check for Is Counterfactual
        if 'is_counterfactual' in df.columns:
            print("\n👻 Counterfactual Breakdown:")
            counts = df['is_counterfactual'].value_counts()
            for val, count in counts.items():
                print(f" - {val}: {count}")
             
        # Check for High-Alpha vs Fallback if metadata column exists
        # Metadata is usually a JSON string or dict? In sqlite it's often a string.
        # But pandas read_sql might not parse it automatically unless handled.
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_trades()
