"""
tests/search/test_boolean.py

Tests for search.boolean.

Covers:

- BooleanLexer tokenisation
- BooleanParser AST generation
- operator precedence
- syntax validation
- SQLite FTS5 compilation
- injection safety
"""

from __future__ import annotations

import pytest

from search.boolean import (
    AndNode,
    BooleanLexer,
    BooleanParser,
    BooleanSyntaxError,
    NorNode,
    NotNode,
    OrNode,
    SQLiteFTS5Compiler,
    TermNode,
    TokenType,
)


# ---------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------


class TestBooleanLexer:
    def test_empty_query_raises(self):
        lexer = BooleanLexer()

        with pytest.raises(BooleanSyntaxError):
            lexer.tokenize("")

    def test_whitespace_query_raises(self):
        lexer = BooleanLexer()

        with pytest.raises(BooleanSyntaxError):
            lexer.tokenize("   ")

    def test_none_query_raises(self):
        lexer = BooleanLexer()

        with pytest.raises(BooleanSyntaxError):
            lexer.tokenize(None)

    def test_tokenizes_simple_expression(self):
        lexer = BooleanLexer()

        tokens = lexer.tokenize(
            "climate AND water"
        )

        assert tokens[0].token_type is TokenType.TERM
        assert tokens[0].value == "climate"

        assert tokens[1].token_type is TokenType.AND

        assert tokens[2].token_type is TokenType.TERM
        assert tokens[2].value == "water"

        assert tokens[-1].token_type is TokenType.EOF

    def test_tokenizes_all_operators(self):
        lexer = BooleanLexer()

        tokens = lexer.tokenize(
            "A OR B NOR C NOT D"
        )

        types = [
            token.token_type
            for token in tokens[:-1]
        ]

        assert types == [
            TokenType.TERM,
            TokenType.OR,
            TokenType.TERM,
            TokenType.NOR,
            TokenType.TERM,
            TokenType.NOT,
            TokenType.TERM,
        ]

    def test_tokenizes_parentheses(self):
        lexer = BooleanLexer()

        tokens = lexer.tokenize(
            "(climate OR water)"
        )

        assert tokens[0].token_type is TokenType.LPAREN
        assert tokens[-2].token_type is TokenType.RPAREN

    def test_tokenizes_quotes(self):
        lexer = BooleanLexer()

        tokens = lexer.tokenize(
            '"climate change"'
        )

        assert tokens[0].value == '"climate change"'
        assert tokens[0].token_type is TokenType.TERM


# ---------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------


class TestBooleanParser:
    def setup_method(self):
        self.parser = BooleanParser()

    def test_single_term(self):
        ast = self.parser.parse(
            "climate"
        )

        assert isinstance(
            ast,
            TermNode,
        )

        assert ast.value == "climate"

    def test_and_expression(self):
        ast = self.parser.parse(
            "climate AND water"
        )

        assert isinstance(
            ast,
            AndNode,
        )

        assert isinstance(
            ast.left,
            TermNode,
        )

        assert isinstance(
            ast.right,
            TermNode,
        )

    def test_or_expression(self):
        ast = self.parser.parse(
            "climate OR water"
        )

        assert isinstance(
            ast,
            OrNode,
        )

    def test_nor_expression(self):
        ast = self.parser.parse(
            "climate NOR water"
        )

        assert isinstance(
            ast,
            NorNode,
        )

    def test_not_expression(self):
        ast = self.parser.parse(
            "NOT climate"
        )

        assert isinstance(
            ast,
            NotNode,
        )

        assert isinstance(
            ast.operand,
            TermNode,
        )

    def test_not_has_highest_precedence(self):
        ast = self.parser.parse(
            "NOT climate AND water"
        )

        assert isinstance(
            ast,
            AndNode,
        )

        assert isinstance(
            ast.left,
            NotNode,
        )

    def test_and_precedence_over_or(self):
        ast = self.parser.parse(
            "A OR B AND C"
        )

        assert isinstance(
            ast,
            OrNode,
        )

        assert isinstance(
            ast.right,
            AndNode,
        )

    def test_parentheses_override_precedence(self):
        ast = self.parser.parse(
            "(A OR B) AND C"
        )

        assert isinstance(
            ast,
            AndNode,
        )

        assert isinstance(
            ast.left,
            OrNode,
        )

    def test_nested_parentheses(self):
        ast = self.parser.parse(
            "((A AND B) OR C)"
        )

        assert isinstance(
            ast,
            OrNode,
        )

    def test_quoted_terms_are_unwrapped(self):
        ast = self.parser.parse(
            '"climate change"'
        )

        assert ast.value == "climate change"

    def test_embedded_quotes_are_unescaped(self):
        ast = self.parser.parse(
            '"a ""quoted"" term"'
        )

        assert ast.value == 'a "quoted" term'

    def test_missing_closing_parenthesis(self):
        with pytest.raises(BooleanSyntaxError):
            self.parser.parse(
                "(climate AND water"
            )

    def test_unexpected_closing_parenthesis(self):
        with pytest.raises(BooleanSyntaxError):
            self.parser.parse(
                "climate)"
            )

    def test_empty_expression(self):
        with pytest.raises(BooleanSyntaxError):
            self.parser.parse("")


# ---------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------


class TestSQLiteFTS5Compiler:
    def setup_method(self):
        self.compiler = SQLiteFTS5Compiler()

    def compile(self, expression):
        ast = BooleanParser().parse(expression)

        return self.compiler.compile(ast)

    def test_compile_returns_parameterised_match(self):
        sql, params = self.compile(
            "climate"
        )

        assert sql == (
            "paragraph_fts MATCH ?"
        )

        assert params == [
            "climate"
        ]

    def test_compile_and(self):
        _, params = self.compile(
            "A AND B"
        )

        assert params == [
            "(A AND B)"
        ]

    def test_compile_or(self):
        _, params = self.compile(
            "A OR B"
        )

        assert params == [
            "(A OR B)"
        ]

    def test_compile_not(self):
        _, params = self.compile(
            "NOT A"
        )

        assert params == [
            "NOT (A)"
        ]

    def test_compile_nor(self):
        _, params = self.compile(
            "A NOR B"
        )

        assert params == [
            "NOT (A OR B)"
        ]

    def test_phrase_terms_are_quoted(self):
        _, params = self.compile(
            '"climate change"'
        )

        assert params == [
            '"climate change"'
        ]

    def test_quotes_are_escaped(self):
        _, params = self.compile(
            '"a ""quoted"" term"'
        )

        assert params == [
            '"a ""quoted"" term"'
        ]

    def test_compiler_never_inlines_sql(self):
        sql, params = self.compile(
            "x'; DROP TABLE documents; --"
        )

        assert "DROP TABLE" not in sql
        assert len(params) == 1

    def test_whitespace_term_becomes_phrase(self):
        ast = TermNode(
            "climate adaptation"
        )

        sql, params = self.compiler.compile(ast)

        assert sql == (
            "paragraph_fts MATCH ?"
        )

        assert params == [
            '"climate adaptation"'
        ]