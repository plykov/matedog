"""TM matching, lexicon learning, alignment and QA tests."""

import pytest

from matedog import db, mlx, mt, qa, tm


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


CORPUS = [
    ("the cat sleeps", "кот спит"),
    ("the dog sleeps", "собака спит"),
    ("the cat eats fish", "кот ест рыбу"),
    ("the dog eats meat", "собака ест мясо"),
    ("a big cat", "большой кот"),
    ("a big dog", "большая собака"),
    ("the cat drinks milk", "кот пьёт молоко"),
    ("the dog drinks water", "собака пьёт воду"),
]


def seed(conn):
    tm.add_units(conn, "en", "ru", CORPUS, origin="corpus")


def test_exact_match(conn):
    seed(conn)
    m = tm.lookup(conn, "en", "ru", "the cat sleeps")
    assert m and m[0]["percent"] == 100 and m[0]["target"] == "кот спит"


def test_fuzzy_match(conn):
    seed(conn)
    m = tm.lookup(conn, "en", "ru", "the cat sleeps deeply", min_score=0.5)
    assert m and 50 <= m[0]["percent"] < 100
    assert m[0]["target"] == "кот спит"


def test_concordance(conn):
    seed(conn)
    rows = tm.concordance(conn, "en", "ru", "рыбу")
    assert rows and rows[0]["source"] == "the cat eats fish"


def test_lexicon_training_learns_word_translations(conn):
    seed(conn)
    n = mlx.train_lexicon(conn, "en", "ru")
    assert n > 0
    cat = [t for t, _ in mlx.lexicon_lookup(conn, "en", "ru", "cat")]
    dog = [t for t, _ in mlx.lexicon_lookup(conn, "en", "ru", "dog")]
    assert "кот" in cat
    assert "собака" in dog


def test_fuzzy_repair_substitutes_learned_word(conn):
    seed(conn)
    mlx.train_lexicon(conn, "en", "ru")
    repaired = mlx.repair_fuzzy(conn, "en", "ru",
                                new_source="the dog sleeps",
                                match_source="the cat sleeps",
                                match_target="кот спит")
    assert repaired is not None
    assert "собака" in repaired and "кот" not in repaired


def test_mt_suggest_chain(conn):
    seed(conn)
    mlx.train_lexicon(conn, "en", "ru")
    sug = mt.suggest(conn, "en", "ru", "the cat sleeps")
    assert sug["percent"] == 100
    sug2 = mt.suggest(conn, "en", "ru", "the dog sleeps loudly")
    assert sug2 is not None and sug2["text"]


def test_align_corpus_line_aligned():
    pairs = mlx.align_corpus("one\ntwo\n", "een\ntwee\n")
    assert pairs == [("one", "een"), ("two", "twee")]


def test_align_corpus_length_based():
    src = "First sentence here. Second one is a bit longer than that. Third."
    tgt = "Первое предложение здесь. Второе немного длиннее чем то. Третье."
    pairs = mlx.align_corpus(src, tgt)
    assert len(pairs) == 3
    assert pairs[0][1].startswith("Первое")


# ---------- QA ----------

def test_qa_empty_and_numbers():
    assert qa.check_segment("Hello", "", "en", "ru")[0]["code"] == "empty"
    issues = qa.check_segment("Pay 42 dollars.", "Заплатите 43 доллара.", "en", "ru")
    assert any(i["code"] == "numbers" for i in issues)
    ok = qa.check_segment("Pay 42.5 dollars.", "Заплатите 42,5 доллара.", "en", "ru")
    assert not any(i["code"] == "numbers" for i in ok)  # decimal comma accepted


def test_qa_tags():
    issues = qa.check_segment('Hi <g id="1">there</g>', "Привет там", "en", "ru")
    assert any(i["code"] == "tags" for i in issues)


def test_qa_russian_typography():
    issues = qa.check_segment('He said "hi".', 'Он сказал "привет".', "en", "ru")
    assert any(i["code"] == "ru_quotes" for i in issues)
    mixed = qa.check_segment("Order", "Зaказ", "en", "ru")  # Latin 'a' inside Cyrillic
    assert any(i["code"] == "ru_mixed_script" for i in mixed)


def test_qa_glossary():
    gl = [{"src_term": "invoice", "tgt_term": "счёт"}]
    issues = qa.check_segment("Send the invoice.", "Отправьте документ.", "en", "ru", glossary=gl)
    assert any(i["code"] == "glossary" for i in issues)
    ok = qa.check_segment("Send the invoice.", "Отправьте счёт.", "en", "ru", glossary=gl)
    assert not any(i["code"] == "glossary" for i in ok)


def test_qa_untranslated_and_punct():
    issues = qa.check_segment("This is a long sentence.", "This is a long sentence.", "en", "nl")
    assert any(i["code"] == "untranslated" for i in issues)
    issues = qa.check_segment("Done.", "Klaar", "en", "nl")
    assert any(i["code"] == "punct_end" for i in issues)
