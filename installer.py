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

from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = docker.from_env()

def execute_command_with_timeout(container, command, repo_name, timeout=60):
    q = queue.Queue()
    def target():
        bash_command = f"bash -c {shlex.quote(command)}"
        path = '/repos' + '/' + repo_name
        print()
        print(f"Running command = {bash_command} at path {path}")
        exit_code, output = container.exec_run(bash_command, workdir=path)
        #print(f"Output to command was {output}")
        print()
        q.put((exit_code, output))

    thread = threading.Thread(target=target)
    thread.start()
    try:
        exit_code, output = q.get(timeout=timeout)
        return exit_code, output.decode('utf-8')
    except queue.Empty:
        return -1, "Command timed out"


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

def installation_oracle(container):
    # This function abstracts the verification command

    exec_args = ExecutionArgs(
        testgen_exp_id="temp_generate",
        execution_multiprocess=0,  # Replace with your desired number of processes
        image_name="r2e:placeholder3"
    )

    print(f"Running Oracle self-equivalence test...")
    # Run the self_equiv function
    run_self_equiv(exec_args, container)

    # This file contains the output of the execution
    #command = f"python r2e/execution/run_self_equiv.py --testgen_exp_id temp_generate --image_name {image_name} --execution_multiprocess 0"
    try:
        print(f"Checking execution status...")
        success, message = check_execution_status("/home/vkethana/buckets/r2e_bucket/testgen/temp_generate_out.json")
        print(success, message)
        return success, message
        '''
        #process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

        # Display output in real-time
        full_output = ""
        for line in process.stdout:
            print(line, end='')  # Print each line as it's produced
            full_output += line

        # Wait for the process to complete and get the return code
        return_code = process.wait()
        '''

    except Exception as e:
        print(f"\nOracle result: ERROR; Exception: {e}")
        return f"ERROR: {e}"

def llm_suggest_next_command(context, last_command, last_output, oracle_result):
    msg_content = f"""
    Context: {context}
    Last command executed: {last_command}
    Output/Error: {last_output}
    Oracle result: {oracle_result}

    1) Suggest the next command to run in the Docker container to complete the installation process.
    2) The repo in question is already partially installed in the Docker container at /repos/{repo_name}. You may assume that you are CDed into this directory automatically. The repo may already contain a `.venv` which you can activate.
    3) The installation is complete if and only if the Oracle returns "INSTALLATION SUCCESSFUL".
    4) Important Note: Every shell command that you run is executed in a separate bash session in the Docker container. If you create any aliases or environment variables, make sure to save them to ~/.bashrc, otherwise the command will have no effect.
    5) Your response should be a shell command for the Docker container or 'RUN ORACLE TESTS'. When you write 'RUN ORACLE TESTS', the Oracle will be consulted to determine if the installation is complete. Submit 'RUN ORACLE TESTS' only when you believe the installation is complete. 'RUN ORACLE TESTS' cannot be run alongside other shell commands.
    6) Do not attempt to run the Oracle directly, as it is located somewhere that you cannot access. The Oracle will be automatically consulted for you if you say, 'RUN ORACLE TESTS'.
    """
    response = openai_client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "You are an AI assistant helping to complete the installation process of a partially-installed repo within a Docker container. Read the following instructions, which will help guide you to suggest the next command to run in the Docker container. Do NOT include any reasoning in your response. Simply include a terminal command to be executed or the words 'RUN ORACLE TESTS'. Do NOT attempt to format your response in Markdown; for example, do NOT include ``` backticks."},
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

def complete_installation(image_name, repo_name):
    container = client.containers.run(
        image_name,
        command="/bin/bash",
        stdin_open=True,
        tty=True,
        detach=True
    )

    try:
        context = f"Docker image: {image_name}. Partially-installed repo can be found at: /repos/{repo_name}"
        last_command = "Initial setup"
        last_output = "Container created"
        oracle_result = "Not yet consulted"

        while True:
            print("Asking LLM for next command...")
            next_command = llm_suggest_next_command(context, last_command, last_output, oracle_result)
            print(f"Result: {next_command}")

            if next_command == "RUN ORACLE TESTS":
                print("Consulting the Oracle...")
                oracle_result, message = installation_oracle(container)
                print(f"Oracle result: {oracle_result}")
                last_command = next_command
                last_output = "N/A; Oracle was consulted"

                if oracle_result:
                    print("Installation completed successfully according to the Oracle.")
                    break

            else:
                exit_code, output = execute_command_with_timeout(container, next_command, repo_name)

                if exit_code != 0:
                    print(f"Command failed with exit code {exit_code}")
                    print(f"Output: {output}")
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
        container.stop()
        container.remove()

if __name__ == "__main__":
    #url = ""
    #image_name = input("Enter the Docker image name: ")
    #repo_name = input("Enter the repo name: ")
    image_name = "r2e:placeholder3"
    repo_name = "bad-repo-2"
    complete_installation(image_name, repo_name)
