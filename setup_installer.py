import os
import json
import random

def clone_repos(url):
    # Clone the relevant repos from a list
    command = f"python r2e/repo_builder/setup_repos.py --repo_url {url}"
    os.system(command)

def extract_data():
    # Extract data from all repos
    command = "python r2e/repo_builder/extract_func_methods.py --overwrite_extracted True"
    os.system(command)

def reduce_data():
    # Trim down the extracted data
    # Open up the extracted file (~/buckets/r2e_bucket/extracted_data/temp_extracted.json)
    # It consists of a list of JSON objects. Possibly hundreds. Trim it down to just num_funcs (let num_funcs=5). Select the num_funcs tests at random
    num_funcs = 5
    extracted_file_path = os.path.expanduser('~/buckets/r2e_bucket/extracted_data/temp_extracted.json')

    # Read the extracted data
    with open(extracted_file_path, 'r') as f:
        data = json.load(f)

    # Select num_funcs items at random
    if len(data) > num_funcs:
        data = random.sample(data, num_funcs)

    # Write the trimmed data back to the file
    with open(extracted_file_path, 'w') as f:
        json.dump(data, f, indent=4)

def make_equiv_test():
    # Generate the equivalence tests
    command="python r2e/generators/testgen/generate.py -i temp_extracted.json --multiprocess 0"
    os.system(command)

def setup_repo(url):
    clone_repos(url)
    extract_data()
    reduce_data()
    make_equiv_test()

if __name__ == "__main__":
    # Assume repo has already been cloned
    extract_data()
    reduce_data()
    make_equiv_test()
