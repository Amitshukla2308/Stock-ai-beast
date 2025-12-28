def read_file(path):
    print(f"--- START: {path} ---")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            print(f.read())
    except Exception as e:
        print(f"Error reading {path}: {e}")
    print(f"--- END: {path} ---")

read_file('brain/llm_client.py')
read_file('brain/prompts.py')
