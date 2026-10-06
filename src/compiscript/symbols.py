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

from .types import WORD, ClassType, FunctionType, Type

if TYPE_CHECKING:  # pragma: no cover
    from .scope import Scope


# ===========================================================================
# Registro de activación
# ===========================================================================
#
# Distribución del marco de una rutina. Los desplazamientos son relativos al
# puntero de marco ``fp``, que apunta al enlace de control:
#
#       direcciones altas
#       +-----------------------------+
#  +8+k | parámetro k                 |  los deja el llamador
#       | ...                         |
#  +4   | dirección de retorno        |
#   0   | enlace de control (fp ant.) |  <- fp
#  -4   | enlace de acceso (estático) |  <- permite los closures
#  -8-k | variable local k            |
#       | ...                         |
#       | temporales                  |  <- sp
#       +-----------------------------+
#       direcciones bajas
#
#: Desplazamiento del enlace de control (el ``fp`` del llamador).
CONTROL_LINK_OFFSET = 0
#: Desplazamiento de la dirección de retorno.
RETURN_ADDRESS_OFFSET = 4
#: Desplazamiento del enlace de acceso (marco del padre léxico).
ACCESS_LINK_OFFSET = -4
#: Primer parámetro.
PARAM_BASE_OFFSET = 8
#: Primera variable local.
LOCAL_BASE_OFFSET = -8
#: Tamaño de una palabra (se toma de ``types`` para no duplicar el valor).
WORD_SIZE = WORD


@dataclass
class ActivationRecord:
    """Descripción del marco de pila de una rutina.

    Es la información que la fase de generación de código necesita para emitir
    el prólogo y el epílogo de cada llamada, y lo que permite que las funciones
    anidadas encuentren las variables que capturan.
    """

    function: str
    label: str
    #: Bytes que ocupan los parámetros (los reserva el llamador).
    param_size: int = 0
    #: Bytes de las variables locales declaradas.
    local_size: int = 0
    #: Temporales simultáneos máximos que necesitó el generador.
    temp_count: int = 0
    #: Profundidad léxica: 0 para las rutinas globales.
    nesting_level: int = 0
    #: ``True`` si la rutina es anidada y por tanto necesita enlace de acceso.
    needs_access_link: bool = False

    @property
    def temp_size(self) -> int:
        return self.temp_count * WORD_SIZE

    @property
    def links_size(self) -> int:
        """Enlace de control + enlace de acceso."""
        return 2 * WORD_SIZE

    @property
    def size(self) -> int:
        """Bytes que el prólogo debe reservar (sin contar los parámetros)."""
        return self.links_size + self.local_size + self.temp_size

    def param_address(self, offset: int) -> str:
        return f"fp+{PARAM_BASE_OFFSET + offset}"

    def local_address(self, offset: int) -> str:
        return f"fp{LOCAL_BASE_OFFSET - offset}"

    def temp_address(self, index: int) -> str:
        return f"fp{LOCAL_BASE_OFFSET - self.local_size - index * WORD_SIZE}"

    def address_of(self, symbol: "Symbol") -> str:
        """Dirección simbólica de ``symbol`` dentro de este marco."""
        if symbol.offset is None:
            return "-"
        if symbol.storage is StorageKind.PARAM:
            return self.param_address(symbol.offset)
        if symbol.storage is StorageKind.LOCAL:
            return self.local_address(symbol.offset)
        if symbol.storage is StorageKind.GLOBAL:
            return f"global+{symbol.offset}"
        if symbol.storage is StorageKind.FIELD:
            return f"this+{symbol.offset}"
        return "-"

    def layout(self) -> list[dict]:
        """Distribución del marco, de la dirección más alta a la más baja."""
        filas = [
            {"offset": RETURN_ADDRESS_OFFSET, "nombre": "direccion de retorno", "tam": WORD_SIZE},
            {"offset": CONTROL_LINK_OFFSET, "nombre": "enlace de control (fp)", "tam": WORD_SIZE},
        ]
        if self.needs_access_link:
            filas.append(
                {"offset": ACCESS_LINK_OFFSET, "nombre": "enlace de acceso", "tam": WORD_SIZE}
            )
        if self.local_size:
            filas.append(
                {"offset": LOCAL_BASE_OFFSET, "nombre": "variables locales", "tam": self.local_size}
            )
        if self.temp_count:
            filas.append(
                {
                    "offset": LOCAL_BASE_OFFSET - self.local_size,
                    "nombre": f"temporales ({self.temp_count})",
                    "tam": self.temp_size,
                }
            )
        return filas

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "label": self.label,
            "paramSize": self.param_size,
            "localSize": self.local_size,
            "tempCount": self.temp_count,
            "tempSize": self.temp_size,
            "size": self.size,
            "nestingLevel": self.nesting_level,
            "needsAccessLink": self.needs_access_link,
            "layout": self.layout(),
        }


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

    # --- datos que añade la fase de código intermedio ----------------------
    #: Temporales simultáneos máximos que necesitó generar su cuerpo.
    temp_count: int = 0
    #: Distribución completa de su marco de pila.
    activation_record: Optional[ActivationRecord] = None

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
                "tempCount": self.temp_count,
                "activationRecord": (
                    self.activation_record.to_dict() if self.activation_record else None
                ),
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

    # --- datos que añade la fase de código intermedio ----------------------
    #: ``metodo -> ranura`` dentro de la tabla de métodos. Una subclase
    #: conserva las ranuras heredadas, que es lo que hace posible el despacho
    #: dinámico: la misma ranura significa el mismo método en toda la jerarquía.
    vtable_slots: dict[str, int] = field(default_factory=dict)
    #: Etiqueta del bloque de memoria que contiene la tabla de métodos.
    vtable_label: str = ""

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
                "vtableSlots": self.vtable_slots,
                "vtableLabel": self.vtable_label,
            }
        )
        return d
