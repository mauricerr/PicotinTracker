from picotin_monitor.rules import identify_product, normalize_color


def test_identifies_allowed_sizes() -> None:
    assert identify_product("Picotin Lock 18 bag") is not None
    assert identify_product("Picotin Lock 22 bag") is not None


def test_rejects_non_targets() -> None:
    assert identify_product("Picotin Pocket 18 bag") is None
    assert identify_product("Micro Picotin bag") is None
    assert identify_product("Lindy 26 bag") is None


def test_normalizes_primary_colors() -> None:
    assert normalize_color("Noir") == "Black"
    assert normalize_color("Étoupe Clemence") == "Etoupe"
    assert normalize_color("Gold Clemence") == "Gold"


def test_secondary_colors_require_flag() -> None:
    assert normalize_color("Gris Meyer") is None
    assert normalize_color("Gris Meyer", include_secondary=True) == "Gris Meyer"
