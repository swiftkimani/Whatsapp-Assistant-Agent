from types import SimpleNamespace as Info

from app.lang import looks_swahili, pick_language


def test_english_and_swahili_are_kept():
    assert pick_language(Info(language="en")) == "en"
    assert pick_language(Info(language="sw")) == "sw"


def test_other_guesses_fall_back_to_the_likelier_of_the_two():
    assert pick_language(Info(language="de", all_language_probs=[("de", .5), ("sw", .3), ("en", .1)])) == "sw"
    assert pick_language(Info(language="fr", all_language_probs=[("fr", .5), ("en", .4), ("sw", .01)])) == "en"
    assert pick_language(Info(language="ur")) == "en"      # no probabilities: English is the safer guess


def test_swahili_is_recognised_from_the_words_alone():
    """Swahili and English share the Latin script, so the voice picker and the
    dashboard assistant have no characters to go on — only vocabulary."""
    assert looks_swahili("niaje uko wapi")
    assert looks_swahili("sawa nitakuambia baadaye")
    assert looks_swahili("manze traffic ni noma leo")


def test_plain_english_is_not_mistaken_for_swahili():
    assert not looks_swahili("are you coming tomorrow")
    assert not looks_swahili("let me check and tell you")
    assert not looks_swahili("")
