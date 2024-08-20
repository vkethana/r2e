import requests
from urllib.parse import urlencode
import gzip
import csv
import json

# Base URL for SEART API
BASE_URL = "https://seart-ghs.si.usi.ch/api/r/download/csv"
JSON_OUTPUT_PATH = "urls.json"

# Max # of URLs to output to JSON
MAX_URLS_TO_OUTPUT_TO_JSON = 100

# Hardcoded variables for all fields
params = {
    "nameEquals": "false",
    "language": "Python",
    #"commitsMin": 0,
    #"commitsMax": 100,
    #"contributorsMin": 0,
    #"contributorsMax": 1000,
    #"issuesMin": 0,
    #"issuesMax": 1000,
    #"pullsMin": 0,
    #"pullsMax": 1000,
    #"branchesMin": 0,
    #"branchesMax": 1000,
    #"releasesMin": 0,
    #"releasesMax": 1000,
    "createdMin": "2023-12-25",
    "createdMax": "2024-01-01",
    #"committedMin": "2008-01-01",
    #"committedMax": "2024-01-01",
    "starsMin": 0,
    "starsMax": 1000,
    #"watchersMin": 0,
    #"watchersMax": 1000,
    #"forksMin": 0,
    #"forksMax": 1000,
    #"nonBlankLinesMin": 0,
    #"nonBlankLinesMax": 1000,
    "codeLinesMin": 10000,
    #"codeLinesMax": 1000,
    #"commentLinesMin": 0,
    #"commentLinesMax": 1000,
    "sort": "name,asc"
}

def generate_url():
    """Generate the full URL with query parameters."""
    query_string = urlencode(params)
    return f"{BASE_URL}?{query_string}"


def extract_urls(csv_file):
    # Initialize an empty list to store the names
    names_list = []

    # Open the CSV file
    with open(csv_file, mode='r') as csv_file:
        # Create a CSV reader object
        csv_reader = csv.DictReader(csv_file)

        # Iterate over each row in the CSV file
        i = 0
        for row in csv_reader:
            if i >= MAX_URLS_TO_OUTPUT_TO_JSON:
                break
            # Append the name to the names list
            names_list.append("https://github.com/" + row['name'])
            i += 1
    
    # Write the names list to a JSON file
    with open(JSON_OUTPUT_PATH, mode='a') as json_file:
        json.dump(names_list, json_file, indent=4)
    print(f"Extracted {i} URLs to {JSON_OUTPUT_PATH}")

def download_csv():
    """Download the CSV file from SEART."""
    url = generate_url()
    response = requests.get(url, verify=False)
    
    if response.status_code == 200:
        # Response.content is a .gz file
        with open("seart_results.csv", "wb") as f:
            f.write(gzip.decompress(response.content))

        print("CSV file downloaded successfully as 'seart_results.csv'")

    else:
        print(f"Failed to download CSV. Status code: {response.status_code}")
        print(f"Response content: {response.text}")

if __name__ == "__main__":
    print("Generated URL:")
    print(generate_url())
    print("\nDownloading CSV...")
    download_csv()
    print("\nExtracting URLs...")
    extract_urls('seart_results.csv')
