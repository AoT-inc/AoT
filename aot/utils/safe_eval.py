# coding=utf-8
"""Safe arithmetic expression evaluation for user-supplied equations.

AoT lets operators type equations in the web UI (unit conversions, measurement
rescaling, Equation/Equation-Multi functions, Input actions). These were
evaluated with a bare `eval()`, which means anyone who can edit a Function or a
measurement conversion could execute arbitrary Python in the daemon process —
a privilege escalation for any non-admin role holding `edit_controllers`.

This module parses the expression with `ast` and walks it against a node
whitelist, so only arithmetic survives. Attribute access, subscripting,
comprehensions, lambdas, imports, and any name that isn't an explicitly
supplied variable or whitelisted function are rejected before evaluation.

Passing values via `variables` (rather than the old
`equation.replace('x', str(value))`) also fixes a latent correctness bug: naive
substitution corrupts any identifier containing the variable letter, so
`max(x, 5)` became `ma5.0(5.0, 5)` and `exp(a)` became `e5.0p(5.0)`. Equations
using the whitelisted function names below therefore only start working now.
"""
import ast
import math

__all__ = ['safe_eval', 'validate_expression', 'UnsafeExpressionError']


class UnsafeExpressionError(ValueError):
    """Raised when an expression contains anything beyond plain arithmetic."""


# Exponents above this are rejected: `9**9**9` is syntactically just a BinOp but
# will hang the daemon thread and exhaust memory.
_MAX_EXPONENT = 1000

_ALLOWED_FUNCTIONS = {
    'abs': abs,
    'min': min,
    'max': max,
    'round': round,
    'int': int,
    'float': float,
    'pow': pow,
    'sqrt': math.sqrt,
    'log': math.log,
    'log10': math.log10,
    'log2': math.log2,
    'exp': math.exp,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'asin': math.asin,
    'acos': math.acos,
    'atan': math.atan,
    'atan2': math.atan2,
    'floor': math.floor,
    'ceil': math.ceil,
    'fabs': math.fabs,
    'degrees': math.degrees,
    'radians': math.radians,
}

_ALLOWED_CONSTANTS = {
    'pi': math.pi,
    'e': math.e,
    'tau': math.tau,
}

_ALLOWED_BINOPS = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub, ast.Not)
_ALLOWED_COMPARE = (
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)
_ALLOWED_BOOLOPS = (ast.And, ast.Or)


def _validate(node, names):
    """Reject disallowed syntax anywhere in the tree, including branches that
    evaluation would short-circuit past.

    Without this pass, validation would be lazy: `x if x else __import__('os')`
    evaluates fine whenever x is truthy and only blows up later when a
    measurement happens to make it falsy. Equations are saved once and run
    unattended for months, so they must be rejected up front, not on the
    unlucky reading. Evaluation itself stays lazy (below) so short-circuits
    like `x / y if y else 0` keep working.
    """
    if isinstance(node, ast.Expression):
        return _validate(node.body, names)

    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, bool)):
            raise UnsafeExpressionError(
                "Only numeric constants are allowed, got {!r}".format(node.value))
        return

    if isinstance(node, ast.Name):
        if node.id not in names:
            raise UnsafeExpressionError("Unknown name '{}'".format(node.id))
        return

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise UnsafeExpressionError(
                "Operator {} is not allowed".format(type(node.op).__name__))
        _validate(node.left, names)
        _validate(node.right, names)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise UnsafeExpressionError(
                "Operator {} is not allowed".format(type(node.op).__name__))
        _validate(node.operand, names)
        return

    if isinstance(node, ast.Compare):
        for op in node.ops:
            if not isinstance(op, _ALLOWED_COMPARE):
                raise UnsafeExpressionError(
                    "Comparison {} is not allowed".format(type(op).__name__))
        _validate(node.left, names)
        for comparator in node.comparators:
            _validate(comparator, names)
        return

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOLOPS):
            raise UnsafeExpressionError("Boolean operator not allowed")
        for value in node.values:
            _validate(value, names)
        return

    if isinstance(node, ast.IfExp):
        _validate(node.test, names)
        _validate(node.body, names)
        _validate(node.orelse, names)
        return

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise UnsafeExpressionError("Only direct function calls are allowed")
        if node.func.id not in _ALLOWED_FUNCTIONS:
            raise UnsafeExpressionError(
                "Function '{}' is not allowed".format(node.func.id))
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not allowed")
        for arg in node.args:
            _validate(arg, names)
        return

    raise UnsafeExpressionError(
        "Expression element {} is not allowed".format(type(node).__name__))


def _evaluate(node, names):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, names)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise UnsafeExpressionError(
            "Only numeric constants are allowed, got {!r}".format(node.value))

    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise UnsafeExpressionError("Unknown name '{}'".format(node.id))

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise UnsafeExpressionError(
                "Operator {} is not allowed".format(type(node.op).__name__))
        left = _evaluate(node.left, names)
        right = _evaluate(node.right, names)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise UnsafeExpressionError(
                "Exponent {} exceeds the maximum of {}".format(right, _MAX_EXPONENT))
        return _BINOP_IMPL[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise UnsafeExpressionError(
                "Operator {} is not allowed".format(type(node.op).__name__))
        return _UNARYOP_IMPL[type(node.op)](_evaluate(node.operand, names))

    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, names)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_COMPARE):
                raise UnsafeExpressionError(
                    "Comparison {} is not allowed".format(type(op).__name__))
            right = _evaluate(comparator, names)
            if not _COMPARE_IMPL[type(op)](left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOLOPS):
            raise UnsafeExpressionError("Boolean operator not allowed")
        values = [_evaluate(v, names) for v in node.values]
        if isinstance(node.op, ast.And):
            result = True
            for value in values:
                result = result and value
            return result
        result = False
        for value in values:
            result = result or value
        return result

    if isinstance(node, ast.IfExp):
        if _evaluate(node.test, names):
            return _evaluate(node.body, names)
        return _evaluate(node.orelse, names)

    if isinstance(node, ast.Call):
        # Only bare `name(...)` calls — never `obj.method(...)`, which is the
        # usual route to attribute-based sandbox escapes.
        if not isinstance(node.func, ast.Name):
            raise UnsafeExpressionError("Only direct function calls are allowed")
        if node.func.id not in _ALLOWED_FUNCTIONS:
            raise UnsafeExpressionError(
                "Function '{}' is not allowed".format(node.func.id))
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not allowed")
        args = [_evaluate(arg, names) for arg in node.args]
        return _ALLOWED_FUNCTIONS[node.func.id](*args)

    raise UnsafeExpressionError(
        "Expression element {} is not allowed".format(type(node).__name__))


_BINOP_IMPL = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}

_UNARYOP_IMPL = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
    ast.Not: lambda a: not a,
}

_COMPARE_IMPL = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}


def safe_eval(expression, variables=None):
    """Evaluate an arithmetic expression, rejecting anything else.

    :param expression: the expression source, e.g. 'x * 1.8 + 32'
    :param variables: mapping of variable name -> numeric value, e.g. {'x': 21.5}
    :return: the numeric result
    :raises UnsafeExpressionError: on disallowed syntax, unknown names, or a
        syntactically invalid expression

    Callers that previously did `eq.replace('x', str(v))` should pass
    `variables={'x': v}` instead — see this module's docstring.
    """
    if not isinstance(expression, str):
        raise UnsafeExpressionError(
            "Expression must be a string, got {}".format(type(expression).__name__))

    names = dict(_ALLOWED_CONSTANTS)
    if variables:
        names.update(variables)

    try:
        parsed = ast.parse(expression.strip(), mode='eval')
    except SyntaxError as err:
        raise UnsafeExpressionError(
            "Invalid expression {!r}: {}".format(expression, err))

    _validate(parsed, names)
    return _evaluate(parsed, names)


def validate_expression(expression, variable_names=()):
    """Check an equation without evaluating it — for validating user input at
    save time rather than waiting for the first measurement to arrive.

    :param expression: the expression source
    :param variable_names: names the expression is allowed to reference,
        e.g. ('x',) or ('a', 'b')
    :raises UnsafeExpressionError: if the expression would be rejected
    """
    safe_names = dict(_ALLOWED_CONSTANTS)
    for name in variable_names:
        safe_names[name] = 0

    if not isinstance(expression, str):
        raise UnsafeExpressionError(
            "Expression must be a string, got {}".format(type(expression).__name__))

    try:
        parsed = ast.parse(expression.strip(), mode='eval')
    except SyntaxError as err:
        raise UnsafeExpressionError(
            "Invalid expression {!r}: {}".format(expression, err))

    _validate(parsed, safe_names)
