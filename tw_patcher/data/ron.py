"""A small, tolerant reader for RON (Rusty Object Notation), enough for RPFM's schema files.

Value mapping:

- ``(a: 1, b: 2)`` (named struct) -> ``dict``; ``(1, 2)`` (tuple) -> ``list``
- ``[1, 2]`` -> ``list``; ``{k: v}`` -> ``dict``
- strings and chars -> ``str``; integers -> ``int``; floats -> ``float``; ``true``/``false`` -> ``bool``
- ``None`` -> ``None``; ``Some(x)`` -> ``x``
- a bare identifier (unit enum variant such as ``StringU8``) -> ``"StringU8"``
- a variant with a payload such as ``SequenceU32(x)`` -> ``{"SequenceU32": x}`` (a single positional
  payload is unwrapped; several stay a list; named fields become a dict)

Trailing commas, ``//`` and ``/* */`` comments and a leading ``#![enable(...)]`` are accepted.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["RonError", "loads"]


class RonError(ValueError):
    """Malformed RON input; ``line`` and ``column`` are 1-based."""

    def __init__(self, message: str, text: str, pos: int):
        self.line = text.count("\n", 0, pos) + 1
        self.column = pos - text.rfind("\n", 0, pos)
        self.pos = pos
        super().__init__(f"{message} at line {self.line}, column {self.column}")


_TOKEN_RE = re.compile(
    r"""
    (?:\s+|//[^\n]*|/\*[\s\S]*?\*/|\#!\[[^\]]*\])*
    (?:
        (?P<str>"(?:[^"\\]|\\[\s\S])*")
      | (?P<raw>r(?P<hashes>\#*)"[\s\S]*?"(?P=hashes))
      | (?P<num>[-+]?(?:0x[0-9A-Fa-f_]+|0o[0-7_]+|0b[01_]+
                     |(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][-+]?\d[\d_]*)?
                     |inf\b|NaN\b))
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<punct>[()\[\]{},:])
      | (?P<char>'(?:[^'\\]|\\[\s\S])+')
      | (?P<end>\Z)
      | (?P<bad>[\s\S])
    )
    """,
    re.VERBOSE,
)

_STR = _TOKEN_RE.groupindex["str"]
_RAW = _TOKEN_RE.groupindex["raw"]
_NUM = _TOKEN_RE.groupindex["num"]
_IDENT = _TOKEN_RE.groupindex["ident"]
_PUNCT = _TOKEN_RE.groupindex["punct"]
_CHAR = _TOKEN_RE.groupindex["char"]
_END = _TOKEN_RE.groupindex["end"]

_ESCAPE_RE = re.compile(r"\\(?:u\{([0-9A-Fa-f]{1,6})\}|u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|\n\s*|([\s\S]))")
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "b": "\b", "f": "\f"}

_CLOSERS = {"(": ")", "[": "]", "{": "}"}

# Frame states: what the innermost container expects next.
_ITEM = 0  # a value (or field name / map key), or the closer
_COLON = 1  # ':' after a map key
_VALUE = 2  # a value after ':'
_SEP = 3  # ',' or the closer

_MISSING = object()


def _unescape(match: re.Match[str]) -> str:
    braced, four, hex2, other = match.groups()
    code = braced or four or hex2
    if code is not None:
        return chr(int(code, 16))
    if other is None:  # backslash-newline continuation
        return ""
    return _SIMPLE_ESCAPES.get(other, other)


def _decode_quoted(token: str) -> str:
    body = token[1:-1]
    if "\\" not in body:
        return body
    return _ESCAPE_RE.sub(_unescape, body)


def _parse_number(token: str) -> int | float:
    lowered = token.lstrip("+-").lower()
    if lowered.startswith(("0x", "0o", "0b")):
        return int(token, 0)
    if lowered in ("inf", "nan") or "." in token or "e" in lowered:
        return float(token)
    return int(token)


class _Frame:
    __slots__ = ("opener", "closer", "items", "named", "key", "state", "variant", "pos")

    def __init__(self, opener: str, variant: str | None, pos: int):
        self.opener = opener
        self.closer = _CLOSERS[opener]
        self.items: Any = {} if opener == "{" else []
        self.named = False
        self.key: Any = None
        self.state = _ITEM
        self.variant = variant
        self.pos = pos


def _finish(frame: _Frame) -> Any:
    value = frame.items
    if frame.variant is None:
        return value
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if frame.variant == "Some":
        return value
    return {frame.variant: value}


def loads(text: str) -> Any:
    """Parse a RON document into plain Python values; raises :class:`RonError` on malformed input."""
    tokens = _TOKEN_RE.finditer(text)
    stack: list[_Frame] = []
    pushed: re.Match[str] | None = None
    result: Any = _MISSING

    while True:
        if pushed is not None:
            m, pushed = pushed, None
        else:
            m = next(tokens, None)
            if m is None:  # finditer stops after the empty end-of-input match
                raise RonError("unexpected end of input", text, len(text))
        kind = m.lastindex
        assert kind is not None
        tok = m.group(kind)
        pos = m.start(kind)

        if result is not _MISSING:
            if kind == _END:
                return result
            raise RonError(f"unexpected {tok!r} after the end of the document", text, pos)

        frame = stack[-1] if stack else None

        # Structural tokens that depend on the frame's state.
        if frame is not None:
            state = frame.state
            if kind == _PUNCT and tok == frame.closer and state in (_ITEM, _SEP):
                stack.pop()
                value = _finish(frame)
                # fall through to emit the closed container below
            elif state == _SEP:
                if kind == _PUNCT and tok == ",":
                    frame.state = _ITEM
                    continue
                raise RonError(f"expected ',' or {frame.closer!r}, found {_describe(kind, tok)}", text, pos)
            elif state == _COLON:
                if kind == _PUNCT and tok == ":":
                    frame.state = _VALUE
                    continue
                raise RonError(f"expected ':', found {_describe(kind, tok)}", text, pos)
            else:
                value = _MISSING
        else:
            value = _MISSING

        if value is _MISSING:
            # Start of a value (or a struct field name).
            if kind == _STR:
                value = _decode_quoted(tok)
            elif kind == _NUM:
                try:
                    value = _parse_number(tok)
                except ValueError:
                    raise RonError(f"invalid number {tok!r}", text, pos) from None
            elif kind == _IDENT:
                if tok == "true":
                    value = True
                elif tok == "false":
                    value = False
                elif tok == "None":
                    value = None
                else:
                    nxt = next(tokens, None)
                    if nxt is None:
                        raise RonError("unexpected end of input", text, len(text))
                    nkind = nxt.lastindex
                    ntok = nxt.group(nkind) if nkind is not None else ""
                    if nkind == _PUNCT and ntok == "(":
                        stack.append(_Frame("(", tok, pos))
                        continue
                    if (
                        nkind == _PUNCT
                        and ntok == ":"
                        and frame is not None
                        and frame.opener == "("
                        and frame.state == _ITEM
                    ):
                        if frame.items and not frame.named:
                            raise RonError(f"named field {tok!r} in a tuple", text, pos)
                        if not frame.named:
                            frame.named = True
                            frame.items = {}
                        frame.key = tok
                        frame.state = _VALUE
                        continue
                    pushed = nxt
                    value = tok
            elif kind == _PUNCT and tok in _CLOSERS:
                stack.append(_Frame(tok, None, pos))
                continue
            elif kind == _CHAR:
                value = _decode_quoted(tok)
            elif kind == _RAW:
                value = tok[tok.index('"') + 1 : tok.rindex('"')]
            elif kind == _END:
                where = f"unclosed {stack[-1].opener!r}" if stack else "no value"
                raise RonError(f"unexpected end of input ({where})", text, pos)
            elif tok == '"':
                raise RonError("unterminated string", text, pos)
            else:
                raise RonError(f"unexpected {_describe(kind, tok)}", text, pos)

        # Emit the completed value into the enclosing container.
        if not stack:
            result = value
            continue
        frame = stack[-1]
        if frame.state == _VALUE:
            frame.items[frame.key] = value
            frame.state = _SEP
        elif frame.opener == "{":
            try:
                hash(value)
            except TypeError:
                raise RonError("map key must be a string, number or identifier", text, pos) from None
            frame.key = value
            frame.state = _COLON
        elif frame.named:
            raise RonError("expected a field name", text, pos)
        else:
            frame.items.append(value)
            frame.state = _SEP


def _describe(kind: int, tok: str) -> str:
    if kind == _END:
        return "end of input"
    if len(tok) > 40:
        tok = tok[:37] + "..."
    return repr(tok)
