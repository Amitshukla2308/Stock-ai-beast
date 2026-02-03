
import joblib
import os
import sys

def verify_models():
    base_path = "atlas/models"
    
    # 1. Check K-Means
    try:
        km = joblib.load(os.path.join(base_path, "kmeans_5m.joblib"))
        print(f"KMeans (5m) n_clusters: {km.n_clusters}")
    except Exception as e:
        print(f"Error loading kmeans_5m: {e}")

    try:
        km15 = joblib.load(os.path.join(base_path, "kmeans_15m.joblib"))
        print(f"KMeans (15m) n_clusters: {km15.n_clusters}")
    except Exception as e:
        print(f"Error loading kmeans_15m: {e}")

    # 2. Check PCA
    try:
        pca_bundle = joblib.load(os.path.join(base_path, "atlas_pca.joblib"))
        pca = pca_bundle['model']
        features = pca_bundle['features']
        print(f"PCA n_components: {pca.n_components_}")
        print(f"PCA n_features_input: {pca.n_features_in_}")
        print(f"PCA features saved list len: {len(features)}")
    except Exception as e:
        print(f"Error loading atlas_pca: {e}")

if __name__ == "__main__":
    verify_models()
