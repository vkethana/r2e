import os
import sys

from paths import REPOS_DIR, PDM_BIN_DIR
from multiprocess_utils import run_tasks_in_parallel_iter
from bash_utils import run_subprocess_shell
from install_single_repo import install_single_repo


def main():
    # Modify pdm

    start, end, parallel = sys.argv[1:4]
    start = int(start)
    end = int(end)
    parallel = int(parallel)

    print("Running subprocess to install dependencies...")
    result = run_subprocess_shell(
        f"export PATH={PDM_BIN_DIR} \
            && pip install setuptools\
            && pip install wheel\
            && pip install pipreqs\
        ",
    )
    print("Done!")
    try:
        print("Result: ", result)
    except Exception as e:
        print("Error: ", e)

    all_repos = sorted(os.listdir(REPOS_DIR))
    all_repos = all_repos[start:end]

    results = run_tasks_in_parallel_iter(
        install_single_repo,
        all_repos,
        num_workers=parallel,
        use_progress_bar=True,
    )

    for output in results:
        if output.is_success():
            pass
        else:
            print(output.exception_tb)


if __name__ == "__main__":
    main()