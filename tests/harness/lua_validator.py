"""Robust recursive-descent Lua 5.1-5.4 AST and syntax validator for UE4SS Lua bridge scripts."""

from __future__ import annotations

import re
from typing import NamedTuple


class Token(NamedTuple):
    type: str
    value: str
    line: int
    col: int


class LuaSyntaxError(Exception):
    """Raised when Lua syntax validation fails."""


KEYWORDS = {
    "and",
    "break",
    "do",
    "else",
    "elseif",
    "end",
    "false",
    "for",
    "function",
    "goto",
    "if",
    "in",
    "local",
    "nil",
    "not",
    "or",
    "repeat",
    "return",
    "then",
    "true",
    "until",
    "while",
}

BINARY_PRECEDENCE = {
    "or": 1,
    "and": 2,
    "<": 3,
    ">": 3,
    "<=": 3,
    ">=": 3,
    "~=": 3,
    "==": 3,
    "|": 4,
    "~": 5,
    "&": 6,
    "<<": 7,
    ">>": 7,
    "..": 8,
    "+": 9,
    "-": 9,
    "*": 10,
    "/": 10,
    "//": 10,
    "%": 10,
    "^": 12,
}

RIGHT_ASSOCIATIVE = {"..", "^"}
UNARY_OPERATORS = {"not", "#", "-", "~"}


def tokenize_lua(source: str) -> list[Token]:
    """Converts raw Lua source code into a stream of tokens, skipping whitespace and comments."""
    token_patterns = [
        ("COMMENT_LONG", r"--\[(?P<cleq>=*)\[[\s\S]*?\](?P=cleq)\]"),
        ("COMMENT_SHORT", r"--[^\r\n]*"),
        ("STRING_LONG", r"\[(?P<sleq>=*)\[[\s\S]*?\](?P=sleq)\]"),
        ("STRING_SHORT", r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
        (
            "NUMBER",
            r"0[xX][0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?(?:[pP][+-]?\d+)?|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?",
        ),
        ("SYM2", r"==|~=|<=|>=|\.\.\.|\.\.|::|//|<<|>>"),
        ("SYM1", r"[+\-*\/%^#<>=();:{}\[\],.:&~|]"),
        ("ID", r"[a-zA-Z_][a-zA-Z0-9_]*"),
        ("WS", r"[ \t\r\n]+"),
    ]
    master = "|".join(f"(?P<{name}>{pattern})" for name, pattern in token_patterns)
    regex = re.compile(master)

    tokens: list[Token] = []
    line_num = 1
    line_start = 0

    pos = 0
    source_len = len(source)
    while pos < source_len:
        match = regex.match(source, pos)
        if not match:
            col = pos - line_start + 1
            sample = source[pos : pos + 20]
            raise LuaSyntaxError(f"Unexpected character at line {line_num}, col {col}: {sample!r}")

        kind = match.lastgroup
        val = match.group()
        col = pos - line_start + 1

        # Track line numbers
        newlines = val.count("\n")
        if newlines > 0:
            line_num += newlines
            line_start = match.end() - (len(val) - val.rfind("\n") - 1)

        pos = match.end()

        if kind in ("WS", "COMMENT_SHORT", "COMMENT_LONG"):
            continue

        if kind == "ID" and val in KEYWORDS:
            tokens.append(Token("KEYWORD", val, line_num, col))
        elif kind == "ID":
            tokens.append(Token("IDENT", val, line_num, col))
        elif kind in ("STRING_SHORT", "STRING_LONG"):
            tokens.append(Token("STRING", val, line_num, col))
        elif kind == "NUMBER":
            tokens.append(Token("NUMBER", val, line_num, col))
        else:
            tokens.append(Token("SYMBOL", val, line_num, col))

    return tokens


class LuaParser:
    """Recursive-descent syntactic parser for Lua scripts."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def accept(self, *vals: str) -> Token | None:
        tok = self.peek()
        if tok and tok.value in vals:
            self.pos += 1
            return tok
        return None

    def expect(self, *vals: str) -> Token:
        tok = self.accept(*vals)
        if tok is None:
            curr = self.peek()
            loc = f"line {curr.line}, col {curr.col} ({curr.value!r})" if curr else "end of file"
            expected = " or ".join(repr(v) for v in vals)
            raise LuaSyntaxError(f"Expected {expected} at {loc}")
        return tok

    def expect_ident(self) -> str:
        tok = self.peek()
        if tok and tok.type == "IDENT":
            self.pos += 1
            return tok.value
        loc = f"line {tok.line}, col {tok.col} ({tok.value!r})" if tok else "end of file"
        raise LuaSyntaxError(f"Expected identifier at {loc}")

    def parse(self) -> None:
        self.parse_chunk()
        if self.pos < len(self.tokens):
            extra = self.tokens[self.pos]
            raise LuaSyntaxError(
                f"Unexpected token at line {extra.line}, col {extra.col}: {extra.value!r}"
            )

    def parse_chunk(self) -> None:
        while True:
            tok = self.peek()
            if tok is None or tok.value in ("end", "else", "elseif", "until"):
                break
            self.parse_stat()
            self.accept(";")

    def parse_stat(self) -> None:
        tok = self.peek()
        if tok is None:
            return

        if self.accept(";"):
            return
        if self.accept("break"):
            return
        if self.accept("goto"):
            self.expect_ident()
            return
        if self.accept("do"):
            self.parse_chunk()
            self.expect("end")
            return
        if self.accept("while"):
            self.parse_exp()
            self.expect("do")
            self.parse_chunk()
            self.expect("end")
            return
        if self.accept("repeat"):
            self.parse_chunk()
            self.expect("until")
            self.parse_exp()
            return
        if self.accept("if"):
            self.parse_exp()
            self.expect("then")
            self.parse_chunk()
            while self.accept("elseif"):
                self.parse_exp()
                self.expect("then")
                self.parse_chunk()
            if self.accept("else"):
                self.parse_chunk()
            self.expect("end")
            return
        if self.accept("for"):
            self.expect_ident()
            if self.accept("="):
                self.parse_exp()
                self.expect(",")
                self.parse_exp()
                if self.accept(","):
                    self.parse_exp()
                self.expect("do")
                self.parse_chunk()
                self.expect("end")
            else:
                while self.accept(","):
                    self.expect_ident()
                self.expect("in")
                self.parse_explist()
                self.expect("do")
                self.parse_chunk()
                self.expect("end")
            return
        if self.accept("function"):
            self.parse_funcname()
            self.parse_funcbody()
            return
        if self.accept("local"):
            if self.accept("function"):
                self.expect_ident()
                self.parse_funcbody()
            else:
                self.expect_ident()
                while self.accept(","):
                    self.expect_ident()
                if self.accept("="):
                    self.parse_explist()
            return
        if self.accept("return"):
            nxt = self.peek()
            if nxt and nxt.value not in ("end", "else", "elseif", "until", ";"):
                self.parse_explist()
            self.accept(";")
            return

        # Label ::Name::
        if self.accept("::"):
            self.expect_ident()
            self.expect("::")
            return

        # Must be function call or assignment
        self.parse_call_or_assignment()

    def parse_funcname(self) -> None:
        self.expect_ident()
        while self.accept("."):
            self.expect_ident()
        if self.accept(":"):
            self.expect_ident()

    def parse_funcbody(self) -> None:
        self.expect("(")
        if self.accept("..."):
            pass
        elif (pk := self.peek()) is not None and pk.type == "IDENT":
            self.expect_ident()
            while self.accept(","):
                if self.accept("..."):
                    break
                self.expect_ident()
        self.expect(")")
        self.parse_chunk()
        self.expect("end")

    def parse_explist(self) -> None:
        self.parse_exp()
        while self.accept(","):
            self.parse_exp()

    def parse_exp(self, min_prec: int = 0) -> None:
        # Unary or primary
        tok = self.peek()
        if tok and tok.value in UNARY_OPERATORS:
            self.pos += 1
            self.parse_exp(min_prec=11)
        else:
            self.parse_primary_exp()

        # Binary operator precedence climbing
        while True:
            op = self.peek()
            if op is None or op.value not in BINARY_PRECEDENCE:
                break
            prec = BINARY_PRECEDENCE[op.value]
            if prec < min_prec:
                break
            self.pos += 1
            next_min_prec = prec if op.value in RIGHT_ASSOCIATIVE else prec + 1
            self.parse_exp(min_prec=next_min_prec)

    def parse_primary_exp(self) -> None:
        tok = self.peek()
        if tok is None:
            raise LuaSyntaxError("Unexpected end of file expecting expression")

        if tok.type in ("NUMBER", "STRING") or tok.value in ("nil", "false", "true", "..."):
            self.pos += 1
            return
        if tok.value == "function":
            self.pos += 1
            self.parse_funcbody()
            return
        if tok.value == "{":
            self.parse_tableconstructor()
            return

        # prefixexp
        self.parse_prefixexp()

    def parse_tableconstructor(self) -> None:
        self.expect("{")
        while True:
            if self.accept("}"):
                return
            if self.accept("["):
                self.parse_exp()
                self.expect("]")
                self.expect("=")
                self.parse_exp()
            elif (
                (pk := self.peek()) is not None
                and pk.type == "IDENT"
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].value == "="
            ):
                self.expect_ident()
                self.expect("=")
                self.parse_exp()
            else:
                self.parse_exp()

            if not self.accept(",", ";"):
                self.expect("}")
                return

    def parse_prefixexp(self) -> bool:
        """Parses prefixexp, returning True if the trailing expression was a function call."""
        is_call = False
        tok = self.peek()
        if tok and tok.value == "(":
            self.pos += 1
            self.parse_exp()
            self.expect(")")
            is_call = False
        elif tok and tok.type == "IDENT":
            self.pos += 1
            is_call = False
        else:
            loc = f"line {tok.line}, col {tok.col} ({tok.value!r})" if tok else "EOF"
            raise LuaSyntaxError(f"Unexpected token in prefixexp at {loc}")

        while True:
            if self.accept("."):
                self.expect_ident()
                is_call = False
            elif self.accept("["):
                self.parse_exp()
                self.expect("]")
                is_call = False
            elif self.accept(":"):
                self.expect_ident()
                self.parse_args()
                is_call = True
            elif (pk := self.peek()) is not None and (
                pk.value in ("(", "{") or pk.type == "STRING"
            ):
                self.parse_args()
                is_call = True
            else:
                break

        return is_call

    def parse_args(self) -> None:
        tok = self.peek()
        if tok and tok.value == "(":
            self.pos += 1
            if not self.accept(")"):
                self.parse_explist()
                self.expect(")")
        elif tok and tok.value == "{":
            self.parse_tableconstructor()
        elif tok and tok.type == "STRING":
            self.pos += 1
        else:
            loc = f"line {tok.line}, col {tok.col} ({tok.value!r})" if tok else "EOF"
            raise LuaSyntaxError(f"Expected function call arguments at {loc}")

    def parse_call_or_assignment(self) -> None:
        is_call = self.parse_prefixexp()
        if self.accept("="):
            self.parse_explist()
        elif self.accept(","):
            while True:
                self.parse_prefixexp()
                if not self.accept(","):
                    break
            self.expect("=")
            self.parse_explist()
        elif not is_call:
            tok = self.peek()
            loc = f"line {tok.line}, col {tok.col} ({tok.value!r})" if tok else "EOF"
            raise LuaSyntaxError(f"Statement must be function call or assignment at {loc}")


def validate_lua_syntax(source: str) -> None:
    """Validates the syntax and AST structure of Lua code. Raises LuaSyntaxError on error."""
    tokens = tokenize_lua(source)
    parser = LuaParser(tokens)
    parser.parse()


__all__ = ["LuaSyntaxError", "Token", "tokenize_lua", "validate_lua_syntax"]
