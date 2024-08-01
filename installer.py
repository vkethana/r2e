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

from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs
from r2e.execution.r2e_simulator import DockerSimulator
from r2e.execution.execute_futs import self_equiv_futs

from setup_installer import setup_repo, setup_container
from r2e.paths import R2E_BUCKET_DIR

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()

# Check the logs directory and make it if it doesn't exist
if not os.path.exists("logs"):
    os.makedirs("logs")

# Set up the basic configuration for logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s %(name)s %(levelname)s %(message)s (%(filename)s:%(lineno)d)',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    handlers=[
                        logging.FileHandler("logs/1_repo.log"),
                        logging.StreamHandler()
                    ])

# Create a logger object
logger = logging.getLogger(__name__)
logger.info("This is an info message")
logger.warning("This is a warning message")
logger.error("This is an error message")

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

def agentic_loop(image_name, repo_name, simulator, conn):
    oracle_failures = 0
    try:
        context = f"Docker image: {image_name}. Partially-installed repo can be found at: /repos/{repo_name}"
        last_command = "Initial setup"
        last_output = "Container created"
        oracle_result = "Not yet consulted"
        user_command = None

        while True:
            print("*" * 50)
            print("Asking LLM for next command...")
            if user_command:
                next_command = user_command
                print("Using user-suggested command:", next_command)
                user_command = None
            else:
                next_command = llm_suggest_next_command(context, last_command, last_output, oracle_result)
            # Put the color in green
            print(f"\033[92mSuggested command: {next_command}\033[0m")
             
            if oracle_failures >= 10:
                raise RuntimeError(f"Oracle has failed 10. Skipping {repo_name} installation.")
            

            if next_command == "RUN ORACLE":
                #  CASE 1: Run the Oracle
                logger.info("Consulting the Oracle...")
                oracle_result, message = installation_oracle(simulator, conn)
                logger.info(f"Oracle result: {oracle_result}")
                logger.info(f"Oracle message: {message}")
                last_command = next_command
                last_output = "N/A; Oracle was consulted"

                if oracle_result:
                    logger.info(f"Installation of {image_name} completed successfully according to the Oracle.")
                    break
                else:
                    oracle_failures += 1
                    logger.error(f"FAILURE MODE: command = RUN ORACLE, output={message}")
            else:
                # CASE 2: Run the suggested command
                bash_command = "source .venv/bin/activate && " + next_command
                bash_command = f"bash -c {shlex.quote(bash_command)}"
                exit_code, output = simulator.run_single_command(bash_command)
                output = output.decode('utf-8')

                if exit_code != 0:
                    print(f"Command {bash_command} failed with exit code {exit_code}")
                    print("Output:")
                    print("*" * 50)
                    print(output)
                    print("*" * 50)

                    # Write this to failures/<image_name>_failures.json
                    logger.error(f"FAILURE MODE: command = {bash_command}, output = {output}")

                    if exit_code == -1 or "critical error" in output.lower():
                        human_command = human_intervention(context, next_command, output, oracle_result)
                        if human_command.upper() == 'ABORT':
                            print("Installation aborted by human intervention")
                            break
                        next_command = human_command
                else:
                    print(f"Command {bash_command} succeeded with exit code {exit_code} and output {output}")

                last_command = next_command
                last_output = output
                message = "N/A; Oracle was not consulted in previous round"

            context += f"\nExecuted: {last_command}\nResult: {last_output}\nOracle: {message}"
            logger.debug(f"Context updated to: {context}")

            try:
                cont = inputimeout(prompt="Press Enter to continue the installation or 'q' to quit or 'm' to manually suggest a command: ", timeout=0.5)
            except TimeoutOccurred:
                cont = ''

            if cont.lower() == 'q':
                print("Installation aborted by user")
                break
            if cont.lower() == 'm':
                print("Warning: Manual entry of commands is still a work in progress feature.")
                user_command = input("Please suggest the next command for the Docker container: ")

    finally:
        simulator.stop_container()

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

    # Check if repo has already been inst
    #setup_repo(url)
    #setup_container(image_name)

    simulator, conn = init_docker(repo_id, image_name, logger)
    #agentic_loop(image_name, repo_name, simulator, conn) # no agentic loop for now
    oracle_result, message = installation_oracle(simulator, conn)
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

if __name__ == "__main__":
    # Open up urls.json and read the results as a list
    with open("urls.json", "r") as f:
        urls = json.load(f)

    logger.info(f"Attempting to install {len(urls)} repos")
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

    logger.info(f"Detected installed repos: {installed_repos}")
    logger.info("Removing already-installed repos from list...")
    urls = [url for url in urls if url not in installed_repos]
    logger.info(f"Attempting to install {len(urls)} repos")

    total_fails = 0
    total_succ = 0
    tot_len = len(urls)
    for url in urls:
        assert url not in installed_repos
        logger.info(f"Attempting to install: {url}")
        repo_name = url.split("/")[-1]
        repo_author = url.split("/")[-2]
        repo_id = repo_author + "___" + repo_name
        image_name = "r2e:temp_" + repo_name
        try:
            result = install_repo(url, logger)
            if result: # succeess
                total_succ += 1
                # Open the file installed_repos.json and write the repo name
                with open("installed_repos.json", "a") as f:
                    f.write(url + "\n")
            else:
                total_fails += 1
        except Exception as e:
            total_fails += 1
            logger.info(f"Error message is: {repr(e)}")
            error_trace = traceback.format_exc()
            logger.info("FAILURE MODE: command = (attempted to run installer), output = {error_trace}")
        logger.info(f"Repo installation finished. Total successful installed: {total_succ}, total fails: {total_fails}")
    logger.info(f"Among {tot_len} repos, {total_fails} installations failed")
