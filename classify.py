import os
import re
import subprocess
import sys
import json
from collections import defaultdict

def convert_back_repo_format(repo):
    """Convert the repo format back from the success message format to URL format."""
    return 'https://github.com/' + repo.replace('___', '/')

# Function to check if a keyword exists in the log file
def keyword_in_log(log_path, keyword):
    if not os.path.isfile(log_path):
        print(f"[ERROR] The log file '{log_path}' does not exist.")
        return False

    try:
        result = subprocess.run(['grep', '-q', keyword, log_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode == 0
    except FileNotFoundError:
        print("[INFO] Grep not found, using Python fallback.")

    try:
        with open(log_path, 'r') as file:
            for line in file:
                if keyword in line:
                    return True
    except Exception as e:
        print(f"[ERROR] Error reading file: {e}")
    
    return False

# Function to parse log files and classify small errors
def parse_log_file(file_path):
    with open(file_path, 'r') as file:
        log_data = file.read()

    error_pattern = re.compile(r'Small Error: ([^\(]+)', re.DOTALL)
    
    error_classes = defaultdict(list)
    for match in error_pattern.finditer(log_data):
        error_type = match.group(1).strip()
        error_classes[error_type].append(file_path)

    return error_classes

# Function to process all logs in a directory and categorize errors
def process_logs_in_directory(log_directory):
    num_failures = 0
    num_blank = 0
    num_success = 0
    num_did_not_finish = 0
    failed_repos = []
    error_summary = defaultdict(list)

    if not os.path.isdir(log_directory):
        print(f"[ERROR] The directory '{log_directory}' does not exist.")
        return

    # Process each log file
    for filename in os.listdir(log_directory):
        file_path = os.path.join(log_directory, filename)
        
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
                num_did_not_finish += 1
                num_failures += 1

    # Process failed repos and categorize errors
    if failed_repos:
        for failed_repo in failed_repos:
            error_classes = parse_log_file(failed_repo)
            for error_type, repos in error_classes.items():
                repo_url = convert_back_repo_format(failed_repo)  # Assuming this converts the path to a URL
                error_summary[error_type].append(repo_url)

    # Generate the installation summary
    installation_summary = {
        "total": num_success + num_failures,
        "fails": num_failures,
        "blanks": num_blank,
        "num_did_not_finish": num_did_not_finish,
        "successes": num_success,
        "success rate": round(num_success / (num_success + num_failures), 2) if (num_success + num_failures) > 0 else 0
    }

    # Generate the final summary
    final_summary = {
        "Installation Summary": installation_summary,
        "Failed Installations": {f"{error} ({len(repos)})": repos for error, repos in error_summary.items()}
    }

    # Print the final summary in JSON-like format
    print(json.dumps(final_summary, indent=4))

if __name__ == "__main__":
    # Ensure correct usage
    if len(sys.argv) != 2:
        print("Usage: python <name of file>.py <log_directory>")
        sys.exit(1)

    log_directory = sys.argv[1]

    # Process the logs
    process_logs_in_directory(log_directory)
