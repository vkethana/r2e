import os
import json
import random

from r2e.paths import HOME_DIR

R2E_REPO = HOME_DIR / "r2e"

def clear_repos_folder():
    # Check if there are any files or folders in ~/buckets/local_repoeval_bucket/repos
    # If there are, for each file/folder ask the user for confirmation before deleting
    # If the user confirms, delete the file/folder
    repos_folder = os.path.expanduser('~/buckets/local_repoeval_bucket/repos')
    for item in os.listdir(repos_folder):
        item_path = os.path.join(repos_folder, item)
        if os.path.isfile(item_path):
            # Ask for confirmation
            confirm = input(f"Delete {item_path}? (y/n): ")
            if confirm.lower() == 'y':
                os.remove(item_path)
        elif os.path.isdir(item_path):
            confirm = input(f"Delete {item_path}? (y/n): ")
            if confirm.lower() == 'y':
                # Delete the whole directory
                os.system(f"rm -rf {item_path}")

# TODO: Change setup_repos.py architecture -- DONE
def clone_repos(url):
    # Clone the relevant repos from a list
    command = f"python r2e/repo_builder/setup_repos.py --repo_url {url}"
    os.system(command)

# TODO arch change in extract_func_methods; provide repo_url for parsing -- DONE
def extract_data(url):
    # Extract data from all repos
    command = f"python r2e/repo_builder/extract_func_methods.py --repo_url {url} --overwrite_extracted True"
    os.system(command)

#TODO: Modify path for arch change -- DONE 
def reduce_data(url):
    # Trim down the extracted data
    # Open up the extracted file (~/buckets/local_repoeval_bucket/repos/dir_{repo_name}/extracted_data/temp_extracted.json  
    # It consists of a list of JSON objects. Possibly hundreds. Trim it down to just num_funcs (let num_funcs=5). Select the num_funcs tests at random
    num_funcs = 5
    repo_name = url.split("/")[-1] 
    extracted_file_path = os.path.expanduser(f"~/buckets/local_repoeval_bucket/repos/dir_{repo_name}/extracted_data/temp_extracted.json")

    # Read the extracted data
    with open(extracted_file_path, 'r') as f:
        data = json.load(f)

    # Select num_funcs items at random
    if len(data) > num_funcs:
        data = random.sample(data, num_funcs)

    # Write the trimmed data back to the file
    with open(extracted_file_path, 'w') as f:
        json.dump(data, f, indent=4)

def make_equiv_test(url):
    # TODO: put testgen in the respective folder of the repo
    # Generate the equivalence tests
    command=f"python r2e/generators/testgen/generate.py -i temp_extracted.json --multiprocess 0 --repo_url {url}"
    os.system(command)

def setup_repo(url):
    clear_repos_folder()
    clone_repos(url)
    extract_data(url)
    reduce_data(url)
    make_equiv_test(url)

def setup_test_container(image_name="r2e:interactive_partial_install"):
    clone_repos("https://github.com/psf/requests")
    print("IMPORTANT: MAKE SURE YOUR R2E INSTALL IS LOCATED AT ~/r2e")
    print("IMPORTANT: MAKE SURE YOUR R2E INSTALL IS LOCATED AT ~/r2e")
    print("IMPORTANT: MAKE SURE YOUR R2E INSTALL IS LOCATED AT ~/r2e")
    #ans = input("Have you configured your R2E install to be located at /home/<username>/r2e? (y/n)")

    dockerfile_path = R2E_REPO + " r2e/repo_builder/docker_builder/base_dockerfile.dockerfile"
    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f {dockerfile_path} .")

# TODO: Add second arg of the repo specific folder name
def setup_container(image_name):
    # TODO Throw an error if either process doesn't succeed
    os.system(f"cd {R2E_REPO} && python r2e/repo_builder/docker_builder/r2e_dockerfile_builder.py  --install_batch_size 1")
    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f {R2E_REPO}/r2e/repo_builder/docker_builder/r2e_final_dockerfile.dockerfile .")


if __name__ == "__main__":
    # Assume repo has already been cloned
    #setup_test_container()
    print("Run installer.py to test this file")
