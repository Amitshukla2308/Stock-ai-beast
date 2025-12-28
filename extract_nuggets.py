import duckdb

conn = duckdb.connect('/app/data/trading.db', read_only=True)

print("=== GOOD NUGGETS ===")
good = conn.execute("SELECT lesson FROM knowledge_nuggets WHERE category='GOOD'").fetchall()
for i, (lesson,) in enumerate(good, 1):
    print(f"{i}. {lesson}")

print("\n=== BAD NUGGETS ===")
bad = conn.execute("SELECT lesson FROM knowledge_nuggets WHERE category='BAD'").fetchall()
for i, (lesson,) in enumerate(bad, 1):
    print(f"{i}. {lesson}")

conn.close()
