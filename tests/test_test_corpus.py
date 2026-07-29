from pathlib import Path

from archive_workbench.test_corpus import load_test_corpus


def test_completed_test_corpus_is_valid() -> None:
    root = Path(__file__).parents[1]
    corpus = load_test_corpus(root / "config" / "test_corpus.yaml")
    assert len(corpus.documents) == 5
    assert any(item.input_characteristics.format == "tiff" for item in corpus.documents)
