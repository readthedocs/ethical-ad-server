"""
Build an ML training and test set from the categorized data YAML file.

The first time this is run, it can take a while.
It goes out and fetches data from the web.
For future runs, the URLs are cached.

cd machine_learning_experiments/
# Generate training and test set from the categorized data (Yaml file)
python scripts/generate-training-test-sets.py -o assets/train.json -f assets/test.json assets/categorized-data.yml
python -m spacy project run all . --vars.train=train --vars.dev=test --vars.name=ethicalads_topics --vars.version=`date "+%Y%m%d_%H_%M_%S"`
"""
import argparse
import json
import random
import sys
from collections import Counter

import langdetect
import requests
import urllib3
import yaml
from bs4 import BeautifulSoup
from requests_cache import CachedSession
from textacy import preprocessing


DEFAULT_TRAIN_TEST_SPLIT = 0.8

MAIN_CONTENT_SELECTORS = (
    "[role='main']",
    "main",
    "body",
)
REMOVE_CONTENT_SELECTORS = (
    "[role=navigation]",
    "[role=search]",
    ".headerlink",
    "nav",
    "footer",
    "div.header",
    # Django Packages specific
    "#myrotatingnav",
)
PREPROCESSOR = preprocessing.make_pipeline(
    preprocessing.normalize.unicode,
    preprocessing.remove.punctuation,
    preprocessing.normalize.whitespace,
    # Removes inline SVGs and *some* malformed HTML
    preprocessing.remove.html_tags,
)


def preprocess_html(html):
    """Preprocesses HTML into text for our model."""
    soup = BeautifulSoup(html, features="html.parser")

    for selector in REMOVE_CONTENT_SELECTORS:
        for nodes in soup.select(selector):
            nodes.decompose()

    for selector in MAIN_CONTENT_SELECTORS:
        results = soup.select(selector, limit=1)

        # If no results, go to the next selector
        # If results are found, use these and stop looking at the selectors
        if results:
            return PREPROCESSOR(results[0].get_text()).lower()

    return ""


def preprocess_training_set(infile):
    """Loop through our training set and fetch the actual URL contents."""
    # Setup the cache so we don't hammer these sites
    session = CachedSession("trainingset-urls-cache")

    new_training_set = []
    seen_urls = set()

    data = yaml.safe_load(infile)
    for dat in data:
        url = dat["url"].strip()

        if "topics" not in dat:
            # The key has to be there but the array can be empty
            print(f"No topics for {url}...")
            continue

        if url in seen_urls:
            print(f"Duplicate url: {url}")
            continue

        seen_urls.add(url)

        try:
            resp = session.get(url, timeout=3)
        except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError):
            print(f"Skipping URL {url} which returned an error...")
            continue

        if resp.ok:
            text = preprocess_html(resp.content)
            new_training_set.append(
                {
                    "text": text,
                    "labels": dat["topics"],
                    # Not sure if these are necessary
                    # "keywords": [],
                    "meta": {"url": url},
                }
            )

            lang = langdetect.detect(text)
            if lang != "en":
                print(f"Language for {url} was not english ({lang})...")

    return new_training_set


def print_training_set_details(new_training_set):
    topic_counter = Counter()

    for dat in new_training_set:
        topics = dat["labels"]
        if not topics:
            topic_counter["notopic"] += 1
        for topic in topics:
            topic_counter[topic] += 1

    print("Training/Test Set Details")
    print("=" * 80)
    print(f"Total Training/Test Set Items:\t\t\t{len(new_training_set)}")

    for topic, count in topic_counter.most_common(10):
        print(f"Training/Test Set Items for '{topic}':\t\t{count}")

    print("\n")


def write_train_test_sets(
    processed_set, train_set_file, test_set_file, split_percentage
):
    split_set = int(len(processed_training_set) * split_percentage)

    print("Writing Training & Test Sets")
    print("=" * 80)

    # "Randomize" the dataset order so we can randomly split into train/test sets
    # We use a deterministic seed so we don't get different results when building the model
    # again and again. The goal is just to shuffle them so the test/train sets are a good representation
    random.seed(987654321)
    random.shuffle(processed_set)

    # This is just a protection in case random is ever used again.
    # This just sets to the seed back to an unknowable value
    random.seed()

    print(f"Writing {train_set_file.name} ({len(processed_set[:split_set])} items)...")
    train_set_file.write(json.dumps(processed_set[:split_set], indent=2))

    print(f"Writing {test_set_file.name} ({len(processed_set[split_set:])} items)...")
    test_set_file.write(json.dumps(processed_set[split_set:], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess the specified YAML training set."
    )
    parser.add_argument(
        "infile",
        type=argparse.FileType("r"),
        help="Path to a YAML training set file",
    )

    parser.add_argument(
        "-o",
        "--training-outfile",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="Path to write the processed training set (eg. train.json).",
    )

    parser.add_argument(
        "-f",
        "--test-outfile",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="Path to write the processed test set(eg. test.json).",
    )

    parser.add_argument(
        "--split",
        type=float,
        default=DEFAULT_TRAIN_TEST_SPLIT,
        help="The percentage to split between training and test set [0, 1]",
    )
    args = parser.parse_args()

    if args.split > 1 or args.split < 0:
        parser.error(
            f"The training/test split must be between 0 and 1 [default: {DEFAULT_TRAIN_TEST_SPLIT}]"
        )

    processed_training_set = preprocess_training_set(args.infile)
    print_training_set_details(processed_training_set)
    write_train_test_sets(
        processed_training_set, args.training_outfile, args.test_outfile, args.split
    )
