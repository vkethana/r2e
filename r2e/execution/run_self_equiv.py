import rpyc
import random
import traceback
from pathlib import Path

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
    #print(f"Error@{fut.repo_id}:\n{tb}")
    return False, tb, fut

def run_fut_mp(args: tuple[FunctionUnderTest | MethodUnderTest, str, any]) -> tuple[bool, str, FunctionUnderTest | MethodUnderTest]:
    fut = args[0]
    image_name = args[1]
    logger = args[2]
    logger.debug(f"Currently executing FUT: {fut}")

    port = random.randint(3000, 10000)

    try:
        simulator, conn = get_service(fut.repo_id, port, image_name, logger)
    except Exception as e:
        print("Service error@", fut.repo_id, repr(e))
        fut.test_history.update_exec_stats({"error": repr(e)})
        return False, repr(e), fut

    try:
        logger.debug(f"Currently executing FUT: {fut}")
        output = run_fut_with_port(fut, simulator, conn)
    except Exception as e:
        logger.error(f"Error running FUT at {fut.repo_id}:{repr(e)}")
        tb = traceback.format_exc()

    simulator.stop_container()
    conn.close()

    if (output[0]):
        logger.info(f"Test passed successfully!")
    else:
        logger.error(f"Test failed!")
        logger.error(f"Output of failed test: {output[1]}")
        raise(Exception("Test failed"))

    return output

def run_self_equiv(exec_args, simulator, conn, logger):
    logger.info(f"Running FUTs from {exec_args.testgen_exp_id}.json")
    print("simulator: ", simulator)
    assert (simulator != None)
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
            #port = exec_args.port
            try:
                #output = run_fut_with_port(fut, exec_args.image_name)
                logger.debug(f"Currently executing FUT: {fut}")
                output = run_fut_with_port(fut, simulator, conn)
            except Exception as e:
                logger.error(f"Error running FUT at {fut.repo_id}:{repr(e)}")
                tb = traceback.format_exc()
            if (output[0]):
                logger.info(f"Test {i} passed successfully!")
            else:
                logger.error(f"Test {i} failed!")
                logger.error(f"Output of failed test: {output[1]}")
                num_fails += 1
                #print("Result of failed test:", output[1])
            #print("Result of FUT, 2: ", output[2]) #output[2] is the raw FUT object, 
            # which in most cases you dont need to actually see
            new_futs.append(output[2])
    else:
        outputs = run_tasks_in_parallel_iter(
            run_fut_mp,
            [(i, image_name, logger) for i in futs],
            num_workers=exec_args.execution_multiprocess,
            timeout_per_task=exec_args.timeout_per_task,
            use_progress_bar=True,
        )
        i = 0
        for x in outputs:
            if x.is_success():
                logger.info(f"Test {i} passed successfully!")
                new_futs.append(x.result[2])  # type: ignore
            else:
                logger.error(f"Test {i} failed! Traceback: {x.exception_tb}")
            i += 1

    logger.info(f"Number of failed tests: {num_fails} out of {len(futs)} tests, pass rate is {round((len(futs) - num_fails)/len(futs), 2)}")
    write_functions_under_test(
        new_futs, TESTGEN_DIR / f"{exec_args.testgen_exp_id}_out.json"
    )


if __name__ == "__main__":
    exec_args = fire.Fire(ExecutionArgs)
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    #run_self_equiv(exec_args)
    print("You can't run this file directly anymore. Sorry.")
