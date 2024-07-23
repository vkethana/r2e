import docker
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

from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs
from r2e.execution.r2e_simulator import DockerSimulator
from r2e.execution.execute_futs import self_equiv_futs

from setup_installer import setup_repo, setup_container

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()

def check_execution_status(execution_output_path="/home/vkethana/buckets/r2e_bucket/testgen/temp_generate_out.json"):
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
                # If we find a success, set the flag
                elif "success" in exec_stats.lower():
                    any_success = True
    
    # If we've seen at least one success and no errors, return "INSTALLATION SUCCESSFUL"
    if any_success:
        return True, None
    
    # If we haven't seen any exec_stats or they were all None, return a neutral message
    print("WARNING: NO ERROR OR SUCCESS MESSAGES FOUND")
    return False, "No error or success messages found"

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
        success, message = check_execution_status("/home/vkethana/buckets/r2e_bucket/testgen/temp_generate_out.json")
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
    try:
        context = f"Docker image: {image_name}. Partially-installed repo can be found at: /repos/{repo_name}"
        last_command = "Initial setup"
        last_output = "Container created"
        oracle_result = "Not yet consulted"

        while True:
            num_consecutive_failures = 0
            print("*" * 50)
            print("Asking LLM for next command...")
            next_command = llm_suggest_next_command(context, last_command, last_output, oracle_result)
            # Put the color in green
            print(f"\033[92mSuggested command: {next_command}\033[0m")
            ''' 
            if num_consecutive_failures >= 5:
                print("Oracle has failed 5 times in a row")
            '''

            if next_command == "RUN ORACLE":
                #  CASE 1: Run the Oracle
                print("Consulting the Oracle...")
                oracle_result, message = installation_oracle(simulator, conn)
                print(f"Oracle result: {oracle_result}")
                last_command = next_command
                last_output = "N/A; Oracle was consulted"

                if oracle_result:
                    print("Installation completed successfully according to the Oracle.")
                    break
                else:
                    with open(f"~/buckets/local_repoeval_bucket/failures/{image_name}_failures.json", "a") as f:
                        f.write(json.dumps({
                            "command": "RUN ORACLE",
                            "output": output
                        }) + "\n")
                    #num_consecutive_failures += 1
                    pass

            else:
                #num_consecutive_failures = 0
                # CASE 2: Run the suggested command
                bash_command = "printenv && source .venv/bin/activate && " + next_command
                bash_command = f"bash -c {shlex.quote(bash_command)}"
                exit_code, output = simulator.run_single_command(bash_command)
                output = output.decode('utf-8')

                if exit_code != 0:
                    print(f"Command failed with exit code {exit_code}")
                    print("Output:")
                    print("*" * 50)
                    print(output)
                    print("*" * 50)

                    # Write this to failures/<image_name>_failures.json
                    with open(f"failures/{image_name}_failures.json", "a") as f:
                        f.write(json.dumps({
                            "command": bash_command,
                            "output": output
                        }) + "\n")

                    if exit_code == -1 or "critical error" in output.lower():
                        human_command = human_intervention(context, next_command, output, oracle_result)
                        if human_command.upper() == 'ABORT':
                            print("Installation aborted by human intervention")
                            break
                        next_command = human_command
                else:
                    print(f"Output: {output}")
                    print("Command was executed successfully.")

                last_command = next_command
                last_output = output
                message = "N/A; Oracle was not consulted in previous round"

            context += f"\nExecuted: {last_command}\nResult: {last_output}\nOracle: {message}"

            cont = input("Press Enter to continue the installation or 'q' to quit: ")
            if cont.lower() == 'q':
                print("Installation aborted by user")
                break

    finally:
        simulator.stop_container()

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

def install_repo(url):
    '''
    Clone, extract tests for, and install the repo at the given URL
    '''
    repo_name = url.split("/")[-1]
    repo_author = url.split("/")[-2]
    repo_id = repo_author + "___" + repo_name
    image_name = "r2e:temp_" + repo_name

    #setup_repo(url)
    #setup_container(image_name)

    simulator, conn = init_docker(repo_id, image_name)
    agentic_loop(image_name, repo_name, simulator, conn)
    print(f"Installation completed for repo with image name {image_name}")

if __name__ == "__main__":
    urls = ["https://github.com/numpy/numpy", "https://github.com/pallets/jinja", "https://github.com/pallets/flask", "https://github.com/pallets/jinja"]

    #for url in urls:
    url = urls[1]
    print("Attempting to install:", url)
    install_repo(url)
