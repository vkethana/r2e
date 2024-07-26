import os
from datetime import datetime
from pathlib import Path
import yaml

# Load configuration from config.yaml

current_dir = Path(__file__).parent
config_path = current_dir / "config.yml"
with open(config_path, "r") as file:
    config: dict[str, str] = yaml.safe_load(file)  # type: ignore

HOME_DIR = Path(os.path.expanduser("~"))
REPOS_DIR = HOME_DIR / config["repos_dir"]
CACHE_DIR = HOME_DIR / config["cache_dir"]

# Everything previously under r2e_buckets is now under repos
# TODO: this paths.py needs further changes:
#       I think the following directories should be assorted under dir_{repo_name} individually
#       For now they are all together for miscellaneous repos

GRAPHS_DIR = REPOS_DIR / "repo_graphs"
INTERESTING_FUNCS_DIR = REPOS_DIR / "interesting_functions"
TESTGEN_DIR = REPOS_DIR / "testgen"
EXECUTION_DIR = REPOS_DIR / "execution"
SPECGEN_DIR = REPOS_DIR / "specgen"


CACHE_PATH = CACHE_DIR / "cache.json"

PDM_BIN_DIR = "/home/naman_jain/.local/bin:$PATH"


# HELPER FUNCTIONS


def timestamp() -> str:
    """Return the current timestamp"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")
