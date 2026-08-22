"""Símbolos de la tabla de símbolos de Compiscript.

Un **símbolo** es todo nombre que el programa declara: variables, constantes,
parámetros, funciones, métodos, clases y atributos.

Además de lo que necesita el análisis semántico (tipo, categoría, ubicación),
cada símbolo guarda desde ya la información que consumirán las fases
posteriores del compilador, tal como exige el requerimiento 5 del enunciado
("...almacenar toda la información necesaria para esta y futuras fases"):

============  =============================================================
Campo         Para qué sirve
============  =============================================================
``storage``   Dónde vive el dato: global, local, parámetro o atributo
``offset``    Desplazamiento en bytes dentro del área de datos o del
              registro de activación (fase de TAC / MIPS)
``size``      Bytes que ocupa
``label``     Etiqueta de ensamblador de una función o método
``captured``  El símbolo lo captura un closure; no puede vivir sólo en
              un registro
``frame_size`` Tamaño del registro de activación de una función
============  =============================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from .types import ClassType, FunctionType, Type

if TYPE_CHECKING:  # pragma: no cover
    from .scope import Scope


class SymbolCategory(str, Enum):
    """Qué clase de entidad nombra el símbolo."""

    VARIABLE = "variable"
    CONSTANT = "constante"
    PARAMETER = "parametro"
    FUNCTION = "funcion"
    METHOD = "metodo"
    CLASS = "clase"
    FIELD = "atributo"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class StorageKind(str, Enum):
    """Dónde reside físicamente el valor (información para TAC / MIPS)."""

    GLOBAL = "global"      # área de datos estática
    LOCAL = "local"        # registro de activación
    PARAM = "parametro"    # zona de parámetros del registro de activación
    FIELD = "atributo"     # dentro del objeto, en el heap
    CODE = "codigo"        # funciones y clases: viven en el segmento de código

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class Symbol:
    """Entrada base de la tabla de símbolos."""

    name: str
    category: SymbolCategory
    type: Type
    line: int = 0
    column: int = 0

    # --- estado del análisis semántico ------------------------------------
    initialized: bool = False
    used: bool = False
    scope_name: str = ""
    scope_id: int = 0

    # --- información para las fases posteriores ---------------------------
    storage: StorageKind = StorageKind.LOCAL
    offset: Optional[int] = None
    size: int = 0
    label: Optional[str] = None
    captured: bool = False

    def __post_init__(self) -> None:
        if not self.size:
            self.size = self.type.size

    @property
    def is_constant(self) -> bool:
        return self.category is SymbolCategory.CONSTANT

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category.value,
            "type": str(self.type),
            "line": self.line,
            "column": self.column,
            "scope": self.scope_name,
            "scopeId": self.scope_id,
            "initialized": self.initialized,
            "used": self.used,
            "storage": self.storage.value,
            "offset": self.offset,
            "size": self.size,
            "label": self.label,
            "captured": self.captured,
        }


@dataclass
class VariableSymbol(Symbol):
    """Variable, constante, parámetro o atributo de clase."""

    #: Sólo para atributos: clase que lo declara.
    owner: Optional[str] = None
    #: Longitud conocida en tiempo de compilación si se inicializó con un
    #: literal de arreglo. Permite avisar de índices constantes fuera de rango.
    array_length: Optional[int] = None


@dataclass
class FunctionSymbol(Symbol):
    """Función global, función anidada o método de clase."""

    params: list[VariableSymbol] = field(default_factory=list)
    return_type: Type = None  # type: ignore[assignment]
    #: Ámbito propio de la función (parámetros + cuerpo).
    body_scope: Optional["Scope"] = None
    #: Clase propietaria si es un método.
    owner: Optional[str] = None
    is_constructor: bool = False
    #: Se llama a sí misma (directa o mutuamente).
    is_recursive: bool = False
    #: Variables de ámbitos exteriores capturadas por este closure.
    captures: dict[str, Symbol] = field(default_factory=dict)
    #: Profundidad de anidamiento léxico (0 = global).
    nesting_level: int = 0
    #: Bytes de variables locales del registro de activación.
    frame_size: int = 0
    #: Bytes ocupados por los parámetros.
    param_size: int = 0

    @property
    def signature(self) -> str:
        params = ", ".join(f"{p.name}: {p.type}" for p in self.params)
        return f"{self.name}({params}): {self.return_type}"

    @property
    def function_type(self) -> FunctionType:
        return FunctionType(
            [p.type for p in self.params],
            self.return_type,
            param_names=[p.name for p in self.params],
        )

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(
            {
                "signature": self.signature,
                "params": [p.to_dict() for p in self.params],
                "returnType": str(self.return_type),
                "owner": self.owner,
                "isConstructor": self.is_constructor,
                "isRecursive": self.is_recursive,
                "captures": sorted(self.captures),
                "nestingLevel": self.nesting_level,
                "frameSize": self.frame_size,
                "paramSize": self.param_size,
            }
        )
        return d


@dataclass
class ClassSymbol(Symbol):
    """Clase declarada por el usuario."""

    class_type: Optional[ClassType] = None
    superclass: Optional["ClassSymbol"] = None
    #: Atributos propios en orden de declaración (define el layout).
    fields: dict[str, VariableSymbol] = field(default_factory=dict)
    #: Métodos propios.
    methods: dict[str, FunctionSymbol] = field(default_factory=dict)
    #: Ámbito propio de la clase (miembros).
    class_scope: Optional["Scope"] = None
    #: Bytes de una instancia, con los atributos heredados incluidos.
    instance_size: int = 0
    #: Etiquetas de los métodos, herencia resuelta (despacho dinámico).
    vtable: dict[str, str] = field(default_factory=dict)

    def lookup_field(self, name: str) -> Optional[VariableSymbol]:
        klass: Optional[ClassSymbol] = self
        while klass is not None:
            if name in klass.fields:
                return klass.fields[name]
            klass = klass.superclass
        return None

    def lookup_method(self, name: str) -> Optional[FunctionSymbol]:
        klass: Optional[ClassSymbol] = self
        while klass is not None:
            if name in klass.methods:
                return klass.methods[name]
            klass = klass.superclass
        return None

    def constructor(self) -> Optional[FunctionSymbol]:
        return self.lookup_method("constructor")

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(
            {
                "superclass": self.superclass.name if self.superclass else None,
                "fields": [f.to_dict() for f in self.fields.values()],
                "methods": [m.to_dict() for m in self.methods.values()],
                "instanceSize": self.instance_size,
                "vtable": self.vtable,
            }
        )
        return d
