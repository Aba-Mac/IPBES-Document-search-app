"""
search.boolean
==============

Boolean query parser for SQLite FTS5.

Query syntax
------------

Operators are recognised ONLY when written in capitals:

    AND    OR    NOT

Grouping uses SQUARE brackets:

    [ ... ]

Everything else is a search term. Because of this, glossary terms may
freely contain the words "and"/"or"/"not" in lowercase and may contain
round parentheses, commas, hyphens etc.:

    peace and security AND [climate change OR water]
    Convention on Biological Diversity (CBD) NOT tourism

Consecutive bare words are merged into one multiword term, so no quotes
are needed for multiword terms. Quotes remain available as an escape
hatch for terms that contain capitalised operator words or square
brackets:

    "peace AND security" AND [water OR soil]

Operator precedence:

    1. NOT
    2. AND
    3. OR

The parser is independent from SQLite so that it can be unit-tested
without a database connection.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import Enum
import re
from typing import Sequence, Iterator

__all__ = [
    "BooleanSyntaxError",
    "Token",
    "TokenType",
    "ASTNode",
    "TermNode",
    "NotNode",
    "AndNode",
    "OrNode",
    "BooleanParser",
    "iter_term_nodes",
    "SQLiteFTS5Compiler",
]


# ---------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------


class BooleanSyntaxError(ValueError):
    """
    Raised when a Boolean expression cannot be parsed.

    The message is written for end users so it can be shown by the UI.
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

    LBRACKET = "["
    RBRACKET = "]"

    EOF = "EOF"


@dataclass(slots=True, frozen=True)
class Token:
    """
    A lexical token.

    ``value`` is the token text; for quoted terms the surrounding quotes
    are already removed and doubled quotes unescaped.
    """

    token_type: TokenType
    value: str
    position: int
    quoted: bool = False


# ---------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------

# quoted phrase | [ | ] | any run of characters that are neither
# whitespace nor square brackets (so "(", ")", ",", "-" stay in terms)
_TOKEN_PATTERN = re.compile(r'"(?:[^"]|"")*"|\[|\]|[^\s\[\]]+')


class BooleanLexer:
    """Converts a query into a stream of tokens."""

    # Case-sensitive on purpose: only capitalised words are operators.
    OPERATORS = {
        "AND": TokenType.AND,
        "OR": TokenType.OR,
        "NOT": TokenType.NOT,
    }

    def tokenize(self, text: str) -> list[Token]:
        if text is None or not text.strip():
            raise BooleanSyntaxError("Please enter a search query.")

        tokens: list[Token] = []

        for match in _TOKEN_PATTERN.finditer(text):
            value = match.group(0)
            position = match.start()

            if value == "[":
                tokens.append(Token(TokenType.LBRACKET, value, position))

            elif value == "]":
                tokens.append(Token(TokenType.RBRACKET, value, position))

            elif value.startswith('"'):
                if len(value) < 2 or not value.endswith('"'):
                    raise BooleanSyntaxError("Unbalanced quotation marks.")
                inner = value[1:-1].replace('""', '"')
                if not inner.strip():
                    raise BooleanSyntaxError("Empty quoted phrase.")
                tokens.append(
                    Token(TokenType.TERM, inner, position, quoted=True)
                )

            else:
                tokens.append(
                    Token(
                        self.OPERATORS.get(value, TokenType.TERM),
                        value,
                        position,
                    )
                )

        tokens.append(Token(TokenType.EOF, "", len(text)))
        return tokens


# ---------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------


class ASTNode(ABC):
    """Base class for all AST nodes."""


@dataclass(slots=True)
class TermNode(ASTNode):
    """Leaf node representing one search term (quotes already removed)."""

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


# ---------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------


class BooleanParser:
    """
    Recursive-descent Boolean parser.

    Grammar
    -------

    expression       := or_expression
    or_expression    := and_expression ( OR and_expression )*
    and_expression   := unary_expression ( (AND | NOT) unary_expression )*
    unary_expression := NOT unary_expression | primary
    primary          := TERM | "[" expression "]"
    """

    def __init__(self) -> None:
        self._tokens: Sequence[Token] = ()
        self._index = 0

    @staticmethod
    def _merge_adjacent_terms(tokens: list[Token]) -> list[Token]:
        """
        Merge consecutive BARE term tokens into one multiword term.
        Quoted terms are never merged.
        """
        merged: list[Token] = []

        for token in tokens:
            if (
                token.token_type is TokenType.TERM
                and not token.quoted
                and merged
                and merged[-1].token_type is TokenType.TERM
                and not merged[-1].quoted
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

    @property
    def current(self) -> Token:
        return self._tokens[self._index]

    def parse(self, query: str) -> ASTNode:
        """
        Parse a Boolean query into an AST.

        Raises
        ------
        BooleanSyntaxError
        """
        tokens = BooleanLexer().tokenize(query)
        self._tokens = self._merge_adjacent_terms(tokens)
        self._index = 0

        root = self._expression()

        token = self.current
        if token.token_type is not TokenType.EOF:
            if token.token_type is TokenType.RBRACKET:
                raise BooleanSyntaxError("Unexpected closing bracket ']'.")
            raise BooleanSyntaxError(
                f"Unexpected '{token.value}' - put AND, OR or NOT "
                "between search terms."
            )

        return root

    def _advance(self) -> None:
        if self._index < len(self._tokens) - 1:
            self._index += 1

    def _accept(self, token_type: TokenType) -> bool:
        if self.current.token_type is token_type:
            self._advance()
            return True
        return False

    def _expect(self, token_type: TokenType, message: str) -> Token:
        if self.current.token_type is token_type:
            token = self.current
            self._advance()
            return token
        raise BooleanSyntaxError(message)

    def _expression(self) -> ASTNode:
        return self._or_expression()

    def _or_expression(self) -> ASTNode:
        node = self._and_expression()
        while self._accept(TokenType.OR):
            node = OrNode(node, self._and_expression())
        return node

    def _and_expression(self) -> ASTNode:
        node = self._unary_expression()

        while True:
            if self._accept(TokenType.AND):
                node = AndNode(node, self._unary_expression())
                continue

            # "A NOT B" is shorthand for "A AND NOT B"
            if self._accept(TokenType.NOT):
                node = AndNode(node, NotNode(self._unary_expression()))
                continue

            return node

    def _unary_expression(self) -> ASTNode:
        if self._accept(TokenType.NOT):
            return NotNode(self._unary_expression())
        return self._primary()

    def _primary(self) -> ASTNode:
        if self._accept(TokenType.LBRACKET):
            expression = self._expression()
            self._expect(
                TokenType.RBRACKET,
                "Missing closing bracket ']'.",
            )
            return expression

        token = self.current

        if token.token_type is TokenType.TERM:
            self._advance()
            return TermNode(token.value)

        if token.token_type is TokenType.RBRACKET:
            raise BooleanSyntaxError("Unexpected closing bracket ']'.")

        if token.token_type is TokenType.EOF:
            raise BooleanSyntaxError(
                "The search is incomplete - a term is missing after the "
                "last operator or bracket."
            )

        raise BooleanSyntaxError(
            f"Unexpected '{token.value}' - a search term is expected here."
        )


def iter_term_nodes(node: ASTNode) -> Iterator[TermNode]:
    """Yield every search term in a parsed Boolean expression."""

    if isinstance(node, TermNode):
        yield node
    elif isinstance(node, NotNode):
        yield from iter_term_nodes(node.operand)
    elif isinstance(node, BinaryNode):
        yield from iter_term_nodes(node.left)
        yield from iter_term_nodes(node.right)


# ---------------------------------------------------------------------
# SQLite compiler
# ---------------------------------------------------------------------


class SQLiteFTS5Compiler:
    """
    Compile a validated Boolean AST into a single SQLite FTS5 MATCH
    expression.

    FTS5's NOT is binary only (``A NOT B``), so NotNode is only
    compilable as a conjunct of an AND chain, where a positive term is
    guaranteed to exist. Any other placement raises BooleanSyntaxError
    instead of producing invalid SQL.

    Every term is emitted as a quoted FTS5 string, so characters such as
    hyphens, apostrophes, colons or ampersands can never cause an FTS5
    syntax error.
    """

    def compile(self, ast: ASTNode) -> tuple[str, list[str]]:
        expression = self._compile_node(ast)
        return ("paragraphs_fts MATCH ?", [expression])

    def _compile_node(self, node: ASTNode) -> str:
        if isinstance(node, TermNode):
            return self._compile_term(node)

        if isinstance(node, AndNode):
            return self._compile_and_chain(node)

        if isinstance(node, OrNode):
            if isinstance(node.left, NotNode) or isinstance(node.right, NotNode):
                raise BooleanSyntaxError(
                    "NOT can't be combined directly with OR. "
                    "Use AND instead of OR, e.g. 'Climate AND NOT Biodiversity'."
                )
            return (
                f"({self._compile_node(node.left)} "
                f"OR {self._compile_node(node.right)})"
            )

        if isinstance(node, NotNode):
            raise BooleanSyntaxError(
                "NOT needs a positive search term to exclude from - "
                "try 'Climate NOT Biodiversity' or "
                "'Climate AND NOT Biodiversity'."
            )

        raise TypeError(f"Unsupported AST node: {type(node)!r}")

    def _compile_and_chain(self, node: AndNode) -> str:
        """
        Flatten a chain of AND-connected operands and compile to
        FTS5's binary NOT form:

            (positive terms ANDed) NOT (excluded terms ORed)
        """
        positives: list[str] = []
        negatives: list[str] = []

        for conjunct in self._flatten_and(node):
            if isinstance(conjunct, NotNode):
                negatives.append(self._compile_node(conjunct.operand))
            else:
                positives.append(self._compile_node(conjunct))

        if not positives:
            raise BooleanSyntaxError(
                "A search needs at least one positive term - "
                "NOT alone can't be searched."
            )

        positive_expr = (
            positives[0]
            if len(positives) == 1
            else "(" + " AND ".join(positives) + ")"
        )

        if not negatives:
            return positive_expr

        negative_expr = (
            negatives[0]
            if len(negatives) == 1
            else "(" + " OR ".join(negatives) + ")"
        )

        return f"({positive_expr} NOT {negative_expr})"

    @staticmethod
    def _flatten_and(node: ASTNode) -> list[ASTNode]:
        """Collect all AND-connected operands of a (possibly nested) AndNode."""
        if isinstance(node, AndNode):
            return SQLiteFTS5Compiler._flatten_and(
                node.left
            ) + SQLiteFTS5Compiler._flatten_and(node.right)
        return [node]

    @staticmethod
    def _compile_term(node: TermNode) -> str:
        value = node.value.strip()
        if not value:
            raise ValueError("Empty search term.")
        escaped = value.replace('"', '""')
        return f'"{escaped}"'