import os

def scan_logs_for_error(directory, error_phrase):
    total_files = 0
    files_with_error = 0

    # Iterate through all files in the directory
    for filename in os.listdir(directory):
        # Check if the file has a .log extension
        if filename.endswith(".log"):
            total_files += 1
            file_path = os.path.join(directory, filename)

            # Read the file and search for the error phrase
            with open(file_path, 'r') as file:
                if error_phrase in file.read():
                    files_with_error += 1

    # Output the results
    print(f"Total log files scanned: {total_files}")
    print(f"Number of files with '{error_phrase}': {files_with_error}")

# Set your directory path here
directory_path = "logs_pt1/"
scan_logs_for_error(directory_path, "BLANK REPO ERROR")
scan_logs_for_error(directory_path, "UnixHTTPConnection")
scan_logs_for_error(directory_path, "INSTALLATION SUCCEEDED")


