"""
Borrowed and inspired from https://github.com/princeton-nlp/intercode/blob/master/intercode/envs/bash/bash_env.py
https://stackoverflow.com/questions/46390309/how-to-copy-a-file-from-host-to-container-using-docker-py-docker-sdk
"""

import io
import os
import tarfile
from time import sleep

import docker
from docker.models.containers import Container


class DockerSimulator:
    def __init__(
        self,
        image_name: str = "r2e_docker_v4",
        repo_id: str = "aider",
        port: int = 3006,
        command: str = "/bin/bash",
        logger: None = None,
        **docker_kwargs,
    ):
        self.logger = logger
        if self.logger is None:
            print("ERROR: LOGGER NOT FOUND")
        self.image_name = image_name
        self.repo_id = repo_id
        self.command = command
        self.client = docker.from_env()
        self.start_container(image_name, command, port, **docker_kwargs)
        self.workdir = f"/repos/{repo_id}"
        self.start_server(repo_id, port)

    def start_container(
        self, image_name: str, command: str, port: int, **docker_kwargs
    ):
        self.logger.info(f"Attempting to start image with id={image_name}")
        self.container: Container = self.client.containers.run(  # type: ignore
            image_name,
            command,
            detach=True,
            tty=True,
            ports={f"{port}/tcp": port},
            # network_mode="host",
            **docker_kwargs,
        )
        try:
            while self.container.status != "running":
                sleep(1)
                self.container.reload()
        except Exception as e:
            self.logger.info(f"Container start error {repr(e)}")
            self.stop_container()

    def run_single_command(self, command: str):
        output = ""
        try:
            exit_code, output = self.container.exec_run(
                command,
                workdir=self.workdir
                #timeout=100,
            )
            if exit_code != 0:
                self.logger.debug(f"r2e_simulator.py: repo_id = {self.repo_id} ran into error {command}")
            else:
                self.logger.debug(f"r2e_simulator.py: repo_id = {self.repo_id} ran {command} and got output {output}")
            return exit_code, output

        except Exception as e:
            self.logger.error(f"r2e_simulator.py: repo_id = {self.repo_id}, workdir = {self.workdir}. Ran {command} and got start error {repr(e)}")
            self.stop_container()
        return -1, "ERROR: Failed to execute command inside Docker container"

    def start_server(self, repo_id: str, port: int):
        # self.run_single_command("pip install pipreqs")
        # self.run_single_command(
        #     f"pipreqs --encoding=iso-8859-1 --ignore .venv --savepath new_reqs.txt --mode no-pin ."
        # )
        # self.run_single_command(".venv/bin/python -m pip install -r new_reqs.txt")

        #print("Running R2E test server...")
        self.logger.debug(f"Starting R2E test server for repo_id {self.repo_id}...")
        command = f"bash -c \
            'source .venv/bin/activate && ls && \
            r2e-test-server start --port {port} &\
            '"

        exit_code, output = self.run_single_command(command)
        self.logger.debug(f"Finished running R2E test server with exit code {exit_code} and output {output}...")

        # try:
        #     exit_code, output = self.container.exec_run(
        #         command,
        #         workdir=f"/repos/{repo_id}",
        #     )
        #     if exit_code != 0:
        #         pass
        #         # print("Server start error", output)
        #     else:
        #         pass
        #         # print("Server started")
        #         # print(output)
        # except Exception as e:
        #     print("Server start error", repr(e))
        #     print(command)
        #     self.stop_container()
        return

    def stop_container(self):
        self.logger.debug(f"Stopping image with id {self.repo_id}...")
        try:
            self.container.stop()
            self.container.remove()
        except Exception as erepo_id:
            self.logger.error(f"Container stop error {repr(e)}")


if __name__ == "__main__":
    ds = DockerSimulator()
