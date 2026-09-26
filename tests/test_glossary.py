from pathlib import Path

from caps_talk.glossary import (
    glossary_normalize,
    load_terms,
    select_relevant_terms,
)


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
