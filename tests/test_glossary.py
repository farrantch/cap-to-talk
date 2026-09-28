from pathlib import Path

from cap_to_talk.glossary import (
    glossary_normalize,
    load_terms,
    select_relevant_terms,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_terms_ignores_comments_duplicates_and_long_values(tmp_path: Path):
    path = tmp_path / "terms.txt"
    path.write_text(
        "# comment\nOpenASR\nopenasr\nOllama\n" + "x" * 129 + "\n",
        encoding="utf-8",
    )

    assert load_terms(path) == ["OpenASR", "Ollama"]


def test_selects_literal_and_fuzzy_terms():
    terms = ["OpenASR", "RapidFuzz", "PostgreSQL", "UI"]
    selected = select_relevant_terms(
        "Use open A S R and rapid fuzz for the transcript",
        terms,
    )

    assert "OpenASR" in selected
    assert "RapidFuzz" in selected
    assert "UI" not in selected


def test_glossary_normalize():
    assert glossary_normalize("Qwen3-ASR 0.6B") == "qwen3 asr 0 6b"


def test_example_hotwords_fit_limits_and_are_in_master_glossary():
    hotwords = load_terms(PROJECT_ROOT / "config/hotwords.example.txt")
    master_terms = load_terms(PROJECT_ROOT / "config/master-hotwords.example.txt")

    assert len(hotwords) <= 128
    assert sum(map(len, hotwords)) <= 4_000
    assert {term.casefold() for term in hotwords} <= {
        term.casefold() for term in master_terms
    }
