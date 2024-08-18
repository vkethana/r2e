import rpyc
import uuid
import random
import traceback
from pathlib import Path
from io import StringIO

import fire

from r2e.paths import TESTGEN_DIR, EXECUTION_DIR
from r2e.multiprocess import run_tasks_in_parallel_iter
from r2e.execution.execution_args import ExecutionArgs
from r2e.execution.r2e_simulator import DockerSimulator
from r2e.execution.execute_futs import self_equiv_futs
from r2e.models import FunctionUnderTest, MethodUnderTest
from r2e.utils.data import load_functions_under_test, write_functions_under_test
from r2e.models import Tests
from r2e.models import Function

import logging

def get_service(repo_id: str, port: int, image_name: str, logger: any) -> tuple[DockerSimulator, rpyc.Connection]:
    simulator = DockerSimulator(repo_id=repo_id, port=port, image_name=image_name, logger=logger)
    try:
        conn = rpyc.connect(
            "localhost", port, keepalive=True, config={"sync_request_timeout": 180}
        )
    except Exception as e:
        print(f"Connection error -- {repo_id} -- {repr(e)}")
        simulator.stop_container()
        raise e
    return simulator, conn


def run_fut_with_port(
    fut: FunctionUnderTest | MethodUnderTest, simulator, conn) -> tuple[bool, str, FunctionUnderTest | MethodUnderTest]:
    try:
        return self_equiv_futs([fut], conn)
    except Exception as e:
        tb = traceback.format_exc()
        pass
    finally:
        #simulator.stop_container()
        #conn.close()
        pass

    fut.test_history.update_exec_stats({"error": tb})
    print(f"Error@{fut.repo_id}:\n{tb}")
    return False, tb, fut

def run_fut_mp(args: tuple[FunctionUnderTest | MethodUnderTest, str, int]) -> tuple[bool, str, FunctionUnderTest | MethodUnderTest] | None:
    fut = args[0]
    image_name = args[1]
    i = args[2]

    port = random.randint(3000, 10000)

    log_stream = StringIO()
    second_logger = logging.getLogger(f"logger_{image_name}_{i}")
    handler = logging.StreamHandler(log_stream)
    second_logger.setLevel(logging.DEBUG)
    second_logger.addHandler(handler)
    second_logger.info("Logger initialized")

    try:
        second_logger.debug(f"Getting service for {fut.repo_id}")
        simulator, conn = get_service(fut.repo_id, port, image_name, second_logger)

    except Exception as e:
        fut.test_history.update_exec_stats({"error": repr(e)})
        print("Service error@", fut.repo_id, repr(e))
        second_logger.debug("Service error@", fut.repo_id, repr(e))
        # Get the log output
        log_contents = log_stream.getvalue()
        second_logger.removeHandler(handler)
        handler.close()

        return False, repr(e), fut, log_contents

    print("Got service successfully")
    second_logger.debug("Got service successfully")
    try:
        log_contents = log_stream.getvalue()
        second_logger.removeHandler(handler)
        handler.close()

        print("Running self equiv futs")
        res = self_equiv_futs([fut], conn)
        res = (res[0], res[1], res[2], log_contents)
        return res

    except Exception as e:
        tb = traceback.format_exc()
        pass

    finally:
        simulator.stop_container()
        conn.close()

    print("Running self equiv futs failed: ", tb)
    second_logger.debug("Running self equiv futs failed: ", tb)

    log_contents = log_stream.getvalue()
    second_logger.removeHandler(handler)
    handler.close()

    fut.test_history.update_exec_stats({"error": tb})
    print(f"Error@{fut.repo_id}:\n{tb}")
    return False, tb, fut, log_contents


def run_self_equiv(exec_args, simulator, conn, logger):
    logger.info(f"Running FUTs from {exec_args.testgen_exp_id}.json")

    if simulator is None or conn is None:
        logger.debug(f"Simulator or connection is currently undefined. This is fine as long as you intended to run the FUTs in parallel. In that case the simulator and connection objects will be created later on")
    futs = load_functions_under_test(TESTGEN_DIR / f"{exec_args.testgen_exp_id}.json")
    logger.info(f"There are {len(futs)} FUTs to run.")
    #futs = Tests(tests={})
    '''
    for fut in futs:
       fut.test_history.history = [{}] # << edit this as per the type
    '''
    #print("PRINTING OUT FUTS", futs)
    #print(type(futs))
    #sample_test = Function(function_id="", file="")
    #futs = Tests(tests={"": "", "": "", "": ""})
    #print(futs)
    #print(type(futs))

    new_futs = []
    image_name = exec_args.image_name
    #image_name = "r2e:jul12"
    num_fails = 0
    if exec_args.execution_multiprocess == 0:
        i = 0
        for fut in futs:
            i += 1
            try:
                #output = run_fut_with_port(fut, exec_args.image_name)
                logger.debug(f"Currently executing FUT: {fut}")
                output = run_fut_with_port(fut, simulator, conn)
            except Exception as e:
                logger.error(f"Error running FUT at {fut.repo_id}:{repr(e)}")
                tb = traceback.format_exc()
            if (output[0]):
                logger.info(f"Test {i} of {len(futs)} passed successfully!")
            else:
                logger.error(f"Test {i} of {len(futs)} failed!")
                logger.error(f"Output of failed test: {output[1]}")
                num_fails += 1
                logger.info(f"Total number of fails so far: {num_fails}")
                #print("Result of failed test:", output[1])
            #print("Result of FUT, 2: ", output[2]) #output[2] is the raw FUT object, 
            # which in most cases you dont need to actually see
            new_futs.append(output[2])
    else:
        logger.info(f"Running FUTs in parallel.")
        outputs = run_tasks_in_parallel_iter(
            run_fut_mp,
            [(futs[i], image_name, i) for i in range(len(futs))],
            num_workers=exec_args.execution_multiprocess,
            timeout_per_task=exec_args.timeout_per_task,
            use_progress_bar=True,
        )
        '''
        # Code for merging together sub-logs
        # not yet implemented
        with open(f"logs/fut_logs/{image_name.replace(':', '')}_merged.log", "w") as merged_log:
            for i in range(len(futs)):
                with open(f"logs/fut_logs/{image_name.replace(':', '')}_test_{i}.log", "r") as single_log:
                    merged_log.write(single_log.read())
                # remove the single log file
                Path(f"logs/fut_logs/{image_name.replace(':', '')}_test_{i}.log").unlink()
        '''
        i = 0
        logger.info(f"Done running FUTs in parallel.")

        # check if logs/fut_logs exists

        Path("logs/fut_logs").mkdir(parents=True, exist_ok=True)
        output_log_path = f"logs/fut_logs/{image_name.replace(':', '_')}_test_merged.log"

        with open(output_log_path, "a") as log_file:
            log_file.write(f" <<<<<<<< Logs for {image_name}:\n")

        for x in outputs:
            logger.debug(f"Appending test {i} of {len(futs)} to the testgen_out file...")
            logger.debug(f"Result of test was {x.result}")
            new_futs.append(x.result[2])  # type: ignore
            try:
                if x.result[3]:
                    logger_data = x.result[3]
                    # now log all that data to the logger
                    logger.info(f"FUT Execution Data: {logger_data}")
                    '''
                    with open(output_log_path, "a") as log_file:
                        log_file.write(logger_data)
                    '''
            except Exception as e:
                logger.error(f"Could not retreive FUT execution data for test {i} of {len(futs)}. Traceback: {e}")
            if not x.is_success():
                logger.error(f"Test {i} of {len(futs)} ran into a service error (result of the FUT is unknown; it could not be executed): {x.exception_tb}")
            i += 1

    write_functions_under_test(
        new_futs, TESTGEN_DIR / f"{exec_args.testgen_exp_id}_out.json"
    )


if __name__ == "__main__":
    exec_args = fire.Fire(ExecutionArgs)
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    #run_self_equiv(exec_args)
    print("You can't run this file directly anymore. Sorry.")
