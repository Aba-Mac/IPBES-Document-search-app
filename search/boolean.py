"""
search.boolean
==============

Production-grade Boolean query parser for SQLite FTS5.

This module provides:

* lexical analysis (tokenisation)
* recursive-descent parsing
* Abstract Syntax Tree (AST)
* validation with user-friendly error reporting
* compilation into parameterised SQLite WHERE clauses
* protection against SQL injection by ensuring user input is always
  passed as bound parameters rather than interpolated into SQL.

Supported operators
-------------------

    AND
    OR
    NOT
    NOR

Parentheses may be nested arbitrarily.

Operator precedence:

    1. NOT
    2. AND
    3. OR / NOR

Examples
--------

    climate AND adaptation

    (water OR soil) AND governance

    climate AND NOT biodiversity

    (A OR B) NOR (C OR D)

The parser is intentionally independent from SQLite so that it can be
unit-tested without a database connection.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable, Iterator, List, Sequence

__all__ = [
    "BooleanSyntaxError",
    "Token",
    "TokenType",
    "ASTNode",
    "TermNode",
    "NotNode",
    "AndNode",
    "OrNode",
    "NorNode",
    "BooleanParser",
    "SQLiteFTS5Compiler",
]


# ---------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------


class BooleanSyntaxError(ValueError):
    """
    Raised when a Boolean expression cannot be parsed.

    The message is written for end users rather than developers so that
    it can safely be displayed by the UI layer.
    """


# ---------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------


class TokenType(Enum):
    """Lexical token types."""

    TERM = "TERM"

    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    NOR = "NOR"

    LPAREN = "("
    RPAREN = ")"

    EOF = "EOF"


@dataclass(slots=True, frozen=True)
class Token:
    """
    A lexical token.

    Parameters
    ----------
    token_type
        Token classification.

    value
        Original token text.

    position
        Character offset within the original query.
    """

    token_type: TokenType
    value: str
    position: int


# ---------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------


_TOKEN_PATTERN = re.compile(
    r"""
    \(
    |
    \)
    |
    "(?:[^"]|"")*"
    |
    [^\s()]+
    """,
    re.VERBOSE,
)


class BooleanLexer:
    """
    Converts a Boolean query into a stream of tokens.

    Notes
    -----
    The lexer performs no semantic validation beyond recognising
    operators and parentheses.
    """

    OPERATORS = {
        "AND": TokenType.AND,
        "OR": TokenType.OR,
        "NOT": TokenType.NOT,
        "NOR": TokenType.NOR,
    }

    def tokenize(self, text: str) -> list[Token]:
        """
        Tokenise a Boolean query.

        Parameters
        ----------
        text
            Raw user query.

        Returns
        -------
        list[Token]

        Raises
        ------
        BooleanSyntaxError
            If the query is empty.
        """

        if text is None:
            raise BooleanSyntaxError("Please enter a search query.")

        stripped = text.strip()

        if not stripped:
            raise BooleanSyntaxError("Please enter a search query.")

        tokens: list[Token] = []

        for match in _TOKEN_PATTERN.finditer(text):

            value = match.group(0)

            if value == "(":
                token_type = TokenType.LPAREN

            elif value == ")":
                token_type = TokenType.RPAREN

            else:
                upper = value.upper()

                token_type = self.OPERATORS.get(
                    upper,
                    TokenType.TERM,
                )

            tokens.append(
                Token(
                    token_type=token_type,
                    value=value,
                    position=match.start(),
                )
            )

        tokens.append(
            Token(
                TokenType.EOF,
                "",
                len(text),
            )
        )

        return tokens


# ---------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------


class ASTNode(ABC):
    """Base class for all AST nodes."""


@dataclass(slots=True)
class TermNode(ASTNode):
    """
    Leaf node representing one search term.

    Terms are stored exactly as entered by the user (minus any outer
    quotes removed by the parser).
    """

    value: str


@dataclass(slots=True)
class NotNode(ASTNode):
    """Unary NOT."""

    operand: ASTNode


@dataclass(slots=True)
class BinaryNode(ASTNode):
    """Common base class for binary operators."""

    left: ASTNode
    right: ASTNode


@dataclass(slots=True)
class AndNode(BinaryNode):
    """Logical AND."""


@dataclass(slots=True)
class OrNode(BinaryNode):
    """Logical OR."""


@dataclass(slots=True)
class NorNode(BinaryNode):
    """
    Logical NOR.

    A NOR B

    ==

    NOT (A OR B)
    """


# ---------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------


class BooleanParser:
    """
    Production-grade recursive-descent Boolean parser.

    Grammar
    -------

    expression

        := or_expression

    or_expression

        := and_expression
           ( (OR | NOR) and_expression )*

    and_expression

        := unary_expression
           (AND unary_expression)*

    unary_expression

        := NOT unary_expression
         | primary

    primary

        := TERM
         | "(" expression ")"
    """

    def __init__(self) -> None:
        self._tokens: Sequence[Token] = ()
        self._index = 0

    @staticmethod
    def _merge_adjacent_terms(tokens: list[Token]) -> list[Token]:
        """
        Merge consecutive bare TERM tokens into a single phrase term.
        ...
        """
        merged: list[Token] = []

        for token in tokens:
            if (
                token.token_type is TokenType.TERM
                and merged
                and merged[-1].token_type is TokenType.TERM
            ):
                previous = merged[-1]
                merged[-1] = Token(
                    token_type=TokenType.TERM,
                    value=f"{previous.value} {token.value}",
                    position=previous.position,
                )
            else:
                merged.append(token)

        return merged

    # -------------------------------------------------------------

    @property
    def current(self) -> Token:
        return self._tokens[self._index]

    # -------------------------------------------------------------

    def parse(self, query: str) -> ASTNode:
        """
        Parse a Boolean query into an AST.

        Parameters
        ----------
        query
            User-entered Boolean expression.

        Returns
        -------
        ASTNode

        Raises
        ------
        BooleanSyntaxError
            If parsing fails.
        """

        lexer = BooleanLexer()

        tokens = lexer.tokenize(query)
        self._tokens = self._merge_adjacent_terms(tokens)
        self._index = 0

        root = self._expression()

        if self.current.token_type is not TokenType.EOF:
            raise BooleanSyntaxError(
                f"Unexpected token '{self.current.value}'."
            )

        return root

    # -------------------------------------------------------------

    def _advance(self) -> None:
        if self._index < len(self._tokens) - 1:
            self._index += 1

    # -------------------------------------------------------------

    def _accept(
        self,
        token_type: TokenType,
    ) -> bool:

        if self.current.token_type is token_type:
            self._advance()
            return True

        return False

    # -------------------------------------------------------------

    def _expect(
        self,
        token_type: TokenType,
        message: str,
    ) -> Token:

        if self.current.token_type is token_type:
            token = self.current
            self._advance()
            return token

        raise BooleanSyntaxError(message)

    # -------------------------------------------------------------

    def _expression(self) -> ASTNode:
        return self._or_expression()

    # -------------------------------------------------------------

    def _or_expression(self) -> ASTNode:

        node = self._and_expression()

        while True:

            if self._accept(TokenType.OR):
                rhs = self._and_expression()
                node = OrNode(node, rhs)
                continue

            if self._accept(TokenType.NOR):
                rhs = self._and_expression()
                node = NorNode(node, rhs)
                continue

            return node

    # -------------------------------------------------------------

    def _and_expression(self) -> ASTNode:

        node = self._unary_expression()

        while self._accept(TokenType.AND):
            rhs = self._unary_expression()
            node = AndNode(node, rhs)

        return node

    # -------------------------------------------------------------

    def _unary_expression(self) -> ASTNode:

        if self._accept(TokenType.NOT):
            return NotNode(self._unary_expression())

        return self._primary()

    # -------------------------------------------------------------

    def _primary(self) -> ASTNode:

        if self._accept(TokenType.LPAREN):

            expression = self._expression()

            self._expect(
                TokenType.RPAREN,
                "Missing closing parenthesis.",
            )

            return expression

        if self.current.token_type is TokenType.TERM:

            token = self.current
            self._advance()

            value = token.value

            if (
                len(value) >= 2
                and value.startswith('"')
                and value.endswith('"')
            ):
                value = value[1:-1].replace(
                    '""',
                    '"',
                )

            return TermNode(value)

        if self.current.token_type is TokenType.RPAREN:

            raise BooleanSyntaxError(
                "Unexpected closing parenthesis."
            )

        raise BooleanSyntaxError(
            f"Unexpected token '{self.current.value}'."
        )


# ---------------------------------------------------------------------
# SQLite compiler
# ---------------------------------------------------------------------


class SQLiteFTS5Compiler:
    """
    Compile a validated Boolean AST into a single SQLite FTS5 MATCH
    expression.

    The generated expression is intended to be supplied as a bound
    parameter to SQLite::

        SELECT ...
        FROM paragraph_fts
        WHERE paragraph_fts MATCH ?

    No user input is ever concatenated into SQL.
    """

    def compile(
        self,
        ast: ASTNode,
    ) -> tuple[str, list[str]]:
        """
        Compile an AST into a MATCH parameter.

        Parameters
        ----------
        ast
            Root AST node.

        Returns
        -------
        tuple[str, list[str]]

            sql_fragment

                Always::

                    paragraph_fts MATCH ?

            parameters

                Single-element list containing the validated MATCH
                expression.
        """

        expression = self._compile_node(ast)

        return (
            "paragraph_fts MATCH ?",
            [expression],
        )

    def _compile_node(
        self,
        node: ASTNode,
    ) -> str:
        """
        Recursively serialize an AST into FTS5 Boolean syntax.
        """

        if isinstance(node, TermNode):
            return self._compile_term(node)

        if isinstance(node, NotNode):
            return f"NOT ({self._compile_node(node.operand)})"

        if isinstance(node, AndNode):
            return (
                f"({self._compile_node(node.left)} "
                f"AND "
                f"{self._compile_node(node.right)})"
            )

        if isinstance(node, OrNode):
            return (
                f"({self._compile_node(node.left)} "
                f"OR "
                f"{self._compile_node(node.right)})"
            )

        if isinstance(node, NorNode):
            return (
                f"NOT ("
                f"{self._compile_node(node.left)} "
                f"OR "
                f"{self._compile_node(node.right)}"
                f")"
            )

        raise TypeError(
            f"Unsupported AST node: {type(node)!r}"
        )

    @staticmethod
    def _compile_term(
        node: TermNode,
    ) -> str:
        """
        Convert a validated search term into FTS5 syntax.

        Terms containing whitespace are emitted as quoted FTS5 phrases.

        Any embedded quotes are escaped according to SQLite FTS5 rules.
        """

        value = node.value.strip()

        if not value:
            raise ValueError("Empty search term.")

        escaped = value.replace('"', '""')

        if any(ch.isspace() for ch in escaped):
            return f'"{escaped}"'

        return escaped