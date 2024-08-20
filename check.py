import os

def count_empty_out_files(directory):
    directory = os.path.expanduser(directory)
    empty = 0
    t = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith("_out.json"):  
                t += 1
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    content = f.read().strip()
                    if content == "[]":
                        empty += 1
    return empty, t

if __name__ == "__main__":
    directory = "~/buckets/r2e_bucket/testgen" 
    empty_files, tot_files = count_empty_out_files(directory)
    print(f"Number of empty '_out' files: {empty_files} out of {tot_files}")
