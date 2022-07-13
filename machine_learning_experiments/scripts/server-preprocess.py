"""
Script that generates a training & validation set.

Generally does ~75% in the training set, and ~25% in the validation set.

Once these are generated, they should be passed to the scripts with:

python -m spacy project run all . --vars.train=set1 --vars.dev=set2 --vars.name=basic-topics --vars.version=`date "+%Y%m%d_%H_%M_%S"`
pip install packages/*
python test.py
"""
import json
import random

from adserver.models import Keyword


prefix = "rtd-"

# Write the training set to the tmp directory
with open(f"/tmp/{prefix}training-set.json", "r", encoding="utf-8") as fd:
    dataset = json.load(fd)

training_set = []

# Split up topics
random.shuffle(dataset)

for item in dataset:
    topics = set()
    keywords = item["keywords"]
    for keyword in keywords:
        k = Keyword.objects.filter(slug=keyword).first()
        if not k:
            continue
        for topic in k.topics.values("slug"):
            print(keyword, topic["slug"])
            topics.add(topic["slug"])
    training_set.append(
        {
            "text": item["text"],
            "labels": list(topics),
            "keywords": item["keywords"],
            # "meta": {
            #     "url": item['url']
            # }
        }
    )


# Write the split sets to the tmp directory
split_set = int(len(training_set) // 1.3)

with open(f"/tmp/{prefix}set1.json", "w", encoding="utf-8") as fd:
    fd.write(json.dumps(training_set[:split_set], indent=2))

with open(f"/tmp/{prefix}set2.json", "w", encoding="utf-8") as fd:
    fd.write(json.dumps(training_set[split_set:], indent=2))
