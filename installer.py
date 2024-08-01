import docker
import traceback

import multiprocessing
import os
import threading
import concurrent.futures
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

from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs
from r2e.execution.r2e_simulator import DockerSimulator
from r2e.execution.execute_futs import self_equiv_futs

from setup_installer import setup_repo, setup_container
from r2e.paths import R2E_BUCKET_DIR

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()

# Using multiprocessing for parallel installation
lock = multiprocessing.Lock()
manager = multiprocessing.Manager()
total_fails = manager.Value('i', 0)
total_succ = manager.Value('i', 0)
installed_repos = manager.list()

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

def check_execution_status(execution_output_path = str(R2E_BUCKET_DIR) + "/testgen/temp_generate_out.json"):
    # Read the JSON output file
    with open(execution_output_path, "r") as f:
        output = json.load(f)

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

def installation_oracle(simulator, conn):
    # This function abstracts the verification command

    exec_args = ExecutionArgs(
        testgen_exp_id="temp_generate",
        execution_multiprocess=0,  # Replace with your desired number of processes
        image_name="r2e:placeholder3"
    )

    print(f"Running Oracle self-equivalence test...")
    # Run the self_equiv function
    run_self_equiv(exec_args, simulator, conn)

    # This file contains the output of the execution
    #command = f"python r2e/execution/run_self_equiv.py --testgen_exp_id temp_generate --image_name {image_name} --execution_multiprocess 0"
    try:
        print(f"Checking execution status...")
        success, message = check_execution_status()
        print(success, message)
        return success, message

    except Exception as e:
        print(f"\nOracle result: ERROR; Exception: {e}")
        return f"ERROR: {e}"

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
def get_service(repo_id: str, port: int, image_name: str) -> tuple[DockerSimulator, rpyc.Connection]:
    simulator = DockerSimulator(repo_id=repo_id, port=port, image_name=image_name)
    print("Simulatr created successfully")
    try:
        conn = rpyc.connect(
            "localhost", port, keepalive=True, config={"sync_request_timeout": 180}
        )
    except Exception as e:
        print(f"Connection error -- {repo_id} -- {repr(e)}")
        simulator.stop_container()
        raise e
    return simulator, conn

def init_docker(repo_name, image_name):
    port = random.randint(3000, 10000) # Random port
    try:
        simulator, conn = get_service(repo_name, port, image_name)
        return simulator, conn
    except Exception as e:
        print(f"Service error -- {repo_name} -- {repr(e)}")
        raise e

def parallel_installer(url):
    global total_fails, total_succ
    repo_name = url.split("/")[-1]
    repo_author = url.split("/")[-2]
    image_name = "r2e:temp_" + repo_name

    with lock:
        if url in installed_repos:
            print(f"URL {url} is already installed. Skipping.")
            return
        installed_repos.append(url)

    print("Attempting to install:", url)
    
    try: 
        result = install_repo(url)
        if result: # success
            with lock:
                total_succ += 1
                with open("installed_repos.json", "a") as f:
                    f.write(url + "\n")
        else:
            with lock:
                total_fails += 1
    except Exception as e:
        with lock:
            total_fails += 1
        print("Error message is: ", e)
        error_trace = traceback.format_exc()
        write_failure_mode(image_name, "installation error", error_trace)

    with lock:
        print(f"Total successful installs: {total_succ}, total fails: {total_fails}")

def install_repo(url):
    '''
    Clone, extract tests for, and install the repo at the given URL
    '''
    repo_name = url.split("/")[-1]
    repo_author = url.split("/")[-2]
    repo_id = repo_author + "___" + repo_name
    image_name = "r2e:temp_" + repo_name

    # Check if repo has already been inst
    setup_repo(url)
    setup_container(image_name)

    simulator, conn = init_docker(repo_id, image_name)
    oracle_result, message = installation_oracle(simulator, conn)
    if oracle_result:
        # Print out successful repo
        print(f"INSTALLATION SUCCEEDED: {repo_id}")
        return True
    else:
        # Print out failed repo
        print(f"INSTALLATION FAILURE: {repo_id}")
        print(f"ERROR MESSAGE: {message}")
        write_failure_mode(image_name, "(ran base installation)", message)
        return False

if __name__ == "__main__":
    #Scale up repo counts here

    # Open up urls.json and read the results as a list
    with open("urls.json", "r") as f:
        urls = json.load(f)

    print(f"Attempting to install {len(urls)} repos")
    # also open installed_repos.json and read the results as a list
    # check if the file even exists
    if not os.path.exists("installed_repos.json"):
        with open("installed_repos.json", "w") as f:
            f.write("")

    with open("installed_repos.json", "r") as f:
        installed_repos = f.readlines()

    installed_repos = [i.replace("\n", "") for i in installed_repos]
    installed_repos = [i.replace(" ", "") for i in installed_repos]
    installed_repos = [i for i in installed_repos if i != ""]

    print("Detected installed repos:", installed_repos)
    print("Removing already-installed repos from list...")
    urls = [url for url in urls if url not in installed_repos]



    total_fails.value = 0
    total_succ.value = 0
    tot_len = len(urls)

    # Use multiprocessing for parallel execution
    with multiprocessing.Pool() as pool:
        print(f"Doing parallel installation on {tot_len} repositories.")
        pool.map(parallel_installer, urls)

    print(f"Among {tot_len} repos, {total_fails} installations failed")

