"""Tests for route_heuristic confidence + length reinterpretation (change 1).

Run with pytest, or standalone: `python3 tests/test_route_heuristic_confidence.py`.
The standalone runner exists because some envs lack pytest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core" / "skills"))
import route_heuristic as rh  # noqa: E402

# Pass modules explicitly so the test does not depend on a project index.
_MODS = [{"name": "payments"}, {"name": "auth"}, {"name": "ledger"}]


def test_short_ambiguous_is_low_confidence():
    # Short, no keyword/module signal → under-specified, low confidence.
    r = rh.classify("make it better", kind="tech", modules=_MODS)
    assert r.confidence == "low", r
    # Length must not be used to *lower* the track below the floor: a short
    # ticket still aggregates max-wins, so the hint is not forced up either.
    assert r.hint in ("XS", "S"), r


def test_long_description_is_high_confidence():
    long_text = "word " * 120
    r = rh.classify(long_text, kind="feature", modules=_MODS)
    assert r.confidence == "high", r


def test_ml_keyword_is_high_confidence_and_raises_track():
    r = rh.classify("add an auth migration to the schema", kind="feature",
                    modules=_MODS)
    assert r.confidence == "high", r
    assert r.hint == "M", r


def test_explicit_typo_is_high_confidence_xs():
    r = rh.classify("fix typo in readme", kind="bug", modules=_MODS)
    assert r.confidence == "high", r
    assert r.hint == "XS", r


def test_single_module_short_is_medium_not_high():
    # Matches one module but is short and otherwise unspecified → medium:
    # the dangerous "looks small but maybe deep" case the triage must catch.
    r = rh.classify("tweak payments", kind="tech", modules=_MODS)
    assert r.confidence == "medium", r
    assert r.modules_matched == ["payments"], r


def test_russian_access_tokens_raises_track():
    # The motivating example: short RU ticket, English keyword list would
    # miss it; bilingual stems catch "токен"/"доступ"/"только на чтение".
    r = rh.classify("поддержать токены доступа только на чтение",
                    kind="feature", modules=_MODS)
    assert r.hint == "M", r
    assert r.confidence == "high", r


def test_russian_light_theme_raises_track():
    # "support light theme" — short but cross-cutting; "тему" is a theme stem.
    r = rh.classify("поддержать светлую тему", kind="feature", modules=_MODS)
    assert r.hint == "M", r


def test_no_false_positive_sistema_vs_tema():
    # "система" must NOT hit the theme stem "тема" (substring would; \b won't).
    assert rh._signal_from_keywords("обновить систему логирования") != "M"


def test_no_false_positive_author_vs_auth():
    # "author" must NOT hit an auth stem (substring "auth" would; \b + authoriz won't).
    assert rh._signal_from_keywords("show the commit author name") != "M"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
