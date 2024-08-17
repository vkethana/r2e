import os
import json
import random
from r2e.paths import HOME_DIR, LOGGER_DIR
import docker
import logging
import time
import tarfile

R2E_REPO = HOME_DIR / "r2e"
logger_dir = LOGGER_DIR

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
    extracted_file_path = os.path.expanduser(f"~/buckets/r2e_bucket/extracted_data/{repo_id}_extracted.json")

    # Read the extracted data
    with open(extracted_file_path, 'r') as f:
        data = json.load(f)

    if len(data) < 1:
        print("WARNING: No data found in extracted file")

    # Write the trimmed data back to the file
    with open(extracted_file_path, 'w') as f:
        json.dump(data[0:500], f, indent=4)

def make_equiv_test(repo_id):
    # Generate the equivalence tests
    command = f"python r2e/generators/testgen/generate.py -i {repo_id}_extracted.json --multiprocess 16 --exp_id {repo_id}"
    os.system(command)

def setup_repo(url,repo_id, logger):
    logger.debug("Cloning new repo...")
    clone_repos(url)
    logger.debug("Extracting tests...")
    extract_data(repo_id)
    logger.debug("Reducing number of tests...")
    reduce_data(repo_id)
    logger.debug("Generating equivalence tests...")
    make_equiv_test(repo_id)

def setup_container(image_name, repo_id, logger):
    logger.debug("Building dockerfile...")
    os.system(f"cd {R2E_REPO} && python r2e/repo_builder/docker_builder/r2e_dockerfile_builder.py --install_batch_size 1 --repo_id {repo_id}")

    # Double-check that the docker image actually got created
    dockerfile_path = f"{R2E_REPO}/r2e/repo_builder/docker_builder/r2e_final_dockerfile_{repo_id}.dockerfile"
    if not os.path.exists(dockerfile_path):
        logger.critical("Dockerfile was not successfully generated!")
        return

    logger.debug(f"Building docker image at path {dockerfile_path}...")
    os.system(f"cd ~/buckets/local_repoeval_bucket/repos && docker build -t {image_name} -f {dockerfile_path} .")

def setup_logger(path, repo_id):
    # Check the logs directory and make it if it doesn't exist
    if not os.path.exists(logger_dir):
        os.makedirs(logger_dir)

    path = os.path.join(logger_dir, path)

    # Create a logger object
    logger = logging.getLogger(f"logger_{repo_id}")
    logger.setLevel(logging.DEBUG)

    # Ensure the local time is used
    formatter = logging.Formatter(
        fmt=f'%(asctime)s %(name)s %(levelname)s %(message)s (%(filename)s:%(lineno)d) ({repo_id})',
        datefmt='%m/%d/%Y %I:%M:%S %p'
    )
    formatter.converter = time.localtime

    # Create file handler
    file_handler = logging.FileHandler(path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Create stream handler
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    # Silence debug messages from docker and urllib
    logging.getLogger("docker.utils.config").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logger.info("<<<<<<<<<<<<<<<<<< Logger setup anew <<<<<<<<<<<<<<<<<<<")

    print("Successfully set up logger at path ", path)
    return logger


def analyze_tests(file_path, logger):

    logger.info(f"Reading FUT data at path {file_path}")

    with open(file_path, 'r') as file:
        data = json.load(file)

    assert(type(data) == list)
    if len(data) > 0:
        assert(type(data[0]) == dict)

    total_tests = len(data)
    passed_tests = 0
    no_history_tests = 0

    logger.debug(f"Detected {total_tests} tests in the file. Analyzing...")
    i = 0

    for entry in data:
        logger.debug(f"Analyzing test {i} of {total_tests}")
        test_history = entry.get('test_history', {})
        history = test_history.get('history', [])

        if history:
            latest_test = history[-1]
            exec_stats = latest_test.get('exec_stats', {})

            if 'error' not in exec_stats:
                passed_tests += 1
                logger.info(f"Test {i} passed")
            else:
                logger.warning(f"Test {i} failed with error msg: {exec_stats['error']}")

        else:
            no_history_tests += 1
            logger.warning(f"Test {i} has no history. Skipping...")

        i += 1

    logger.info(f"Passed {passed_tests} out of {total_tests} tests")
    logger.info(f"Skipped {no_history_tests} tests due to missing history")
    return passed_tests, total_tests


def llm_suggest_next_command(context, last_command, last_output, oracle_result):
    msg_content = f"""
    Context: {context}
    Last command executed: {last_command}
    Output/Error: {last_output}
    Oracle result: {oracle_result}

    - Suggest the next command to run in the Docker container to complete the installation process.
    - The repo in question is already partially installed in the Docker container at /repos/(name_of_repo). You may assume that you are CDed into this directory automatically.
    - The repo has a partially installed virtual environment at `.venv`; you may assume that the virtual environment is already activated.
    - The installation is complete if and only if the Oracle returns "INSTALLATION SUCCESSFUL".
    - Important Note: Every shell command that you run is executed in a separate bash session in the Docker container. If you create any aliases or environment variables, make sure to save them to ~/.bashrc, otherwise the command will have no effect.
    - Your response should be a shell command for the Docker container or 'RUN ORACLE'. When you write 'RUN ORACLE', the Oracle will be consulted to determine if the installation is complete. Submit 'RUN ORACLE' only when you believe the installation is complete. 'RUN ORACLE' cannot be run alongside other shell commands.
    - Do not attempt to run the Oracle directly, as it is located somewhere that you cannot access. The Oracle will be automatically consulted for you if you say, 'RUN ORACLE'.
    """
    #TODO: Enhance prompt engineering
    response = openai_client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "You are an AI assistant helping to complete the installation process of a partially-installed repo within a Docker container. Read the following instructions, which will help guide you to suggest the next command to run in the Docker container. Do NOT include any reasoning in your response. Simply include a terminal command to be executed or the words 'RUN ORACLE'. Do NOT attempt to format your response in Markdown; for example, do NOT include ``` backticks."},
            {"role": "user", "content": msg_content}
        ]
    )
    return response.choices[0].message.content.strip().replace("```bash", "").replace("`", "").replace("\n", "")

def human_intervention(context, last_command, last_output, oracle_result):
    print("\nRequesting human intervention:")
    print(f"Context: {context}")
    print(f"Last command: {last_command}")
    print(f"Output/Error: {last_output}")
    print(f"Oracle result: {oracle_result}")
    return input("Please suggest the next command for the Docker container (or type 'ABORT'): ")

def get_install_logs_from_image(image_name):
    # Create a Docker client
    client = docker.from_env()

    try:
        # Create a container from the image
        container = client.containers.create(image_name)

        # Define the source and destination paths
        src_path = '/install_code/install_logs'
        dst_path = os.path.join(logger_dir, f'{image_name}_install_logs')

        # Ensure the destination directory exists
        os.makedirs(dst_path, exist_ok=True)

        # Copy the contents from the container to the host
        bits, stat = container.get_archive(src_path)

        # Write the contents to the destination directory
        with open(os.path.join(dst_path, 'install_logs.tar'), 'wb') as f:
            for chunk in bits:
                f.write(chunk)

        # Extract the tar file
        with tarfile.open(os.path.join(dst_path, 'install_logs.tar'), 'r') as tar:
            tar.extractall(path=dst_path)

        # Remove the temporary tar file
        os.remove(os.path.join(dst_path, 'install_logs.tar'))

    finally:
        # Always remove the container, even if an exception occurs
        container.remove()

    print(f"Install logs copied from {image_name} to {dst_path}")

