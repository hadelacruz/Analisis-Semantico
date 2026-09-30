"""Segunda pasada: comprobación semántica de Compiscript.

Implementa el recorrido del árbol sintáctico con un **Visitor** de ANTLR
(``CompiscriptVisitor``). Se eligió Visitor y no Listener porque cada nodo de
expresión debe **devolver su tipo** hacia el nodo padre, y los listeners no
retornan valores.

Convención del recorrido
------------------------
* ``visitXxx`` de una **expresión** devuelve un :class:`~compiscript.types.Type`.
* ``visitXxx`` de una **sentencia** devuelve ``None`` y sólo produce efectos
  (declarar símbolos, reportar diagnósticos).
* Cuando algo falla se devuelve ``ERROR``, un tipo compatible con todo, para
  que un único error real no dispare una cascada de errores derivados.

Cada comprobación lleva en el comentario el código de diagnóstico que emite;
ese mismo código es el que verifica la batería de tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from antlr4 import ParserRuleContext

from .collector import DeclarationCollector
from .diagnostics import ErrorReporter
from .generated.CompiscriptParser import CompiscriptParser as P
from .generated.CompiscriptVisitor import CompiscriptVisitor
from .scope import ScopeKind, SymbolTable
from .symbols import ClassSymbol, FunctionSymbol, Symbol, SymbolCategory, VariableSymbol
from .syntax import span, token_span
from .types import (
    BOOLEAN,
    ERROR,
    FLOAT,
    INTEGER,
    NULL,
    STRING,
    VOID,
    ArrayType,
    ClassType,
    FunctionType,
    Type,
    arithmetic_result,
    is_assignable,
    is_comparable,
    is_ordered,
    unify,
)


def _de(descripcion: str) -> str:
    """``de`` + descripción, contrayendo ``de el`` en ``del``.

    Las descripciones de :class:`LValue` empiezan por su artículo ("el metodo
    'x'", "la variable 'y'") para poder incrustarlas en cualquier mensaje; sin
    esta contracción saldría "de el constructor de 'A'".
    """
    if descripcion.startswith("el "):
        return "del " + descripcion[3:]
    return "de " + descripcion


@dataclass
class LValue:
    """Resultado de analizar un ``leftHandSide``.

    Además del tipo, guarda de qué **clase de destino** se trata, lo que
    permite decidir si se le puede asignar y qué error emitir si no.
    """

    type: Type
    kind: str = "value"            # value | variable | index | property | this | function | class
    symbol: Optional[Symbol] = None
    member_name: str = ""
    owner_class: Optional[ClassType] = None
    writable: bool = False
    description: str = "la expresion"


class SemanticChecker(CompiscriptVisitor):
    """Recorre el árbol aplicando todas las reglas semánticas del enunciado."""

    def __init__(self, reporter: ErrorReporter) -> None:
        self.reporter = reporter
        self.table = SymbolTable()
        self.collector = DeclarationCollector(self.table, reporter)

        # Estado del recorrido
        self.loop_depth = 0
        self.switch_depth = 0
        self.function_stack: list[FunctionSymbol] = []
        self.class_stack: list[ClassSymbol] = []
        #: Tipo inferido de cada nodo de expresión (lo consume el visor de árbol).
        self.node_types: dict[int, str] = {}

    # ======================================================================
    # Utilidades
    # ======================================================================
    def _record(self, ctx: ParserRuleContext, type_: Type) -> Type:
        self.node_types[id(ctx)] = str(type_)
        return type_

    def _err(self, code: str, message: str, ctx) -> None:
        line, col, eline, ecol = span(ctx)
        self.reporter.error(code, message, line, col, end_line=eline, end_column=ecol)

    def _warn(self, code: str, message: str, ctx) -> None:
        line, col, eline, ecol = span(ctx)
        self.reporter.warning(code, message, line, col, end_line=eline, end_column=ecol)

    def _err_token(self, code: str, message: str, token) -> None:
        line, col, eline, ecol = token_span(token)
        self.reporter.error(code, message, line, col, end_line=eline, end_column=ecol)

    @staticmethod
    def _deep_single(node, stop_types: tuple = ()):
        """Desciende por los nodos de un solo hijo (cadena de precedencia)."""
        while True:
            if stop_types and isinstance(node, stop_types):
                return node
            if not isinstance(node, ParserRuleContext) or node.getChildCount() != 1:
                return node
            child = node.getChild(0)
            if not isinstance(child, ParserRuleContext):
                return node
            node = child

    def _constant_int(self, ctx) -> Optional[int]:
        """Valor de ``ctx`` si es un literal entero constante (posiblemente negado)."""
        node = self._deep_single(ctx)
        if isinstance(node, P.UnaryExprContext) and node.getChildCount() == 2:
            if node.getChild(0).getText() == "-":
                inner = self._constant_int(node.unaryExpr())
                return None if inner is None else -inner
            return None
        if isinstance(node, P.LiteralExprContext) and node.Literal() is not None:
            text = node.Literal().getText()
            if text.isdigit():
                return int(text)
        return None

    def _array_literal(self, ctx) -> Optional[P.ArrayLiteralContext]:
        node = self._deep_single(ctx, (P.ArrayLiteralContext,))
        return node if isinstance(node, P.ArrayLiteralContext) else None

    def _require_boolean(self, type_: Type, ctx, construct: str) -> None:
        """E401 — las condiciones de control de flujo deben ser boolean."""
        if type_.is_error or type_ is BOOLEAN:
            return
        self._err(
            "E401",
            f"La condicion de '{construct}' debe ser de tipo boolean, pero es '{type_}'.",
            ctx,
        )

    # ======================================================================
    # Programa y listas de sentencias
    # ======================================================================
    def visitProgram(self, ctx: P.ProgramContext):
        self._visit_statement_list(ctx.statement())
        self._report_unused_locals()
        return None

    def _visit_statement_list(self, statements) -> None:
        """Hace *hoisting*, visita en orden y detecta código muerto (W902)."""
        stmts = list(statements or [])
        self.collector.hoist(stmts)

        unreachable_from: Optional[str] = None
        for stmt in stmts:
            if unreachable_from is not None:
                self._warn(
                    "W902",
                    f"Codigo muerto: esta instruccion nunca se ejecuta porque el "
                    f"flujo ya termino en el '{unreachable_from}' anterior.",
                    stmt,
                )
                unreachable_from = None  # sólo avisamos de la primera
            self.visit(stmt)
            terminator = self._terminator(stmt)
            if terminator is not None:
                unreachable_from = terminator

    def _visit_block(self, block_ctx: P.BlockContext, label: str) -> None:
        """Visita un bloque creando su propio ámbito (requerimiento 2.2)."""
        line = block_ctx.start.line
        self.table.push(ScopeKind.BLOCK, f"bloque {label} (linea {line})", line=line)
        self._visit_statement_list(block_ctx.statement())
        self.table.pop()

    def visitBlock(self, ctx: P.BlockContext):
        self._visit_block(ctx, "anonimo")
        return None

    # ======================================================================
    # Declaraciones
    # ======================================================================
    def visitVariableDeclaration(self, ctx: P.VariableDeclarationContext):
        token = ctx.Identifier().getSymbol()
        name = token.text
        keyword = ctx.getChild(0).getText()

        annotation = ctx.typeAnnotation()
        declared: Optional[Type] = (
            self.collector.resolve_type(annotation.type_()) if annotation is not None else None
        )

        init_ctx = ctx.initializer()
        init_type: Optional[Type] = None
        if init_ctx is not None:
            init_type = self.visit(init_ctx.expression())

        final_type = self._resolve_declared_type(ctx, name, declared, init_type, init_ctx)

        # E202 — redeclaración en el mismo ámbito
        if self.table.resolve_local(name) is not None:
            previous = self.table.resolve_local(name)
            self._err_token(
                "E202",
                f"'{name}' ya esta declarado en este ambito (linea {previous.line}).",
                token,
            )
            return None

        line, col, _, _ = token_span(token)
        symbol = VariableSymbol(
            name=name,
            category=SymbolCategory.VARIABLE,
            type=final_type,
            line=line,
            column=col,
            initialized=init_ctx is not None,
        )
        if init_ctx is not None:
            literal = self._array_literal(init_ctx.expression())
            if literal is not None:
                symbol.array_length = len(literal.expression())
        self.table.declare(symbol)
        self.node_types[id(ctx)] = f"{keyword} {name}: {final_type}"
        return None

    def _resolve_declared_type(
        self,
        ctx,
        name: str,
        declared: Optional[Type],
        init_type: Optional[Type],
        init_ctx,
    ) -> Type:
        """Combina anotación e inicializador para obtener el tipo definitivo."""
        if declared is not None and init_type is not None:
            # E105 — el valor inicial debe encajar en el tipo declarado
            if not is_assignable(declared, init_type):
                self._err(
                    "E105",
                    f"No se puede inicializar '{name}' de tipo '{declared}' "
                    f"con un valor de tipo '{init_type}'.",
                    init_ctx.expression() if hasattr(init_ctx, "expression") else ctx,
                )
            return declared

        if declared is not None:
            return declared

        if init_type is not None:
            if init_type is VOID:
                # E112 — una llamada a procedimiento no produce valor
                self._err(
                    "E112",
                    f"No se puede inferir el tipo de '{name}': la expresion no "
                    f"produce ningun valor (es de tipo void).",
                    init_ctx.expression(),
                )
                return ERROR
            literal = self._array_literal(init_ctx.expression())
            empty_literal = literal is not None and not literal.expression()
            if isinstance(init_type, ArrayType) and init_type.element.is_error and empty_literal:
                # E112 — literal de arreglo vacío sin anotación. Se exige que el
                # literal esté realmente vacío: si el tipo del elemento es ERROR
                # por un E111 previo, ese error ya se reportó y no se repite.
                self._err(
                    "E112",
                    f"No se puede inferir el tipo de los elementos de '{name}'. "
                    f"Anota el tipo explicitamente, por ejemplo: "
                    f"let {name}: integer[] = [];",
                    init_ctx.expression(),
                )
                return init_type
            return init_type

        # E112 — ni tipo ni valor inicial
        self._err(
            "E112",
            f"No se puede inferir el tipo de '{name}': declarala con una "
            f"anotacion de tipo o con un valor inicial.",
            ctx,
        )
        return ERROR

    def visitConstantDeclaration(self, ctx: P.ConstantDeclarationContext):
        token = ctx.Identifier().getSymbol()
        name = token.text

        annotation = ctx.typeAnnotation()
        declared = (
            self.collector.resolve_type(annotation.type_()) if annotation is not None else None
        )

        # La gramática obliga al '=' en las constantes, de modo que E106 sólo
        # puede darse si el árbol viene incompleto por un error de sintaxis.
        expr_ctx = ctx.expression()
        if expr_ctx is None:
            self._err_token(
                "E106", f"La constante '{name}' debe inicializarse en su declaracion.", token
            )
            value_type: Type = ERROR
        else:
            value_type = self.visit(expr_ctx)

        if declared is not None and expr_ctx is not None:
            if not is_assignable(declared, value_type):
                self._err(
                    "E105",
                    f"No se puede inicializar la constante '{name}' de tipo "
                    f"'{declared}' con un valor de tipo '{value_type}'.",
                    expr_ctx,
                )
            final_type = declared
        elif declared is not None:
            final_type = declared
        else:
            final_type = value_type

        if self.table.resolve_local(name) is not None:
            previous = self.table.resolve_local(name)
            self._err_token(
                "E202",
                f"'{name}' ya esta declarado en este ambito (linea {previous.line}).",
                token,
            )
            return None

        line, col, _, _ = token_span(token)
        symbol = VariableSymbol(
            name=name,
            category=SymbolCategory.CONSTANT,
            type=final_type,
            line=line,
            column=col,
            initialized=True,
        )
        if expr_ctx is not None:
            literal = self._array_literal(expr_ctx)
            if literal is not None:
                symbol.array_length = len(literal.expression())
        self.table.declare(symbol)
        return None

    # ======================================================================
    # Asignaciones (regla 'assignment' a nivel de sentencia)
    # ======================================================================
    def visitAssignment(self, ctx: P.AssignmentContext):
        expressions = ctx.expression()
        token = ctx.Identifier().getSymbol()

        if len(expressions) == 1:
            # Identifier '=' expression ';'
            value_type = self.visit(expressions[0])
            self._assign_to_name(token, value_type, expressions[0])
        else:
            # expression '.' Identifier '=' expression ';'
            object_type = self.visit(expressions[0])
            value_type = self.visit(expressions[1])
            self._assign_to_property(object_type, token, value_type, expressions[1])
        return None

    def _assign_to_name(self, token, value_type: Type, value_ctx) -> None:
        name = token.text
        found = self.table.resolve_with_capture(name)
        if found is None:
            # E201 — variable no declarada
            self._err_token("E201", f"La variable '{name}' no esta declarada.", token)
            return
        symbol, _ = found

        if isinstance(symbol, (FunctionSymbol, ClassSymbol)):
            # E203 — el nombre existe pero no designa un valor asignable
            self._err_token(
                "E203",
                f"'{name}' es una {symbol.category.value} y no se le puede asignar un valor.",
                token,
            )
            return
        if symbol.category is SymbolCategory.CONSTANT:
            # E107 — las constantes no se reasignan
            self._err_token(
                "E107",
                f"'{name}' es una constante (declarada en la linea {symbol.line}) "
                f"y no puede reasignarse.",
                token,
            )
            return
        if not is_assignable(symbol.type, value_type):
            # E105 — tipos incompatibles en la asignación
            self._err(
                "E105",
                f"No se puede asignar un valor de tipo '{value_type}' a "
                f"'{name}', que es de tipo '{symbol.type}'.",
                value_ctx,
            )
            return
        symbol.initialized = True

    def _assign_to_property(self, object_type: Type, token, value_type: Type, value_ctx) -> None:
        name = token.text
        if object_type.is_error:
            return
        if not isinstance(object_type, ClassType):
            # E507 — sólo los objetos tienen propiedades
            self._err_token(
                "E507",
                f"No se puede acceder a la propiedad '{name}': el valor es de "
                f"tipo '{object_type}', que no es un objeto.",
                token,
            )
            return

        field_type = object_type.lookup_field(name)
        if field_type is None:
            if object_type.lookup_method(name) is not None:
                # E502 — no se asigna sobre un método
                self._err_token(
                    "E502",
                    f"'{name}' es un metodo de la clase '{object_type.name}' y no "
                    f"puede recibir una asignacion.",
                    token,
                )
            else:
                # E502 — atributo inexistente
                self._err_token(
                    "E502",
                    f"La clase '{object_type.name}' no tiene un atributo llamado '{name}'.",
                    token,
                )
            return

        owner = object_type.owner_of(name)
        field_symbol = owner.symbol.fields.get(name) if owner and owner.symbol else None
        if field_symbol is not None and field_symbol.category is SymbolCategory.CONSTANT:
            self._err_token(
                "E107",
                f"'{name}' es una constante de la clase '{object_type.name}' y no "
                f"puede reasignarse.",
                token,
            )
            return

        if not is_assignable(field_type, value_type):
            self._err(
                "E105",
                f"No se puede asignar un valor de tipo '{value_type}' al atributo "
                f"'{name}', que es de tipo '{field_type}'.",
                value_ctx,
            )
            return
        if field_symbol is not None:
            field_symbol.initialized = True

    # ======================================================================
    # Sentencias simples
    # ======================================================================
    def visitExpressionStatement(self, ctx: P.ExpressionStatementContext):
        expr = ctx.expression()
        self.visit(expr)
        if not self._has_side_effect(expr):
            # E701 — expresión sin sentido semántico como sentencia
            self._err(
                "E701",
                "Esta expresion no produce ningun efecto: como sentencia solo "
                "tienen sentido las llamadas a funcion, las asignaciones y 'new'.",
                ctx,
            )
        return None

    def _has_side_effect(self, expr_ctx: P.ExpressionContext) -> bool:
        node = expr_ctx.assignmentExpr()
        if isinstance(node, (P.AssignExprContext, P.PropertyAssignExprContext)):
            return True
        deep = self._deep_single(node, (P.LeftHandSideContext,))
        if isinstance(deep, P.LeftHandSideContext):
            suffixes = deep.suffixOp()
            if suffixes and isinstance(suffixes[-1], P.CallExprContext):
                return True
            if not suffixes and isinstance(deep.primaryAtom(), P.NewExprContext):
                return True
        return False

    def visitPrintStatement(self, ctx: P.PrintStatementContext):
        value_type = self.visit(ctx.expression())
        if value_type is VOID:
            # E702 — no hay nada que imprimir
            self._err(
                "E702",
                "'print' no puede imprimir el resultado de una funcion que no "
                "devuelve valor (void).",
                ctx.expression(),
            )
        return None

    def visitBreakStatement(self, ctx: P.BreakStatementContext):
        # E402 — 'break' fuera de bucle. Se acepta dentro de 'switch' por ser
        # el comportamiento convencional del lenguaje (ver docs/ARQUITECTURA.md).
        if self.loop_depth == 0 and self.switch_depth == 0:
            self._err("E402", "'break' solo puede usarse dentro de un bucle o un 'switch'.", ctx)
        return None

    def visitContinueStatement(self, ctx: P.ContinueStatementContext):
        # E403 — 'continue' sólo tiene sentido en un bucle
        if self.loop_depth == 0:
            self._err("E403", "'continue' solo puede usarse dentro de un bucle.", ctx)
        return None

    def visitReturnStatement(self, ctx: P.ReturnStatementContext):
        expr = ctx.expression()
        if not self.function_stack:
            # E404 — return fuera de una función
            self._err("E404", "'return' solo puede aparecer dentro de una funcion.", ctx)
            if expr is not None:
                self.visit(expr)
            return None

        function = self.function_stack[-1]
        if function.return_type is VOID:
            if expr is not None:
                self.visit(expr)
                if function.is_constructor:
                    self._err(
                        "E305",
                        f"El constructor de '{function.owner}' no puede devolver un valor.",
                        ctx,
                    )
                else:
                    self._err(
                        "E305",
                        f"La funcion '{function.name}' no declara tipo de retorno, "
                        f"asi que 'return' no debe llevar valor.",
                        ctx,
                    )
            return None

        if expr is None:
            # E305 — falta el valor de retorno
            self._err(
                "E305",
                f"La funcion '{function.name}' debe devolver un valor de tipo "
                f"'{function.return_type}'.",
                ctx,
            )
            return None

        value_type = self.visit(expr)
        if not is_assignable(function.return_type, value_type):
            # E304 — el valor devuelto no encaja con la firma
            self._err(
                "E304",
                f"La funcion '{function.name}' declara devolver "
                f"'{function.return_type}' pero este 'return' devuelve "
                f"'{value_type}'.",
                expr,
            )
        return None

    # ======================================================================
    # Control de flujo
    # ======================================================================
    def visitIfStatement(self, ctx: P.IfStatementContext):
        self._require_boolean(self.visit(ctx.expression()), ctx.expression(), "if")
        blocks = ctx.block()
        self._visit_block(blocks[0], "if")
        if len(blocks) > 1:
            self._visit_block(blocks[1], "else")
        return None

    def visitWhileStatement(self, ctx: P.WhileStatementContext):
        self._require_boolean(self.visit(ctx.expression()), ctx.expression(), "while")
        self.loop_depth += 1
        self._visit_block(ctx.block(), "while")
        self.loop_depth -= 1
        return None

    def visitDoWhileStatement(self, ctx: P.DoWhileStatementContext):
        self.loop_depth += 1
        self._visit_block(ctx.block(), "do-while")
        self.loop_depth -= 1
        self._require_boolean(self.visit(ctx.expression()), ctx.expression(), "do-while")
        return None

    def visitForStatement(self, ctx: P.ForStatementContext):
        line = ctx.start.line
        self.table.push(ScopeKind.BLOCK, f"bloque for (linea {line})", line=line)

        init, condition, update = self._split_for_header(ctx)
        if init is not None:
            self.visit(init)
        if condition is not None:
            self._require_boolean(self.visit(condition), condition, "for")
        if update is not None:
            self.visit(update)

        self.loop_depth += 1
        self._visit_block(ctx.block(), "for")
        self.loop_depth -= 1
        self.table.pop()
        return None

    @staticmethod
    def _split_for_header(ctx: P.ForStatementContext):
        """Separa ``for (init; condicion; actualizacion)``.

        Los tres componentes son opcionales, así que no basta con el índice:
        hay que recorrer los hijos y contar los ``;``.
        """
        children = list(ctx.getChildren())
        index = 2  # se saltan 'for' y '('
        init = None
        if isinstance(children[index], (P.VariableDeclarationContext, P.AssignmentContext)):
            init = children[index]
            index += 1
        else:
            index += 1  # el ';' vacío del inicializador

        condition = None
        if isinstance(children[index], P.ExpressionContext):
            condition = children[index]
            index += 1
        index += 1  # el ';' que cierra la condición

        update = None
        if isinstance(children[index], P.ExpressionContext):
            update = children[index]
        return init, condition, update

    def visitForeachStatement(self, ctx: P.ForeachStatementContext):
        token = ctx.Identifier().getSymbol()
        iterable_type = self.visit(ctx.expression())

        element_type: Type = ERROR
        if isinstance(iterable_type, ArrayType):
            element_type = iterable_type.element
        elif not iterable_type.is_error:
            # E406 — foreach sólo recorre arreglos
            self._err(
                "E406",
                f"'foreach' necesita un arreglo, pero la expresion es de tipo "
                f"'{iterable_type}'.",
                ctx.expression(),
            )

        line = ctx.start.line
        self.table.push(ScopeKind.BLOCK, f"bloque foreach (linea {line})", line=line)
        tline, tcol, _, _ = token_span(token)
        self.table.declare(
            VariableSymbol(
                name=token.text,
                category=SymbolCategory.VARIABLE,
                type=element_type,
                line=tline,
                column=tcol,
                initialized=True,
            )
        )
        self.loop_depth += 1
        self._visit_block(ctx.block(), "foreach")
        self.loop_depth -= 1
        self.table.pop()
        return None

    def visitTryCatchStatement(self, ctx: P.TryCatchStatementContext):
        blocks = ctx.block()
        self._visit_block(blocks[0], "try")

        token = ctx.Identifier().getSymbol()
        line = blocks[1].start.line
        self.table.push(ScopeKind.BLOCK, f"bloque catch (linea {line})", line=line)
        tline, tcol, _, _ = token_span(token)
        # Decisión de diseño: el objeto de error de 'catch' es un string con el
        # mensaje (ver docs/ARQUITECTURA.md, "Supuestos del lenguaje").
        self.table.declare(
            VariableSymbol(
                name=token.text,
                category=SymbolCategory.VARIABLE,
                type=STRING,
                line=tline,
                column=tcol,
                initialized=True,
            )
        )
        self._visit_statement_list(blocks[1].statement())
        self.table.pop()
        return None

    def visitSwitchStatement(self, ctx: P.SwitchStatementContext):
        subject_type = self.visit(ctx.expression())
        self.switch_depth += 1

        for case in ctx.switchCase():
            case_type = self.visit(case.expression())
            if not is_comparable(subject_type, case_type):
                # E405 — el case debe ser comparable con el sujeto del switch
                self._err(
                    "E405",
                    f"El 'case' es de tipo '{case_type}' y no puede compararse con "
                    f"el 'switch', que es de tipo '{subject_type}'.",
                    case.expression(),
                )
            line = case.start.line
            self.table.push(ScopeKind.BLOCK, f"bloque case (linea {line})", line=line)
            self._visit_statement_list(case.statement())
            self.table.pop()

        default_case = ctx.defaultCase()
        if default_case is not None:
            line = default_case.start.line
            self.table.push(ScopeKind.BLOCK, f"bloque default (linea {line})", line=line)
            self._visit_statement_list(default_case.statement())
            self.table.pop()

        self.switch_depth -= 1
        return None

    # ======================================================================
    # Funciones y clases
    # ======================================================================
    def visitFunctionDeclaration(self, ctx: P.FunctionDeclarationContext):
        symbol = self.collector.function_by_ctx.get(ctx)
        if symbol is None:
            return None  # la declaración fue rechazada (duplicada); no hay cuerpo que revisar
        self._check_function_body(symbol, ctx)
        return None

    def _check_function_body(self, symbol: FunctionSymbol, ctx: P.FunctionDeclarationContext):
        scope = symbol.body_scope
        if scope is None:
            return
        self.table.enter(scope)
        self.function_stack.append(symbol)
        # 'break'/'continue' no cruzan la frontera de una función.
        saved_loop, saved_switch = self.loop_depth, self.switch_depth
        self.loop_depth = self.switch_depth = 0

        # El cuerpo comparte el ámbito de la función: así un local con el mismo
        # nombre que un parámetro se detecta como redeclaración (E202).
        self._visit_statement_list(ctx.block().statement())

        self.loop_depth, self.switch_depth = saved_loop, saved_switch
        self.function_stack.pop()
        self.table.leave(scope)

        # E308 — toda ruta de una función con tipo de retorno debe devolver algo
        if symbol.return_type is not VOID and not symbol.return_type.is_error:
            if not self._always_returns(ctx.block()):
                self._err_token(
                    "E308",
                    f"No todos los caminos de '{symbol.name}' devuelven un valor de "
                    f"tipo '{symbol.return_type}'.",
                    ctx.Identifier().getSymbol(),
                )

    def visitClassDeclaration(self, ctx: P.ClassDeclarationContext):
        symbol = self.collector.class_by_ctx.get(ctx)
        if symbol is None or symbol.class_scope is None:
            return None

        self.table.enter(symbol.class_scope)
        self.class_stack.append(symbol)

        for member in ctx.classMember():
            func_ctx = member.functionDeclaration()
            if func_ctx is not None:
                method = self.collector.function_by_ctx.get(func_ctx)
                if method is not None:
                    self._check_function_body(method, func_ctx)
                continue
            self._check_field_initializer(member, symbol)

        self.class_stack.pop()
        self.table.leave(symbol.class_scope)
        return None

    def _check_field_initializer(self, member: P.ClassMemberContext, klass: ClassSymbol) -> None:
        var_ctx = member.variableDeclaration()
        const_ctx = member.constantDeclaration()
        target = var_ctx if var_ctx is not None else const_ctx
        if target is None:
            return

        name = target.Identifier().getText()
        field = klass.fields.get(name)

        if var_ctx is not None:
            init = var_ctx.initializer()
            expr = init.expression() if init is not None else None
        else:
            expr = const_ctx.expression()

        if expr is None:
            return
        value_type = self.visit(expr)
        if field is not None and not is_assignable(field.type, value_type):
            self._err(
                "E105",
                f"No se puede inicializar el atributo '{name}' de tipo "
                f"'{field.type}' con un valor de tipo '{value_type}'.",
                expr,
            )

    # ======================================================================
    # Expresiones
    # ======================================================================
    def visitExpression(self, ctx: P.ExpressionContext):
        return self._record(ctx, self.visit(ctx.assignmentExpr()))

    def visitExprNoAssign(self, ctx: P.ExprNoAssignContext):
        return self.visit(ctx.conditionalExpr())

    def visitAssignExpr(self, ctx: P.AssignExprContext):
        target = self._analyze_left_hand_side(ctx.lhs, reading=False)
        value_type = self.visit(ctx.assignmentExpr())
        self._check_assignment_target(target, value_type, ctx)
        return self._record(ctx, target.type)

    def visitPropertyAssignExpr(self, ctx: P.PropertyAssignExprContext):
        object_type = self._analyze_left_hand_side(ctx.lhs, reading=True).type
        value_type = self.visit(ctx.assignmentExpr())
        self._assign_to_property(object_type, ctx.Identifier().getSymbol(), value_type, ctx.assignmentExpr())
        return self._record(ctx, value_type)

    def _check_assignment_target(self, target: LValue, value_type: Type, ctx) -> None:
        if target.type.is_error:
            return
        if not target.writable:
            if target.kind == "variable" and target.symbol is not None:
                # E107 — asignación a constante
                self._err(
                    "E107",
                    f"'{target.symbol.name}' es una constante y no puede reasignarse.",
                    ctx,
                )
            else:
                # E701 — el destino no es asignable
                self._err("E701", f"{target.description} no es un destino asignable.", ctx)
            return
        if not is_assignable(target.type, value_type):
            self._err(
                "E105",
                f"No se puede asignar un valor de tipo '{value_type}' a "
                f"{target.description}, de tipo '{target.type}'.",
                ctx,
            )
            return
        if target.symbol is not None:
            target.symbol.initialized = True

    def visitTernaryExpr(self, ctx: P.TernaryExprContext):
        condition_type = self.visit(ctx.logicalOrExpr())
        branches = ctx.expression()
        if not branches:
            return self._record(ctx, condition_type)

        if not condition_type.is_error and condition_type is not BOOLEAN:
            # E113 — la condición del ternario debe ser boolean
            self._err(
                "E113",
                f"La condicion del operador '?:' debe ser boolean, pero es "
                f"'{condition_type}'.",
                ctx.logicalOrExpr(),
            )

        then_type = self.visit(branches[0])
        else_type = self.visit(branches[1])
        result = unify(then_type, else_type)
        if result is None:
            # E114 — las ramas deben producir un tipo común
            self._err(
                "E114",
                f"Las ramas del operador '?:' devuelven tipos incompatibles: "
                f"'{then_type}' y '{else_type}'.",
                ctx,
            )
            result = ERROR
        return self._record(ctx, result)

    def visitLogicalOrExpr(self, ctx: P.LogicalOrExprContext):
        return self._check_logical(ctx, ctx.logicalAndExpr(), "||")

    def visitLogicalAndExpr(self, ctx: P.LogicalAndExprContext):
        return self._check_logical(ctx, ctx.equalityExpr(), "&&")

    def _check_logical(self, ctx, operands, operator: str) -> Type:
        if len(operands) == 1:
            return self.visit(operands[0])
        for operand in operands:
            operand_type = self.visit(operand)
            if not operand_type.is_error and operand_type is not BOOLEAN:
                # E102 — los operadores lógicos exigen boolean
                self._err(
                    "E102",
                    f"El operador '{operator}' requiere operandos boolean, pero "
                    f"se encontro '{operand_type}'.",
                    operand,
                )
        return self._record(ctx, BOOLEAN)

    def visitEqualityExpr(self, ctx: P.EqualityExprContext):
        operands = ctx.relationalExpr()
        if len(operands) == 1:
            return self.visit(operands[0])
        current = self.visit(operands[0])
        for index in range(1, len(operands)):
            operator = ctx.getChild(2 * index - 1).getText()
            right = self.visit(operands[index])
            if not is_comparable(current, right):
                # E103 — igualdad entre tipos incompatibles
                self._err(
                    "E103",
                    f"No se pueden comparar con '{operator}' un valor de tipo "
                    f"'{current}' y uno de tipo '{right}'.",
                    operands[index],
                )
            current = BOOLEAN
        return self._record(ctx, BOOLEAN)

    def visitRelationalExpr(self, ctx: P.RelationalExprContext):
        operands = ctx.additiveExpr()
        if len(operands) == 1:
            return self.visit(operands[0])
        current = self.visit(operands[0])
        for index in range(1, len(operands)):
            operator = ctx.getChild(2 * index - 1).getText()
            right = self.visit(operands[index])
            comparable = (
                is_ordered(current)
                and is_ordered(right)
                and (current.is_error or right.is_error or unify(current, right) is not None)
            )
            if not comparable:
                # E104 — los operadores relacionales exigen tipos ordenables
                self._err(
                    "E104",
                    f"El operador '{operator}' no puede comparar '{current}' con "
                    f"'{right}'; se esperaban valores numericos o string.",
                    operands[index],
                )
            current = BOOLEAN
        return self._record(ctx, BOOLEAN)

    def visitAdditiveExpr(self, ctx: P.AdditiveExprContext):
        return self._check_arithmetic(ctx, ctx.multiplicativeExpr())

    def visitMultiplicativeExpr(self, ctx: P.MultiplicativeExprContext):
        return self._check_arithmetic(ctx, ctx.unaryExpr())

    def _check_arithmetic(self, ctx, operands) -> Type:
        if len(operands) == 1:
            return self.visit(operands[0])

        current = self.visit(operands[0])
        for index in range(1, len(operands)):
            operator = ctx.getChild(2 * index - 1).getText()
            right = self.visit(operands[index])

            # W904 — división o módulo entre la constante cero
            if operator in ("/", "%") and self._constant_int(operands[index]) == 0:
                self._warn(
                    "W904",
                    f"El operador '{operator}' se aplica sobre la constante 0; "
                    f"esto provocara un error en tiempo de ejecucion.",
                    operands[index],
                )

            result = arithmetic_result(operator, current, right)
            if result is None:
                if operator == "%":
                    # E115 — el módulo es sólo para enteros
                    self._err(
                        "E115",
                        f"El operador '%' requiere operandos de tipo integer, pero "
                        f"se encontro '{current}' y '{right}'.",
                        operands[index],
                    )
                else:
                    # E101 — aritmética sobre operandos no numéricos
                    self._err(
                        "E101",
                        f"El operador '{operator}' no puede aplicarse a '{current}' "
                        f"y '{right}'; se esperaban valores numericos"
                        + (" o una concatenacion con string." if operator == "+" else "."),
                        operands[index],
                    )
                result = ERROR
            current = result
        return self._record(ctx, current)

    def visitUnaryExpr(self, ctx: P.UnaryExprContext):
        inner = ctx.unaryExpr()
        if inner is None:
            return self.visit(ctx.primaryExpr())

        operator = ctx.getChild(0).getText()
        operand_type = self.visit(inner)
        if operator == "-":
            if not operand_type.is_error and not operand_type.is_numeric:
                # E108 — negación aritmética sobre un valor no numérico
                self._err(
                    "E108",
                    f"El operador unario '-' requiere un valor numerico, pero se "
                    f"encontro '{operand_type}'.",
                    inner,
                )
                return self._record(ctx, ERROR)
            return self._record(ctx, operand_type)

        # operador '!'
        if not operand_type.is_error and operand_type is not BOOLEAN:
            # E109 — negación lógica sobre un valor no booleano
            self._err(
                "E109",
                f"El operador unario '!' requiere un valor boolean, pero se "
                f"encontro '{operand_type}'.",
                inner,
            )
        return self._record(ctx, BOOLEAN)

    def visitPrimaryExpr(self, ctx: P.PrimaryExprContext):
        if ctx.literalExpr() is not None:
            return self.visit(ctx.literalExpr())
        if ctx.leftHandSide() is not None:
            return self._analyze_left_hand_side(ctx.leftHandSide(), reading=True).type
        return self.visit(ctx.expression())

    def visitLiteralExpr(self, ctx: P.LiteralExprContext):
        literal = ctx.Literal()
        if literal is not None:
            text = literal.getText()
            if text.startswith('"'):
                return self._record(ctx, STRING)
            if "." in text:
                return self._record(ctx, FLOAT)
            return self._record(ctx, INTEGER)
        if ctx.arrayLiteral() is not None:
            return self.visit(ctx.arrayLiteral())
        return self._record(ctx, NULL if ctx.getText() == "null" else BOOLEAN)

    def visitArrayLiteral(self, ctx: P.ArrayLiteralContext):
        elements = ctx.expression()
        if not elements:
            # El tipo de los elementos se tomará de la anotación del destino.
            return self._record(ctx, ArrayType(ERROR))

        element_type = self.visit(elements[0])
        for element in elements[1:]:
            other = self.visit(element)
            merged = unify(element_type, other)
            if merged is None:
                # E111 — los elementos de una lista deben ser del mismo tipo
                self._err(
                    "E111",
                    f"Los elementos del arreglo deben ser del mismo tipo: se "
                    f"esperaba '{element_type}' pero se encontro '{other}'.",
                    element,
                )
                element_type = ERROR
            else:
                element_type = merged
        return self._record(ctx, ArrayType(element_type))

    def visitLeftHandSide(self, ctx: P.LeftHandSideContext):
        return self._analyze_left_hand_side(ctx, reading=True).type

    # ======================================================================
    # leftHandSide: identificadores, llamadas, índices y propiedades
    # ======================================================================
    def _analyze_left_hand_side(self, ctx: P.LeftHandSideContext, *, reading: bool) -> LValue:
        info = self._analyze_atom(ctx.primaryAtom(), reading=reading)
        for suffix in ctx.suffixOp():
            info = self._apply_suffix(info, suffix)

        # E309 — una función usada como valor sin invocarla
        if reading and isinstance(info.type, FunctionType):
            self._err(
                "E309",
                f"'{info.member_name or (info.symbol.name if info.symbol else 'la funcion')}' "
                f"es una funcion: para usar su resultado hay que invocarla con '()'.",
                ctx,
            )
            info = LValue(ERROR)
        self.node_types[id(ctx)] = str(info.type)
        return info

    def _analyze_atom(self, ctx, *, reading: bool) -> LValue:
        if isinstance(ctx, P.IdentifierExprContext):
            return self._analyze_identifier(ctx, reading=reading)
        if isinstance(ctx, P.NewExprContext):
            return self._analyze_new(ctx)
        if isinstance(ctx, P.ThisExprContext):
            return self._analyze_this(ctx)
        return LValue(ERROR)

    def _analyze_identifier(self, ctx: P.IdentifierExprContext, *, reading: bool) -> LValue:
        token = ctx.Identifier().getSymbol()
        name = token.text
        found = self.table.resolve_with_capture(name)
        if found is None:
            # E201 — identificador no declarado
            self._err_token("E201", f"'{name}' no esta declarado.", token)
            return LValue(ERROR)

        symbol, _ = found
        if reading:
            symbol.used = True

        if isinstance(symbol, ClassSymbol):
            # E203 — una clase no es un valor; hay que instanciarla con 'new'
            self._err_token(
                "E203",
                f"'{name}' es una clase; para crear una instancia usa "
                f"'new {name}(...)'.",
                token,
            )
            return LValue(ERROR)

        if isinstance(symbol, FunctionSymbol):
            return LValue(
                symbol.type,
                kind="function",
                symbol=symbol,
                member_name=name,
                description=f"la funcion '{name}'",
            )

        # W901 — lectura de una variable que puede no tener valor todavía
        if reading and not symbol.initialized and symbol.category is SymbolCategory.VARIABLE:
            self._warn_token(
                "W901",
                f"'{name}' se usa antes de asignarle un valor.",
                token,
            )

        return LValue(
            symbol.type,
            kind="variable",
            symbol=symbol,
            member_name=name,
            writable=symbol.category is not SymbolCategory.CONSTANT,
            description=f"la variable '{name}'",
        )

    def _warn_token(self, code: str, message: str, token) -> None:
        line, col, eline, ecol = token_span(token)
        self.reporter.warning(code, message, line, col, end_line=eline, end_column=ecol)

    def _analyze_new(self, ctx: P.NewExprContext) -> LValue:
        token = ctx.Identifier().getSymbol()
        name = token.text
        found = self.table.resolve(name)
        if found is None or not isinstance(found[0], ClassSymbol):
            # E501 — no existe la clase que se intenta instanciar
            self._err_token("E501", f"La clase '{name}' no esta declarada.", token)
            self._visit_arguments(ctx.arguments())
            return LValue(ERROR)

        klass: ClassSymbol = found[0]
        klass.used = True
        constructor = klass.constructor()

        if constructor is None:
            arguments = self._visit_arguments(ctx.arguments())
            if arguments:
                # E504 — la clase no declara constructor pero se le pasan argumentos
                self._err(
                    "E504",
                    f"La clase '{name}' no declara constructor, por lo que "
                    f"'new {name}()' no admite argumentos (se recibieron {len(arguments)}).",
                    ctx,
                )
        else:
            constructor.used = True
            self._check_arguments(
                constructor,
                ctx.arguments(),
                ctx,
                description=f"el constructor de '{name}'",
                arity_code="E504",
            )

        return LValue(
            klass.class_type or ERROR,
            kind="value",
            symbol=klass,
            member_name=name,
            description=f"la instancia de '{name}'",
        )

    def _analyze_this(self, ctx: P.ThisExprContext) -> LValue:
        if not self.class_stack:
            # E503 — 'this' sólo existe dentro de una clase
            self._err("E503", "'this' solo puede usarse dentro de un metodo de una clase.", ctx)
            return LValue(ERROR)
        klass = self.class_stack[-1]
        return LValue(
            klass.class_type or ERROR,
            kind="this",
            symbol=klass,
            member_name="this",
            description="'this'",
        )

    # -- sufijos -------------------------------------------------------------
    def _apply_suffix(self, info: LValue, suffix) -> LValue:
        if isinstance(suffix, P.CallExprContext):
            return self._apply_call(info, suffix)
        if isinstance(suffix, P.IndexExprContext):
            return self._apply_index(info, suffix)
        if isinstance(suffix, P.PropertyAccessExprContext):
            return self._apply_property(info, suffix)
        return LValue(ERROR)

    def _apply_call(self, info: LValue, suffix: P.CallExprContext) -> LValue:
        if info.type.is_error:
            self._visit_arguments(suffix.arguments())
            return LValue(ERROR)

        if not isinstance(info.type, FunctionType):
            # E303 — se intenta invocar algo que no es una función
            self._err(
                "E303",
                f"{info.description} es de tipo '{info.type}' y no puede invocarse "
                f"como una funcion.",
                suffix,
            )
            self._visit_arguments(suffix.arguments())
            return LValue(ERROR)

        callee = info.symbol if isinstance(info.symbol, FunctionSymbol) else None
        if callee is not None and callee in self.function_stack:
            callee.is_recursive = True

        self._check_arguments(
            callee,
            suffix.arguments(),
            suffix,
            description=info.description,
            function_type=info.type,
        )
        return LValue(info.type.return_type, kind="value", description="el resultado de la llamada")

    def _apply_index(self, info: LValue, suffix: P.IndexExprContext) -> LValue:
        index_type = self.visit(suffix.expression())
        if not index_type.is_error and index_type is not INTEGER:
            # E601 — el índice debe ser entero
            self._err(
                "E601",
                f"El indice de un arreglo debe ser de tipo integer, pero es "
                f"'{index_type}'.",
                suffix.expression(),
            )

        if info.type.is_error:
            return LValue(ERROR)
        if not isinstance(info.type, ArrayType):
            # E602 — indexación sobre algo que no es un arreglo
            self._err(
                "E602",
                f"{info.description} es de tipo '{info.type}' y no puede indexarse "
                f"con '[]'.",
                suffix,
            )
            return LValue(ERROR)

        # W903 — índice constante fuera del tamaño conocido del arreglo.
        # Sólo aplica cuando la base es una variable con longitud conocida: en
        # 'matriz[0][2]' la longitud de 'matriz' describe las filas, no las
        # columnas, así que el segundo índice no se puede comprobar.
        constant = self._constant_int(suffix.expression())
        if constant is not None:
            length = info.symbol.array_length if info.kind == "variable" else None
            if constant < 0:
                self._warn(
                    "W903",
                    f"El indice {constant} es negativo; el acceso fallara en "
                    f"tiempo de ejecucion.",
                    suffix.expression(),
                )
            elif length is not None and constant >= length:
                self._warn(
                    "W903",
                    f"El indice {constant} esta fuera del rango del arreglo "
                    f"'{info.member_name}', que tiene {length} elementos "
                    f"(indices validos: 0..{length - 1}).",
                    suffix.expression(),
                )

        # El elemento no es un símbolo con nombre propio: se conserva el nombre
        # del arreglo sólo para los mensajes, pero no su longitud.
        return LValue(
            info.type.element,
            kind="index",
            symbol=None,
            member_name=info.member_name,
            writable=True,
            description=f"el elemento de '{info.member_name}'" if info.member_name else "el elemento del arreglo",
        )

    def _apply_property(self, info: LValue, suffix: P.PropertyAccessExprContext) -> LValue:
        token = suffix.Identifier().getSymbol()
        name = token.text

        if info.type.is_error:
            return LValue(ERROR)
        if not isinstance(info.type, ClassType):
            # E507 — acceso con '.' sobre algo que no es un objeto
            self._err_token(
                "E507",
                f"No se puede acceder a '.{name}': {info.description} es de tipo "
                f"'{info.type}', que no es un objeto.",
                token,
            )
            return LValue(ERROR)

        klass_type: ClassType = info.type
        field_type = klass_type.lookup_field(name)
        if field_type is not None:
            owner = klass_type.owner_of(name)
            field_symbol = owner.symbol.fields.get(name) if owner and owner.symbol else None
            if field_symbol is not None:
                field_symbol.used = True
            writable = field_symbol is None or field_symbol.category is not SymbolCategory.CONSTANT
            return LValue(
                field_type,
                kind="property",
                symbol=field_symbol,
                member_name=name,
                owner_class=klass_type,
                writable=writable,
                description=f"el atributo '{name}' de '{klass_type.name}'",
            )

        method_type = klass_type.lookup_method(name)
        if method_type is not None:
            owner = klass_type.owner_of(name)
            method_symbol = owner.symbol.methods.get(name) if owner and owner.symbol else None
            if method_symbol is not None:
                method_symbol.used = True
            return LValue(
                method_type,
                kind="property",
                symbol=method_symbol,
                member_name=name,
                owner_class=klass_type,
                description=f"el metodo '{name}' de '{klass_type.name}'",
            )

        # E502 — el miembro no existe en la clase ni en sus superclases
        inherited = klass_type.ancestors()
        extra = f" ni en sus superclases ({', '.join(inherited)})" if inherited else ""
        self._err_token(
            "E502",
            f"La clase '{klass_type.name}' no tiene un miembro llamado '{name}'{extra}.",
            token,
        )
        return LValue(ERROR)

    # -- argumentos -----------------------------------------------------------
    def _visit_arguments(self, arguments_ctx) -> list[Type]:
        if arguments_ctx is None:
            return []
        return [self.visit(expr) for expr in arguments_ctx.expression()]

    def _check_arguments(
        self,
        callee: Optional[FunctionSymbol],
        arguments_ctx,
        position_ctx,
        *,
        description: str,
        arity_code: str = "E301",
        function_type: Optional[FunctionType] = None,
    ) -> None:
        """Valida número y tipo de los argumentos (coincidencia posicional)."""
        signature = function_type or (callee.function_type if callee else None)
        if signature is None:
            self._visit_arguments(arguments_ctx)
            return

        argument_ctxs = list(arguments_ctx.expression()) if arguments_ctx is not None else []
        argument_types = [self.visit(expr) for expr in argument_ctxs]

        expected = len(signature.params)
        received = len(argument_types)
        if expected != received:
            # E301 / E504 — número incorrecto de argumentos
            self._err(
                arity_code,
                f"{description[0].upper()}{description[1:]} espera {expected} "
                f"argumento(s) pero recibio {received}.",
                position_ctx,
            )

        names = signature.param_names or [f"#{i + 1}" for i in range(expected)]
        for index, (given, declared) in enumerate(zip(argument_types, signature.params)):
            if not is_assignable(declared, given):
                # E302 — tipo de argumento incompatible
                self._err(
                    "E302",
                    f"El argumento {index + 1} ('{names[index]}') {_de(description)} debe "
                    f"ser de tipo '{declared}', pero se recibio '{given}'.",
                    argument_ctxs[index],
                )

    # ======================================================================
    # Análisis de flujo
    # ======================================================================
    def _terminator(self, node) -> Optional[str]:
        """Palabra que corta el flujo en ``node``, o ``None`` si continúa."""
        if node is None:
            return None
        if isinstance(node, P.StatementContext):
            return self._terminator(node.getChild(0))
        if isinstance(node, P.ReturnStatementContext):
            return "return"
        if isinstance(node, P.BreakStatementContext):
            return "break"
        if isinstance(node, P.ContinueStatementContext):
            return "continue"
        if isinstance(node, P.BlockContext):
            for statement in node.statement():
                found = self._terminator(statement)
                if found is not None:
                    return found
            return None
        if isinstance(node, P.IfStatementContext):
            blocks = node.block()
            if len(blocks) < 2:
                return None
            first = self._terminator(blocks[0])
            second = self._terminator(blocks[1])
            return first if first is not None and second is not None else None
        return None

    def _always_returns(self, node) -> bool:
        """¿Toda ruta de ejecución dentro de ``node`` ejecuta un ``return``?"""
        if node is None:
            return False
        if isinstance(node, P.StatementContext):
            return self._always_returns(node.getChild(0))
        if isinstance(node, P.ReturnStatementContext):
            return True
        if isinstance(node, P.BlockContext):
            return any(self._always_returns(s) for s in node.statement())
        if isinstance(node, P.IfStatementContext):
            blocks = node.block()
            return len(blocks) == 2 and all(self._always_returns(b) for b in blocks)
        if isinstance(node, P.DoWhileStatementContext):
            # El cuerpo de un do-while se ejecuta al menos una vez.
            return self._always_returns(node.block())
        if isinstance(node, P.TryCatchStatementContext):
            return all(self._always_returns(b) for b in node.block())
        if isinstance(node, P.SwitchStatementContext):
            if node.defaultCase() is None:
                return False
            branches = [case.statement() for case in node.switchCase()]
            branches.append(node.defaultCase().statement())
            return all(
                any(self._always_returns(s) for s in statements) for statements in branches
            )
        return False

    # ======================================================================
    # Cierre
    # ======================================================================
    def _report_unused_locals(self) -> None:
        """W905 — variables locales declaradas y nunca leídas.

        Se limita a los ámbitos no globales: en el ámbito global es habitual
        declarar constantes de configuración que sólo usa otro módulo.
        """
        for scope in self.table.all_scopes():
            if scope.is_global:
                continue
            for symbol in scope.symbols.values():
                if symbol.used:
                    continue
                if symbol.category not in (SymbolCategory.VARIABLE, SymbolCategory.CONSTANT):
                    continue
                self.reporter.warning(
                    "W905",
                    f"La variable '{symbol.name}' se declara pero nunca se utiliza.",
                    symbol.line,
                    symbol.column,
                    end_line=symbol.line,
                    end_column=symbol.column + len(symbol.name),
                )
