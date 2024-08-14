import docker
import traceback

import os
import threading
import queue
import shlex
import sys
import time
import subprocess
from openai import OpenAI
import json
import rpyc
import random
from inputimeout import inputimeout, TimeoutOccurred
import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor
import signal
import tarfile

from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs
from r2e.execution.r2e_simulator import DockerSimulator
from r2e.execution.execute_futs import self_equiv_futs
from r2e.multiprocess import run_tasks_in_parallel

from setup_installer import setup_repo, setup_container
from r2e.paths import R2E_BUCKET_DIR, TESTGEN_DIR, REPOS_DIR, EXTRACTED_DATA_DIR, LOCAL_EVAL_DIR

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()
logger_dir = "1500_repo_logs"

def setup_logger(path, repo_id):
    # Check the logs directory and make it if it doesn't exist
    if not os.path.exists(logger_dir):
        os.makedirs(logger_dir)

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
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    # Silence debug messages from docker and urllib
    logging.getLogger("docker.utils.config").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

    print("Successfully set up logger at path ", path)
    return logger

def write_failure_mode(image_name, command, output):
    # Write this to failures/<image_name>_failures.json
    # Check to see if the failures directory exists

    if not os.path.exists("failures"):
        os.makedirs("failures")
    path = f"{image_name}_failures.json"
    # Check if the file is already present in the failures directory
    if not os.path.exists(path):
        with open(f"failures/{image_name}_failures.json", "w") as f:
            f.write(json.dumps({
                "command": command,
                "output": output
            }) + "\n")
    else:
        with open(path) as f:
            f.write(json.dumps({
                "command": bash_command,
                "output": output
            }) + "\n")
    print("Wrote failure mode to file path:", path)

def check_execution_status(execution_output_path):
    # Read the JSON output file
    with open(execution_output_path, "r") as f:
        output = json.load(f)

    if output == []:
        return False, "No output found in the JSON file. Does repo contain no Python code?"

    # Initialize a flag to track if we've seen any successful executions
    any_success = False

    # Search for all the "exec_stats" fields
    for item in output:
        test_history = item.get('test_history', {})
        history = test_history.get('history', [])

        for entry in history:
            exec_stats = entry.get('exec_stats')

            if exec_stats is not None:
                # If any of them contains "error", return "ERROR"
                if "error" in exec_stats.keys():
                    try:
                        return False, exec_stats['error']
                    except:
                        return False, "No error message found"
            else:
                print("WARNING: At least one test did not get properly executed")
                print("Attempting to print method id of entry :", entry.get('method_id', 'No method id found'))

    return True, None

def installation_oracle(simulator, conn, repo_id, logger):
    # This function abstracts the verification command
    exec_args = ExecutionArgs(
        testgen_exp_id=f"{repo_id}_generate",
        execution_multiprocess=0,  # Replace with your desired number of processes
        image_name=f"r2e:temp_{repo_id.split('___')[-1]}",
    )

    logger.info(f"Running Oracle self-equivalence test...")
    # Run the self_equiv function
    run_self_equiv(exec_args, simulator, conn, logger)
    logger.info("Done running self-equivalence test")

    # This file contains the output of the execution
    #command = f"python r2e/execution/run_self_equiv.py --testgen_exp_id temp_generate --image_name {image_name} --execution_multiprocess 0"
    try:
        logger.info(f"Checking execution status...")
        success, message = check_execution_status(str(TESTGEN_DIR) + f"/{repo_id}_generate_out.json")
        return success, message

    except Exception as e:
        logger.info(f"\nOracle result: ERROR; Exception: {e}")
        return 0, f"ERROR: {e}"

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

'''
The below two methods are used to instantiate the docker container and rpyc connection
'''
def get_service(repo_id: str, port: int, image_name: str, logger: None) -> tuple[DockerSimulator, rpyc.Connection]:
    try:
        simulator = DockerSimulator(repo_id=repo_id, port=port, image_name=image_name, logger=logger)
    except Exception as e:
        logger.info(f"Simulator start error -- {repo_id} -- {repr(e)}")
        raise e
    logger.info(f"Starting container for {repo_id}...")
    try:
        conn = rpyc.connect(
            "localhost", port, keepalive=True, config={"sync_request_timeout": 180}
        )
    except Exception as e:
        logger.info(f"Connection error -- {repo_id} -- {repr(e)}")
        simulator.stop_container()
        raise e
    return simulator, conn

def init_docker(repo_name, image_name, logger):
    port = random.randint(3000, 10000) # Random port
    #print(f"PORT NUMBER IS: {port} !!!!!!!!!!!!!!\n")
    try:
        assert logger is not None
        simulator, conn = get_service(repo_name, port, image_name, logger)
        return simulator, conn
    except Exception as e:
        logger.info(f"Service error -- {repo_name} -- {repr(e)}")
        raise e

def install_repo(url, logger):
    '''
    Clone, extract tests for, and install the repo at the given URL
    '''
    repo_name = url.split("/")[-1]
    repo_author = url.split("/")[-2]
    repo_id = repo_author + "___" + repo_name
    image_name = "r2e:temp_" + repo_name
    #repo_path = "~/buckets/local_repoeval_bucket/repos/" + repo_id
    repo_path = REPOS_DIR / repo_id

    print(f"Installing on repo_path: {repo_path}\n")

    # Check if repo has already been installed
    for directory in [LOCAL_EVAL_DIR, REPOS_DIR, R2E_BUCKET_DIR, EXTRACTED_DATA_DIR, TESTGEN_DIR]:
        if not directory.exists():
            directory.mkdir()
            print(f"Newly created directory: {directory}\n")

    #cloned_repo_exists = os.path.exists(REPOS_DIR / repo_id)
    #extracted_tests_exist = os.path.exists(EXTRACTED_DATA_DIR / f"{repo_id}_extracted.json")
    testgen_exists = os.path.exists(TESTGEN_DIR / f"{repo_id}_generate.json")
    docker_image_exists = any([image_name in image.tags for image in client.images.list()])
    #setup_repo_already_done = cloned_repo_exists and extracted_tests_exist and testgen_exists
    # Important: cloned_repo_exists and extracted_tests_exist don't do anything right now. 
    # all that matters is whether the testgen file and docker image exist

    if not testgen_exists:
        setup_repo(url, repo_id, logger)
        logger.info("Testgen file not found. Running setup_repo...")
    else:
        logger.info("Skipping repository setup")

    if not docker_image_exists:
        setup_container(image_name, repo_id, logger)
    else:
        logger.info("Skipping dockerfile build")

    # check if path `logs/{image_name}_install_logs` exists
    if not os.path.exists(f"{logger_dir}/{repo_id}_install_logs"):
        logger.info("Transferring docker logs to host machine...")
        get_install_logs_from_image(image_name)

    try:
        simulator, conn = init_docker(repo_id, image_name, logger)
        #agentic_loop(image_name, repo_name, simulator, conn) # no agentic loop for now
        oracle_result, message = installation_oracle(simulator, conn, repo_id, logger)
        if oracle_result:
            # Print out successful repo
            logger.info(f"INSTALLATION SUCCEEDED: {repo_id}")
            return True
        else:
            # Print out failed repo
            logger.info(f"INSTALLATION FAILURE: {repo_id}")
            logger.error(f"FAILURE MODE: command = RUN ORACLE, output = {message}")
            #write_failure_mode(image_name, "(ran base installation)", output)
            return False
    except Exception as e:
        logger.error(f"Error installing repo: {repo_id}")
        logger.error(f"Exception: {e}")
        return False
    finally:
        # Always stop the container
        print("Closing connection and stopping container")
        simulator.stop_container()
        logger.info(f"Stopped container for {repo_id}")
        conn.close()
        print("Done with connection and container close")

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

def install_repo_from_url(url):
    repo_name = url.split("/")[-1]
    repo_author = url.split("/")[-2]
    repo_id = repo_author + "___" + repo_name
    image_name = "r2e:temp_" + repo_name

    logger = setup_logger(f"{logger_dir}/{repo_id}_install.log", repo_id)
    logger.info(f"Attempting to install: {url}\n")

    result = install_repo(url, logger)
    logger.info(f"Repo installation finished. Result: {result}")
    if not result:
        raise Exception(f"Installation failed for {url}")
    '''
    if result: # succeess
        total_succ += 1
    else:
        total_fails += 1
    '''
    #logger.info(f"Repo installation finished. Total successful installed: {total_succ}, total fails: {total_fails}\n")

# Define a function to handle the SIGINT signal (Ctrl+C)
def signal_handler(sig, frame):
    print("Caught SIGINT, terminating child processes...")
    
    # Terminate all child processes
    for process in mp.active_children():
        process.terminate()

    # Exit the main process
    sys.exit(0)
    
if __name__ == "__main__":
    try:
        # Open up urls.json and read the results as a list
        with open("nomodule_urls.json", "r") as f:
            urls = json.load(f)

        print(f"Attempting to install {len(urls)} repos")

        # TODO: Get total_fails, total_succ to work with multiprocessing
        # Might need to use locks? shared variables? 

        total_fails = 0
        total_succ = 0
        tot_len = len(urls)

        #signal.signal(signal.SIGINT, signal_handler)
        #parallel_execution(install_repo_from_url, urls, max_workers=2)

        outputs = run_tasks_in_parallel(
            install_repo_from_url,
            urls,
            num_workers=4,
            timeout_per_task=None,
            use_progress_bar=True,
            progress_bar_desc="Installing repos..."
        )
        print("*" * 50)
        print("Repo installations finished")
        print("Detailed breakdown of failures:")
        for x in outputs:
            if not x.is_success():
                print(f"Error: {x.exception_tb}")

        print("Quick breakdown (for more detailed info scroll up):")

        for i in range(len(urls)):
            url = urls[i]
            x = outputs[i]
            if x.is_success():
                print(f"URL {url} was a success")
            else:
                print(f"URL {url} was a failure, or was thrown out due to bad data")

    except Exception as e:
        print(f"Error: {e}")
