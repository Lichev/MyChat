"""
test_name_validator.py

Unit tests for validate_human_name (M5).  Verifies that the replacement for
str.isalpha() correctly accepts international names and rejects invalid inputs.
"""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from USERS.models import validate_human_name, validate_alphabetical


class ValidHumanNamesTest(SimpleTestCase):
    """Names that must pass validation without raising ValidationError."""

    def _ok(self, name: str) -> None:
        try:
            validate_human_name(name)
        except ValidationError as exc:
            self.fail(f"validate_human_name raised for {name!r}: {exc}")

    def test_plain_ascii(self):
        self._ok("Alice")

    def test_apostrophe_straight(self):
        self._ok("O'Neil")

    def test_apostrophe_curly(self):
        self._ok("O’Neil")

    def test_hyphenated(self):
        self._ok("Jean-Luc")

    def test_space_in_name(self):
        self._ok("Mary Jane")

    def test_cjk_single_char(self):
        self._ok("李")  # 李

    def test_accented_latin(self):
        self._ok("María")  # María

    def test_combined_extras(self):
        # All allowed extras in one name
        self._ok("D'Arcy-Smith Jones")

    def test_alias_still_works(self):
        """validate_alphabetical is the deprecated alias — it must not raise."""
        try:
            validate_alphabetical("Jean-Luc")
        except ValidationError as exc:
            self.fail(f"deprecated alias raised: {exc}")


class InvalidHumanNamesTest(SimpleTestCase):
    """Names that must raise ValidationError."""

    def _bad(self, name: str) -> None:
        with self.assertRaises(ValidationError, msg=f"Expected ValidationError for {name!r}"):
            validate_human_name(name)

    def test_empty_string(self):
        self._bad("")

    def test_whitespace_only(self):
        self._bad("   ")

    def test_digits_only(self):
        self._bad("123")

    def test_apostrophe_then_bang(self):
        self._bad("O'Neil!")

    def test_at_sign(self):
        self._bad("Jack@")

    def test_digit_mixed(self):
        self._bad("Alice2")

    def test_underscore(self):
        self._bad("first_name")

    def test_punctuation(self):
        self._bad("name#here")
