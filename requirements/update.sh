#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Loop through all .in files in the current directory
for file in *.in
do
  # Check if the file exists to avoid errors if there are no .in files
  if [[ -f "$file" ]]; then
    echo "Compiling $file..."
    # Call pip-compile for each .in file
    pip-compile -U "$file"
  else
    echo "No .in files found in the directory."
    break
  fi
done

echo "All .in files have been processed."
