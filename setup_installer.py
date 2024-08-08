import os
import json
import random
from multiprocessing import Lock
from r2e.paths import HOME_DIR
import docker
R2E_REPO = HOME_DIR / "r2e"
lock = Lock()
def clear_repos_folder():
    # Check if there are any files or folders in ~/buckets/local_repoeval_bucket/repos
    # If there are, for each file/folder ask the user for confirmation before deleting
    # If the user confirms, delete the file/folder
    repos_folder = os.path.expanduser('~/buckets/local_repoeval_bucket/repos')
    for item in os.listdir(repos_folder):
        item_path = os.path.join(repos_folder, item)
        print("Deleting ", item_path)
        if os.path.isfile(item_path):
            # Ask for confirmation
           # confirm = input(f"Delete {item_path}? (y/n): ")
           # if confirm.lower() == 'y':
             os.remove(item_path)
        elif os.path.isdir(item_path):
            #confirm = input(f"Delete {item_path}? (y/n): ")
            #if confirm.lower() == 'y':
                # Delete the whole directory
             os.system(f"rm -rf {item_path}")

def clone_repos(url):
    # Clone the relevant repos from a list
    command = f"python r2e/repo_builder/setup_repos.py --repo_url {url}"
    os.system(command)

def extract_data(repo_id):
    # Extract data from all repos
    command = f"python r2e/repo_builder/extract_func_methods.py --overwrite_extracted True --exp_id {repo_id} --repo_id {repo_id}"
    os.system(command)

def reduce_data(repo_id):
    # Trim down the extracted data
    # Open up the extracted file (~/buckets/r2e_bucket/extracted_data/{repo_id}_extracted.json)
    # It consists of a list of JSON objects. Possibly hundreds. Trim it down to just num_funcs (let num_funcs=5). Select the num_funcs tests at random
    num_funcs = 5
    extracted_file_path = os.path.expanduser(f"~/buckets/r2e_bucket/extracted_data/{repo_id}_extracted.json")

    # Read the extracted data
    with open(extracted_file_path, 'r') as f:
        data = json.load(f)

    # Select num_funcs items at random
    if len(data) > num_funcs:
        data = random.sample(data, num_funcs)

    # Write the trimmed data back to the file
    with open(extracted_file_path, 'w') as f:
        json.dump(data, f, indent=4)

def make_equiv_test(repo_id):
    # Generate the equivalence tests
    command = f"python r2e/generators/testgen/generate.py -i {repo_id}_extracted.json --multiprocess 16 --exp_id {repo_id}"
    os.system(command)

def setup_repo(url,repo_id,clear_existing_repos=False):
    if clear_existing_repos:
        print("Clearing existing repos...")
        clear_repos_folder()
    else:
        print("Skipping clearing existing repos...")

    print("Cloning new repo...")
    clone_repos(url)
    print("Extracting tests...")
    extract_data(repo_id)
    print("Reducing number of tests...")
    reduce_data(repo_id)
    print("Generating equivalence tests...")
    make_equiv_test(repo_id)

def setup_test_container(image_name="r2e:interactive_partial_install"):
    clone_repos("https://github.com/psf/requests")
    print("IMPORTANT: MAKE SURE YOUR R2E INSTALL IS LOCATED AT ~/r2e")
    #ans = input("Have you configured your R2E install to be located at /home/<username>/r2e? (y/n)")

    dockerfile_path = R2E_REPO + " r2e/repo_builder/docker_builder/base_dockerfile.dockerfile. "
    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f {dockerfile_path} .")

def setup_container(image_name, repo_id):
    os.system(f"cd {R2E_REPO} && python r2e/repo_builder/docker_builder/r2e_dockerfile_builder.py --install_batch_size 1 --repo_id {repo_id}")
    #os.system(f"cd ~/buckets/local_repoeval_bucket/repos && pip install pipreqs")
    #os.system(f"cd ~/buckets/local_repoeval_bucket/repos && pipreqs . --force")
    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f {R2E_REPO}/r2e/repo_builder/docker_builder/r2e_final_dockerfile.dockerfile .")


if __name__ == "__main__":
    # Assume repo has already been cloned
    #setup_test_container()
    print("Run installer.py to test this file")
