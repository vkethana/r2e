import requests
from urllib.parse import urlencode
import gzip
import csv
import json
from datetime import datetime
import os

def download_github_repos(start_date, end_date, output_file_name, min_stars, max_stars):
    # Base URL for SEART API
    BASE_URL = "https://seart-ghs.si.usi.ch/api/r/download/csv"
    
    # Validate date inputs
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Incorrect date format, should be YYYY-MM-DD")

    # Create seart folder if it doesn't exist
    seart_folder = "seart"
    os.makedirs(seart_folder, exist_ok=True)

    # Parameters for the API request
    params = {
        "nameEquals": "false",
        "language": "Python",
        "createdMin": start_date,
        "starsMin": min_stars,
        "codeLinesMin": 10000,
        "sort": "name,asc"
    }
    if max_stars:
        params["starsMax"] = max_stars
    if end_date:
        params["createdMax"] = end_date

    # Generate file names with date range
    if not end_date:
        end_date = "now"
    csv_file_name = f"seart_results_{start_date}_to_{end_date}_min_stars_{min_stars}.csv"
    json_file_name = f"{output_file_name}_{start_date}_to_{end_date}_min_stars_{min_stars}.json"

    csv_file_path = os.path.join(seart_folder, csv_file_name)
    json_file_path = os.path.join(seart_folder, json_file_name)


    def generate_url():
        """Generate the full URL with query parameters."""
        query_string = urlencode(params)
        return f"{BASE_URL}?{query_string}"

    def download_csv():
        """Download the CSV file from SEART."""
        url = generate_url()
        response = requests.get(url, verify=False)
        
        if response.status_code == 200:
            # Response.content is a .gz file
            with open(csv_file_path, "wb") as f:
                f.write(gzip.decompress(response.content))
            print(f"CSV file downloaded successfully as '{csv_file_path}'")
        else:
            print(f"Failed to download CSV. Status code: {response.status_code}")
            print(f"Response content: {response.text}")

    def extract_urls(csv_file, json_output_path, max_urls=100):
        names_list = []
        with open(csv_file, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for i, row in enumerate(csv_reader):
                if i >= max_urls:
                    break
                names_list.append("https://github.com/" + row['name'])
        
        with open(json_output_path, mode='w') as json_file:
            json.dump(names_list, json_file, indent=4)
        print(f"Extracted {len(names_list)} URLs to {json_output_path}")

    print("Generated URL:")
    print(generate_url())
    print("\nDownloading CSV...")
    download_csv()
    print("\nExtracting URLs...")
    extract_urls(csv_file_path, json_file_path)

download_github_repos("2015-01-01", "2017-12-31", "urls", 50, 500)
download_github_repos("2015-01-01", "2017-12-31", "urls", 500, 1000)
download_github_repos("2015-01-01", "2017-12-31", "urls", 1000, None)
download_github_repos("2018-01-01", "2019-12-31", "urls", 50, 500)
download_github_repos("2018-01-01", "2019-12-31", "urls", 500, 1000)
download_github_repos("2018-01-01", "2019-12-31", "urls", 1000, None)
download_github_repos("2020-01-01", None, "urls", 50, 500)
download_github_repos("2020-01-01", None, "urls", 500, 1000)
download_github_repos("2020-01-01", None, "urls", 1000, None)
