#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Get the directory where the script is located
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

# Loop through all .in files in the script's directory
for file in "$SCRIPT_DIR"/*.in
do
  # Check if the file exists to avoid errors if there are no .in files
  if [[ -f "$file" ]]; then
    echo "Compiling $file..."
    # Call pip-compile for each .in file
    pip-compile -U "$file"
  else
    echo "No .in files found in $SCRIPT_DIR."
    break
  fi
done

echo "All .in files have been processed."
