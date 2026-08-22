"""Tabla de símbolos y manejo de entornos (ámbitos) de Compiscript.

Modelo
------
La tabla de símbolos es un **árbol de ámbitos** (`Scope`) encadenados por su
puntero ``parent``. Se crea un ámbito nuevo para:

* el programa completo (``GLOBAL``),
* cada función y método (``FUNCTION``): contiene parámetros y cuerpo,
* cada clase (``CLASS``): contiene atributos y métodos,
* cada bloque ``{ ... }``, incluidos los de ``if``/``while``/``for``/``foreach``
  y los cuerpos de ``try``/``catch`` (``BLOCK``).

La resolución de un nombre sube por la cadena de padres hasta el ámbito
global. Eso implementa a la vez el anidamiento de bloques, el sombreado
(*shadowing*) y la captura de variables por parte de los closures.

Asignación de memoria
---------------------
Los ámbitos de bloque **no** tienen marco propio: comparten el registro de
activación de la función que los contiene (su *frame owner*). Por eso los
desplazamientos se piden siempre al ámbito ``FUNCTION`` o ``GLOBAL`` más
cercano. Esa información la consumirán las fases de TAC y MIPS.
"""
from __future__ import annotations

import itertools
from enum import Enum
from typing import Iterator, Optional

from .symbols import ClassSymbol, FunctionSymbol, StorageKind, Symbol, SymbolCategory
from .types import align


class ScopeKind(str, Enum):
    GLOBAL = "global"
    FUNCTION = "funcion"
    CLASS = "clase"
    BLOCK = "bloque"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Scope:
    """Un entorno de símbolos."""

    _ids = itertools.count(0)

    def __init__(
        self,
        kind: ScopeKind,
        name: str,
        parent: Optional["Scope"] = None,
        owner: Optional[Symbol] = None,
    ) -> None:
        self.id: int = next(Scope._ids)
        self.kind = kind
        self.name = name
        self.parent = parent
        self.owner = owner
        self.children: list["Scope"] = []
        #: ``nombre -> Symbol`` en orden de declaración.
        self.symbols: dict[str, Symbol] = {}
        self.depth: int = 0 if parent is None else parent.depth + 1
        self.line: int = 0

        # Contadores de asignación de memoria (sólo GLOBAL y FUNCTION).
        self.next_local_offset: int = 0
        self.next_param_offset: int = 0

        if parent is not None:
            parent.children.append(self)

    # -- ámbitos especiales -------------------------------------------------
    def frame_owner(self) -> "Scope":
        """Ámbito ``FUNCTION`` o ``GLOBAL`` que posee el registro de activación."""
        scope: Scope = self
        while scope.kind not in (ScopeKind.FUNCTION, ScopeKind.GLOBAL):
            assert scope.parent is not None
            scope = scope.parent
        return scope

    def enclosing_function(self) -> Optional[FunctionSymbol]:
        """``FunctionSymbol`` de la función que contiene este ámbito."""
        scope: Optional[Scope] = self
        while scope is not None:
            if scope.kind is ScopeKind.FUNCTION and isinstance(scope.owner, FunctionSymbol):
                return scope.owner
            scope = scope.parent
        return None

    def enclosing_class(self) -> Optional[ClassSymbol]:
        """``ClassSymbol`` de la clase que contiene este ámbito, si la hay."""
        scope: Optional[Scope] = self
        while scope is not None:
            if scope.kind is ScopeKind.CLASS and isinstance(scope.owner, ClassSymbol):
                return scope.owner
            scope = scope.parent
        return None

    def enclosing_method(self) -> Optional[FunctionSymbol]:
        """Método de clase más cercano; ``None`` si no estamos dentro de uno.

        Es lo que decide si ``this`` es válido: una función anidada dentro de
        un método sigue estando dentro del método, pero una función global no.
        """
        scope: Optional[Scope] = self
        while scope is not None:
            if scope.kind is ScopeKind.FUNCTION and isinstance(scope.owner, FunctionSymbol):
                if scope.owner.owner is not None:
                    return scope.owner
            if scope.kind is ScopeKind.GLOBAL:
                return None
            scope = scope.parent
        return None

    @property
    def is_global(self) -> bool:
        return self.kind is ScopeKind.GLOBAL

    # -- declaración y resolución -------------------------------------------
    def declare(self, symbol: Symbol) -> bool:
        """Registra ``symbol``. Devuelve ``False`` si el nombre ya existe aquí."""
        if symbol.name in self.symbols:
            return False
        symbol.scope_name = self.name
        symbol.scope_id = self.id
        self.symbols[symbol.name] = symbol
        return True

    def resolve_local(self, name: str) -> Optional[Symbol]:
        """Busca ``name`` **sólo** en este ámbito."""
        return self.symbols.get(name)

    def resolve(self, name: str) -> Optional[tuple[Symbol, "Scope"]]:
        """Busca ``name`` aquí y en los ámbitos exteriores."""
        scope: Optional[Scope] = self
        while scope is not None:
            found = scope.symbols.get(name)
            if found is not None:
                return found, scope
            scope = scope.parent
        return None

    # -- utilidades ----------------------------------------------------------
    def walk(self) -> Iterator["Scope"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def path(self) -> str:
        parts: list[str] = []
        scope: Optional[Scope] = self
        while scope is not None:
            parts.append(scope.name)
            scope = scope.parent
        return " > ".join(reversed(parts))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "path": self.path(),
            "depth": self.depth,
            "line": self.line,
            "frameSize": self.next_local_offset,
            "paramSize": self.next_param_offset,
            "symbols": [s.to_dict() for s in self.symbols.values()],
            "children": [c.to_dict() for c in self.children],
        }

    def __repr__(self) -> str:  # pragma: no cover - depuración
        return f"<Scope #{self.id} {self.kind.value}:{self.name} n={len(self.symbols)}>"


class SymbolTable:
    """Fachada sobre el árbol de ámbitos.

    Mantiene el ámbito actual y se encarga de asignar el almacenamiento
    (``storage`` + ``offset``) de cada símbolo que se declara.
    """

    def __init__(self) -> None:
        Scope._ids = itertools.count(0)
        self.global_scope = Scope(ScopeKind.GLOBAL, "global")
        self.current: Scope = self.global_scope

    # -- pila de ámbitos ------------------------------------------------------
    def push(self, kind: ScopeKind, name: str, owner: Optional[Symbol] = None, line: int = 0) -> Scope:
        scope = Scope(kind, name, self.current, owner)
        scope.line = line
        self.current = scope
        return scope

    def enter(self, scope: Scope) -> Scope:
        """Vuelve a entrar en un ámbito ya creado (p. ej. el cuerpo de una
        función que se declaró durante la fase de *hoisting*)."""
        self.current = scope
        return scope

    def leave(self, scope: Scope) -> None:
        """Sale de un ámbito al que se entró con :meth:`enter`."""
        if scope.kind is ScopeKind.FUNCTION and isinstance(scope.owner, FunctionSymbol):
            scope.owner.frame_size = scope.next_local_offset
            scope.owner.param_size = scope.next_param_offset
        self.current = scope.parent or self.global_scope

    def pop(self) -> Scope:
        closed = self.current
        if closed.parent is not None:
            self.current = closed.parent
        # Propagamos el tamaño del marco a la función dueña.
        if closed.kind is ScopeKind.FUNCTION and isinstance(closed.owner, FunctionSymbol):
            closed.owner.frame_size = closed.next_local_offset
            closed.owner.param_size = closed.next_param_offset
        return closed

    # -- declaración -----------------------------------------------------------
    def declare(self, symbol: Symbol, scope: Optional[Scope] = None) -> bool:
        """Declara ``symbol`` y le asigna almacenamiento. ``False`` si ya existía."""
        target = scope or self.current
        if not target.declare(symbol):
            return False
        self._assign_storage(symbol, target)
        return True

    def _assign_storage(self, symbol: Symbol, scope: Scope) -> None:
        """Decide ``storage`` y ``offset``; información para TAC y MIPS."""
        if isinstance(symbol, (FunctionSymbol, ClassSymbol)):
            symbol.storage = StorageKind.CODE
            symbol.offset = None
            return

        if symbol.category is SymbolCategory.FIELD:
            # El offset dentro del objeto lo fija el layout de la clase.
            symbol.storage = StorageKind.FIELD
            return

        frame = scope.frame_owner()
        if symbol.category is SymbolCategory.PARAMETER:
            symbol.storage = StorageKind.PARAM
            symbol.offset = frame.next_param_offset
            frame.next_param_offset = align(frame.next_param_offset + symbol.size)
            return

        symbol.storage = StorageKind.GLOBAL if frame.is_global else StorageKind.LOCAL
        symbol.offset = frame.next_local_offset
        frame.next_local_offset = align(frame.next_local_offset + symbol.size)

    # -- resolución -------------------------------------------------------------
    def resolve(self, name: str) -> Optional[tuple[Symbol, Scope]]:
        return self.current.resolve(name)

    def resolve_local(self, name: str) -> Optional[Symbol]:
        return self.current.resolve_local(name)

    def resolve_with_capture(self, name: str) -> Optional[tuple[Symbol, Scope]]:
        """Resuelve ``name`` y registra la captura si cruza una frontera de función.

        Si el símbolo vive en el marco de una función *exterior* a la actual, la
        función actual (y toda función intermedia) lo captura: es un **closure**.
        Los globales, las funciones y las clases no se capturan porque no viven
        en un registro de activación.
        """
        found = self.resolve(name)
        if found is None:
            return None
        symbol, def_scope = found

        if isinstance(symbol, (FunctionSymbol, ClassSymbol)):
            return found
        if def_scope.frame_owner().is_global:
            return found

        owner_function = def_scope.enclosing_function()
        current_function = self.current.enclosing_function()
        if owner_function is None or current_function is None:
            return found
        if owner_function is current_function:
            return found

        # El nombre viene de una función exterior: marcamos la captura en la
        # función actual y en todas las intermedias hasta la definidora.
        symbol.captured = True
        scope: Optional[Scope] = self.current
        while scope is not None:
            fn = scope.enclosing_function()
            if fn is None or fn is owner_function:
                break
            fn.captures[name] = symbol
            scope = fn.body_scope.parent if fn.body_scope is not None else None
        return found

    # -- exportación --------------------------------------------------------------
    def all_scopes(self) -> list[Scope]:
        return list(self.global_scope.walk())

    def all_symbols(self) -> list[tuple[Scope, Symbol]]:
        out: list[tuple[Scope, Symbol]] = []
        for scope in self.all_scopes():
            for symbol in scope.symbols.values():
                out.append((scope, symbol))
        return out

    def to_dict(self) -> dict:
        return self.global_scope.to_dict()

    def to_text(self) -> str:
        """Renderiza la tabla como texto plano (salida del CLI)."""
        rows: list[tuple[str, ...]] = []
        header = ("AMBITO", "NOMBRE", "CATEGORIA", "TIPO", "LINEA", "ALMACEN", "OFFSET", "TAM", "INFO")
        for scope in self.all_scopes():
            for symbol in scope.symbols.values():
                notes: list[str] = []
                if symbol.captured:
                    notes.append("capturada")
                if isinstance(symbol, FunctionSymbol):
                    if symbol.is_recursive:
                        notes.append("recursiva")
                    if symbol.captures:
                        notes.append("closure[" + ",".join(sorted(symbol.captures)) + "]")
                    notes.append(f"marco={symbol.frame_size}B")
                if isinstance(symbol, ClassSymbol):
                    if symbol.superclass:
                        notes.append(f"hereda de {symbol.superclass.name}")
                    notes.append(f"instancia={symbol.instance_size}B")
                if not symbol.initialized and symbol.category in (
                    SymbolCategory.VARIABLE,
                    SymbolCategory.FIELD,
                ):
                    notes.append("sin inicializar")
                if not symbol.used and symbol.category is not SymbolCategory.CLASS:
                    notes.append("no usada")
                rows.append(
                    (
                        f"#{scope.id} {scope.name}",
                        symbol.name,
                        symbol.category.value,
                        str(symbol.type),
                        str(symbol.line),
                        symbol.storage.value,
                        "-" if symbol.offset is None else str(symbol.offset),
                        str(symbol.size),
                        ", ".join(notes),
                    )
                )

        if not rows:
            return "(tabla de simbolos vacia)"

        widths = [len(h) for h in header]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        def line(cells: tuple[str, ...]) -> str:
            return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

        sep = "  ".join("-" * w for w in widths)
        return "\n".join([line(header), sep, *(line(r) for r in rows)])
