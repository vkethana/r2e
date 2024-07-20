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

def get_service(repo_id: str, port: int, image_name: str, container) -> tuple[DockerSimulator, rpyc.Connection]:
    simulator = DockerSimulator(repo_id=repo_id, port=port, image_name=image_name)
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
    fut: FunctionUnderTest | MethodUnderTest, port: int, image_name: str, container
) -> tuple[bool, str, FunctionUnderTest | MethodUnderTest]:
    try:
        simulator, conn = get_service(fut.repo_id, port, image_name, container)
    except Exception as e:
        print("Service error@", fut.repo_id, repr(e))
        fut.test_history.update_exec_stats({"error": repr(e)})
        return False, repr(e), fut
    try:
        return self_equiv_futs([fut], conn)
    except Exception as e:
        tb = traceback.format_exc()
        pass
    finally:
        simulator.stop_container()
        conn.close()

    fut.test_history.update_exec_stats({"error": tb})
    #print(f"Error@{fut.repo_id}:\n{tb}")
    return False, tb, fut

def run_fut_mp(args: tuple[FunctionUnderTest | MethodUnderTest, str]) -> tuple[bool, str, FunctionUnderTest | MethodUnderTest]:
    fut, image_name = args
    ## TODO: selected a random port, can collide with other processes!
    port = random.randint(3000, 10000)
    output = run_fut_with_port(fut, port, image_name)
    return output

def run_self_equiv(exec_args: ExecutionArgs, container=None):
    futs = load_functions_under_test(TESTGEN_DIR / f"{exec_args.testgen_exp_id}.json")
    #futs = Tests(tests={})
    '''
    for fut in futs:
       fut.test_history.history = [{}] # << edit this as per the type
    '''
    #print(futs)
    #print(type(futs))
    #sample_test = Function(function_id="", file="")
    #futs = Tests(tests={"": "", "": "", "": ""})
    #print(futs)
    #print(type(futs))

    new_futs = []
    image_name = exec_args.image_name
    #image_name = "r2e:jul12"
    if exec_args.execution_multiprocess == 0:
        i = 0
        for fut in futs:
            i += 1
            port = exec_args.port
            try:
                #output = run_fut_with_port(fut, port, exec_args.image_name)
                #print("Passing in fut ", fut)
                output = run_fut_with_port(fut, port, image_name, container)
            except Exception as e:
                print(f"Error@{fut.repo_id}:\n{repr(e)}")
                tb = traceback.format_exc()
                print(tb)
                continue
            '''
            if (output[0]):
                print(f"Test {i} passed successfully!")
            else:
                print(f"ERROR: Test {i} failed!")
                print("Result of failed test:", output[1])
            '''
            #print("Result of FUT, 2: ", output[2]) #output[2] is the raw FUT object, 
            # which in most cases you dont need to actually see
            new_futs.append(output[2])
    else:
        print(1/0) # DONT USE MULTIPROCESSING RN!
        outputs = run_tasks_in_parallel_iter(
            run_fut_mp,
            [(i, image_name) for i in futs],
            num_workers=exec_args.execution_multiprocess,
            timeout_per_task=exec_args.timeout_per_task,
            use_progress_bar=True,
        )
        for x in outputs:
            if x.is_success():
                new_futs.append(x.result[2])  # type: ignore
            else:
                print(f"Error: {x.exception_tb}")
    write_functions_under_test(
        new_futs, TESTGEN_DIR / f"{exec_args.testgen_exp_id}_out.json"
    )


if __name__ == "__main__":
    exec_args = fire.Fire(ExecutionArgs)
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    run_self_equiv(exec_args)
