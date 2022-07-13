"""Conver JSON files into JsonL (??)."""
import json
import os

for f in os.listdir("assets"):
    file = os.path.abspath(f"assets/{f}")
    if file.endswith("json"):
        with open(f"{file}l", "w", encoding="utf-8") as outfile:
            with open(file, "r", encoding="utf-8") as infile:
                for entry in json.load(infile):
                    json.dump(entry, outfile)
                    outfile.write("\n")
