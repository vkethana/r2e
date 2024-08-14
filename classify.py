import re
import sys
import json
import os
from collections import defaultdict

"""
NOTE: This file is only supposed to catch Small Error through failure logging.
Consider going through the output manually when there are more generic errors.
"""

def convert_back_repo_format(repo):
    """Convert the repo format back from the success message format to URL format."""
    return 'https://github.com/' + repo.replace('___', '/')

def parse_log_file(file_path):
    with open(file_path, 'r') as file:
        log_data = file.read()

    error_pattern = re.compile(r'INFO INSTALLATION FAILURE: ([^\s]+).*?Small Error: ([^\(]+)', re.DOTALL)
    success_pattern = re.compile(r'INFO INSTALLATION SUCCEEDED: (\S+)')

    error_groups = defaultdict(list)
    success_groups = set()
    fails = 0
    successes = 0

    for match in success_pattern.finditer(log_data):
        successes += 1
        repo = match.group(1)
        repo_url = convert_back_repo_format(repo)
        success_groups.add(repo_url)

    for match in error_pattern.finditer(log_data):
        repo = match.group(1)
        error_type = match.group(2).strip()
        # Do not add successful installations or duplicate repos.
        repo_url = convert_back_repo_format(repo)
        if (repo_url not in success_groups) and (repo_url not in error_groups[error_type]):
            fails += 1
            error_groups[error_type].append(repo_url)

    return error_groups, success_groups, fails, successes

# Use to traverse a log folder, now only capturing "Installation Failure/Error mode"
def aggregate_results(folder_path):
    aggregated_errors = defaultdict(list)
    aggregated_successes = set()
    total_fails = 0
    total_successes = 0

    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        if os.path.isfile(file_path):
            error_groups, success_groups, fails, successes = parse_log_file(file_path)

            for error_type, repos in error_groups.items():
                aggregated_errors[error_type].extend(repos)
                
            aggregated_successes.update(success_groups)
            total_fails += fails
            total_successes += successes

    error_groups_with_counts = {f"{error_type} ({len(repos)})": repos for error_type, repos in aggregated_errors.items()}
    successes_with_counts = {f"Successes ({total_successes})": list(aggregated_successes)}
    
    output_data = {
        "Installation Summary": {
            "total": total_fails + total_successes,
            "fails": total_fails,
            "successes": total_successes,
            "success rate": round(total_successes / (total_fails + total_successes), 2) if (total_fails + total_successes) > 0 else 0
        },
        "Failed Installations": error_groups_with_counts,
        "Successful Installations": successes_with_counts
    }

    with open('grouped_repos.json', 'w') as json_file:
        json.dump(output_data, json_file, indent=4)
    
    print(f"Processed {total_fails + total_successes} log files from {folder_path}. Results saved to grouped_repos.json.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Example Usage: python classify.py logs/")
        sys.exit(1)
    
    folder_path = sys.argv[1]
    aggregate_results(folder_path)
