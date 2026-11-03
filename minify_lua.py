#!/usr/bin/env python3
"""Minify Lua without changing line numbers.

Comments are removed. Whitespace that only affects readability is removed.
Local variables, parameters, and loop variables are renamed to shorter names.
Newlines are kept, including blank lines and newlines inside long strings and
long comments, so every remaining token stays on its original line.

Globals, table fields, and the implicit `self` on method definitions are left
unchanged. Requires only the Python 3 standard library so GitHub Actions can
run it.
"""

from __future__ import annotations

import argparse
import pathlib
import string
import sys

MULTI_SYMBOLS = (
    "...",
    "..",
    "==",
    "~=",
    "<=",
    ">=",
    "//",
    "<<",
    ">>",
    "::",
)
SINGLE_SYMBOLS = set("+-*/%^#<>=(){}[];:,.~")


def _is_name_char(ch: str, first: bool) -> bool:
    if first:
        return ch == "_" or ch.isalpha()
    return ch == "_" or ch.isalnum()


def _read_short_string(src: str, i: int) -> tuple[str, int]:
    quote = src[i]
    n = len(src)
    j = i + 1
    while j < n:
        ch = src[j]
        if ch == "\\":
            if j + 1 >= n:
                break
            j += 2
            continue
        if ch == "\n":
            raise ValueError(f"unterminated string at index {i}")
        if ch == quote:
            return src[i : j + 1], j + 1
        j += 1
    raise ValueError(f"unterminated string at index {i}")


def _opening_long_bracket(src: str, i: int) -> int | None:
    """Return the level of a long bracket starting at i, or None."""
    if i >= len(src) or src[i] != "[":
        return None
    j = i + 1
    while j < len(src) and src[j] == "=":
        j += 1
    if j < len(src) and src[j] == "[":
        return j - i - 1
    return None


def _skip_long_bracket(src: str, i: int, level: int) -> int:
    close = "]" + ("=" * level) + "]"
    end = src.find(close, i)
    if end < 0:
        raise ValueError(f"unterminated long bracket at index {i}")
    return end + len(close)


def _read_number(src: str, i: int) -> tuple[str, int]:
    n = len(src)
    j = i
    if src[j] == "0" and j + 1 < n and src[j + 1] in "xX":
        j += 2
        while j < n and (src[j].isdigit() or src[j] in "abcdefABCDEF"):
            j += 1
        return src[i:j], j
    if src[j] == ".":
        j += 1
        while j < n and src[j].isdigit():
            j += 1
    else:
        while j < n and src[j].isdigit():
            j += 1
        if j < n and src[j] == ".":
            j += 1
            while j < n and src[j].isdigit():
                j += 1
    if j < n and src[j] in "eE":
        k = j + 1
        if k < n and src[k] in "+-":
            k += 1
        if k < n and src[k].isdigit():
            j = k + 1
            while j < n and src[j].isdigit():
                j += 1
    return src[i:j], j


def _needs_space(prev: str, nxt: str) -> bool:
    if not prev or not nxt:
        return False
    a = prev[-1]
    b = nxt[0]
    if (a.isalnum() or a == "_") and (b.isalnum() or b == "_"):
        return True
    # `a--b` would start a comment; `1..2` would become concatenation.
    if a == "-" and b == "-":
        return True
    if a == "." and (b == "." or b.isdigit()):
        return True
    if a == "/" and b == "/":
        return True
    return False


def _strip_lua(src: str) -> str:
    n = len(src)
    i = 0
    out: list[str] = []
    line: list[str] = []

    def emit(token: str) -> None:
        if line and _needs_space(line[-1], token):
            line.append(" ")
        line.append(token)

    def emit_newline() -> None:
        out.append("".join(line))
        line.clear()

    while i < n:
        ch = src[i]
        if ch in " \t\v\f":
            i += 1
            continue
        if ch == "\n":
            emit_newline()
            i += 1
            continue
        if ch == "\r":
            emit_newline()
            i += 1
            if i < n and src[i] == "\n":
                i += 1
            continue
        if ch == "-" and i + 1 < n and src[i + 1] == "-":
            level = _opening_long_bracket(src, i + 2)
            if level is None:
                i += 2
                while i < n and src[i] not in "\r\n":
                    i += 1
                continue
            end = _skip_long_bracket(src, i + 2 + level + 2, level)
            # Keep newlines that belong to this comment so later lines stay put.
            comment = src[i:end]
            for part in comment.splitlines(keepends=True):
                if part.endswith("\r\n"):
                    emit_newline()
                elif part.endswith("\n") or part.endswith("\r"):
                    emit_newline()
            i = end
            continue
        if ch in "\"'":
            token, i = _read_short_string(src, i)
            emit(token)
            continue
        level = _opening_long_bracket(src, i)
        if level is not None:
            end = _skip_long_bracket(src, i + level + 2, level)
            body = src[i:end]
            pieces = body.splitlines(keepends=True)
            for part in pieces:
                if part.endswith("\r\n"):
                    emit(part[:-2])
                    emit_newline()
                elif part.endswith("\n") or part.endswith("\r"):
                    emit(part[:-1])
                    emit_newline()
                else:
                    emit(part)
            i = end
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            token, i = _read_number(src, i)
            emit(token)
            continue
        if _is_name_char(ch, True):
            j = i + 1
            while j < n and _is_name_char(src[j], False):
                j += 1
            emit(src[i:j])
            i = j
            continue
        matched = False
        for symbol in MULTI_SYMBOLS:
            if src.startswith(symbol, i):
                emit(symbol)
                i += len(symbol)
                matched = True
                break
        if matched:
            continue
        if ch in SINGLE_SYMBOLS:
            emit(ch)
            i += 1
            continue
        raise ValueError(f"unexpected character {ch!r} at index {i}")

    out.append("".join(line))
    if src.endswith("\n") or src.endswith("\r"):
        text = "\n".join(out)
        if not text.endswith("\n"):
            text += "\n"
        return text
    return "\n".join(out)


_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "until", "while",
}
_BINOPS = {
    "+", "-", "*", "/", "%", "^", "..", "<", "<=", ">", ">=", "==", "~=", "and", "or", "//",
}
_EXPR_KEYWORDS = {"function", "nil", "true", "false", "not"}


def _short_names() -> list[str]:
    letters = string.ascii_letters
    names = list(letters)
    names.extend(a + b for a in letters for b in letters)
    return names


_SHORT_NAMES = _short_names()


def _tokenize(src: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\v\f":
            i += 1
            continue
        if ch == "\n":
            tokens.append(("nl", "\n"))
            i += 1
            continue
        if ch == "\r":
            i += 1
            if i < n and src[i] == "\n":
                i += 1
            tokens.append(("nl", "\n"))
            continue
        if ch in "\"'":
            token, i = _read_short_string(src, i)
            tokens.append(("str", token))
            continue
        level = _opening_long_bracket(src, i)
        if level is not None:
            end = _skip_long_bracket(src, i + level + 2, level)
            tokens.append(("str", src[i:end]))
            i = end
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            token, i = _read_number(src, i)
            tokens.append(("num", token))
            continue
        if _is_name_char(ch, True):
            j = i + 1
            while j < n and _is_name_char(src[j], False):
                j += 1
            tokens.append(("name", src[i:j]))
            i = j
            continue
        for symbol in MULTI_SYMBOLS:
            if src.startswith(symbol, i):
                tokens.append(("sym", symbol))
                i += len(symbol)
                break
        else:
            if ch not in SINGLE_SYMBOLS:
                raise ValueError(f"unexpected character {ch!r} at index {i}")
            tokens.append(("sym", ch))
            i += 1
    return tokens


class _Scope:
    def __init__(self, parent: _Scope | None = None):
        self.parent = parent
        self.bindings: list[dict] = []
        self.by_name: dict[str, dict] = {}
        self.children: list[_Scope] = []
        self.end = 0
        if parent:
            parent.children.append(self)

    def lookup(self, name: str) -> dict | None:
        scope: _Scope | None = self
        while scope:
            found = scope.by_name.get(name)
            if found:
                return found
            scope = scope.parent
        return None

    def bind(self, name: str, index: int | None, *, frozen: bool) -> None:
        binding = {
            "name": name,
            "frozen": frozen or name == "_",
            "idxs": [] if index is None else [index],
            "new": name,
        }
        self.bindings.append(binding)
        self.by_name[name] = binding


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.toks = tokens
        self.i = 0
        self.globals: list[tuple[int, str]] = []

    def _skip_nl(self) -> None:
        while self.i < len(self.toks) and self.toks[self.i][0] == "nl":
            self.i += 1

    def peek(self) -> tuple[str, str] | None:
        j = self.i
        while j < len(self.toks) and self.toks[j][0] == "nl":
            j += 1
        if j >= len(self.toks):
            return None
        return self.toks[j]

    def ahead(self, k: int) -> tuple[str, str] | None:
        j = self.i
        seen = 0
        while j < len(self.toks):
            if self.toks[j][0] == "nl":
                j += 1
                continue
            seen += 1
            if seen == k:
                return self.toks[j]
            j += 1
        return None

    def at(self, *vals: str) -> bool:
        tok = self.peek()
        return tok is not None and tok[1] in vals

    def eat(self, val: str | None = None) -> tuple[str, str]:
        self._skip_nl()
        if self.i >= len(self.toks):
            raise ValueError(f"expected {val!r} at end of file")
        tok = self.toks[self.i]
        if val is not None and tok[1] != val:
            raise ValueError(f"expected {val!r} got {tok[1]!r}")
        self.i += 1
        return tok

    def eat_name(self) -> str:
        tok = self.eat()
        if tok[0] != "name":
            raise ValueError(f"expected name got {tok[1]!r}")
        return tok[1]

    def ref(self, scope: _Scope, name: str) -> None:
        index = self.i - 1
        found = scope.lookup(name)
        if found:
            found["idxs"].append(index)
            return
        self.globals.append((index, name))

    def chunk(self, scope: _Scope) -> None:
        while self.peek() and not self.at("end", "else", "elseif", "until"):
            self.stat(scope)
            if self.at(";"):
                self.eat(";")
        scope.end = self.i

    def stat(self, scope: _Scope) -> None:
        if self.at(";"):
            self.eat(";")
        elif self.at("local"):
            self.local_stat(scope)
        elif self.at("function"):
            self.eat("function")
            self.funcname(scope)
        elif self.at("do"):
            self.eat("do")
            inner = _Scope(scope)
            self.chunk(inner)
            self.eat("end")
        elif self.at("if"):
            self.if_stat(scope)
        elif self.at("for"):
            self.for_stat(scope)
        elif self.at("while"):
            self.eat("while")
            self.exp(scope)
            self.eat("do")
            inner = _Scope(scope)
            self.chunk(inner)
            self.eat("end")
        elif self.at("repeat"):
            self.eat("repeat")
            inner = _Scope(scope)
            self.chunk(inner)
            self.eat("until")
            self.exp(inner)
            inner.end = self.i
        elif self.at("return"):
            self.eat("return")
            if self.exp_start():
                self.explist(scope)
        elif self.at("break"):
            self.eat("break")
        elif self.at("goto"):
            self.eat("goto")
            self.eat_name()
        elif self.at("::"):
            self.eat("::")
            self.eat_name()
            self.eat("::")
        else:
            self.assign_or_call(scope)

    def local_stat(self, scope: _Scope) -> None:
        self.eat("local")
        if self.at("function"):
            self.eat("function")
            name = self.eat_name()
            scope.bind(name, self.i - 1, frozen=False)
            self.funcbody(scope, colon=False)
            return
        names = [(self.eat_name(), self.i - 1)]
        while self.at(","):
            self.eat(",")
            names.append((self.eat_name(), self.i - 1))
        if self.at("="):
            self.eat("=")
            self.explist(scope)
        for name, index in names:
            scope.bind(name, index, frozen=False)

    def if_stat(self, scope: _Scope) -> None:
        self.eat("if")
        self.exp(scope)
        self.eat("then")
        self.chunk(_Scope(scope))
        while self.at("elseif"):
            self.eat("elseif")
            self.exp(scope)
            self.eat("then")
            self.chunk(_Scope(scope))
        if self.at("else"):
            self.eat("else")
            self.chunk(_Scope(scope))
        self.eat("end")

    def for_stat(self, scope: _Scope) -> None:
        self.eat("for")
        names = [(self.eat_name(), self.i - 1)]
        if self.at("="):
            self.eat("=")
            self.exp(scope)
            self.eat(",")
            self.exp(scope)
            if self.at(","):
                self.eat(",")
                self.exp(scope)
            self.eat("do")
            inner = _Scope(scope)
            inner.bind(names[0][0], names[0][1], frozen=False)
            self.chunk(inner)
            self.eat("end")
            return
        while self.at(","):
            self.eat(",")
            names.append((self.eat_name(), self.i - 1))
        self.eat("in")
        self.explist(scope)
        self.eat("do")
        inner = _Scope(scope)
        for name, index in names:
            inner.bind(name, index, frozen=False)
        self.chunk(inner)
        self.eat("end")

    def funcname(self, scope: _Scope) -> None:
        name = self.eat_name()
        self.ref(scope, name)
        colon = False
        while self.at("."):
            self.eat(".")
            self.eat_name()
        if self.at(":"):
            self.eat(":")
            self.eat_name()
            colon = True
        self.funcbody(scope, colon)

    def funcbody(self, scope: _Scope, colon: bool) -> None:
        self.eat("(")
        inner = _Scope(scope)
        if colon:
            inner.bind("self", None, frozen=True)
        if not self.at(")"):
            while True:
                if self.at("..."):
                    self.eat("...")
                    break
                name = self.eat_name()
                inner.bind(name, self.i - 1, frozen=False)
                if not self.at(","):
                    break
                self.eat(",")
        self.eat(")")
        self.chunk(inner)
        self.eat("end")

    def assign_or_call(self, scope: _Scope) -> None:
        self.prefixexp(scope)
        if self.at(",") or self.at("="):
            while self.at(","):
                self.eat(",")
                self.prefixexp(scope)
            self.eat("=")
            self.explist(scope)

    def explist(self, scope: _Scope) -> None:
        self.exp(scope)
        while self.at(","):
            self.eat(",")
            self.exp(scope)

    def exp_start(self) -> bool:
        tok = self.peek()
        if tok is None:
            return False
        kind, val = tok
        if kind in {"num", "str"}:
            return True
        if kind == "name":
            return val not in _KEYWORDS or val in _EXPR_KEYWORDS
        return val in {"(", "{", "...", "-", "#"}

    def exp(self, scope: _Scope) -> None:
        self.operand(scope)
        while self.peek() and self.peek()[1] in _BINOPS:
            self.eat()
            self.operand(scope)

    def operand(self, scope: _Scope) -> None:
        while self.at("not", "-", "#"):
            self.eat()
        self.simple(scope)

    def simple(self, scope: _Scope) -> None:
        if self.at("function"):
            self.eat("function")
            self.funcbody(scope, colon=False)
        elif self.at("{"):
            self.table(scope)
        elif self.at("..."):
            self.eat("...")
        elif self.at("nil", "true", "false"):
            self.eat()
        elif self.peek() and self.peek()[0] in {"num", "str"}:
            self.eat()
        elif self.at("(") or (self.peek() and self.peek()[0] == "name" and self.peek()[1] not in _KEYWORDS):
            self.prefixexp(scope)
        else:
            tok = self.peek()
            raise ValueError(f"bad expression {tok[1] if tok else 'eof'!r}")

    def prefixexp(self, scope: _Scope) -> None:
        if self.at("("):
            self.eat("(")
            self.exp(scope)
            self.eat(")")
        else:
            name = self.eat_name()
            self.ref(scope, name)
        while True:
            if self.at("."):
                self.eat(".")
                self.eat_name()
            elif self.at("["):
                self.eat("[")
                self.exp(scope)
                self.eat("]")
            elif self.at(":"):
                self.eat(":")
                self.eat_name()
                self.args(scope)
            elif self.at("(") or self.at("{") or (self.peek() and self.peek()[0] == "str"):
                self.args(scope)
            else:
                break

    def args(self, scope: _Scope) -> None:
        if self.at("("):
            self.eat("(")
            if not self.at(")"):
                self.explist(scope)
            self.eat(")")
        elif self.at("{"):
            self.table(scope)
        else:
            self.eat()

    def table(self, scope: _Scope) -> None:
        self.eat("{")
        while not self.at("}"):
            nxt = self.ahead(2)
            if self.at("["):
                self.eat("[")
                self.exp(scope)
                self.eat("]")
                self.eat("=")
                self.exp(scope)
            elif self.peek() and self.peek()[0] == "name" and nxt and nxt[1] == "=":
                self.eat_name()
                self.eat("=")
                self.exp(scope)
            else:
                self.exp(scope)
            if self.at(",") or self.at(";"):
                self.eat()
            elif not self.at("}"):
                tok = self.peek()
                raise ValueError(f"bad table {tok[1] if tok else 'eof'!r}")
        self.eat("}")


def _assign_short_names(scope: _Scope, reserved: set[str], globals_: list[tuple[int, str]]) -> None:
    used = set(reserved)
    for binding in scope.bindings:
        if binding["frozen"] or len(binding["name"]) <= 1:
            binding["new"] = binding["name"]
            used.add(binding["name"])
    for binding in scope.bindings:
        if binding["new"] != binding["name"] or binding["frozen"] or len(binding["name"]) <= 1:
            continue
        decl = binding["idxs"][0]
        forbidden = {name for index, name in globals_ if decl < index <= scope.end}
        chosen = None
        for candidate in _SHORT_NAMES:
            if len(candidate) >= len(binding["name"]):
                break
            if candidate in used or candidate in _KEYWORDS or candidate in forbidden:
                continue
            chosen = candidate
            break
        if chosen is not None:
            binding["new"] = chosen
            used.add(chosen)
        else:
            used.add(binding["name"])
    for child in scope.children:
        _assign_short_names(child, used, globals_)


def _rename_locals(src: str) -> str:
    tokens = _tokenize(src)
    parser = _Parser(tokens)
    root = _Scope()
    parser.chunk(root)
    if parser.peek() is not None:
        tok = parser.peek()
        raise ValueError(f"trailing token {tok[1]!r}")
    _assign_short_names(root, set(), parser.globals)
    repl: dict[int, str] = {}

    def collect(scope: _Scope) -> None:
        for binding in scope.bindings:
            if binding["new"] == binding["name"]:
                continue
            for index in binding["idxs"]:
                repl[index] = binding["new"]
        for child in scope.children:
            collect(child)

    collect(root)
    out: list[str] = []
    line: list[str] = []
    for index, (kind, value) in enumerate(tokens):
        if kind == "nl":
            out.append("".join(line))
            line.clear()
            continue
        value = repl.get(index, value)
        if line and _needs_space(line[-1], value):
            line.append(" ")
        line.append(value)
    out.append("".join(line))
    if src.endswith("\n") or src.endswith("\r"):
        text = "\n".join(out)
        if not text.endswith("\n"):
            text += "\n"
        return text
    return "\n".join(out)


def minify_lua(src: str) -> str:
    return _rename_locals(_strip_lua(src))


def _line_count(text: str) -> int:
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def minify_file(path: pathlib.Path) -> bool:
    original = path.read_text(encoding="utf-8")
    minified = minify_lua(original)
    if _line_count(original) != _line_count(minified):
        raise RuntimeError(f"line count changed for {path}")
    if minified != original:
        path.write_text(minified, encoding="utf-8", newline="\n")
        return True
    return False


def iter_lua_files(root: pathlib.Path, skip: set[str]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in root.rglob("*.lua"):
        if any(part in skip for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minify Lua files in place, preserving line numbers.")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories. Defaults to Lua files under the current directory.",
    )
    parser.add_argument(
        "--exclude",
        default=".git,Libs,Embeds",
        help="Comma-separated directory names to skip while searching.",
    )
    args = parser.parse_args(argv)
    skip = {part.strip() for part in args.exclude.split(",") if part.strip()}
    if args.paths:
        targets: list[pathlib.Path] = []
        for raw in args.paths:
            path = pathlib.Path(raw)
            if path.is_dir():
                targets.extend(iter_lua_files(path, skip))
            else:
                targets.append(path)
    else:
        targets = iter_lua_files(pathlib.Path("."), skip)

    changed = 0
    for path in targets:
        if minify_file(path):
            changed += 1
            print(path)
    print(f"minified {changed} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
