import json
import os

for f in os.listdir("assets"):
    file = os.path.abspath(f"assets/{f}")
    if file.endswith("json"):
        with open(f"{file}l", "w") as outfile:
            for entry in json.load(open(file)):
                json.dump(entry, outfile)
                outfile.write("\n")
