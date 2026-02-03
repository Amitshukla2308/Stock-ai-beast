import json
import os

def check():
    try:
        # Load Map
        with open('atlas/models/confluence_map.json', 'r') as f:
            map_data = json.load(f)
            
        edges = map_data.get('long_edges', []) + map_data.get('short_edges', [])
        map_keys = set(f"{e['cluster_15m']}:{e['cluster_5m']}" for e in edges)
        
        # Load Config
        with open('config/trading_config.json', 'r') as f:
            cfg = json.load(f)
            
        blocks = cfg.get('BLOCKED_REGIMES', {}).get('regimes', [])
        
        # Check
        missing = [r for r in blocks if r not in map_keys]
        
        print(f"Total Blocks in Config: {len(blocks)}")
        print(f"Total Regimes in Map: {len(map_keys)}")
        print(f"Blocks NOT in Map: {len(missing)}")
        if missing:
            print(f"Missing Regimes: {missing}")
        else:
            print("✅ All blocked regimes are valid existing regimes in the map.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check()
