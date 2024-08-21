import docker
import traceback

import fire
import re
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

#openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()
oracle_num_workers = config["oracle_num_workers"]
installer_num_workers = config["installer_num_workers"]

#Check the disk usage of /dev/root
def check_disk_usage():
    """Check the disk usage of /dev/root"""
    try:
        result = subprocess.run(["df", "-h"], stdout=subprocess.PIPE, text=True)
        output = result.stdout
        for line in output.splitlines():
            if '/dev/root' in line:
                used = int(re.search(r'(\d+)%', line).group(1))
                return used
    except Exception as e:
        print(f"An error occurred while checking disk usage: {e}")
        return None

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

def analyze_oracle_output(repo_id, logger):
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
    testgen_exists = os.path.exists(TESTGEN_DIR / f"{repo_id}_generate.json")
    docker_image_exists = any([image_name in image.tags for image in client.images.list()])
    #testgen_exists = False
    #docker_image_exists = False
    testgen_out_exists = os.path.exists(TESTGEN_DIR / f"{repo_id}_generate_out.json")
    #testgen_out_exists = False
    #setup_repo_already_done = cloned_repo_exists and extracted_tests_exist and testgen_exists
    # Important: cloned_repo_exists and extracted_tests_exist don't do anything right now. 
    # all that matters is whether the testgen file and docker image exist

    if not testgen_exists:
        logger.info("Testgen file not found. Running setup_repo...")
        success = setup_repo(url, repo_id, logger)
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
        # We can skip running the oracle if a testgen output already exists
        if not testgen_out_exists:
            if oracle_num_workers == 0:
                simulator, conn = init_docker(repo_id, image_name, logger)
            else:
                simulator, conn = None, None
            installation_oracle(simulator, conn, repo_id, logger)
        else:
            logger.info("Skipping Oracle tests because already run before")

        ratio = analyze_oracle_output(repo_id, logger)
        logger.info(f"Repo has FUT success ratio of {round(ratio, 3)}")
        oracle_result = ratio >= 0.95
        logger
        if oracle_result:
            # Print out successful repo
            logger.info(f"INSTALLATION SUCCEEDED: {repo_id}. SUCCESS RATIO: {ratio}")
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

def install_from_url_list(url_list, prune_timeout):
    with open(url_list, "r") as f:
        urls = json.load(f)

    print(f"Attempting to install {len(urls)} repos")

    total_fails = 0
    total_succ = 0
    tot_len = len(urls)

    def prune_docker(timeout=240):
        # Default timeout of 4 minutes
        try:
            print("Pruning Docker.")
            proc = subprocess.Popen(["docker", "system", "prune", "-a", "-f", "--volumes"], stdout=subprocess.PIPE)
            try:
                stdout = proc.communicate(timeout=timeout)
                return stdout
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout = proc.communicate()
                print(f"Pruning process killed due to timeout of {timeout}.")
                return stdout
        except Exception as e:
            print(f"An error occurred: {e}")

    # Install repos in 50 piecemeal
    segment_size = 50

    for start in range(500, len(urls), segment_size):
        end = min(start + segment_size, len(urls))
        segment_urls = urls[start:end]

        print(f"Installing segment {start + 1} to {end}...")

        used = check_disk_usage()
        print(f"[INFO] Current /dev/root disk usage: {used}% \n")

        # Confirm cleaning process at 50% usage cutoff
        if used > 50:
            prune_confirm = input("Do you want to prune Docker before continuing? (y/n): ").strip().lower()
            if prune_confirm == 'y':
                print(f"Start pruning with timeout: {prune_timeout}\n")
                prune_docker(timeout=prune_timeout)
            elif prune_confirm == 'n':
                print("Quitting installation.\n")
                sys.exit()
            else:
                print("Skipping pruning to continue. \n")
        else:
            print("Disk usage below 50%. Continuing.\n")


        # For each segment run this
        outputs = run_tasks_in_parallel(
            install_repo,
            segment_urls,
            num_workers=installer_num_workers,
            timeout_per_task=1800,
            use_progress_bar=True,
            progress_bar_desc=f"Installing repos {start + 1} to {end}..."
        )
 
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

if __name__ == "__main__":
    '''
    USAGE: python installer.py --url_list <url_list.json> --prune_timeout <t_seconds>
    '''
    fire.Fire(install_from_url_list)
