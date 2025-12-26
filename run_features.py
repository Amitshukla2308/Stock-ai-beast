import data.feature_engineer as fe

if __name__ == "__main__":
    print("🚀 Starting Feature Engineering (Technicals + Greeks using VIX)...")
    fe.compute_features("NSE:NIFTYBANK-INDEX")
    print("✅ Feature Engineering Completed.")
