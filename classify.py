import re
import sys
import json
from collections import defaultdict

"""
NOTE: This file is only supposed to catch Small Error through failure logging.
Consider going through the output manually when there are more generic errors.
"""

def convert_back_repo_format(repo):
    """Convert the repo format back from the success message format to URL format."""
    return 'https://github.com/' + repo.replace('___', '/')

def parse_log_file(file_path):
    fails = 0
    successes = 0
    with open(file_path, 'r') as file:
        log_data = file.read()

    error_pattern = re.compile(r'INFO INSTALLATION FAILURE: ([^\s]+).*?Small Error: ([^\(]+)', re.DOTALL)
    success_pattern = re.compile(r'INFO INSTALLATION SUCCEEDED: (\S+)')

    error_groups = defaultdict(list)
    success_groups = set()

    for match in success_pattern.finditer(log_data):
        successes += 1
        repo = match.group(1)
        repo_url = convert_back_repo_format(repo)
        success_groups.add(repo_url)

    for match in error_pattern.finditer(log_data):
        repo = match.group(1)
        error_type = match.group(2).strip()
        # Do not add successful installations or duplicant repos.
        repo_url = convert_back_repo_format(repo)
        if (repo_url not in success_groups) and (repo_url not in error_groups[error_type]):
            fails += 1
            error_groups[error_type].append(repo_url)



    error_groups_with_counts = {f"{error_type} ({len(repos)})": repos for error_type, repos in error_groups.items()}
    successes_with_counts = {f"Successes ({successes})": list(success_groups)}
    return error_groups_with_counts, successes_with_counts, fails, successes


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Example Usage: python classify.py logs/1_repo.log")
        sys.exit(1)
    
    log_file_path = sys.argv[1]
    error_groups, success_groups, fails, successes = parse_log_file(log_file_path)

    output_data = {
        "Installation Summary": {
            "total": fails + successes,
            "fails": fails,
            "successes": successes,
            "success rate": round(successes/ (fails + successes), 2)
        },
        "Failed Installations": error_groups,
        "Successful Installations": success_groups
    }

    with open('grouped_repos.json', 'w') as json_file:
        json.dump(output_data, json_file, indent=4)
    
    print(f"Out of {fails + successes} attempts, {fails} failed installations and {successes} successful installations saved to grouped_repos.json.")
