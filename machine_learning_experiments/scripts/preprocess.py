"""Script that loads data into Spacy."""
from pathlib import Path

import spacy
import srsly
import typer
from spacy.tokens import DocBin
from textacy import preprocessing

topic_list = [
    "datascience",
    "backend",
    "frontend",
    "security",
    "devops",
    # "game-dev",
    "blockchain",
    # "techwriting",
    # "hardware",
]


def main(
    input_path: Path = typer.Argument(..., exists=True, dir_okay=False),
    output_path: Path = typer.Argument(..., dir_okay=False),
):
    """Load specified input files into a Spacy document."""
    nlp = spacy.blank("en")
    doc_bin = DocBin()
    preprocessor = preprocessing.make_pipeline(
        preprocessing.normalize.unicode,
        preprocessing.remove.punctuation,
        preprocessing.normalize.whitespace,
    )
    data_tuples = ((preprocessor(eg["text"]), eg) for eg in srsly.read_json(input_path))
    for doc, eg in nlp.pipe(data_tuples, as_tuples=True):
        for topic in topic_list:
            if topic in eg["labels"]:
                doc.cats[topic] = True
            else:
                doc.cats[topic] = False
        # for keyword in eg['keywords']:
        #     doc.cats[f'keyword-{keyword}'] = True

        doc_bin.add(doc)
    doc_bin.to_disk(output_path)
    print(f"Processed {len(doc_bin)} documents: {output_path.name}")


if __name__ == "__main__":
    typer.run(main)
