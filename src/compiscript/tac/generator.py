"""Generación de código intermedio: Compiscript -> TAC.

Tercera pasada del compilador. Recorre **el mismo árbol** que el análisis
semántico, pero no vuelve a resolver nada: lee las decoraciones que aquella
fase dejó (``checker.annotations``) y se limita a **traducir**.

Convención del recorrido
------------------------
* ``visitXxx`` de una **expresión** devuelve un :class:`Operand` con el lugar
  donde quedó su valor (un temporal, una variable o una constante).
* ``visitXxx`` de una **sentencia** devuelve ``None`` y sólo emite código.
* Las condiciones no se materializan: se traducen con :meth:`gen_condition`,
  que genera saltos directamente (código "por saltos", el tratamiento clásico
  de los operadores booleanos con cortocircuito).

Estructura del programa generado::

    ; --- programa principal ---
    begin_func main
        <inicializacion de las tablas de metodos>
        <sentencias globales>
    end_func main

    ; --- rutinas ---
    begin_func func_f  ... end_func func_f
    begin_func Clase_metodo ... end_func Clase_metodo

Ver ``docs/CODIGO_INTERMEDIO.md`` para el diseño completo del lenguaje.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from antlr4 import ParserRuleContext

from ..generated.CompiscriptParser import CompiscriptParser as P
from ..generated.CompiscriptVisitor import CompiscriptVisitor
from ..scope import SymbolTable
from ..symbols import (
    ACCESS_LINK_OFFSET,
    LOCAL_BASE_OFFSET,
    PARAM_BASE_OFFSET,
    WORD_SIZE,
    ActivationRecord,
    ClassSymbol,
    FunctionSymbol,
    StorageKind,
    Symbol,
    SymbolCategory,
    VariableSymbol,
)
from ..types import (
    ARRAY_HEADER_SIZE,
    ARRAY_LENGTH_OFFSET,
    BOOLEAN,
    ERROR,
    FLOAT,
    INTEGER,
    NULL,
    OBJECT_HEADER_SIZE,
    STRING,
    VOID,
    VTABLE_POINTER_OFFSET,
    ArrayType,
    ClassType,
    Type,
)
from . import runtime as rt
from .quadruple import Op, Operand, Quadruple, TACFunction, TACProgram
from .temporaries import LabelFactory, TempPool

#: Nombre de la rutina que contiene el programa principal.
MAIN_LABEL = "main"


class TACGenerator(CompiscriptVisitor):
    """Traduce un árbol ya analizado a código de tres direcciones."""

    def __init__(
        self,
        table: SymbolTable,
        annotations,
        collector,
        *,
        bounds_checks: bool = True,
        comments: bool = True,
    ) -> None:
        self.table = table
        self.ann = annotations
        self.collector = collector
        self.bounds_checks = bounds_checks
        self.with_comments = comments

        self.program = TACProgram()
        self.temps = TempPool()
        self.labels = LabelFactory()

        # --- estado del recorrido -----------------------------------------
        self.current_function: Optional[FunctionSymbol] = None
        self.class_stack: list[ClassSymbol] = []
        self.break_labels: list[str] = []
        self.continue_labels: list[str] = []
        #: Rutinas anidadas pendientes de emitir (se emiten tras su padre).
        self._pending: list[tuple[P.FunctionDeclarationContext, FunctionSymbol]] = []
        #: ``id(simbolo) -> funcion que lo declara``; detecta las capturas.
        self._owner_of: dict[int, Optional[FunctionSymbol]] = {}
        self._classes: list[ClassSymbol] = []
        #: ``clase -> [(atributo, expresion)]`` de los atributos con valor inicial.
        self._field_inits: dict[str, list] = {}

    # ======================================================================
    # Emisión
    # ======================================================================
    def emit(
        self,
        op: Op,
        arg1: Optional[Operand] = None,
        arg2: Optional[Operand] = None,
        result: Optional[Operand] = None,
        *,
        operator: str = "",
        comment: str = "",
        line: int = 0,
    ) -> Quadruple:
        quad = Quadruple(op, arg1, arg2, result, operator, comment if self.with_comments else "", line)
        return self.program.append(quad)

    def comment(self, text: str) -> None:
        if self.with_comments:
            self.emit(Op.COMMENT, comment=text)

    def label(self, name: str) -> None:
        self.emit(Op.LABEL, Operand.label(name))

    def goto(self, name: str) -> None:
        self.emit(Op.GOTO, Operand.label(name))

    # -- atajos frecuentes ---------------------------------------------------
    def _assign(self, target: Operand, source: Operand, comment: str = "") -> None:
        self.emit(Op.ASSIGN, source, result=target, comment=comment)

    def _binary(self, operator: str, left: Operand, right: Operand, type_: Type) -> Operand:
        """``t = left op right`` reciclando los operandos consumidos."""
        self.temps.free(left)
        self.temps.free(right)
        result = self.temps.alloc(type_)
        self.emit(Op.BINARY, left, right, result, operator=operator)
        return result

    def _call(
        self,
        target: str,
        args: list[Operand],
        *,
        result_type: Optional[Type] = None,
        comment: str = "",
        indirect: Optional[Operand] = None,
        free_args: bool = True,
    ) -> Optional[Operand]:
        """Emite ``param`` por cada argumento y la llamada."""
        for arg in args:
            self.emit(Op.PARAM, arg)
        if free_args:
            for arg in args:
                self.temps.free(arg)

        result = self.temps.alloc(result_type) if result_type is not None else None
        if indirect is not None:
            self.temps.free(indirect)
            self.emit(
                Op.CALL_INDIRECT, indirect, Operand.const(len(args)), result, comment=comment
            )
        else:
            self.emit(Op.CALL, Operand.func(target), Operand.const(len(args)), result, comment=comment)
        return result

    # ======================================================================
    # Punto de entrada
    # ======================================================================
    def generate(self, tree: P.ProgramContext) -> TACProgram:
        self._index_symbols()

        statements = list(tree.statement() or [])
        self._collect_declarations(statements)

        # --- programa principal ---------------------------------------------
        self.comment("=" * 62)
        self.comment("Compiscript - codigo intermedio de tres direcciones")
        self.comment("=" * 62)
        self.comment("programa principal")

        self.temps.reset()
        begin = self.emit(Op.FUNC_BEGIN, Operand.func(MAIN_LABEL), Operand.const(0))
        inicio = len(self.program) - 1

        self._emit_vtables()
        for statement in statements:
            self.visit(statement)

        self.emit(Op.RETURN)
        self.emit(Op.FUNC_END, Operand.func(MAIN_LABEL))
        begin.arg2 = Operand.const(self.temps.peak * WORD_SIZE)
        self.program.functions.append(
            TACFunction(
                name=MAIN_LABEL,
                label=MAIN_LABEL,
                start=inicio,
                end=len(self.program) - 1,
                temp_count=self.temps.peak,
                frame_size=self.temps.peak * WORD_SIZE,
            )
        )

        # --- rutinas -----------------------------------------------------------
        while self._pending:
            ctx, symbol = self._pending.pop(0)
            self._emit_function(ctx, symbol)

        for klass in self._classes:
            if self._has_field_inits(klass):
                self._emit_field_initializer(klass)

        self.program.temps_peak = max(
            (f.temp_count for f in self.program.functions), default=0
        )
        self.program.temps_created = sum(f.temp_count for f in self.program.functions)
        return self.program

    def _index_symbols(self) -> None:
        """Anota qué función declara cada símbolo (para detectar capturas)."""
        for scope in self.table.all_scopes():
            owner = scope.enclosing_function()
            for symbol in scope.symbols.values():
                self._owner_of[id(symbol)] = owner

    def _collect_declarations(self, statements) -> None:
        """Encola las rutinas y recopila los inicializadores de atributos.

        Las clases se toman del recolector, que las tiene **todas**, incluidas
        las declaradas dentro de un bloque; recorrer solo las sentencias de
        nivel superior se dejaria fuera esas.
        """
        for klass_ctx, klass in self.collector.class_by_ctx.items():
            self._classes.append(klass)
            iniciales: list = []
            for member in klass_ctx.classMember():
                func_ctx = member.functionDeclaration()
                if func_ctx is not None:
                    method = self.collector.function_by_ctx.get(func_ctx)
                    if method is not None:
                        self._pending.append((func_ctx, method))
                    continue

                var_ctx = member.variableDeclaration()
                const_ctx = member.constantDeclaration()
                destino = var_ctx if var_ctx is not None else const_ctx
                if destino is None:
                    continue
                campo = klass.fields.get(destino.Identifier().getText())
                if var_ctx is not None:
                    init = var_ctx.initializer()
                    expr = init.expression() if init is not None else None
                else:
                    expr = const_ctx.expression()
                if campo is not None and expr is not None:
                    iniciales.append((campo, expr))
            if iniciales:
                self._field_inits[klass.name] = iniciales

        for statement in statements:
            func_ctx = statement.functionDeclaration()
            if func_ctx is not None:
                symbol = self.collector.function_by_ctx.get(func_ctx)
                if symbol is not None and all(s is not symbol for _, s in self._pending):
                    self._pending.append((func_ctx, symbol))

    def _has_field_inits(self, klass: Optional[ClassSymbol]) -> bool:
        """¿La clase o alguna de sus superclases inicializa algún atributo?"""
        while klass is not None:
            if self._field_inits.get(klass.name):
                return True
            klass = klass.superclass
        return False

    @staticmethod
    def _field_init_label(klass: ClassSymbol) -> str:
        return f"{klass.name}_initfields"

    def _emit_vtables(self) -> None:
        """Reserva y rellena la tabla de métodos de cada clase.

        Cada clase tiene un bloque con una ranura por método. Una subclase
        hereda las ranuras de su superclase y sólo sobrescribe las que
        redefine, de modo que la misma ranura significa siempre el mismo
        método: eso es lo que permite el despacho dinámico.
        """
        if not self._classes:
            return
        self.comment("tablas de metodos (despacho dinamico)")
        for klass in self._classes:
            self.program.vtables[klass.name] = klass.vtable_label
            ranuras = len(klass.vtable_slots)
            tabla = Operand.special(klass.vtable_label, klass.class_type)
            self._call(
                rt.ALLOC.name,
                [Operand.const(max(ranuras, 1) * WORD_SIZE, INTEGER)],
                result_type=None,
                comment=f"tabla de {klass.name}",
            )
            # __alloc devuelve el puntero: lo recogemos en la variable global
            # que nombra la tabla.
            self.program.instructions[-1].result = tabla
            for metodo, ranura in sorted(klass.vtable_slots.items(), key=lambda kv: kv[1]):
                etiqueta = klass.vtable[metodo]
                self.emit(
                    Op.INDEX_STORE,
                    Operand.const(ranura),
                    Operand.func(etiqueta),
                    tabla,
                    comment=f"{klass.name}.{metodo}",
                )

    # ======================================================================
    # Rutinas
    # ======================================================================
    def _emit_function(self, ctx: P.FunctionDeclarationContext, symbol: FunctionSymbol) -> None:
        etiqueta = symbol.label or f"func_{symbol.name}"
        owner = symbol.owner

        self.comment("-" * 62)
        self.comment(
            f"{'metodo' if owner else 'funcion'} {symbol.signature}"
            + (f"   (clase {owner})" if owner else "")
        )

        anterior_fn = self.current_function
        anteriores_break = self.break_labels
        anteriores_continue = self.continue_labels
        self.current_function = symbol
        self.break_labels = []
        self.continue_labels = []
        self.temps.reset()

        if owner is not None:
            klass = self._class_named(owner)
            if klass is not None:
                self.class_stack.append(klass)

        begin = self.emit(Op.FUNC_BEGIN, Operand.func(etiqueta), Operand.const(0))
        inicio = len(self.program) - 1

        for statement in ctx.block().statement() or []:
            self.visit(statement)

        # Toda rutina termina con 'return', aunque el usuario no lo escriba.
        if self.program.instructions[-1].op is not Op.RETURN:
            self.emit(Op.RETURN, comment="retorno implicito")
        self.emit(Op.FUNC_END, Operand.func(etiqueta))

        # Retroparcheo: el tamaño del marco sólo se conoce al terminar el
        # cuerpo, porque depende de cuántos temporales hicieron falta.
        registro = ActivationRecord(
            function=symbol.name,
            label=etiqueta,
            param_size=symbol.param_size,
            local_size=symbol.frame_size,
            temp_count=self.temps.peak,
            nesting_level=symbol.nesting_level,
            needs_access_link=symbol.nesting_level > 0,
        )
        symbol.activation_record = registro
        symbol.temp_count = self.temps.peak
        begin.arg2 = Operand.const(registro.size)

        self.program.functions.append(
            TACFunction(
                name=symbol.name,
                label=etiqueta,
                symbol=symbol,
                start=inicio,
                end=len(self.program) - 1,
                temp_count=self.temps.peak,
                param_size=symbol.param_size,
                local_size=symbol.frame_size,
                frame_size=registro.size,
                is_method=owner is not None,
                owner=owner,
            )
        )

        if owner is not None and self.class_stack:
            self.class_stack.pop()
        self.current_function = anterior_fn
        self.break_labels = anteriores_break
        self.continue_labels = anteriores_continue

    def _emit_field_initializer(self, klass: ClassSymbol) -> None:
        """Rutina que da su valor inicial a los atributos de una instancia.

        Se emite aparte del constructor por dos motivos: una clase puede tener
        atributos con valor inicial y **no** declarar constructor, y los
        atributos heredados deben inicializarse antes que los propios, lo que
        se consigue encadenando con la rutina de la superclase.
        """
        etiqueta = self._field_init_label(klass)
        self.comment("-" * 62)
        self.comment(f"valores iniciales de los atributos de {klass.name}")

        anterior_fn = self.current_function
        self.current_function = None
        self.class_stack.append(klass)
        self.temps.reset()

        begin = self.emit(Op.FUNC_BEGIN, Operand.func(etiqueta), Operand.const(0))
        inicio = len(self.program) - 1

        if klass.superclass is not None and self._has_field_inits(klass.superclass):
            self.emit(Op.PARAM, Operand.special("this"), comment="this")
            self.emit(
                Op.CALL,
                Operand.func(self._field_init_label(klass.superclass)),
                Operand.const(1),
                comment=f"primero los heredados de {klass.superclass.name}",
            )

        for campo, expr in self._field_inits.get(klass.name, []):
            valor = self.visit(expr)
            self.emit(
                Op.INDEX_STORE,
                Operand.const(campo.offset or 0),
                valor,
                Operand.special("this"),
                comment=f".{campo.name}",
            )
            self.temps.free(valor)

        self.emit(Op.RETURN)
        self.emit(Op.FUNC_END, Operand.func(etiqueta))
        begin.arg2 = Operand.const(self.temps.peak * WORD_SIZE)

        self.program.functions.append(
            TACFunction(
                name=etiqueta,
                label=etiqueta,
                start=inicio,
                end=len(self.program) - 1,
                temp_count=self.temps.peak,
                frame_size=self.temps.peak * WORD_SIZE,
                is_method=True,
                owner=klass.name,
            )
        )
        self.class_stack.pop()
        self.current_function = anterior_fn

    def _class_named(self, name: str) -> Optional[ClassSymbol]:
        for klass in self._classes:
            if klass.name == name:
                return klass
        found = self.table.global_scope.resolve_local(name)
        return found if isinstance(found, ClassSymbol) else None

    # ======================================================================
    # Direccionamiento de los símbolos
    # ======================================================================
    @staticmethod
    def frame_offset(symbol: Symbol) -> int:
        """Desplazamiento de ``symbol`` respecto del puntero de marco."""
        if symbol.storage is StorageKind.PARAM:
            return PARAM_BASE_OFFSET + (symbol.offset or 0)
        return LOCAL_BASE_OFFSET - (symbol.offset or 0)

    def operand_of(self, symbol: Symbol) -> Operand:
        """Operando que designa a ``symbol`` desde la rutina actual.

        Si la variable pertenece a una función exterior (un *closure*), no se
        puede nombrar directamente: hay que llegar a su marco subiendo por los
        enlaces de acceso.
        """
        owner = self._owner_of.get(id(symbol))
        if (
            symbol.storage is StorageKind.GLOBAL
            or owner is None
            or owner is self.current_function
        ):
            return Operand.var(symbol)

        frame = self._walk_access_links(owner)
        destino = self.temps.alloc(symbol.type)
        self.emit(
            Op.INDEX_LOAD,
            frame,
            Operand.const(self.frame_offset(symbol)),
            destino,
            comment=f"{symbol.name} (capturada de {owner.name})",
        )
        self.temps.free(frame)
        return destino

    def store_into(self, symbol: Symbol, value: Operand) -> None:
        """Guarda ``value`` en ``symbol``, atravesando closures si hace falta."""
        owner = self._owner_of.get(id(symbol))
        if (
            symbol.storage is StorageKind.GLOBAL
            or owner is None
            or owner is self.current_function
        ):
            self._assign(Operand.var(symbol), value)
            return

        frame = self._walk_access_links(owner)
        self.emit(
            Op.INDEX_STORE,
            Operand.const(self.frame_offset(symbol)),
            value,
            frame,
            comment=f"{symbol.name} (capturada de {owner.name})",
        )
        self.temps.free(frame)

    def _walk_access_links(self, target: FunctionSymbol) -> Operand:
        """Sube por los enlaces de acceso hasta el marco de ``target``."""
        niveles = 1
        if self.current_function is not None:
            niveles = max(1, self.current_function.nesting_level - target.nesting_level)

        frame = self.temps.alloc()
        self.emit(
            Op.INDEX_LOAD,
            Operand.special("fp"),
            Operand.const(ACCESS_LINK_OFFSET),
            frame,
            comment=f"marco de {target.name}",
        )
        for _ in range(niveles - 1):
            self.emit(Op.INDEX_LOAD, frame, Operand.const(ACCESS_LINK_OFFSET), frame)
        return frame

    # ======================================================================
    # Utilidades sobre el árbol
    # ======================================================================
    @staticmethod
    def _significant(node):
        """Desciende por la cadena de precedencia hasta el nodo operativo."""
        while True:
            if isinstance(node, P.PrimaryExprContext) and node.expression() is not None:
                node = node.expression()
                continue
            if not isinstance(node, ParserRuleContext) or node.getChildCount() != 1:
                return node
            child = node.getChild(0)
            if not isinstance(child, ParserRuleContext):
                return node
            node = child

    def type_of(self, ctx) -> Type:
        """Tipo estático que el análisis semántico dedujo para ``ctx``."""
        node = ctx
        while node is not None:
            if node in self.ann.types:
                return self.ann.types[node]
            if node in self.ann.lvalues:
                return self.ann.lvalues[node].type
            if isinstance(node, P.PrimaryExprContext) and node.expression() is not None:
                node = node.expression()
                continue
            if (
                isinstance(node, ParserRuleContext)
                and node.getChildCount() == 1
                and isinstance(node.getChild(0), ParserRuleContext)
            ):
                node = node.getChild(0)
                continue
            return ERROR
        return ERROR

    @staticmethod
    def element_size(array_type: Type) -> int:
        return array_type.element.size if isinstance(array_type, ArrayType) else WORD_SIZE

    # ======================================================================
    # Sentencias
    # ======================================================================
    def visitBlock(self, ctx: P.BlockContext):
        for statement in ctx.statement() or []:
            self.visit(statement)
        return None

    def visitVariableDeclaration(self, ctx: P.VariableDeclarationContext):
        symbol = self.ann.symbols.get(ctx)
        if symbol is None:
            return None
        init = ctx.initializer()
        if init is not None:
            value = self.visit(init.expression())
            self.store_into(symbol, value)
            self.temps.free(value)
        else:
            # Sin inicializador la variable arranca con el valor neutro de su
            # tipo: asi el codigo generado nunca lee memoria indeterminada.
            self.store_into(symbol, self._default_value(symbol.type))
        return None

    def visitConstantDeclaration(self, ctx: P.ConstantDeclarationContext):
        symbol = self.ann.symbols.get(ctx)
        expr = ctx.expression()
        if symbol is None or expr is None:
            return None
        value = self.visit(expr)
        self.store_into(symbol, value)
        self.temps.free(value)
        return None

    @staticmethod
    def _default_value(type_: Type) -> Operand:
        if type_ is INTEGER:
            return Operand.const(0, INTEGER)
        if type_ is FLOAT:
            return Operand.const(0.0, FLOAT)
        if type_ is BOOLEAN:
            return Operand.const(False, BOOLEAN)
        return Operand.const(None, NULL)

    def visitAssignment(self, ctx: P.AssignmentContext):
        expressions = ctx.expression()
        if len(expressions) == 1:
            symbol = self.ann.symbols.get(ctx)
            value = self.visit(expressions[0])
            if symbol is not None:
                self.store_into(symbol, value)
            self.temps.free(value)
            return None

        # expresion '.' Identificador '=' expresion ';'
        obj = self.visit(expressions[0])
        value = self.visit(expressions[1])
        field = self.ann.symbols.get(ctx)
        if field is not None and obj is not None:
            self.emit(
                Op.INDEX_STORE,
                Operand.const(field.offset or 0),
                value,
                obj,
                comment=f".{field.name}",
            )
        self.temps.free(value)
        self.temps.free(obj)
        return None

    def visitExpressionStatement(self, ctx: P.ExpressionStatementContext):
        value = self.visit(ctx.expression())
        self.temps.free(value)
        return None

    def visitPrintStatement(self, ctx: P.PrintStatementContext):
        value = self.visit(ctx.expression())
        self._call(rt.PRINT.name, [value], comment="print")
        return None

    # --- condicionales ------------------------------------------------------
    def visitIfStatement(self, ctx: P.IfStatementContext):
        blocks = ctx.block()
        tiene_else = len(blocks) > 1
        etiqueta_else = self.labels.new("else") if tiene_else else None
        etiqueta_fin = self.labels.new("fin_if")

        self.gen_condition(ctx.expression(), None, etiqueta_else or etiqueta_fin)
        self.visit(blocks[0])
        if tiene_else:
            self.goto(etiqueta_fin)
            self.label(etiqueta_else)
            self.visit(blocks[1])
        self.label(etiqueta_fin)
        return None

    # --- bucles --------------------------------------------------------------
    def visitWhileStatement(self, ctx: P.WhileStatementContext):
        inicio = self.labels.new("while")
        fin = self.labels.new("fin_while")

        self.label(inicio)
        self.gen_condition(ctx.expression(), None, fin)
        self.break_labels.append(fin)
        self.continue_labels.append(inicio)
        self.visit(ctx.block())
        self.break_labels.pop()
        self.continue_labels.pop()
        self.goto(inicio)
        self.label(fin)
        return None

    def visitDoWhileStatement(self, ctx: P.DoWhileStatementContext):
        inicio = self.labels.new("do")
        condicion = self.labels.new("cond_do")
        fin = self.labels.new("fin_do")

        self.label(inicio)
        self.break_labels.append(fin)
        self.continue_labels.append(condicion)
        self.visit(ctx.block())
        self.break_labels.pop()
        self.continue_labels.pop()
        self.label(condicion)
        self.gen_condition(ctx.expression(), inicio, None)
        self.label(fin)
        return None

    def visitForStatement(self, ctx: P.ForStatementContext):
        init, condicion, actualizacion = self._split_for_header(ctx)
        inicio = self.labels.new("for")
        paso = self.labels.new("paso_for")
        fin = self.labels.new("fin_for")

        if init is not None:
            self.visit(init)
        self.label(inicio)
        if condicion is not None:
            self.gen_condition(condicion, None, fin)

        self.break_labels.append(fin)
        self.continue_labels.append(paso)
        self.visit(ctx.block())
        self.break_labels.pop()
        self.continue_labels.pop()

        self.label(paso)
        if actualizacion is not None:
            self.temps.free(self.visit(actualizacion))
        self.goto(inicio)
        self.label(fin)
        return None

    @staticmethod
    def _split_for_header(ctx: P.ForStatementContext):
        """Separa ``for (init; condicion; actualizacion)``; los tres opcionales."""
        children = list(ctx.getChildren())
        index = 2  # se saltan 'for' y '('
        init = None
        if isinstance(children[index], (P.VariableDeclarationContext, P.AssignmentContext)):
            init = children[index]
            index += 1
        else:
            index += 1
        condicion = None
        if isinstance(children[index], P.ExpressionContext):
            condicion = children[index]
            index += 1
        index += 1
        actualizacion = None
        if isinstance(children[index], P.ExpressionContext):
            actualizacion = children[index]
        return init, condicion, actualizacion

    def visitForeachStatement(self, ctx: P.ForeachStatementContext):
        symbol = self.ann.symbols.get(ctx)
        arreglo = self.visit(ctx.expression())
        tipo_arreglo = self.type_of(ctx.expression())
        tam = self.element_size(tipo_arreglo)

        longitud = self._call(
            rt.LENGTH.name, [arreglo], result_type=INTEGER, comment="longitud", free_args=False
        )
        indice = self.temps.alloc(INTEGER)
        self._assign(indice, Operand.const(0, INTEGER), comment="indice del recorrido")

        inicio = self.labels.new("foreach")
        paso = self.labels.new("paso_foreach")
        fin = self.labels.new("fin_foreach")

        self.label(inicio)
        self.emit(Op.IF_REL_GOTO, indice, longitud, Operand.label(fin), operator=">=")

        # elemento = arreglo[cabecera + indice * tam]
        desplazamiento = self.temps.alloc(INTEGER)
        self.emit(Op.BINARY, indice, Operand.const(tam, INTEGER), desplazamiento, operator="*")
        self.emit(
            Op.BINARY,
            desplazamiento,
            Operand.const(ARRAY_HEADER_SIZE, INTEGER),
            desplazamiento,
            operator="+",
        )
        elemento = self.temps.alloc(symbol.type if symbol else ERROR)
        self.emit(Op.INDEX_LOAD, arreglo, desplazamiento, elemento)
        self.temps.free(desplazamiento)
        if symbol is not None:
            self.store_into(symbol, elemento)
        self.temps.free(elemento)

        self.break_labels.append(fin)
        self.continue_labels.append(paso)
        self.visit(ctx.block())
        self.break_labels.pop()
        self.continue_labels.pop()

        self.label(paso)
        self.emit(Op.BINARY, indice, Operand.const(1, INTEGER), indice, operator="+")
        self.goto(inicio)
        self.label(fin)
        self.temps.free(indice)
        self.temps.free(longitud)
        self.temps.free(arreglo)
        return None

    # --- saltos ---------------------------------------------------------------
    def visitBreakStatement(self, ctx: P.BreakStatementContext):
        if self.break_labels:
            self.goto(self.break_labels[-1])
        return None

    def visitContinueStatement(self, ctx: P.ContinueStatementContext):
        if self.continue_labels:
            self.goto(self.continue_labels[-1])
        return None

    def visitReturnStatement(self, ctx: P.ReturnStatementContext):
        expr = ctx.expression()
        if expr is None:
            self.emit(Op.RETURN)
            return None
        value = self.visit(expr)
        self.emit(Op.RETURN, value)
        self.temps.free(value)
        return None

    # --- switch con cascada estilo C ------------------------------------------
    def visitSwitchStatement(self, ctx: P.SwitchStatementContext):
        sujeto = self.visit(ctx.expression())
        casos = list(ctx.switchCase())
        por_defecto = ctx.defaultCase()

        etiquetas = [self.labels.new("case") for _ in casos]
        etiqueta_defecto = self.labels.new("default") if por_defecto is not None else None
        fin = self.labels.new("fin_switch")

        # Tabla de comparaciones: se evalua cada 'case' en orden.
        for caso, etiqueta in zip(casos, etiquetas):
            valor = self.visit(caso.expression())
            self.emit(Op.IF_REL_GOTO, sujeto, valor, Operand.label(etiqueta), operator="==")
            self.temps.free(valor)
        self.goto(etiqueta_defecto or fin)
        self.temps.free(sujeto)

        # Los cuerpos van seguidos y SIN salto al final: sin 'break' la
        # ejecucion cae al siguiente caso (ver docs/CODIGO_INTERMEDIO.md).
        self.break_labels.append(fin)
        for caso, etiqueta in zip(casos, etiquetas):
            self.label(etiqueta)
            for statement in caso.statement() or []:
                self.visit(statement)
        if por_defecto is not None:
            self.label(etiqueta_defecto)
            for statement in por_defecto.statement() or []:
                self.visit(statement)
        self.break_labels.pop()
        self.label(fin)
        return None

    # --- try / catch ------------------------------------------------------------
    def visitTryCatchStatement(self, ctx: P.TryCatchStatementContext):
        blocks = ctx.block()
        manejador = self.labels.new("catch")
        fin = self.labels.new("fin_try")

        self.emit(Op.PUSH_HANDLER, Operand.label(manejador))
        self.visit(blocks[0])
        self.emit(Op.POP_HANDLER)
        self.goto(fin)

        self.label(manejador)
        symbol = self.ann.symbols.get(ctx)
        mensaje = self._call(
            rt.EXC_MESSAGE.name, [], result_type=STRING, comment="mensaje del error"
        )
        if symbol is not None and mensaje is not None:
            self.store_into(symbol, mensaje)
        self.temps.free(mensaje)
        self.visit(blocks[1])
        self.label(fin)
        return None

    # --- declaraciones que se emiten aparte --------------------------------------
    def visitFunctionDeclaration(self, ctx: P.FunctionDeclarationContext):
        """Una funcion anidada se encola: su codigo va despues del de su padre."""
        symbol = self.collector.function_by_ctx.get(ctx)
        if symbol is not None and all(s is not symbol for _, s in self._pending):
            self._pending.append((ctx, symbol))
        return None

    def visitClassDeclaration(self, ctx: P.ClassDeclarationContext):
        return None  # sus metodos ya se encolaron en _collect_declarations

    # ======================================================================
    # Condiciones: codigo por saltos
    # ======================================================================
    #: Comparacion contraria, para poder invertir un salto y ahorrarse un goto.
    _OPUESTO = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}

    def gen_condition(self, ctx, true_label: Optional[str], false_label: Optional[str]) -> None:
        """Traduce una condicion a saltos, sin materializar el booleano.

        Exactamente una de las dos etiquetas puede ser ``None``: significa que
        ese caso continua con la instruccion siguiente. Es el tratamiento
        clasico de los operadores logicos, y el que da el cortocircuito gratis.
        """
        node = self._significant(ctx)

        # --- a || b ---------------------------------------------------------
        if isinstance(node, P.LogicalOrExprContext) and len(node.logicalAndExpr()) > 1:
            operandos = node.logicalAndExpr()
            destino_true = true_label or self.labels.new("or_true")
            for operando in operandos[:-1]:
                self.gen_condition(operando, destino_true, None)
            self.gen_condition(operandos[-1], true_label, false_label)
            if true_label is None:
                self.label(destino_true)
            return

        # --- a && b ---------------------------------------------------------
        if isinstance(node, P.LogicalAndExprContext) and len(node.equalityExpr()) > 1:
            operandos = node.equalityExpr()
            destino_false = false_label or self.labels.new("and_false")
            for operando in operandos[:-1]:
                self.gen_condition(operando, None, destino_false)
            self.gen_condition(operandos[-1], true_label, false_label)
            if false_label is None:
                self.label(destino_false)
            return

        # --- !a : se intercambian los destinos --------------------------------
        if (
            isinstance(node, P.UnaryExprContext)
            and node.unaryExpr() is not None
            and node.getChild(0).getText() == "!"
        ):
            self.gen_condition(node.unaryExpr(), false_label, true_label)
            return

        # --- a relop b --------------------------------------------------------
        comparacion = self._as_comparison(node)
        if comparacion is not None:
            izquierdo_ctx, operador, derecho_ctx = comparacion
            izquierdo = self.visit(izquierdo_ctx)
            derecho = self.visit(derecho_ctx)
            if true_label is not None:
                self.emit(
                    Op.IF_REL_GOTO, izquierdo, derecho, Operand.label(true_label), operator=operador
                )
                if false_label is not None:
                    self.goto(false_label)
            else:
                self.emit(
                    Op.IF_REL_GOTO,
                    izquierdo,
                    derecho,
                    Operand.label(false_label),
                    operator=self._OPUESTO[operador],
                )
            self.temps.free(izquierdo)
            self.temps.free(derecho)
            return

        # --- cualquier otra expresion booleana ---------------------------------
        valor = self.visit(ctx)
        if true_label is not None:
            self.emit(Op.IF_GOTO, valor, Operand.label(true_label))
            if false_label is not None:
                self.goto(false_label)
        else:
            self.emit(Op.IFFALSE_GOTO, valor, Operand.label(false_label))
        self.temps.free(valor)

    def _as_comparison(self, node):
        """``(izquierdo, operador, derecho)`` si ``node`` es una comparacion simple."""
        if isinstance(node, P.EqualityExprContext) and len(node.relationalExpr()) == 2:
            return node.relationalExpr(0), node.getChild(1).getText(), node.relationalExpr(1)
        if isinstance(node, P.RelationalExprContext) and len(node.additiveExpr()) == 2:
            return node.additiveExpr(0), node.getChild(1).getText(), node.additiveExpr(1)
        return None

    # ======================================================================
    # Expresiones
    # ======================================================================
    def visitExpression(self, ctx: P.ExpressionContext):
        return self.visit(ctx.assignmentExpr())

    def visitExprNoAssign(self, ctx: P.ExprNoAssignContext):
        return self.visit(ctx.conditionalExpr())

    def visitAssignExpr(self, ctx: P.AssignExprContext):
        """``destino = valor`` usada como expresion."""
        valor = self.visit(ctx.assignmentExpr())
        self._store_left_hand_side(ctx.lhs, valor)
        return valor

    def visitPropertyAssignExpr(self, ctx: P.PropertyAssignExprContext):
        obj = self.visit(ctx.lhs)
        valor = self.visit(ctx.assignmentExpr())
        field = self.ann.symbols.get(ctx)
        if field is not None and obj is not None:
            self.emit(
                Op.INDEX_STORE,
                Operand.const(field.offset or 0),
                valor,
                obj,
                comment=f".{field.name}",
            )
        self.temps.free(obj)
        return valor

    def visitTernaryExpr(self, ctx: P.TernaryExprContext):
        ramas = ctx.expression()
        if not ramas:
            return self.visit(ctx.logicalOrExpr())

        falso = self.labels.new("ternario_no")
        fin = self.labels.new("fin_ternario")
        resultado = self.temps.alloc(self.type_of(ctx))

        self.gen_condition(ctx.logicalOrExpr(), None, falso)
        entonces = self.visit(ramas[0])
        self._assign(resultado, entonces)
        self.temps.free(entonces)
        self.goto(fin)
        self.label(falso)
        si_no = self.visit(ramas[1])
        self._assign(resultado, si_no)
        self.temps.free(si_no)
        self.label(fin)
        return resultado

    def visitLogicalOrExpr(self, ctx: P.LogicalOrExprContext):
        if len(ctx.logicalAndExpr()) == 1:
            return self.visit(ctx.logicalAndExpr(0))
        return self._materialize_condition(ctx)

    def visitLogicalAndExpr(self, ctx: P.LogicalAndExprContext):
        if len(ctx.equalityExpr()) == 1:
            return self.visit(ctx.equalityExpr(0))
        return self._materialize_condition(ctx)

    def _materialize_condition(self, ctx) -> Operand:
        """Convierte una condicion en un valor booleano concreto.

        Solo hace falta cuando el booleano se guarda o se pasa como argumento;
        dentro de un ``if`` o un ``while`` se usa ``gen_condition`` y no se
        materializa nada.
        """
        verdadero = self.labels.new("bool_si")
        fin = self.labels.new("fin_bool")
        resultado = self.temps.alloc(BOOLEAN)

        self.gen_condition(ctx, verdadero, None)
        self._assign(resultado, Operand.const(False, BOOLEAN))
        self.goto(fin)
        self.label(verdadero)
        self._assign(resultado, Operand.const(True, BOOLEAN))
        self.label(fin)
        return resultado

    def visitEqualityExpr(self, ctx: P.EqualityExprContext):
        return self._fold_binary(ctx, ctx.relationalExpr(), BOOLEAN)

    def visitRelationalExpr(self, ctx: P.RelationalExprContext):
        return self._fold_binary(ctx, ctx.additiveExpr(), BOOLEAN)

    def visitAdditiveExpr(self, ctx: P.AdditiveExprContext):
        return self._fold_binary(ctx, ctx.multiplicativeExpr(), None)

    def visitMultiplicativeExpr(self, ctx: P.MultiplicativeExprContext):
        return self._fold_binary(ctx, ctx.unaryExpr(), None)

    def _fold_binary(self, ctx, operandos, forced_type: Optional[Type]) -> Operand:
        """Pliega ``a op b op c`` de izquierda a derecha reciclando temporales."""
        if len(operandos) == 1:
            return self.visit(operandos[0])

        actual = self.visit(operandos[0])
        tipo_actual = actual.type or self.type_of(operandos[0])
        for indice in range(1, len(operandos)):
            operador = ctx.getChild(2 * indice - 1).getText()
            derecho = self.visit(operandos[indice])
            tipo_derecho = derecho.type or self.type_of(operandos[indice])

            if operador == "+" and (tipo_actual is STRING or tipo_derecho is STRING):
                actual = self._concat(actual, tipo_actual, derecho, tipo_derecho)
                tipo_actual = STRING
                continue

            resultado_tipo = forced_type or self._arith_type(tipo_actual, tipo_derecho)
            actual = self._binary(operador, actual, derecho, resultado_tipo)
            tipo_actual = resultado_tipo
        return actual

    @staticmethod
    def _arith_type(izquierdo: Optional[Type], derecho: Optional[Type]) -> Type:
        if izquierdo is FLOAT or derecho is FLOAT:
            return FLOAT
        return INTEGER

    def _concat(
        self, izquierdo: Operand, tipo_izq: Optional[Type], derecho: Operand, tipo_der: Optional[Type]
    ) -> Operand:
        """``a + b`` cuando alguno es cadena: conversion y llamada al runtime."""
        if tipo_izq is not STRING:
            izquierdo = self._call(
                rt.TO_STRING.name, [izquierdo], result_type=STRING, comment="a cadena"
            )
        if tipo_der is not STRING:
            derecho = self._call(rt.TO_STRING.name, [derecho], result_type=STRING, comment="a cadena")
        return self._call(
            rt.CONCAT.name, [izquierdo, derecho], result_type=STRING, comment="concatenacion"
        )

    def visitUnaryExpr(self, ctx: P.UnaryExprContext):
        interno = ctx.unaryExpr()
        if interno is None:
            return self.visit(ctx.primaryExpr())

        operador = ctx.getChild(0).getText()
        if operador == "!":
            return self._materialize_condition(ctx)

        valor = self.visit(interno)
        tipo = valor.type or self.type_of(interno)
        self.temps.free(valor)
        resultado = self.temps.alloc(tipo)
        self.emit(Op.UNARY, valor, result=resultado, operator="-")
        return resultado

    def visitPrimaryExpr(self, ctx: P.PrimaryExprContext):
        if ctx.literalExpr() is not None:
            return self.visit(ctx.literalExpr())
        if ctx.leftHandSide() is not None:
            return self.visit(ctx.leftHandSide())
        return self.visit(ctx.expression())

    def visitLiteralExpr(self, ctx: P.LiteralExprContext):
        literal = ctx.Literal()
        if literal is not None:
            texto = literal.getText()
            if texto.startswith('"'):
                valor = texto[1:-1]
                clave = f"str_{len(self.program.strings)}"
                self.program.strings.setdefault(valor, clave)
                return Operand.const(valor, STRING)
            if "." in texto:
                return Operand.const(float(texto), FLOAT)
            return Operand.const(int(texto), INTEGER)
        if ctx.arrayLiteral() is not None:
            return self.visit(ctx.arrayLiteral())
        texto = ctx.getText()
        if texto == "null":
            return Operand.const(None, NULL)
        return Operand.const(texto == "true", BOOLEAN)

    def visitArrayLiteral(self, ctx: P.ArrayLiteralContext):
        elementos = list(ctx.expression() or [])
        tipo = self.type_of(ctx)
        tam = self.element_size(tipo)

        arreglo = self._call(
            rt.ARRAY_NEW.name,
            [Operand.const(len(elementos), INTEGER), Operand.const(tam, INTEGER)],
            result_type=tipo,
            comment=f"arreglo de {len(elementos)} elemento(s)",
        )
        for indice, elemento_ctx in enumerate(elementos):
            valor = self.visit(elemento_ctx)
            self.emit(
                Op.INDEX_STORE,
                Operand.const(ARRAY_HEADER_SIZE + indice * tam),
                valor,
                arreglo,
                comment=f"[{indice}]",
            )
            self.temps.free(valor)
        return arreglo

    # ======================================================================
    # leftHandSide: identificadores, llamadas, indices y propiedades
    # ======================================================================
    def visitLeftHandSide(self, ctx: P.LeftHandSideContext):
        cadena = self._gen_atom(ctx.primaryAtom())
        for suffix in ctx.suffixOp():
            cadena = self._gen_suffix(cadena, suffix)
        return cadena.operand if cadena.operand is not None else Operand.const(None, NULL)

    def _gen_atom(self, atom) -> "_Chain":
        info = self.ann.lvalues.get(atom)
        tipo = info.type if info is not None else ERROR

        if isinstance(atom, P.ThisExprContext):
            return _Chain(Operand.special("this", tipo), tipo)

        if isinstance(atom, P.NewExprContext):
            return self._gen_new(atom, info)

        symbol = info.symbol if info is not None else None
        if isinstance(symbol, FunctionSymbol):
            # Todavia no se emite nada: hara falta el sufijo de llamada.
            return _Chain(None, tipo, function=symbol)
        if symbol is not None:
            return _Chain(self.operand_of(symbol), tipo)
        return _Chain(Operand.const(None, NULL), tipo)

    def _gen_new(self, ctx: P.NewExprContext, info) -> "_Chain":
        """``new C(args)``: reservar, enlazar la tabla de metodos y construir."""
        klass = info.symbol if info is not None and isinstance(info.symbol, ClassSymbol) else None
        if klass is None:
            return _Chain(Operand.const(None, NULL), ERROR)

        tipo = klass.class_type or ERROR
        self.emit(Op.PARAM, Operand.const(klass.instance_size, INTEGER))
        objeto = self.temps.alloc(tipo)
        self.emit(
            Op.CALL,
            Operand.func(rt.ALLOC.name),
            Operand.const(1),
            objeto,
            comment=f"new {klass.name} ({klass.instance_size} bytes)",
        )
        self.emit(
            Op.INDEX_STORE,
            Operand.const(VTABLE_POINTER_OFFSET),
            Operand.special(klass.vtable_label),
            objeto,
            comment="enlaza su tabla de metodos",
        )

        if self._has_field_inits(klass):
            self.emit(Op.PARAM, objeto, comment="this")
            self.emit(
                Op.CALL,
                Operand.func(self._field_init_label(klass)),
                Operand.const(1),
                comment="valores iniciales de los atributos",
            )

        argumentos = self._gen_arguments(ctx.arguments())
        constructor = klass.constructor()
        if constructor is not None:
            self.emit(Op.PARAM, objeto, comment="this")
            for argumento in argumentos:
                self.emit(Op.PARAM, argumento)
            self.emit(
                Op.CALL,
                Operand.func(constructor.label or f"{klass.name}_constructor"),
                Operand.const(len(argumentos) + 1),
                comment=f"constructor de {klass.name}",
            )
        for argumento in argumentos:
            self.temps.free(argumento)
        return _Chain(objeto, tipo)

    def _gen_arguments(self, arguments_ctx) -> list[Operand]:
        if arguments_ctx is None:
            return []
        return [self.visit(expr) for expr in arguments_ctx.expression()]

    def _gen_suffix(self, cadena: "_Chain", suffix) -> "_Chain":
        if isinstance(suffix, P.CallExprContext):
            return self._gen_call(cadena, suffix)
        if isinstance(suffix, P.IndexExprContext):
            return self._gen_index(cadena, suffix)
        if isinstance(suffix, P.PropertyAccessExprContext):
            return self._gen_property(cadena, suffix)
        return _Chain(Operand.const(None, NULL), ERROR)  # pragma: no cover

    # --- llamadas -------------------------------------------------------------
    def _gen_call(self, cadena: "_Chain", suffix: P.CallExprContext) -> "_Chain":
        info = self.ann.lvalues.get(suffix)
        tipo_resultado = info.type if info is not None else ERROR
        devuelve = tipo_resultado is not VOID and not tipo_resultado.is_error
        argumentos = self._gen_arguments(suffix.arguments())

        # --- metodo: despacho por la tabla de metodos -----------------------
        if cadena.method is not None:
            return self._gen_dynamic_call(cadena, argumentos, tipo_resultado, devuelve)

        # --- funcion o metodo llamado por su nombre simple --------------------
        funcion = cadena.function
        if funcion is None:
            for argumento in argumentos:
                self.temps.free(argumento)
            return _Chain(Operand.const(None, NULL), tipo_resultado)

        if funcion.owner is not None:
            # Llamada a un metodo de la propia clase sin escribir 'this'.
            receptor = Operand.special("this", ERROR)
            return self._gen_dynamic_call(
                _Chain(None, tipo_resultado, receiver=receptor, method=funcion,
                       owner=self._static_class_of(funcion)),
                argumentos,
                tipo_resultado,
                devuelve,
            )

        if funcion.nesting_level > 0:
            self._emit_access_link(funcion)
        for argumento in argumentos:
            self.emit(Op.PARAM, argumento)
        for argumento in argumentos:
            self.temps.free(argumento)

        resultado = self.temps.alloc(tipo_resultado) if devuelve else None
        self.emit(
            Op.CALL,
            Operand.func(funcion.label or f"func_{funcion.name}"),
            Operand.const(len(argumentos)),
            resultado,
            comment=f"{funcion.name}()",
        )
        return _Chain(resultado, tipo_resultado)

    def _gen_dynamic_call(
        self, cadena: "_Chain", argumentos: list[Operand], tipo_resultado: Type, devuelve: bool
    ) -> "_Chain":
        """Llamada a metodo resuelta en ejecucion por la tabla de metodos."""
        metodo = cadena.method
        receptor = cadena.receiver or Operand.special("this", ERROR)
        ranura = self._vtable_slot(cadena.owner, metodo)

        tabla = self.temps.alloc()
        self.emit(
            Op.INDEX_LOAD,
            receptor,
            Operand.const(VTABLE_POINTER_OFFSET),
            tabla,
            comment="tabla de metodos del objeto",
        )
        destino = self.temps.alloc()
        self.emit(
            Op.INDEX_LOAD,
            tabla,
            Operand.const(ranura),
            destino,
            comment=f"ranura de {metodo.name}",
        )
        self.temps.free(tabla)

        self.emit(Op.PARAM, receptor, comment="this")
        for argumento in argumentos:
            self.emit(Op.PARAM, argumento)
        for argumento in argumentos:
            self.temps.free(argumento)

        resultado = self.temps.alloc(tipo_resultado) if devuelve else None
        self.temps.free(destino)
        self.emit(
            Op.CALL_INDIRECT,
            destino,
            Operand.const(len(argumentos) + 1),
            resultado,
            comment=f"{metodo.name}() por despacho dinamico",
        )
        self.temps.free(receptor)
        return _Chain(resultado, tipo_resultado)

    def _vtable_slot(self, owner: Optional[ClassType], metodo: FunctionSymbol) -> int:
        klass = None
        if owner is not None and getattr(owner, "symbol", None) is not None:
            klass = owner.symbol
        elif metodo.owner:
            klass = self._class_named(metodo.owner)
        if klass is None:
            return 0
        return klass.vtable_slots.get(metodo.name, 0)

    def _static_class_of(self, metodo: FunctionSymbol) -> Optional[ClassType]:
        klass = self._class_named(metodo.owner) if metodo.owner else None
        return klass.class_type if klass is not None else None

    def _emit_access_link(self, callee: FunctionSymbol) -> None:
        """Deja preparado el marco del padre lexico de la rutina llamada.

        Si la rutina llamada esta anidada justo dentro de la actual, su padre
        lexico es este mismo marco. Si esta mas arriba, hay que subir por los
        enlaces de acceso hasta encontrarlo.
        """
        nivel_actual = self.current_function.nesting_level if self.current_function else 0
        if callee.nesting_level > nivel_actual:
            self.emit(
                Op.SET_ACCESS_LINK,
                Operand.special("fp"),
                comment=f"padre lexico de {callee.name}",
            )
            return
        saltos = nivel_actual - callee.nesting_level + 1
        marco = self.temps.alloc()
        self.emit(Op.INDEX_LOAD, Operand.special("fp"), Operand.const(ACCESS_LINK_OFFSET), marco)
        for _ in range(saltos - 1):
            self.emit(Op.INDEX_LOAD, marco, Operand.const(ACCESS_LINK_OFFSET), marco)
        self.emit(Op.SET_ACCESS_LINK, marco, comment=f"padre lexico de {callee.name}")
        self.temps.free(marco)

    # --- indexacion -------------------------------------------------------------
    def _gen_index(self, cadena: "_Chain", suffix: P.IndexExprContext) -> "_Chain":
        base = cadena.operand
        indice = self.visit(suffix.expression())
        info = self.ann.lvalues.get(suffix)
        tipo_elemento = info.type if info is not None else ERROR

        desplazamiento = self._index_offset(base, indice, cadena.type)
        resultado = self.temps.alloc(tipo_elemento)
        self.emit(Op.INDEX_LOAD, base, desplazamiento, resultado)
        self.temps.free(desplazamiento)
        self.temps.free(base)
        return _Chain(resultado, tipo_elemento)

    def _index_offset(self, base: Operand, indice: Operand, tipo_arreglo: Type) -> Operand:
        """Comprueba el indice y calcula el desplazamiento en bytes."""
        if self.bounds_checks:
            self.emit(Op.PARAM, base)
            self.emit(Op.PARAM, indice)
            self.emit(
                Op.CALL,
                Operand.func(rt.CHECK_BOUNDS.name),
                Operand.const(2),
                comment="indice dentro del arreglo",
            )
        tam = self.element_size(tipo_arreglo)
        self.temps.free(indice)
        desplazamiento = self.temps.alloc(INTEGER)
        self.emit(Op.BINARY, indice, Operand.const(tam, INTEGER), desplazamiento, operator="*")
        self.emit(
            Op.BINARY,
            desplazamiento,
            Operand.const(ARRAY_HEADER_SIZE, INTEGER),
            desplazamiento,
            operator="+",
            comment="salta la cabecera",
        )
        return desplazamiento

    # --- acceso a miembros --------------------------------------------------------
    def _gen_property(self, cadena: "_Chain", suffix: P.PropertyAccessExprContext) -> "_Chain":
        info = self.ann.lvalues.get(suffix)
        symbol = info.symbol if info is not None else None
        tipo = info.type if info is not None else ERROR

        if isinstance(symbol, FunctionSymbol):
            # Un metodo no se carga: se deja pendiente para el sufijo de llamada.
            return _Chain(
                None,
                tipo,
                receiver=cadena.operand,
                method=symbol,
                owner=info.owner_class if info is not None else None,
            )

        base = cadena.operand
        resultado = self.temps.alloc(tipo)
        desplazamiento = symbol.offset if symbol is not None and symbol.offset is not None else 0
        self.emit(
            Op.INDEX_LOAD,
            base,
            Operand.const(desplazamiento),
            resultado,
            comment=f".{symbol.name}" if symbol is not None else "",
        )
        self.temps.free(base)
        return _Chain(resultado, tipo)

    # --- escritura sobre un leftHandSide ---------------------------------------------
    def _store_left_hand_side(self, ctx: P.LeftHandSideContext, valor: Operand) -> None:
        """Guarda ``valor`` en el destino que describe ``ctx``."""
        sufijos = list(ctx.suffixOp())

        if not sufijos:
            info = self.ann.lvalues.get(ctx.primaryAtom())
            if info is not None and info.symbol is not None:
                self.store_into(info.symbol, valor)
            return

        # Se recorre la cadena hasta el penultimo paso: eso deja la base.
        cadena = self._gen_atom(ctx.primaryAtom())
        for suffix in sufijos[:-1]:
            cadena = self._gen_suffix(cadena, suffix)

        ultimo = sufijos[-1]
        if isinstance(ultimo, P.IndexExprContext):
            indice = self.visit(ultimo.expression())
            desplazamiento = self._index_offset(cadena.operand, indice, cadena.type)
            self.emit(Op.INDEX_STORE, desplazamiento, valor, cadena.operand)
            self.temps.free(desplazamiento)
            self.temps.free(cadena.operand)
            return

        if isinstance(ultimo, P.PropertyAccessExprContext):
            info = self.ann.lvalues.get(ultimo)
            symbol = info.symbol if info is not None else None
            desplazamiento = symbol.offset if symbol is not None and symbol.offset is not None else 0
            self.emit(
                Op.INDEX_STORE,
                Operand.const(desplazamiento),
                valor,
                cadena.operand,
                comment=f".{symbol.name}" if symbol is not None else "",
            )
            self.temps.free(cadena.operand)


@dataclass
class _Chain:
    """Estado al recorrer un ``leftHandSide``.

    Un acceso como ``inventario[0].precio`` o ``perro.hablar()`` se traduce
    paso a paso. Entre paso y paso hay que arrastrar no solo el valor
    calculado, sino tambien el objeto receptor cuando lo siguiente es una
    llamada a metodo: ``obj.m()`` necesita ``obj`` para pasarlo como ``this``.
    """

    operand: Optional[Operand]
    type: Type
    receiver: Optional[Operand] = None
    method: Optional[FunctionSymbol] = None
    owner: Optional[ClassType] = None
    function: Optional[FunctionSymbol] = None


def generate_tac(
    tree,
    table: SymbolTable,
    annotations,
    collector,
    *,
    bounds_checks: bool = True,
    comments: bool = True,
) -> TACProgram:
    """Traduce un arbol ya analizado a codigo de tres direcciones."""
    generador = TACGenerator(
        table, annotations, collector, bounds_checks=bounds_checks, comments=comments
    )
    return generador.generate(tree)
