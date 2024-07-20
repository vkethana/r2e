from r2e.execution.run_self_equiv import run_self_equiv
from r2e.execution.execution_args import ExecutionArgs

def main():
    # Create an ExecutionArgs object with the desired parameters
    exec_args = ExecutionArgs(
        testgen_exp_id="temp_generate",
        execution_multiprocess=0,  # Replace with your desired number of processes
        image_name="r2e:placeholder3"
    )

    # Run the self_equiv function
    run_self_equiv(exec_args)

if __name__ == "__main__":
    main()

