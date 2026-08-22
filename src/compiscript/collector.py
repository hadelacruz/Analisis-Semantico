"""Primera pasada: recolección de declaraciones (*hoisting*).

Antes de comprobar los tipos de un bloque de sentencias, se registran en la
tabla de símbolos **las clases y funciones que ese bloque declara**. Gracias a
eso el siguiente programa es válido, aunque ``factorial`` se use antes de
aparecer y ``Dog`` herede de una clase declarada más abajo::

    print(factorial(5));
    function factorial(n: integer): integer { ... }

La pasada se ejecuta una vez por cada lista de sentencias (el programa, el
cuerpo de una función, un bloque, la rama de un ``case``...) justo después de
entrar en su ámbito.

Orden interno de la pasada
--------------------------
1. Declarar los **nombres** de todas las clases (permite referencias mutuas).
2. Enlazar cada clase con su superclase y detectar herencia cíclica.
3. Construir los miembros de las clases en orden topológico, para que una
   subclase vea siempre el layout ya calculado de su superclase.
4. Declarar las **firmas** de las funciones (sus cuerpos se revisan después).
"""
from __future__ import annotations

from typing import Iterable, Optional

from .diagnostics import ErrorReporter
from .generated.CompiscriptParser import CompiscriptParser as P
from .scope import Scope, ScopeKind, SymbolTable
from .symbols import (
    ClassSymbol,
    FunctionSymbol,
    StorageKind,
    SymbolCategory,
    VariableSymbol,
)
from .syntax import span, token_span
from .types import (
    ERROR,
    PRIMITIVE_BY_NAME,
    VOID,
    ArrayType,
    ClassType,
    Type,
    align,
)


class DeclarationCollector:
    """Registra clases y funciones de una lista de sentencias."""

    def __init__(self, table: SymbolTable, reporter: ErrorReporter) -> None:
        self.table = table
        self.reporter = reporter
        #: Nodo del árbol -> símbolo creado. El checker lo usa para volver al
        #: símbolo exacto de cada declaración (y no al primero con ese nombre,
        #: que sería el equivocado cuando hay declaraciones duplicadas).
        self.function_by_ctx: dict = {}
        self.class_by_ctx: dict = {}

    # ==================================================================
    # Resolución de anotaciones de tipo
    # ==================================================================
    def resolve_type(self, ctx: Optional[P.TypeContext]) -> Type:
        """Convierte una anotación ``: T`` del árbol en un objeto ``Type``."""
        if ctx is None:
            return ERROR
        base_ctx = ctx.baseType()
        name = base_ctx.getText()
        dims = (len(ctx.children) - 1) // 2

        resolved = PRIMITIVE_BY_NAME.get(name)
        if resolved is None:
            found = self.table.resolve(name)
            if found is not None and isinstance(found[0], ClassSymbol):
                found[0].used = True
                resolved = found[0].class_type
            else:
                line, col, eline, ecol = span(base_ctx)
                self.reporter.error(
                    "E110",
                    f"El tipo '{name}' no esta declarado.",
                    line, col, end_line=eline, end_column=ecol,
                )
                resolved = ERROR

        for _ in range(dims):
            resolved = ArrayType(resolved)
        return resolved

    # ==================================================================
    # Punto de entrada
    # ==================================================================
    def hoist(self, statements: Optional[Iterable]) -> None:
        """Declara las clases y funciones de ``statements`` en el ámbito actual."""
        if not statements:
            return

        class_ctxs: list[P.ClassDeclarationContext] = []
        func_ctxs: list[P.FunctionDeclarationContext] = []
        for stmt in statements:
            klass = stmt.classDeclaration()
            if klass is not None:
                class_ctxs.append(klass)
                continue
            func = stmt.functionDeclaration()
            if func is not None:
                func_ctxs.append(func)

        pending: list[tuple[P.ClassDeclarationContext, ClassSymbol]] = []
        for ctx in class_ctxs:
            symbol = self._declare_class_name(ctx)
            if symbol is not None:
                pending.append((ctx, symbol))

        for ctx, symbol in pending:
            self._link_superclass(ctx, symbol)
        for ctx, symbol in pending:
            self._break_inheritance_cycle(ctx, symbol)
        for ctx, symbol in self._in_inheritance_order(pending):
            self._build_class_members(ctx, symbol)

        for ctx in func_ctxs:
            self._declare_function(ctx, owner=None)

    # ==================================================================
    # Clases
    # ==================================================================
    def _declare_class_name(self, ctx: P.ClassDeclarationContext) -> Optional[ClassSymbol]:
        name_token = ctx.Identifier(0).getSymbol()
        name = name_token.text
        line, col, eline, ecol = token_span(name_token)

        if self.table.resolve_local(name) is not None:
            self.reporter.error(
                "E202",
                f"'{name}' ya esta declarado en este ambito.",
                line, col, end_line=eline, end_column=ecol,
            )
            return None

        class_type = ClassType(name)
        symbol = ClassSymbol(
            name=name,
            category=SymbolCategory.CLASS,
            type=class_type,
            line=line,
            column=col,
            class_type=class_type,
            initialized=True,
            label=f"class_{name}",
        )
        class_type.symbol = symbol
        self.table.declare(symbol)
        self.class_by_ctx[ctx] = symbol
        return symbol

    def _link_superclass(self, ctx: P.ClassDeclarationContext, symbol: ClassSymbol) -> None:
        identifiers = ctx.Identifier()
        if len(identifiers) < 2:
            return
        super_token = identifiers[1].getSymbol()
        super_name = super_token.text
        line, col, eline, ecol = token_span(super_token)

        found = self.table.resolve(super_name)
        if found is None or not isinstance(found[0], ClassSymbol):
            self.reporter.error(
                "E501",
                f"La clase base '{super_name}' no esta declarada.",
                line, col, end_line=eline, end_column=ecol,
            )
            return

        parent = found[0]
        parent.used = True
        symbol.superclass = parent
        if symbol.class_type is not None:
            symbol.class_type.superclass = parent.class_type

    def _break_inheritance_cycle(self, ctx: P.ClassDeclarationContext, symbol: ClassSymbol) -> None:
        seen: set[str] = set()
        current: Optional[ClassSymbol] = symbol
        while current is not None:
            if current.name in seen:
                line, col, eline, ecol = token_span(ctx.Identifier(0).getSymbol())
                self.reporter.error(
                    "E505",
                    f"Herencia ciclica detectada en la clase '{symbol.name}'.",
                    line, col, end_line=eline, end_column=ecol,
                )
                # Rompemos el ciclo para que el resto del analisis no cuelgue.
                symbol.superclass = None
                if symbol.class_type is not None:
                    symbol.class_type.superclass = None
                return
            seen.add(current.name)
            current = current.superclass

    @staticmethod
    def _in_inheritance_order(
        pending: list[tuple[P.ClassDeclarationContext, ClassSymbol]]
    ) -> list[tuple[P.ClassDeclarationContext, ClassSymbol]]:
        """Ordena las clases para que cada superclase se construya primero."""
        by_name = {symbol.name: (ctx, symbol) for ctx, symbol in pending}
        ordered: list[tuple[P.ClassDeclarationContext, ClassSymbol]] = []
        placed: set[str] = set()

        def place(name: str, guard: set[str]) -> None:
            if name in placed or name not in by_name or name in guard:
                return
            guard.add(name)
            ctx, symbol = by_name[name]
            if symbol.superclass is not None:
                place(symbol.superclass.name, guard)
            if name not in placed:
                placed.add(name)
                ordered.append((ctx, symbol))

        for _, symbol in pending:
            place(symbol.name, set())
        return ordered

    def _build_class_members(self, ctx: P.ClassDeclarationContext, symbol: ClassSymbol) -> None:
        line, _, _, _ = span(ctx)
        scope = self.table.push(ScopeKind.CLASS, f"clase {symbol.name}", owner=symbol, line=line)
        symbol.class_scope = scope

        # El layout de la instancia continua donde termina el de la superclase.
        offset = symbol.superclass.instance_size if symbol.superclass else 0
        if symbol.superclass is not None:
            symbol.vtable.update(symbol.superclass.vtable)

        for member in ctx.classMember():
            var_ctx = member.variableDeclaration()
            const_ctx = member.constantDeclaration()
            func_ctx = member.functionDeclaration()

            if var_ctx is not None:
                offset = self._declare_field(var_ctx, symbol, offset, is_const=False)
            elif const_ctx is not None:
                offset = self._declare_field(const_ctx, symbol, offset, is_const=True)
            elif func_ctx is not None:
                self._declare_function(func_ctx, owner=symbol)

        symbol.instance_size = offset
        if symbol.class_type is not None:
            symbol.class_type.instance_size = offset
        self.table.pop()

    def _declare_field(self, ctx, klass: ClassSymbol, offset: int, *, is_const: bool) -> int:
        name_token = ctx.Identifier().getSymbol()
        name = name_token.text
        line, col, eline, ecol = token_span(name_token)

        annotation = ctx.typeAnnotation()
        field_type = self.resolve_type(annotation.type_()) if annotation is not None else ERROR
        if annotation is None:
            self.reporter.error(
                "E112",
                f"El atributo '{name}' necesita una anotacion de tipo explicita.",
                line, col, end_line=eline, end_column=ecol,
            )

        if klass.lookup_field(name) is not None or klass.lookup_method(name) is not None:
            self.reporter.error(
                "E506",
                f"El miembro '{name}' ya existe en la clase '{klass.name}' "
                f"o en una de sus superclases.",
                line, col, end_line=eline, end_column=ecol,
            )
            return offset

        # Un atributo sin inicializador queda pendiente de que lo asigne el
        # constructor; las constantes deben venir siempre con valor.
        initialized = True if is_const else ctx.initializer() is not None

        symbol = VariableSymbol(
            name=name,
            category=SymbolCategory.CONSTANT if is_const else SymbolCategory.FIELD,
            type=field_type,
            line=line,
            column=col,
            owner=klass.name,
            initialized=initialized,
        )
        symbol.storage = StorageKind.FIELD
        symbol.offset = offset

        self.table.declare(symbol)
        klass.fields[name] = symbol
        if klass.class_type is not None:
            klass.class_type.fields[name] = field_type
        return align(offset + symbol.size)

    # ==================================================================
    # Funciones y métodos
    # ==================================================================
    def _declare_function(
        self, ctx: P.FunctionDeclarationContext, owner: Optional[ClassSymbol]
    ) -> Optional[FunctionSymbol]:
        name_token = ctx.Identifier().getSymbol()
        name = name_token.text
        line, col, eline, ecol = token_span(name_token)
        is_constructor = owner is not None and name == "constructor"

        # --- deteccion de duplicados -----------------------------------
        if owner is not None:
            if name in owner.methods or name in owner.fields:
                self.reporter.error(
                    "E506",
                    f"El miembro '{name}' ya esta declarado en la clase '{owner.name}'.",
                    line, col, end_line=eline, end_column=ecol,
                )
                return None
        else:
            existing = self.table.resolve_local(name)
            if existing is not None:
                code = "E306" if isinstance(existing, FunctionSymbol) else "E202"
                detail = (
                    f"La funcion '{name}' ya fue declarada en este ambito "
                    f"(linea {existing.line}); Compiscript no soporta sobrecarga."
                    if code == "E306"
                    else f"'{name}' ya esta declarado en este ambito."
                )
                self.reporter.error(code, detail, line, col, end_line=eline, end_column=ecol)
                return None

        # --- firma --------------------------------------------------------
        if is_constructor:
            return_type: Type = VOID          # el constructor nunca devuelve valor
        elif ctx.type_() is not None:
            return_type = self.resolve_type(ctx.type_())
        else:
            return_type = VOID                # sin ': T' la funcion es un procedimiento

        enclosing = self.table.current.enclosing_function()
        if owner is not None:
            label = f"{owner.name}_{name}"
        elif enclosing is not None and enclosing.label:
            label = f"{enclosing.label}__{name}"
        else:
            label = f"func_{name}"

        symbol = FunctionSymbol(
            name=name,
            category=SymbolCategory.METHOD if owner is not None else SymbolCategory.FUNCTION,
            type=ERROR,  # se reemplaza al final por el FunctionType real
            line=line,
            column=col,
            return_type=return_type,
            owner=owner.name if owner is not None else None,
            is_constructor=is_constructor,
            initialized=True,
            label=label,
            nesting_level=0 if enclosing is None else enclosing.nesting_level + 1,
        )

        self.table.declare(symbol)
        self.function_by_ctx[ctx] = symbol
        if owner is not None:
            owner.methods[name] = symbol
            owner.vtable[name] = label

        # --- ambito propio: parametros + cuerpo -----------------------------
        scope_name = f"metodo {owner.name}.{name}" if owner is not None else f"funcion {name}"
        scope: Scope = self.table.push(ScopeKind.FUNCTION, scope_name, owner=symbol, line=line)
        symbol.body_scope = scope
        self._declare_parameters(ctx, symbol)
        self.table.pop()

        symbol.type = symbol.function_type
        symbol.size = symbol.type.size
        if owner is not None and owner.class_type is not None:
            owner.class_type.methods[name] = symbol.function_type
        if owner is not None:
            self._check_override(symbol, owner, line, col, eline, ecol)
        return symbol

    def _declare_parameters(self, ctx: P.FunctionDeclarationContext, symbol: FunctionSymbol) -> None:
        params_ctx = ctx.parameters()
        if params_ctx is None:
            return
        for param in params_ctx.parameter():
            token = param.Identifier().getSymbol()
            pname = token.text
            line, col, eline, ecol = token_span(token)

            type_ctx = param.type_()
            if type_ctx is None:
                self.reporter.error(
                    "E310",
                    f"El parametro '{pname}' necesita una anotacion de tipo.",
                    line, col, end_line=eline, end_column=ecol,
                )
                ptype: Type = ERROR
            else:
                ptype = self.resolve_type(type_ctx)

            if self.table.resolve_local(pname) is not None:
                self.reporter.error(
                    "E307",
                    f"El parametro '{pname}' esta duplicado en la funcion '{symbol.name}'.",
                    line, col, end_line=eline, end_column=ecol,
                )
                continue

            psymbol = VariableSymbol(
                name=pname,
                category=SymbolCategory.PARAMETER,
                type=ptype,
                line=line,
                column=col,
                initialized=True,
            )
            self.table.declare(psymbol)
            symbol.params.append(psymbol)

    def _check_override(
        self, method: FunctionSymbol, owner: ClassSymbol, line: int, col: int, eline: int, ecol: int
    ) -> None:
        """Una sobrescritura debe conservar la firma del método heredado.

        El constructor queda excluido: no es un método polimórfico, cada clase
        declara el suyo con los parámetros que necesita (y si no lo declara,
        hereda el de su superclase).
        """
        if owner.superclass is None or method.is_constructor:
            return
        inherited = owner.superclass.lookup_method(method.name)
        if inherited is None:
            return
        if not method.function_type.equals(inherited.function_type):
            self.reporter.error(
                "E508",
                f"El metodo '{method.name}' sobrescribe al de '{inherited.owner}' con una "
                f"firma distinta: se esperaba '{inherited.signature}' y se declaro "
                f"'{method.signature}'.",
                line, col, end_line=eline, end_column=ecol,
            )
