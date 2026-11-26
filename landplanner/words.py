"""One small helper for counted nouns, so no sentence the app writes says "1 acres" or "2 signal(s)"."""


def plural_of(word):
    """The usual plural of an English word: signal -> signals, city -> cities, bus -> buses."""
    if word.endswith("y") and word[-2:-1] not in ("a", "e", "i", "o", "u", ""):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def counted(n, one, many=None, digits=None, with_number=True):
    """A number and its noun, agreeing: counted(1, "acre") -> "1 acre", counted(2, "acre") -> "2 acres",
    counted(0.5, "acre") -> "0.5 acres", counted(1, "city", "cities") -> "1 city".
    digits: how many decimals the number is shown with (None shows up to two, with none that are zero). The
    noun follows the number as it is shown, so a size that rounds to 1 is "1 acre" and never "1 acres".
    with_number=False gives only the noun's form, for sentences that write the number themselves."""
    if digits is None:
        shown = f"{n:,.2f}".rstrip("0").rstrip(".")
    else:
        shown = f"{n:,.{digits}f}"
    try:
        single = float(shown.replace(",", "")) == 1
    except ValueError:
        single = False
    word = one if single else (many or plural_of(one))
    return f"{shown} {word}" if with_number else word
