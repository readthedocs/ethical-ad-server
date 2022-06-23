# python -m spacy project run all
# python -m spacy package training/model-best ./packages
# pip install packages/*
import os
import pathlib
import pprint

from textacy import preprocessing

root = pathlib.Path(__file__).parent.resolve()

import en_ethicalads_topics

ea_nlp = en_ethicalads_topics.load()
print(f'EA version: {ea_nlp._meta["version"]}')

# import en_rtd_topics
# print(f'RTD version: {rtd_nlp._meta["version"]}')
# rtd_nlp = en_rtd_topics.load()

preprocessor = preprocessing.make_pipeline(
    preprocessing.normalize.unicode,
    preprocessing.remove.punctuation,
    preprocessing.normalize.whitespace,
)


for f in os.listdir(f"{root}/inputs"):
    file = os.path.abspath(f"{root}/inputs/{f}")
    contents = open(file).read()
    input_str = preprocessor(contents)

    print(f)

    ea_output = ea_nlp(input_str)
    print("EA")
    pprint.pprint(sorted(ea_output.cats.items(), key=lambda x: x[1], reverse=True))

    # print('RTD')
    # rtd_output = rtd_nlp(input_str)
    # pprint.pprint(
    #     sorted(rtd_output.cats.items(), key=lambda x: x[1], reverse=True)
    # )
