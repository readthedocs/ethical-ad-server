#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Check if uv is installed
if command -v uv &> /dev/null; then
  compile_command="uv pip compile"
else
  compile_command="pip-compile"
fi

# Flag to check if any .in files exist
found_files=false

# Loop through all .in files in the current directory
for file in *.in; do
  # Check if the file exists to avoid errors if there are no .in files
  if [[ -f "$file" ]]; then
    found_files=true
    output_file="${file%.in}.txt"
    echo "Compiling $file to $output_file..."
    echo "Running command: $compile_command $file -o $output_file"
    # Call the compile command for each .in file, outputting to the corresponding .txt file
    $compile_command "$file" -o "$output_file"
  fi
done

# If no .in files were found, notify the user
if [[ $found_files == false ]]; then
  echo "No .in files found in the directory."
fi

echo "All .in files have been processed."
