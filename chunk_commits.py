import os
import subprocess
import math

def run(cmd):
    # Use CWD explicitly to avoid UNC default-to-windows issue
    cwd = os.getcwd()
    # CMD.exe needs pushd to handle UNC paths (it creates temporary Z: drive)
    full_cmd = f'pushd "{cwd}" && {cmd}'
    return subprocess.check_output(full_cmd, shell=True).decode('utf-8').strip()

# Get all modified/deleted/new files
# Porcelain gives "XY Path" or "R  Old -> New"
full_cmd = f'pushd "{os.getcwd()}" && git status --porcelain'
status_out = subprocess.check_output(full_cmd, shell=True).decode('utf-8').strip()

files = []
for line in status_out.splitlines():
    if not line.strip(): continue
    # status is first 2 chars.
    # If renamed: "R  Old -> New" -> We want New.
    # But for "git add", we usually add the new path.
    # Simplistic parsing:
    content = line[3:]
    if "->" in content: # Rename
        parts = content.split(" -> ")
        path = parts[-1]
    else:
        path = content
    
    # Remove surrounding quotes if git output them
    path = path.strip('"')
    files.append(path)

total_files = len(files)
print(f"Processing {total_files} files...")

chunk_size = math.ceil(total_files / 4)
chunks = [files[i:i + chunk_size] for i in range(0, total_files, chunk_size)]

for i, chunk in enumerate(chunks):
    chunk_num = i + 1
    print(f"Processing Chunk {chunk_num}/4 ({len(chunk)} files)...")
    
    # Git add
    # Handle filename quoting manually for cmd.exe
    quoted_files = [f'"{f}"' for f in chunk]
    files_str = " ".join(quoted_files)
    
    # Use f-string with pushd
    add_cmd = f'pushd "{os.getcwd()}" && git add {files_str}'
    try:
        subprocess.check_output(add_cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error adding files in chunk {chunk_num}: {e}")
        # Try adding one by one if batch fails?
        for f in chunk:
             try:
                 subprocess.check_output(f'pushd "{os.getcwd()}" && git add "{f}"', shell=True)
             except:
                 print(f"Failed to add {f}")
    
    msg = f"feat(core): Advanced Levels & DB Fix [Part {chunk_num}/4]"
    run(f'git commit -m "{msg}"')
    print(f"Committed Chunk {chunk_num}")

print("All chunks committed.")
