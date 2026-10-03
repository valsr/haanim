"""Tests that the interpreter runs supported Python the way CPython does."""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.ast_evaluator import AstEvaluator
from haanim.engine.callables import accepted_kwargs, as_coroutine_function
from haanim.engine.errors import AutomationRuntimeError, AutomationSyntaxError
from haanim.engine.eval_function import FUNCTION_ATTRIBUTE, get_eval_function, run_to_completion
from haanim.engine.import_controller import ImportController
from haanim.engine.symbol_table import SCOPE_CLASS, SCOPE_COMPREHENSION, SCOPE_FUNCTION, SymbolTable
from haanim.engine.validation import validate_source
from tests.engine.helpers import make_context


async def load(source: str) -> dict[str, Any]:
    """Run a source in the interpreter and return its module-level names."""
    evaluator = AstEvaluator(name="test", import_controller=ImportController(allow_all=True))
    evaluator.parse(source, filename="main.py")
    return await evaluator.execute()


async def run(source: str) -> Any:
    """Run a source and return ``r``, or what its ``main()`` returns if it defines one."""
    symbols = await load(source)
    if "main" in symbols:
        return await symbols["main"]()
    return symbols.get("r")


# (source, expected result): cases beyond the table in test_validation.py.
CASES: dict[str, tuple[str, Any]] = {
    # Arguments
    "defaults are evaluated once": (
        "def f(a, acc=[]):\n    acc.append(a)\n    return acc\nf(1)\nr = f(2)",
        [1, 2],
    ),
    "default sees definition scope": ("n = 1\ndef f(a=n):\n    return a\nn = 2\nr = f()", 1),
    "keyword for positional": ("def f(a, b):\n    return (a, b)\nr = f(b=1, a=2)", (2, 1)),
    "all parameter kinds": (
        "def f(a, /, b, *c, d, e=5, **g):\n    return (a, b, c, d, e, g)\nr = f(1, 2, 3, 4, d=6, h=7)",
        (1, 2, (3, 4), 6, 5, {"h": 7}),
    ),
    "positional-only name reused as keyword": (
        "def f(a, /, **k):\n    return (a, k)\nr = f(1, a=2)",
        (1, {"a": 2}),
    ),
    "keyword-only default": ("def f(*, a=1, b):\n    return a + b\nr = f(b=2)", 3),
    "lambda with varargs": ("f = lambda *a, **k: (a, k)\nr = f(1, x=2)", ((1,), {"x": 2})),
    "starred and keyword unpacking together": (
        "def f(a, b, c, d):\n    return (a, b, c, d)\nr = f(*[1], 2, *(3,), **{'d': 4})",
        (1, 2, 3, 4),
    ),
    # Unpacking
    "star in the middle": ("a, *b, c = range(5)\nr = (a, b, c)", (0, [1, 2, 3], 4)),
    "star takes nothing": ("a, *b = [1]\nr = (a, b)", (1, [])),
    "star first": ("*a, b = 'xyz'\nr = (a, b)", (["x", "y"], "z")),
    "star in for target": ("r = [b for a, *b in [(1, 2, 3)]]", [[2, 3]]),
    "star in tuple and set": ("r = ((*[1, 2], 3), {*[1, 1], 2})", ((1, 2, 3), {1, 2})),
    # Scoping
    "global from a nested function": (
        "g = 0\ndef outer():\n    def inner():\n        global g\n        g += 1\n    inner()\nouter()\nr = g",
        1,
    ),
    "global creates the name": ("def f():\n    global made\n    made = 3\nf()\nr = made", 3),
    "assignment without global stays local": (
        "g = 1\ndef f():\n    g = 2\n    return g\nr = (f(), g)",
        (2, 1),
    ),
    "nonlocal through two levels": (
        "def a():\n    x = 0\n    def b():\n        def c():\n            nonlocal x\n            x = 5\n        c()\n"
        "    b()\n    return x\nr = a()",
        5,
    ),
    "nonlocal skips the module scope": (
        "x = 'module'\ndef a():\n    x = 'a'\n    def b():\n        nonlocal x\n        x = 'b'\n    b()\n    return x\n"
        "r = (a(), x)",
        ("b", "module"),
    ),
    "closures keep separate state": (
        "def counter():\n    n = 0\n    def inc():\n        nonlocal n\n        n += 1\n        return n\n    return inc\n"
        "a = counter()\nb = counter()\na()\na()\nr = (a(), b())",
        (3, 1),
    ),
    "walrus in a comprehension binds outside it": ("values = [last := x for x in range(3)]\nr = last", 2),
    "comprehension variable does not leak": ("x = 'outer'\n[x for x in range(3)]\nr = x", "outer"),
    "del of a local": (
        "def f():\n    x = 1\n    del x\n    try:\n        return x\n    except Exception:\n        return 'gone'\nr = f()",
        "gone",
    ),
    "except name is unbound after the handler": (
        "e = 'kept'\ntry:\n    raise ValueError('x')\nexcept ValueError as e:\n    pass\n"
        "try:\n    r = e\nexcept Exception:\n    r = 'unbound'",
        "unbound",
    ),
    # Control flow through try and with
    "return inside try is not caught by except Exception": (
        "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\nr = f()",
        1,
    ),
    "return inside try is not caught by bare except": (
        "def f():\n    try:\n        return 1\n    except:\n        return 2\nr = f()",
        1,
    ),
    "break inside try runs finally": (
        "log = []\nfor i in range(3):\n    try:\n        break\n    finally:\n        log.append(i)\nr = log",
        [0],
    ),
    "continue inside try": (
        "log = []\nfor i in range(3):\n    try:\n        continue\n    except Exception:\n        log.append('caught')\n"
        "    log.append(i)\nr = log",
        [],
    ),
    "finally runs on return": (
        "log = []\ndef f():\n    try:\n        return 1\n    finally:\n        log.append('finally')\nr = (f(), log)",
        (1, ["finally"]),
    ),
    "first matching handler wins": (
        "try:\n    raise KeyError('k')\nexcept ValueError:\n    r = 'value'\nexcept (KeyError, IndexError):\n    r = 'key'\n"
        "except Exception:\n    r = 'other'",
        "key",
    ),
    "unmatched exception propagates": (
        "def f():\n    try:\n        raise KeyError('k')\n    except ValueError:\n        return 'wrong'\n"
        "try:\n    f()\nexcept KeyError:\n    r = 'propagated'",
        "propagated",
    ),
    "error in else is not caught by the handlers": (
        "try:\n    try:\n        pass\n    except ValueError:\n        r = 'wrong'\n    else:\n        raise ValueError('x')\n"
        "except ValueError:\n    r = 'outer'",
        "outer",
    ),
    "with passes the exception to __exit__": (
        "class C:\n    def __enter__(self):\n        return self\n    def __exit__(self, kind, value, tb):\n"
        "        self.seen = (kind.__name__, str(value))\n        return True\n"
        "c = C()\nwith c:\n    raise ValueError('boom')\nr = c.seen",
        ("ValueError", "boom"),
    ),
    "with does not suppress when __exit__ is falsy": (
        "class C:\n    def __enter__(self):\n        return self\n    def __exit__(self, *a):\n        return None\n"
        "try:\n    with C():\n        raise ValueError('x')\nexcept ValueError:\n    r = 'raised'",
        "raised",
    ),
    "return inside with exits without an exception": (
        "seen = []\nclass C:\n    def __enter__(self):\n        return self\n    def __exit__(self, *a):\n"
        "        seen.append(a)\ndef f():\n    with C():\n        return 1\nr = (f(), seen)",
        (1, [(None, None, None)]),
    ),
    "several managers exit in reverse order": (
        "log = []\nclass C:\n    def __init__(self, n):\n        self.n = n\n    def __enter__(self):\n"
        "        log.append('in' + self.n)\n        return self.n\n    def __exit__(self, *a):\n        log.append('out' + self.n)\n"
        "with C('a') as a, C('b') as b:\n    log.append(a + b)\nr = log",
        ["ina", "inb", "ab", "outb", "outa"],
    ),
    "inner manager can suppress for the outer": (
        "from contextlib import suppress\nseen = []\nclass C:\n    def __enter__(self):\n        return self\n"
        "    def __exit__(self, *a):\n        seen.append(a[0])\n"
        "with C(), suppress(ValueError):\n    raise ValueError('x')\nr = seen",
        [None],
    ),
    # Classes
    "__init__ and instance attributes": (
        "class P:\n    def __init__(self, x, y=2):\n        self.x = x\n        self.y = y\np = P(1)\nr = (p.x, p.y)",
        (1, 2),
    ),
    "classmethod and staticmethod": (
        "class A:\n    n = 3\n    @classmethod\n    def c(cls):\n        return cls.n\n    @staticmethod\n    def s(v):\n"
        "        return v * 2\nr = (A.c(), A().c(), A.s(2), A().s(3))",
        (3, 3, 4, 6),
    ),
    "property with setter": (
        "class A:\n    def __init__(self):\n        self._v = 1\n    @property\n    def v(self):\n        return self._v\n"
        "    @v.setter\n    def v(self, value):\n        self._v = value * 2\na = A()\na.v = 5\nr = a.v",
        10,
    ),
    "dunder methods called by Python": (
        "class V:\n    def __init__(self, n):\n        self.n = n\n    def __repr__(self):\n        return f'V({self.n})'\n"
        "    def __eq__(self, other):\n        return self.n == other.n\n    def __hash__(self):\n        return hash(self.n)\n"
        "    def __add__(self, other):\n        return V(self.n + other.n)\n    def __len__(self):\n        return self.n\n"
        "    def __lt__(self, other):\n        return self.n < other.n\n    def __iter__(self):\n        return iter(range(self.n))\n"
        "    def __getitem__(self, i):\n        return i * 2\n    def __bool__(self):\n        return self.n > 0\n"
        "    def __contains__(self, item):\n        return item == self.n\n    def __call__(self, x):\n        return self.n + x\n"
        "v = V(1) + V(2)\n"
        "r = (repr(v), str(v), v == V(3), len(v), V(1) < V(2), list(v), v[4], bool(V(0)), 3 in v, v(4), len({V(1), V(1)}),"
        " sorted([V(2), V(1)])[0].n, f'{v}')",
        ("V(3)", "V(3)", True, 3, True, [0, 1, 2], 8, False, True, 7, 1, 1, "V(3)"),
    ),
    "super().__init__ with arguments": (
        "class A:\n    def __init__(self, x):\n        self.x = x\nclass B(A):\n    def __init__(self, x, y):\n"
        "        super().__init__(x)\n        self.y = y\nb = B(1, 2)\nr = (b.x, b.y)",
        (1, 2),
    ),
    "super through three levels": (
        "class A:\n    def who(self):\n        return ['A']\nclass B(A):\n    def who(self):\n        return ['B'] + super().who()\n"
        "class C(B):\n    def who(self):\n        return ['C'] + super().who()\nr = C().who()",
        ["C", "B", "A"],
    ),
    "super with explicit arguments": (
        "class A:\n    def m(self):\n        return 1\nclass B(A):\n    def m(self):\n        return super(B, self).m() + 1\nr = B().m()",
        2,
    ),
    "super in a classmethod": (
        "class A:\n    @classmethod\n    def make(cls):\n        return cls.__name__\nclass B(A):\n    @classmethod\n"
        "    def make(cls):\n        return 'B:' + super().make()\nr = B.make()",
        "B:B",
    ),
    "__class__ in a method": (
        "class A:\n    def m(self):\n        return __class__.__name__\nr = A().m()",
        "A",
    ),
    "method does not see class body names": (
        "x = 'module'\nclass A:\n    x = 'class'\n    def m(self):\n        return x\nr = A().m()",
        "module",
    ),
    "class body sees its own names": ("class A:\n    a = 1\n    b = a + 1\nr = A.b", 2),
    "class attributes exclude outer names": (
        "outer = 1\nclass A:\n    inner = 2\nr = (hasattr(A, 'outer'), hasattr(A, 'inner'), A.__name__)",
        (False, True, "A"),
    ),
    "inheriting from a native class": (
        "class MyError(ValueError):\n    def __init__(self, code):\n        super().__init__(f'code {code}')\n"
        "        self.code = code\ntry:\n    raise MyError(7)\nexcept ValueError as e:\n    r = (str(e), e.code)",
        ("code 7", 7),
    ),
    "dataclass": (
        "from dataclasses import dataclass\n@dataclass\nclass P:\n    x: int = 1\n    y: int = 2\n"
        "    def total(self):\n        return self.x + self.y\nr = (P(3).total(), P(1, 2) == P(1, 2))",
        (5, True),
    ),
    "enum": (
        "from enum import Enum\nclass Color(Enum):\n    RED = 1\n    GREEN = 2\nr = (Color.RED.value, Color(2).name)",
        (1, "GREEN"),
    ),
    "class keywords reach __init_subclass__": (
        "class Base:\n    def __init_subclass__(cls, tag=None, **kwargs):\n        super().__init_subclass__(**kwargs)\n"
        "        cls.tag = tag\nclass Child(Base, tag='x'):\n    pass\nr = Child.tag",
        "x",
    ),
    "class decorator written in the automation": (
        "def mark(cls):\n    cls.marked = True\n    return cls\n@mark\nclass A:\n    pass\nr = A.marked",
        True,
    ),
    "nested class": ("class A:\n    class B:\n        v = 1\nr = A.B.v", 1),
    "isinstance and bound method identity": (
        "class A:\n    def m(self):\n        return 1\na = A()\nf = a.m\nr = (isinstance(a, A), f(), A.m(a))",
        (True, 1, 1),
    ),
    # Functions called by Python itself
    "decorator with arguments": (
        "def times(n):\n    def deco(f):\n        def wrapper(*a, **k):\n            return f(*a, **k) * n\n        return wrapper\n"
        "    return deco\n@times(3)\ndef f(x):\n    return x + 1\nr = f(1)",
        6,
    ),
    "functools.wraps": (
        "import functools\ndef deco(f):\n    @functools.wraps(f)\n    def wrapper(*a):\n        return f(*a) + 1\n    return wrapper\n"
        "@deco\ndef f(x):\n    '''doc'''\n    return x\nr = (f(1), f.__name__, f.__doc__)",
        (2, "f", "doc"),
    ),
    "stacked decorators apply bottom up": (
        "def a(f):\n    return lambda: 'a' + f()\ndef b(f):\n    return lambda: 'b' + f()\n@a\n@b\ndef f():\n    return 'f'\nr = f()",
        "abf",
    ),
    "callbacks": (
        "import functools\ndef double(v):\n    return v * 2\n"
        "r = (list(map(double, [1, 2])), list(filter(lambda v: v > 1, [1, 2])), max([1, -3], key=abs),"
        " min(['bb', 'a'], key=lambda s: len(s)), functools.reduce(lambda a, b: a + b, [1, 2, 3]),"
        " functools.partial(double, 4)())",
        ([2, 4], [2], -3, "a", 6, 8),
    ),
    "recursion": ("def fact(n):\n    return 1 if n <= 1 else n * fact(n - 1)\nr = fact(10)", 3628800),
    "function attributes": (
        "def f(a, b=1):\n    '''The doc.'''\nf.tag = 'x'\nr = (f.__name__, f.__doc__, f.tag, callable(f))",
        ("f", "The doc.", "x", True),
    ),
    "exception from a callback propagates": (
        "def bad(v):\n    raise KeyError(v)\ntry:\n    sorted([2, 1], key=bad)\nexcept KeyError as e:\n    r = e.args[0]",
        2,
    ),
    # Async
    "await a coroutine stored in a variable": (
        "async def f():\n    return 1\nasync def main():\n    pending = f()\n    return await pending",
        1,
    ),
    "gather runs coroutines created without await": (
        "import asyncio\nasync def f(v):\n    await asyncio.sleep(0)\n    return v\n"
        "async def main():\n    return await asyncio.gather(f(1), f(2))",
        [1, 2],
    ),
    "create_task": (
        "import asyncio\nasync def f():\n    return 'done'\nasync def main():\n    task = asyncio.create_task(f())\n    return await task",
        "done",
    ),
    "async method": (
        "class A:\n    async def m(self, v):\n        return v + 1\nasync def main():\n    return await A().m(1)",
        2,
    ),
    "def called from async def": (
        "def helper(v):\n    return v * 2\nasync def main():\n    return helper(2)",
        4,
    ),
    "async with suppresses": (
        "class C:\n    async def __aenter__(self):\n        return self\n    async def __aexit__(self, kind, value, tb):\n"
        "        return kind is ValueError\nasync def main():\n    async with C():\n        raise ValueError('x')\n    return 'after'",
        "after",
    ),
    "CancelledError can be caught": (
        "import asyncio\nasync def main():\n    try:\n        raise asyncio.CancelledError()\n    except asyncio.CancelledError:\n"
        "        return 'cleaned up'",
        "cleaned up",
    ),
    "await in a comprehension condition": (
        "async def ok(v):\n    return v > 1\nasync def main():\n    return [v for v in range(4) if await ok(v)]",
        [2, 3],
    ),
    # Other
    "type alias": (
        "type Pair = tuple[int, int]\nr = (Pair.__name__, Pair.__value__ == tuple[int, int])",
        ("Pair", True),
    ),
}

# (source, exception type, text in the message)
ERRORS: dict[str, tuple[str, type[BaseException], str]] = {
    "missing argument": ("def f(a, b):\n    pass\nf(1)", TypeError, "f() missing required arguments: 'b'"),
    "missing keyword-only argument": (
        "def f(*, a):\n    pass\nf()",
        TypeError,
        "missing required arguments: 'a'",
    ),
    "too many arguments": (
        "def f(a):\n    pass\nf(1, 2)",
        TypeError,
        "takes 1 positional arguments but 2 were given",
    ),
    "unexpected keyword": ("def f(a):\n    pass\nf(1, b=2)", TypeError, "unexpected keyword argument 'b'"),
    "duplicate argument": ("def f(a):\n    pass\nf(1, a=2)", TypeError, "multiple values for argument 'a'"),
    "positional-only passed by keyword": (
        "def f(a, /):\n    pass\nf(a=1)",
        TypeError,
        "unexpected keyword argument 'a'",
    ),
    "lambda argument error": ("f = lambda a: a\nf()", TypeError, "<lambda>() missing"),
    "too many values to unpack": (
        "a, b = [1, 2, 3]",
        ValueError,
        "too many values to unpack (expected 2, got 3)",
    ),
    "not enough values to unpack": (
        "a, b, c = [1, 2]",
        ValueError,
        "not enough values to unpack (expected 3, got 2)",
    ),
    "not enough values with a star": ("a, *b, c = [1]", ValueError, "expected at least 2, got 1"),
    "unpack a non-iterable": ("a, b = 1", TypeError, "cannot unpack non-iterable int object"),
    "with on a non context manager": (
        "with 1:\n    pass",
        TypeError,
        "'int' object does not support the context manager",
    ),
    "async with on a sync context manager": (
        "class C:\n    def __enter__(self):\n        pass\n    def __exit__(self, *a):\n        pass\n"
        "async def main():\n    async with C():\n        pass",
        TypeError,
        "does not support the asynchronous context manager protocol",
    ),
    "await something that is not awaitable": ("async def main():\n    await 1", TypeError, "int"),
    "exception raised in a method": (
        "class A:\n    def m(self):\n        raise KeyError('from method')\nA().m()",
        KeyError,
        "from method",
    ),
    "exception raised in __init__": (
        "class A:\n    def __init__(self):\n        raise ValueError('from init')\nA()",
        ValueError,
        "from init",
    ),
}


# Sources whose module-level ``r`` must be what CPython computes for the same source.
SAME_AS_PYTHON: list[str] = [
    "a = b = [1]\na += [2]\nr = (a, b, a is b)",
    "a = b = (1,)\na += (2,)\nr = (a, b)",
    "s = t = {1}\ns |= {2}\ns &= {2, 3}\nr = (s, t)",
    "class M:\n    def __matmul__(self, o):\n        return 'mat'\n    def __imatmul__(self, o):\n        return 'imat'\nm = M()\nr1 = m @ 1\nm @= 1\nr = (r1, m)",
    "x = 7\nx //= 2\nx **= 2\nx %= 5\nx <<= 2\nx >>= 1\nx ^= 1\nx /= 2\nr = x",
    "r = (0 or 'd', 1 and 2, None or 0 or [], 1 and 0 and 3, '' or None)",
    "s = 'a'\nr = f'{s!r} {s!s} {s!a:>5} {1+1=}'",
    "w = 6\nr = f'{3.14159:{w}.2f}|{12:>{w}}'",
    "r = [1,2,3,4,5][::2], 'hello'[1:-1], [1,2,3][::-1]",
    "d = {'a': [1]}\nd['a'] += [2]\nd['a'][0] -= 5\nr = d",
    "class A:\n    pass\na = A()\na.v = 1\na.v += 2\na.v **= 2\nr = a.v",
    "m = [[1,2],[3,4]]\nm[0][1] = 9\nr = m; del m[1]",
    "r = 1 < 2 > 1 == 1 != 3, 1 < 2 < 2",
    "calls = []\ndef f(v):\n    calls.append(v)\n    return v\nr = (f(1) < f(0) < f(5), calls)",
    "x = [1,2]\ny = x\nr = (x is y, x is not [1,2], 3 not in x)",
    "r = [i for i in range(10) if i % 2 if i > 3]",
    "r = {k: [v for v in range(k)] for k in range(3)}",
    "a = b = c = 5\nr = (a, b, c)",
    "a, b = 1, 2\na, b = b, a\nr = (a, b)",
    "r = 0\nfor i in range(3):\n    for j in range(3):\n        if j == 1:\n            break\n        r += 1\nelse:\n    r += 100",
    "r = 0\ni = 0\nwhile True:\n    i += 1\n    if i > 5:\n        break\n    if i % 2:\n        continue\n    r += i",
    "r = []\nfor i, (a, b) in enumerate([(1, 2), (3, 4)]):\n    r.append((i, a, b))",
    "def f():\n    for i in range(5):\n        if i == 3:\n            return i\n    return -1\nr = f()",
    "def f():\n    while True:\n        try:\n            return 'ret'\n        finally:\n            pass\nr = f()",
    "def f(x):\n    if x:\n        return 'yes'\n    elif x is None:\n        return 'none'\n    else:\n        return 'no'\nr = (f(1), f(None), f(0))",
    "r = (lambda: (yield_ := 3))()",
    "r = -2 ** 2, +3, not None, ~5, 7 / 2, -7 // 2, 2 ** -1, 'a' * 2, [1] + [2], 5 % -3",
    "import math\nr = (math.pi > 3, abs(-1), round(2.567, 1), divmod(7, 2), int('7'), str(1.0), list('ab'), dict(a=1), tuple([1]), set([1]))",
    "r = (isinstance(1, int), isinstance('a', (int, str)), issubclass(bool, int), type(1) is int, len([1,2]), sum([1,2]), any([0,1]), all([]), sorted({3,1}), list(reversed([1,2])), list(zip([1],[2])), max(1,2))",
    "x = 5\nr = 'big' if x > 3 else 'small' if x > 1 else 'tiny'",
    "r = 'a' 'b' + \"c\" + '''d''' + r'\\n' + b'x'.decode()",
    "def f(*, k):\n    return k\nr = f(**{'k': 1})",
    "def outer():\n    x = 1\n    def inner():\n        return x\n    x = 2\n    return inner()\nr = outer()",
    "fs = []\nfor i in range(3):\n    fs.append(lambda: i)\nr = [f() for f in fs]",
    "def f(n):\n    return n if n < 2 else f(n-1) + f(n-2)\nr = f(15)",
    "try:\n    1 / 0\nexcept ZeroDivisionError as e:\n    r = type(e).__name__\nfinally:\n    pass",
    "try:\n    {}['k']\nexcept (KeyError, ValueError) as e:\n    r = repr(e)",
    "try:\n    [][1]\nexcept LookupError:\n    r = 'lookup'",
    "try:\n    int('x')\nexcept ValueError as e:\n    r = str(e)",
    "try:\n    None.x\nexcept AttributeError as e:\n    r = 'attr'",
    "try:\n    undefined_name\nexcept NameError:\n    r = 'name'",
    "def f():\n    return undefined_thing\ntry:\n    f()\nexcept NameError as e:\n    r = str(e)",
    "try:\n    assert 1 == 2, 'msg'\nexcept AssertionError as e:\n    r = str(e)",
    "try:\n    assert False\nexcept AssertionError as e:\n    r = str(e)",
    "class E(Exception):\n    pass\ntry:\n    raise E\nexcept E as e:\n    r = type(e).__name__",
    "try:\n    try:\n        raise ValueError('a')\n    finally:\n        r1 = 'f'\nexcept ValueError:\n    r = r1",
    "try:\n    raise ValueError('a') from None\nexcept ValueError as e:\n    r = (e.__cause__, e.__suppress_context__)",
    "def f():\n    try:\n        raise ValueError('a')\n    except ValueError:\n        raise\ntry:\n    f()\nexcept ValueError as e:\n    r = str(e)",
    "x = 10\ndef f():\n    return x\nx = 20\nr = f()",
    "x = [1, 2, 3]\ndel x[0]\nd = {'a': 1}\ndel d['a']\nr = (x, d)",
    "a = [1,2,3]\na[1:2] = [7, 8]\nr = a",
    "a = [1,2,3,4]\ndel a[::2]\nr = a",
    "r = [x for x in 'abc'][-1], 'abc'.upper().lower().split('b'), ','.join(['a','b'])",
    "r = {1, 2} | {3}, {1, 2} & {2}, {1: 2}.get(3, 'd'), {**{'a': 1}, **{'a': 2}}",
    "r = (1,) + (2,), (1, 2)[1], len(()), [(a, b) for a, b in {'x': 1}.items()]",
    "r = 0x10, 0b11, 1_000, 1e3, 3 // 2, 3.0 // 2, True + True, None is None",
    "class A:\n    count = 0\n    def __init__(self):\n        A.count += 1\nA(); A()\nr = A.count",
    "class A:\n    def __init__(self):\n        self.items = []\n    def add(self, x):\n        self.items.append(x)\n        return self\nr = A().add(1).add(2).items",
    "class A:\n    def m(self):\n        return 'A'\nclass B(A):\n    pass\nclass C(B):\n    def m(self):\n        return 'C' + super().m()\nr = (C().m(), [k.__name__ for k in C.__mro__])",
    "class A:\n    x = 1\nclass B(A):\n    x = 2\nr = (A.x, B.x, B().x, isinstance(B(), A), issubclass(B, A))",
    "class A:\n    def __init__(self, v):\n        self.v = v\n    def __eq__(self, o):\n        return self.v == o.v\nr = (A(1) == A(1), A(1) != A(2), A(1) in [A(1)])",
    "class Stack:\n    def __init__(self):\n        self._d = []\n    def push(self, v):\n        self._d.append(v)\n    def __len__(self):\n        return len(self._d)\n    def __bool__(self):\n        return bool(self._d)\ns = Stack()\nr1 = bool(s)\ns.push(1)\nr = (r1, bool(s), len(s), 'yes' if s else 'no')",
    "class A:\n    def __getattr__(self, name):\n        return name.upper()\nr = A().hello",
    "class A:\n    __slots__ = ('x',)\n    def __init__(self):\n        self.x = 1\nr = A().x",
    "class A:\n    def __iter__(self):\n        return iter([1, 2])\nr = [x for x in A()] + list(A())\nfor v in A():\n    r.append(v)",
    "class A:\n    '''Doc.'''\n    def m(self):\n        '''M doc.'''\nr = (A.__doc__, A.m.__doc__, A.__name__, A.m.__name__)",
    "from dataclasses import dataclass, field\n@dataclass(frozen=True)\nclass P:\n    x: int\n    tags: list = field(default_factory=list)\nr = (P(1), P(1).tags, repr(P(2)))",
    "from typing import NamedTuple\nclass P(NamedTuple):\n    x: int\n    y: int = 0\nr = (P(1), P(1, 2).y, P(1)._asdict())",
    "from abc import ABC, abstractmethod\nclass B(ABC):\n    @abstractmethod\n    def m(self):\n        ...\nclass C(B):\n    def m(self):\n        return 1\ntry:\n    B()\n    r = 'bad'\nexcept TypeError:\n    r = C().m()",
    "import functools\n@functools.lru_cache(maxsize=None)\ndef fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\nr = fib(30)",
    "import itertools\nr = list(itertools.chain([1], [2])), list(itertools.accumulate([1, 2, 3], lambda a, b: a * b))",
    "import re\nr = re.sub(r'\\d', lambda m: str(int(m.group()) * 2), 'a1b2')",
    "from collections import defaultdict\nd = defaultdict(lambda: 'x')\nr = d['k']",
    "data = [{'n': 'b', 'v': 2}, {'n': 'a', 'v': 1}]\ndata.sort(key=lambda d: d['n'])\nr = [d['v'] for d in data]",
    "import json\nclass A:\n    def to(self):\n        return {'a': 1}\nr = json.dumps(A().to(), default=lambda o: str(o))",
    "x: int\ny: str = 'a'\nr = (y, __annotations__)",
    "def f(a: int, b: 'str' = 'x') -> bool:\n    return True\nr = f(1)",
    "r = [(yield_x) for yield_x in range(2)]",
    "r = 5\ndef f():\n    global r\n    r += 1\nf(); f()",
    "r = [n for n in range(3)]\nn = 'kept'\n[n for n in range(5)]\nr = n",
    "i = 'kept'\nfor i in range(3):\n    pass\nr = i",
    "def f(a, b=None):\n    b = b or []\n    b.append(a)\n    return b\nr = (f(1), f(2, [0]))",
    "def gen_like(n):\n    return [i * i for i in range(n)]\nr = sum(gen_like(4))",
    "x = 3\nr = x if (y := x * 2) > 5 else y\nr = (r, y)",
    "r = [y for x in range(3) if (y := x * 2) > 1]",
    "nums = [1, 2, 3]\nr = [*nums, *nums][2:], {*nums}, (*nums,), [*'ab']",
    "def f(a, b, /, c, *, d):\n    return a + b + c + d\nr = f(1, 2, c=3, d=4)",
    "r = (lambda *, k=1: k)(), (lambda a, /, b: a + b)(1, b=2)",
    "r = bool([]) or bool({}) or not ()",
    "a = [3, 1, 2]\na.sort(reverse=True)\nr = (a, sorted(a), min(a), a.index(1), a.count(3))",
    "r = '%s-%d' % ('a', 1), '{}-{k}'.format(1, k=2), 'abc'.startswith(('a', 'x'))",
    "class Temp:\n    def __init__(self):\n        self._c = 0\n    @property\n    def f(self):\n        return self._c * 9 / 5 + 32\n    @f.setter\n    def f(self, v):\n        self._c = (v - 32) * 5 / 9\n    @f.deleter\n    def f(self):\n        self._c = None\nt = Temp()\nt.f = 212\nr1 = t._c\ndel t.f\nr = (r1, t._c)",
]


class TestSupportedPython:
    """The interpreter gives the result Python gives."""

    @pytest.mark.parametrize("case", CASES)
    async def test_result(self, case: str) -> None:
        """The source produces the expected value."""
        source, expected = CASES[case]

        assert await run(source) == expected

    @pytest.mark.parametrize("case", CASES)
    async def test_agrees_with_python(self, case: str) -> None:
        """The expected value is what CPython itself produces for the source."""
        source, expected = CASES[case]
        namespace: dict[str, Any] = {"__name__": "__main__"}

        exec(compile(source, "main.py", "exec", dont_inherit=True), namespace)  # pylint: disable=exec-used
        result = await namespace["main"]() if "main" in namespace else namespace["r"]

        assert result == expected

    @pytest.mark.parametrize("source", SAME_AS_PYTHON)
    async def test_same_as_python(self, source: str) -> None:
        """The interpreter and CPython compute the same value for the source."""
        namespace: dict[str, Any] = {"__name__": "__main__"}
        exec(compile(source, "main.py", "exec", dont_inherit=True), namespace)  # pylint: disable=exec-used

        evaluator = AstEvaluator(name="__main__", import_controller=ImportController(allow_all=True))
        evaluator.parse(source, filename="main.py")
        result = (await evaluator.execute()).get("r")

        assert repr(result) == repr(namespace["r"])

    @pytest.mark.parametrize("case", ERRORS)
    async def test_error(self, case: str) -> None:
        """The source fails with the exception Python raises."""
        source, error, text = ERRORS[case]

        # execute() wraps failures of module-level code; the original exception is the cause.
        with pytest.raises((error, AutomationRuntimeError)) as raised:
            await run(source)

        original = (
            raised.value.__cause__ if isinstance(raised.value, AutomationRuntimeError) else raised.value
        )
        assert isinstance(original, error)

        assert text in str(raised.value)


class TestAwaitRule:
    """An async call does nothing until it is awaited."""

    async def test_async_call_without_await_returns_a_coroutine(self) -> None:
        """Calling an async function gives a coroutine and does not run the body."""
        symbols = await load("ran = []\nasync def f():\n    ran.append(1)\n    return 2\npending = f()\n")

        assert inspect.iscoroutine(symbols["pending"])
        assert symbols["ran"] == []
        assert await symbols["pending"] == 2
        assert symbols["ran"] == [1]

    async def test_native_async_call_is_not_awaited(self) -> None:
        """An async function from outside the automation is not awaited either."""
        calls: list[int] = []

        async def native(value: int) -> int:
            calls.append(value)
            return value

        evaluator = AstEvaluator(name="test")
        evaluator.get_global_symbols().set("native", native)
        evaluator.parse("pending = native(1)\nasync def main():\n    return await native(2)\n")
        symbols = await evaluator.execute()

        assert calls == []
        assert await symbols["main"]() == 2
        assert await symbols["pending"] == 1

    async def test_discarded_coroutine_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """A call written without await logs a warning with file and line, and never runs."""
        source = "ran = []\nasync def notify():\n    ran.append(1)\n\nasync def main():\n    x = 1\n    notify()\n    return ran\n"

        with caplog.at_level(logging.WARNING):
            assert await run(source) == []

        assert "main.py:7: coroutine 'notify' was never awaited" in caplog.text

    async def test_awaited_call_is_not_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """An awaited call logs nothing."""
        with caplog.at_level(logging.WARNING):
            await run("async def f():\n    pass\nasync def main():\n    await f()\n")

        assert "never awaited" not in caplog.text

    @pytest.mark.parametrize(
        ("source", "lineno"),
        [
            ("async def f():\n    pass\n\nawait f()\n", 4),
            ("async def f():\n    pass\ndef g():\n    await f()\n", 4),
            ("async def f():\n    pass\nh = lambda: await f()\n", 3),
            ("class A:\n    await x\n", 2),
        ],
        ids=["top level", "in def", "in lambda", "in class body"],
    )
    def test_await_outside_async_def_is_a_load_error(self, source: str, lineno: int) -> None:
        """Await is only allowed inside async def."""
        with pytest.raises(AutomationSyntaxError, match="outside") as raised:
            validate_source(source, filename="main.py")

        assert raised.value.lineno == lineno
        assert str(raised.value).startswith(f"main.py:{lineno}: invalid syntax: ")

    @pytest.mark.parametrize(
        ("source", "text"),
        [
            ("return 1\n", "'return' outside function"),
            ("break\n", "'break' outside loop"),
            ("def f():\n    x = 1\n    global x\n", "assigned to before global declaration"),
            ("def f():\n    nonlocal x\n", "no binding for nonlocal 'x' found"),
        ],
        ids=["return", "break", "global", "nonlocal"],
    )
    def test_compiler_errors_are_load_errors(self, source: str, text: str) -> None:
        """What Python's compiler rejects is rejected at load."""
        with pytest.raises(AutomationSyntaxError, match=text):
            validate_source(source, filename="main.py")

    def test_compiler_error_is_listed_with_unsupported_constructs(self) -> None:
        """Both kinds of problem are reported together, in source order."""
        source = "def gen():\n    yield 1\n\nawait gen()\n"

        with pytest.raises(AutomationSyntaxError) as raised:
            validate_source(source, filename="main.py")

        assert [problem.lineno for problem in raised.value.problems] == [2, 4]

    def test_syntax_warnings_are_not_raised(self, recwarn: pytest.WarningsRecorder) -> None:
        """Compiling for validation does not leak Python's syntax warnings."""
        validate_source("r = 1 is 1\n")

        assert not [warning for warning in recwarn if issubclass(warning.category, SyntaxWarning)]


class TestFunctionObjects:
    """Functions of an automation are real Python callables."""

    async def test_def_is_a_plain_function(self) -> None:
        """A def can be called from Python without awaiting."""
        symbols = await load("def f(a, b=2):\n    return a + b\n")
        func = symbols["f"]

        assert inspect.isfunction(func)
        assert not inspect.iscoroutinefunction(func)
        assert func(1) == 3
        assert func.__module__ == "test"

    async def test_async_def_is_a_coroutine_function(self) -> None:
        """An async def is seen as a coroutine function by Python."""
        symbols = await load("async def f(a):\n    return a\n")
        func = symbols["f"]

        assert inspect.iscoroutinefunction(func)
        assert await func(5) == 5

    async def test_signature(self) -> None:
        """Python reports the parameters the automation declared."""
        symbols = await load("def f(a, /, b, c=1, *d, e, f=2, **g):\n    pass\n")

        assert str(inspect.signature(symbols["f"])) == "(a, /, b, c=1, *d, e, f=2, **g)"

    async def test_get_eval_function(self) -> None:
        """The interpreter recognises its own functions and bound methods, and nothing else."""
        symbols = await load(
            "import functools\ndef f():\n    pass\nclass A:\n    def m(self):\n        pass\na = A()\n"
            "@functools.wraps(f)\ndef wrapped():\n    return 'wrapper'\n"
        )

        found = get_eval_function(symbols["f"])
        assert found is not None and found[0].name == "f" and found[1] == ()
        method = get_eval_function(symbols["a"].m)
        assert method is not None and method[0].name == "m" and method[1] == (symbols["a"],)
        assert get_eval_function(len) is None
        assert get_eval_function(lambda: None) is None
        assert get_eval_function(symbols["A"]) is None
        # functools.wraps copied f's attributes, but the wrapper is its own function.
        assert getattr(symbols["wrapped"], FUNCTION_ATTRIBUTE).name == "f"
        wrapper = get_eval_function(symbols["wrapped"])
        assert wrapper is None or wrapper[0].name == "wrapped"
        assert symbols["wrapped"]() == "wrapper"

    async def test_as_coroutine_function(self) -> None:
        """Both kinds of automation function can be run as a coroutine."""
        symbols = await load(
            "def f(v):\n    return v\nasync def g(v):\n    return v\nclass A:\n    def m(self, v):\n        return v\na = A()\n"
        )

        for name in ("f", "g"):
            assert await as_coroutine_function(symbols[name])(3) == 3
        assert await as_coroutine_function(symbols["a"].m)(4) == 4
        assert as_coroutine_function(symbols["g"]) is symbols["g"]
        assert await as_coroutine_function(len)("ab") == 2

    async def test_run_to_completion_refuses_to_wait(self) -> None:
        """A function called from outside the interpreter cannot wait for anything."""

        async def waits() -> None:
            await asyncio.get_running_loop().create_future()

        with pytest.raises(RuntimeError, match="'slow' cannot wait"):
            run_to_completion(waits(), "slow")

    def test_run_to_completion_skips_checkpoints(self) -> None:
        """A bare yield to the event loop does not stop the function."""

        async def checkpoints() -> str:
            for _ in range(3):
                await asyncio.sleep(0)
            return "done"

        assert run_to_completion(checkpoints(), "f") == "done"


class TestAcceptedKwargs:
    """The engine passes a function only the context it declares."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("def f():\n    pass\n", {}),
            ("def f(manual):\n    pass\n", {"manual": False}),
            ("def f(value, *, manual=True):\n    pass\n", {"manual": False, "value": 1}),
            ("def f(**context):\n    pass\n", {"manual": False, "value": 1, "extra": 2}),
            ("def f(manual, /):\n    pass\n", {}),
            ("f = lambda value: value\n", {"value": 1}),
        ],
        ids=["none", "one", "keyword-only", "var keyword", "positional-only", "lambda"],
    )
    async def test_automation_function(self, source: str, expected: dict[str, Any]) -> None:
        """Only declared parameters are kept."""
        func = (await load(source))["f"]

        assert accepted_kwargs(func, {"manual": False, "value": 1, "extra": 2}) == expected

    def test_callable_without_signature_gets_everything(self) -> None:
        """A callable Python cannot inspect is given all of the context."""
        offered = {"manual": False}

        assert accepted_kwargs(dict.update, offered) == offered or accepted_kwargs(dict.update, offered) == {}
        assert accepted_kwargs(type, offered) == offered


class TestEngineCalls:
    """The engine runs def and async def actions the same way."""

    @pytest.mark.parametrize("definition", ["def", "async def"])
    async def test_action_without_parameters(self, tmp_path: Path, definition: str) -> None:
        """An action that declares no parameters is not given any."""
        path = tmp_path / "auto.py"
        path.write_text(f"@action\n{definition} compute():\n    return 7\n", encoding="utf-8")
        context = make_context(str(path))
        await context.load()

        assert await context.run_action("compute") == 7

    @pytest.mark.parametrize("definition", ["def", "async def"])
    async def test_action_taking_manual(self, tmp_path: Path, definition: str) -> None:
        """An action that declares ``manual`` receives it."""
        path = tmp_path / "auto.py"
        path.write_text(
            f"@action\n{definition} compute(manual, extra=1):\n    return (manual, extra)\n", encoding="utf-8"
        )
        context = make_context(str(path))
        await context.load()

        assert await context.run_action("compute", manual=True, extra=5) == (True, 5)

    async def test_action_using_a_class(self, tmp_path: Path) -> None:
        """An automation can define a class with methods and use it from an action."""
        path = tmp_path / "auto.py"
        path.write_text(
            "class Counter:\n"
            "    def __init__(self):\n"
            "        self.count = 0\n"
            "    def add(self, n):\n"
            "        self.count += n\n"
            "        return self\n"
            "\n"
            "counter = Counter()\n"
            "\n"
            "@action\n"
            "async def bump():\n"
            "    return counter.add(2).add(3).count\n",
            encoding="utf-8",
        )
        context = make_context(str(path))
        await context.load()

        assert await context.run_action("bump") == 5

    async def test_top_level_await_fails_the_load(self, tmp_path: Path) -> None:
        """An automation that awaits at the top level is rejected and nothing runs."""
        path = tmp_path / "auto.py"
        path.write_text("ran = True\nawait sleep(1)\n", encoding="utf-8")
        context = make_context(str(path))

        with pytest.raises(
            AutomationSyntaxError, match=r"^auto.py:2: invalid syntax: 'await' outside function"
        ):
            await context.load()

        assert context.get_symbol("ran") is None


class TestSymbolTable:
    """Scope rules the interpreter relies on."""

    def test_global_declaration(self) -> None:
        """A name declared global is read, written and deleted in the module scope."""
        root = SymbolTable()
        root.set("x", 1)
        function = root.create_child(SCOPE_FUNCTION).create_child(SCOPE_FUNCTION)
        function.declare_global("x")
        function.declare_global("new")

        function.set("x", 2)
        function.set("new", 3)

        assert root.get("x") == 2 and function.get("x") == 2
        assert root.get("new") == 3
        assert function.exists("x") and not function.own_symbols()
        assert function.delete("x") and not root.exists("x")
        assert not function.exists("x")
        assert not function.delete("x")

    def test_nonlocal_declaration(self) -> None:
        """A name declared nonlocal is written in the nearest enclosing function that has it."""
        root = SymbolTable()
        root.set("x", "module")
        outer = root.create_child(SCOPE_FUNCTION)
        outer.set("x", "outer")
        inner = outer.create_child(SCOPE_FUNCTION)
        inner.declare_nonlocal("x")

        inner.set("x", "changed")

        assert outer.get("x") == "changed"
        assert root.get("x") == "module"
        assert inner.own_symbols() == {}

    def test_nonlocal_without_binding(self) -> None:
        """A nonlocal name that no enclosing function has is an error."""
        root = SymbolTable()
        root.set("x", 1)
        inner = root.create_child(SCOPE_FUNCTION)
        inner.declare_nonlocal("x")

        with pytest.raises(SyntaxError, match="no binding for nonlocal 'x'"):
            inner.set("x", 2)

    def test_scope_navigation(self) -> None:
        """Comprehension and class scopes are skipped where Python skips them."""
        root = SymbolTable()
        function = root.create_child(SCOPE_FUNCTION)
        function.first_arg = "self"
        comprehension = function.create_child(SCOPE_COMPREHENSION).create_child(SCOPE_COMPREHENSION)
        class_scope = function.create_child(SCOPE_CLASS)

        assert comprehension.function_scope() is function
        assert function.function_scope() is function
        assert class_scope.closure_scope() is function
        assert function.closure_scope() is function
        assert comprehension.enclosing_first_arg() == "self"
        assert root.enclosing_first_arg() is None
        assert root.function_scope() is root and root.closure_scope() is root
