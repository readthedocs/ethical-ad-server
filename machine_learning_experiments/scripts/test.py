"""Test the ML topic classification model against inputs from inputs/."""
# python -m spacy project run all
# python -m spacy package training/model-best ./packages
# pip install packages/*
import os
import pathlib
import pprint
import sys

from textacy import preprocessing

try:
    import en_ethicalads_topics  # noqa
except ImportError:
    print("No ML model available (cannot import 'en_ethicalads_topics')")
    sys.exit(1)

root = pathlib.Path(__file__).parent.resolve()

ea_nlp = en_ethicalads_topics.load()
print(f'EA version: {ea_nlp._meta["version"]}\n')

preprocessor = preprocessing.make_pipeline(
    preprocessing.normalize.unicode,
    preprocessing.remove.punctuation,
    preprocessing.normalize.whitespace,
)


for f in os.listdir(f"{root}/inputs"):
    file = os.path.abspath(f"{root}/inputs/{f}")
    with open(file, "r", encoding="utf-8") as fd:
        contents = fd.read()
    input_str = preprocessor(contents)

    print(f"{f} classification")
    print("=" * 80)

    ea_output = ea_nlp(input_str)
    pprint.pprint(sorted(ea_output.cats.items(), key=lambda x: x[1], reverse=True))
    print("\n")
