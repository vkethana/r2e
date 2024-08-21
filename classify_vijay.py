import os
import subprocess
import sys

def keyword_in_log(log_path, keyword):
    # Check if the file exists
    if not os.path.isfile(log_path):
        print(f"[ERROR] The log file '{log_path}' does not exist.")
        return False
    
    # Try to use grep for efficiency
    try:
        result = subprocess.run(['grep', '-q', keyword, log_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode == 0
    except FileNotFoundError:
        print("[INFO] Grep not found, using Python fallback.")
    
    # Fallback to native Python approach if grep is not available
    try:
        with open(log_path, 'r') as file:
            for line in file:
                if keyword in line:
                    return True
    except Exception as e:
        print(f"[ERROR] Error reading file: {e}")
    
    return False

def process_logs_in_directory(log_directory):
    # Initialize variables to track the number of failures, blank repos, and successes
    num_failures = 0
    num_blank = 0
    num_success = 0

    failed_repos = []

    # Ensure the directory exists
    if not os.path.isdir(log_directory):
        print(f"[ERROR] The directory '{log_directory}' does not exist.")
        return

    # Loop through all files in the log directory
    for filename in os.listdir(log_directory):
        file_path = os.path.join(log_directory, filename)
        
        # If it's not a folder, process the file
        if not os.path.isdir(file_path):
            print(f"[DEBUG] Processing log file: {file_path}")
            
            if keyword_in_log(file_path, "INSTALLATION SUCCEEDED"):
                print(f"[INFO] Install success detected in {file_path}")
                num_success += 1
            elif keyword_in_log(file_path, "BLANK REPO ERROR"):
                print(f"[INFO] Blank repo error detected in {file_path}")
                num_blank += 1
            elif keyword_in_log(file_path, "INSTALLATION FAILURE"):
                print(f"[INFO] Install failure error detected in {file_path}")
                failed_repos.append(file_path)
                num_failures += 1
            else:
                print(f"[DEBUG] No relevant keywords found in {file_path}")
                num_failures += 1
    
    # Print the results
    print(f"Number of installation failures: {num_failures}")
    print(f"Number of blank repo errors: {num_blank}")
    print(f"Number of successful installations: {num_success}")
    print(f"Success ratio: {num_success / (num_success + num_failures):.2f}")

if __name__ == "__main__":
    # Check for valid command-line arguments
    if len(sys.argv) != 2:
        print("Usage: python script.py <log_directory>")
        sys.exit(1)

    log_directory = sys.argv[1]


    # Process the log directory
    failed_repos = process_logs_in_directory(log_directory)
