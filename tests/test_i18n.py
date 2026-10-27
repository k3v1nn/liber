# SPDX-License-Identifier: AGPL-3.0-only
"""Keeps the English catalogue and the Portuguese source strings in step with each other."""

import ast
import string
import unittest
from collections import Counter
from pathlib import Path

import conversor
from conversor.gui import TYPE_LABELS
from conversor.i18n import EN
from conversor.models import BLOCK_ROLES, PAGE_ROLES

PACKAGE = Path(conversor.__file__).parent
# Methods that pass a string argument through `_t`, with the positions of those arguments.
TRANSLATING_CALLS = {
    "_t": (0,), "_plural": (1, 2), "_start": (0,), "_label": (0,), "_plain_label": (0,),
    "_eyebrow": (0,), "_centered_text": (0,), "_button": (0,), "_field": (0,),
}


def _sources() -> dict[Path, ast.Module]:
    return {path: ast.parse(path.read_text(encoding="utf-8")) for path in sorted(PACKAGE.glob("*.py"))}


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "text"` constants, so `_t(IMAGE_FILTER)` can be resolved."""
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            values.update({target.id: node.value.value for target in node.targets if isinstance(target, ast.Name)})
    return values


def _translated_literals() -> list[tuple[str, int, str]]:
    """(file, line, text) for every constant string handed to a translating call."""
    found = []
    for path, tree in _sources().items():
        constants = _module_strings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            for position in TRANSLATING_CALLS.get(name, ()):
                if position >= len(node.args):
                    continue
                argument = node.args[position]
                if isinstance(argument, ast.Name):
                    argument = ast.Constant(constants[argument.id]) if argument.id in constants else argument
                # Symbols, empty captions and computed values are not catalogue entries.
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and any(c.isalpha() for c in argument.value):
                    found.append((path.name, node.lineno, argument.value))
    return found


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class CatalogueTests(unittest.TestCase):
    def test_role_and_type_labels_are_translated(self):
        for label in (*PAGE_ROLES, *BLOCK_ROLES, *TYPE_LABELS.values()):
            self.assertIn(label, EN, f"{label!r} is shown to the user but has no English entry")

    def test_every_translated_literal_has_an_english_entry(self):
        literals = _translated_literals()
        self.assertGreater(len(literals), 50, "the scan found suspiciously few translated strings")
        missing = sorted({f"{file}:{line} {text!r}" for file, line, text in literals if text not in EN})
        self.assertEqual(missing, [])

    def test_no_english_entry_is_unused(self):
        used = set(PAGE_ROLES) | set(BLOCK_ROLES) | set(TYPE_LABELS.values())
        for path, tree in _sources().items():
            if path.name == "i18n.py":
                continue
            used.update(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str))
        self.assertEqual(sorted(key for key in EN if key not in used), [])

    def test_english_keys_are_written_once(self):
        tree = ast.parse((PACKAGE / "i18n.py").read_text(encoding="utf-8"))
        catalogue = next(node.value for node in tree.body
                         if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "EN" for t in node.targets))
        keys = [key.value for key in catalogue.keys if isinstance(key, ast.Constant)]
        self.assertEqual([key for key, count in Counter(keys).items() if count > 1], [])

    def test_placeholders_survive_translation(self):
        for key, value in EN.items():
            self.assertEqual(_fields(key), _fields(value), f"placeholders differ for {key!r}")


if __name__ == "__main__":
    unittest.main()
