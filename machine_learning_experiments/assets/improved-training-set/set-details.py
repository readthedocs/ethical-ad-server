import argparse
from collections import Counter
from pathlib import Path
from pprint import pprint

import yaml


BASE_DIR = Path(__file__).parent


def print_set_details(infile):
    print(f"Details about {infile.name}")
    print("=" * 80)

    topic_counter = Counter()

    data = yaml.safe_load(infile)
    for dat in data:
        topics = dat["topics"]
        if not topics:
            topic_counter["notopic"] += 1
        for topic in topics:
            topic_counter[topic] += 1

    print(f"Total Training Set Items:\t\t{len(data)}")

    for topic, count in topic_counter.most_common(10):
        print(f"Training Set Items for '{topic}':\t{count}")


if __name__ == "__main__":
    default_filepath = BASE_DIR / "set.yml"

    parser = argparse.ArgumentParser(
        description="Print details about the specified training set."
    )
    parser.add_argument(
        "infile",
        nargs="?",
        type=argparse.FileType("r"),
        default=open(default_filepath, "r"),
        help="Path to a Yaml training set file",
    )
    args = parser.parse_args()

    print_set_details(args.infile)
