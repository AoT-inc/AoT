# coding=utf-8
"""Tests for aot.utils.safe_eval — the replacement for bare eval() on
user-supplied equations (unit conversions, rescaling, Equation functions)."""
import math

import pytest

from aot.utils.safe_eval import (UnsafeExpressionError, safe_eval,
                                 validate_expression)


class TestArithmetic:
    """Expressions operators are expected to keep working after the switch."""

    @pytest.mark.parametrize("expression,variables,expected", [
        ("1 + 1", None, 2),
        ("x * 2", {'x': 21}, 42),
        ("x * 1.8 + 32", {'x': 100}, 212.0),          # C -> F, a real conversion
        ("(x + 2) * 3", {'x': 1}, 9),                  # from the Conversion model docstring
        ("x / 1000", {'x': 2500}, 2.5),
        ("a + b", {'a': 2, 'b': 3}, 5),                # equation_multi
        ("a * b - 1", {'a': 4, 'b': 5}, 19),
        ("x ** 2", {'x': 5}, 25),
        ("-x", {'x': 5}, -5),
        ("x % 3", {'x': 10}, 1),
        ("x // 3", {'x': 10}, 3),
        ("x * 4.57", {'x': 2}, 9.14),                  # cumulative_tracker PPFD conversion
    ])
    def test_evaluates(self, expression, variables, expected):
        assert safe_eval(expression, variables) == pytest.approx(expected)

    def test_whitespace_tolerated(self):
        assert safe_eval("  x + 1  ", {'x': 1}) == 2


class TestFunctions:
    @pytest.mark.parametrize("expression,variables,expected", [
        ("abs(x)", {'x': -5}, 5),
        ("round(x, 2)", {'x': 3.14159}, 3.14),
        ("sqrt(x)", {'x': 9}, 3.0),
        ("min(x, 5)", {'x': 2}, 2),
        ("log10(x)", {'x': 1000}, 3.0),
        ("exp(0)", None, 1.0),
        ("pi", None, math.pi),
    ])
    def test_allowed_functions(self, expression, variables, expected):
        assert safe_eval(expression, variables) == pytest.approx(expected)

    def test_substring_bug_is_fixed(self):
        """The old code did equation.replace('x', str(value)), which corrupted
        any identifier containing the variable letter: 'max(x, 5)' became
        'ma5.0(5.0, 5)'. Passing variables instead makes these work."""
        assert safe_eval("max(x, 5)", {'x': 10}) == 10
        assert safe_eval("exp(a)", {'a': 0}) == 1.0


class TestRejectsUnsafe:
    """Each of these is a way a bare eval() could be escaped."""

    @pytest.mark.parametrize("expression", [
        "__import__('os').system('id')",
        "().__class__.__bases__[0].__subclasses__()",   # classic sandbox escape
        "x.__class__",                                  # attribute access
        "open('/etc/passwd').read()",
        "[i for i in range(10)]",                       # comprehension
        "lambda: 1",
        "x if x else exit()",                           # exit() not whitelisted
        "print(1)",
        "globals()",
        "eval('1+1')",
        "x[0]",                                         # subscript
        "'a' * 10",                                     # non-numeric constant
        "x = 1",                                        # statement, not expression
    ])
    def test_rejected(self, expression):
        with pytest.raises(UnsafeExpressionError):
            safe_eval(expression, {'x': 1})

    def test_unsafe_branch_rejected_even_when_not_taken(self):
        """Evaluation short-circuits, so a bad `else` branch would never run
        while x is truthy — and would then blow up months later on the one
        reading that makes it falsy. Validation must be eager."""
        with pytest.raises(UnsafeExpressionError):
            safe_eval("x if x else __import__('os')", {'x': 1})
        with pytest.raises(UnsafeExpressionError):
            safe_eval("x or open('/etc/passwd')", {'x': 1})

    def test_short_circuit_semantics_still_work(self):
        """Eager *validation* must not become eager *evaluation* — guards like
        this rely on the divide never being evaluated when y is 0."""
        assert safe_eval("x / y if y else 0", {'x': 10, 'y': 0}) == 0
        assert safe_eval("x / y if y else 0", {'x': 10, 'y': 2}) == 5

    def test_unknown_name_rejected(self):
        with pytest.raises(UnsafeExpressionError):
            safe_eval("y + 1", {'x': 1})

    def test_resource_exhaustion_rejected(self):
        """9**9**9 is only BinOps but would hang the daemon thread."""
        with pytest.raises(UnsafeExpressionError):
            safe_eval("9 ** 9 ** 9")

    def test_method_call_rejected(self):
        with pytest.raises(UnsafeExpressionError):
            safe_eval("x.bit_length()", {'x': 5})

    def test_syntax_error_becomes_unsafe_expression_error(self):
        """Callers only need to catch one exception type."""
        with pytest.raises(UnsafeExpressionError):
            safe_eval("x +", {'x': 1})

    def test_non_string_rejected(self):
        with pytest.raises(UnsafeExpressionError):
            safe_eval(None)


class TestValidateExpression:
    """validate_expression() checks an equation at save time, before any
    measurement exists to substitute in."""

    def test_accepts_valid(self):
        validate_expression("x * 1.8 + 32", ('x',))
        validate_expression("a / b", ('a', 'b'))

    def test_rejects_unsafe(self):
        with pytest.raises(UnsafeExpressionError):
            validate_expression("__import__('os')", ('x',))

    def test_rejects_undeclared_variable(self):
        """An equation referencing 'y' when only 'x' is supplied is a typo that
        should surface on save, not as a daemon error later."""
        with pytest.raises(UnsafeExpressionError):
            validate_expression("y * 2", ('x',))

    def test_does_not_divide_by_zero_while_validating(self):
        """Placeholder values must not be evaluated — 'x / 0' is structurally
        fine and only fails at runtime with real data."""
        validate_expression("100 / x", ('x',))
