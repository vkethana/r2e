import os
import json
import random

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
    clear_repos_folder()
    clone_repos(url)
    extract_data()
    reduce_data()
    make_equiv_test()

def setup_test_container(image_name="r2e:interactive_partial_install"):
    clone_repos("https://github.com/psf/requests")
    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f /home/vkethana/r2e/r2e/repo_builder/docker_builder/base_dockerfile.dockerfile .")

def setup_container(image_name):
    # TODO Throw an error if either process doesn't succeed
    os.system("cd /home/vkethana/r2e && python r2e/repo_builder/docker_builder/r2e_dockerfile_builder.py  --install_batch_size 1")

    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f /home/vkethana/r2e/r2e/repo_builder/docker_builder/r2e_final_dockerfile.dockerfile .")

    # first make the relevant directory if it doesn't exist
    #os.system(f"mkdir -p ~/buckets/local_repoeval_bucket/install_logs/{image_name}")
    # enter the image in interactive mode, which has name image_name, and run cat /install_code/install_logs/* 
    
    # use -it to run the container in interactive mode
    
    # to get the logs of the installation process
    # use --rm to remove the container after running it

    #os.system(f"docker run --rm {image_name} cat /install_code/install_logs/* > ~/buckets/local_repoeval_bucket/install_logs/{image_name}/install_log.txt")
    #os.system(f"docker run -it --rm {image_name} cat /install_code/install_logs/* > ~/buckets/local_repoeval_bucket/install_logs/{image_name}/install_log.txt")
    #os.system(f"docker run -it --rm {image_name} cat /install_code/install_logs/*.log")

if __name__ == "__main__":
    # Assume repo has already been cloned
    #setup_test_container()
    #print("Run installer.py to test this file")
