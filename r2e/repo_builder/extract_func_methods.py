import fire
import os
import re
from r2e.models import Repo
from r2e.utils.data import write_functions
from r2e.repo_builder.repo_args import RepoArgs
from r2e.paths import REPOS_DIR
from r2e.multiprocess import run_tasks_in_parallel_iter
from r2e.repo_builder.fut_extractor.extract_repo_data import extract_repo_data

def remove_bom_from_file(file_path):
    with open(file_path, 'rb') as file:
        content = file.read()
    if content.startswith(b'\xef\xbb\xbf'):
        content = content[3:]
        with open(file_path, 'wb') as file:
            file.write(content)

def remove_bom_from_directory(directory_path):
    for root, _, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            if file_path.endswith('.py'):  
                remove_bom_from_file(file_path)

#TODO: Modify extraction path -- DONE
def build_functions_and_methods(repo_args: RepoArgs):
    repo_name = repo_args.repo_url.split("/")[-1] 
    extraction_repo = REPOS_DIR / f"dir_{repo_name}" / "extracted_data"
    if not extraction_repo.exists():
        extraction_repo.mkdir(parents=True)

    extraction_path = extraction_repo / f"{repo_args.exp_id}_extracted.json"

    if extraction_path.exists():
        if repo_args.overwrite_extracted:
            print("Overwriting existing functions and methods. Interrupt to cancel!")
        else:
            print(
                "Extracted file already exists. Use --overwrite_extracted to overwrite existing."
            )
            return

    repo_dirs = list(REPOS_DIR.glob("dir*"))
    for repo_dir in repo_dirs:
        remove_bom_from_directory(str(repo_dir))  

    repos = [Repo.from_file_path(str(repo_dir)) for repo_dir in repo_dirs]

    functions = []
    methods = []

    outputs = run_tasks_in_parallel_iter(
        extract_repo_data,
        repos,
        num_workers=repo_args.extraction_multiprocess,
        use_progress_bar=True,
        progress_bar_desc="Extracting..",
    )

    for output in outputs:
        if output.is_success():
            new_functions, new_methods = output.result  # type: ignore
            functions.extend(new_functions)
            methods.extend(new_methods)
        else:
            print(f"Error extracting repo data: {output.exception_tb}")

    print(f"Extracted {len(functions)} functions and {len(methods)} methods")

    write_functions(functions + methods, extraction_path)


if __name__ == "__main__":
    repo_args = fire.Fire(RepoArgs)
    build_functions_and_methods(repo_args)
