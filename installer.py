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
import time
from concurrent.futures import ProcessPoolExecutor
import signal
import tarfile

from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs
from r2e.execution.r2e_simulator import DockerSimulator
from r2e.execution.execute_futs import self_equiv_futs
from r2e.multiprocess import run_tasks_in_parallel

from installer_utils import *
from r2e.paths import R2E_BUCKET_DIR, TESTGEN_DIR, REPOS_DIR, EXTRACTED_DATA_DIR, LOCAL_EVAL_DIR, LOGGER_DIR, config

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()
url_list = config["url_list"]
oracle_num_workers = config["oracle_num_workers"]
installer_num_workers = config["installer_num_workers"]


def installation_oracle(simulator, conn, repo_id, logger):
    # This function abstracts the verification command
    exec_args = ExecutionArgs(
        testgen_exp_id=f"{repo_id}_generate",
        execution_multiprocess=oracle_num_workers,  # Replace with your desired number of processes
        image_name=f"r2e:temp_{repo_id.split('___')[-1]}",
    )

    logger.debug(f"Running Oracle self-equivalence test...")
    # Run the self_equiv function
    run_self_equiv(exec_args, simulator, conn, logger)
    logger.debug("Done running self-equivalence test")

    # This file contains the output of the execution
    #command = f"python r2e/execution/run_self_equiv.py --testgen_exp_id temp_generate --image_name {image_name} --execution_multiprocess 0"
    try:
        logger.debug(f"Checking execution status...")
        num_passed_tests, num_total_tests = analyze_tests(str(TESTGEN_DIR) + f"/{repo_id}_generate_out.json", logger)

        if num_total_tests == 0:
            logger.error("BLANK REPO ERROR: Repo should be discarded. It has no Python files to test")
            return 0

        if num_total_tests < 5:
            logger.warning("Repo is very small, as it only contains < 5 tests. Consider discarding")

        return num_passed_tests/num_total_tests

    except Exception as e:
        logger.error(f"Encountered error when checking execution status: {e}")
        return 0


'''
The below two methods are used to instantiate the docker container and rpyc connection
'''
def get_service(repo_id: str, port: int, image_name: str, logger: None) -> tuple[DockerSimulator, rpyc.Connection]:
    try:
        simulator = DockerSimulator(repo_id=repo_id, port=port, image_name=image_name, logger=logger)
    except Exception as e:
        logger.error(f"Simulator start error -- {repo_id} -- {repr(e)}")
        raise e
    logger.debug(f"Starting container for {repo_id}...")
    try:
        conn = rpyc.connect(
            "localhost", port, keepalive=True, config={"sync_request_timeout": 180}
        )
    except Exception as e:
        logger.error(f"Connection error -- {repo_id} -- {repr(e)}")
        simulator.stop_container()
        raise e
    return simulator, conn

def init_docker(repo_name, image_name, logger):
    #port = random.randint(3000, 10000) # Random port
    port = 3001
    #print(f"PORT NUMBER IS: {port} !!!!!!!!!!!!!!\n")
    try:
        assert logger is not None
        simulator, conn = get_service(repo_name, port, image_name, logger)
        return simulator, conn
    except Exception as e:
        logger.error(f"Service error -- {repo_name} -- {repr(e)}")
        raise e

def install_repo(url):
    '''
    Clone, extract tests for, and install the repo at the given URL
    '''
    repo_name = url.split("/")[-1]
    repo_author = url.split("/")[-2]
    repo_id = repo_author + "___" + repo_name
    image_name = "r2e:temp_" + repo_name
    #repo_path = "~/buckets/local_repoeval_bucket/repos/" + repo_id
    repo_path = REPOS_DIR / repo_id

    logger = setup_logger(f"{repo_id}_install.log", repo_id)

    logger.info(f"Attempting to install: {url}\n")

    # Check if repo has already been installed
    for directory in [LOCAL_EVAL_DIR, REPOS_DIR, R2E_BUCKET_DIR, EXTRACTED_DATA_DIR, TESTGEN_DIR]:
        if not directory.exists():
            directory.mkdir()
            logger.debug(f"Newly created directory: {directory}\n")

    #cloned_repo_exists = os.path.exists(REPOS_DIR / repo_id)
    #extracted_tests_exist = os.path.exists(EXTRACTED_DATA_DIR / f"{repo_id}_extracted.json")
    #testgen_exists = os.path.exists(TESTGEN_DIR / f"{repo_id}_generate.json")
    #docker_image_exists = any([image_name in image.tags for image in client.images.list()])
    testgen_exists = False
    docker_image_exists = False
    #setup_repo_already_done = cloned_repo_exists and extracted_tests_exist and testgen_exists
    # Important: cloned_repo_exists and extracted_tests_exist don't do anything right now. 
    # all that matters is whether the testgen file and docker image exist

    if not testgen_exists:
        success = setup_repo(url, repo_id, logger)
        logger.info("Testgen file not found. Running setup_repo...")
        if not success:
            logger.info(f"INSTALLATION FAILURE: {repo_id}")
            return False
    else:
        logger.info("Skipping repository setup")

    if not docker_image_exists:
        logger.info("Building docker image...")
        setup_container(image_name, repo_id, logger)
    else:
        logger.info("Skipping dockerfile build")

    if not os.path.exists(f"{logger_dir}/{repo_id}_install_logs/"):
        logger.info("Transferring docker logs to host machine...")
        get_install_logs_from_image(image_name)

    did_install_pass = False

    try:
        if oracle_num_workers == 0:
            simulator, conn = init_docker(repo_id, image_name, logger)
        else:
            simulator, conn = None, None
        #agentic_loop(image_name, repo_name, simulator, conn) # no agentic loop for now

        ratio = installation_oracle(simulator, conn, repo_id, logger)
        logger.info(f"Repo has FUT success ratio of {round(ratio, 3)}")

        oracle_result = ratio >= 0.95
        if oracle_result:
            # Print out successful repo
            logger.info(f"INSTALLATION SUCCEEDED: {repo_id}")
            did_install_pass = True
        else:
            # Print out failed repo
            logger.info(f"INSTALLATION FAILURE: {repo_id}")
            # No need to update did_install_pass because we assume repos fail by default


    except Exception as e:
        repo_id_str = repo_id if repo_id is not None else "Unknown repo_id"
        logger.error(f"Error installing repo: {repo_id_str}")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception args: {e.args}")
        logger.error(f"The error of above repo: {e}")
        logger.error("Traceback information:")
        logger.error(traceback.format_exc())


    finally:
        # Always stop the container
        if simulator:
            print("Closing connection and stopping container")
            simulator.stop_container()
            logger.debug(f"Stopped container for {repo_id}")
        if conn:
            conn.close()
        print("Done with connection and container close")

    return did_install_pass

# Define a function to handle the SIGINT signal (Ctrl+C)
def signal_handler(sig, frame):
    print("Caught SIGINT, terminating child processes...")

    # Terminate all child processes
    for process in mp.active_children():
        process.terminate()

    # Exit the main process
    sys.exit(0)

if __name__ == "__main__":
    # Open up urls.json and read the results as a list
    # Open up urls.json and read the results as a list
    with open(url_list, "r") as f:
        urls = json.load(f)

    print(f"Attempting to install {len(urls)} repos")

    total_fails = 0
    total_succ = 0
    tot_len = len(urls)

    def prune_docker():
        try:
            print("Pruning Docker.")
            # 4 minutes timeout
            proc = subprocess.Popen(["docker", "system", "prune", "-a", "-f", "--volumes"], stdout=subprocess.PIPE)
            t = 240
            try:
                stdout = proc.communicate(timeout=t)
                return stdout
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout = proc.communicate()
                print(f"Pruning process killed due to timeout of {t}.")
                return stdout
        except Exception as e:
            print(f"An error occurred: {e}")

    # Install repos in 50 piecemeal
    segment_size = 50
    for start in range(0, len(urls), segment_size):
        end = min(start + segment_size, len(urls))
        segment_urls = urls[start:end]

        print(f"Installing segment {start + 1} to {end}...")

        # Confirm cleaning process
        print("CHECK: current disk usage at: ")
        subprocess.run(["df", "-h"])
        prune_confirm = input("Do you want to prune Docker before continuing? (y/n): ").strip().lower()
        if prune_confirm == 'y':
            prune_docker()
        else:
            print("Skip pruning. Beware of space management.")

        # For each segment run this
        outputs = run_tasks_in_parallel(
            install_repo,
            segment_urls,
            num_workers=installer_num_workers,
            timeout_per_task=3000,
            use_progress_bar=True,
            progress_bar_desc=f"Installing repos {start + 1} to {end}..."
        )

        # Kept the original analysis 
        for i in range(len(segment_urls)):
            url = segment_urls[i]
            x = outputs[i]
            if x.is_success():
                if x.result:
                    print(f"URL {url} was a success")
                    total_succ += 1
                else:
                    print(f"URL {url} was a failure")
                    total_fails += 1
            else:
                print(f"URL {url} ran into an error during installation")
                total_fails += 1

        print(f"Segment {start + 1} to {end} completed.")
        print(f"Total successes so far: {total_succ}/{tot_len}")
        print(f"Total failures so far: {total_fails}/{tot_len}")

    # Pause before starting the next segment
    pause_confirm = input("Press Enter to continue to the next segment or 'q' to quit: ").strip().lower()
    if pause_confirm == 'q':
        print("Exiting installation process.")
        sys.exit()
    else:
        print("Continuing with the next segment.")

    print(f"Total successes: {total_succ}/{tot_len}")
    print(f"Total failures: {total_fails}/{tot_len}")
