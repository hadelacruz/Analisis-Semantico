"""Sistema de tipos de Compiscript.

Define la jerarquía de tipos y **todas** las reglas de compatibilidad que usa
el analizador semántico. Mantener estas reglas aquí (y no repartidas por el
visitor) es lo que permite testearlas de forma aislada.

Tipos soportados
----------------
* Primitivos: ``integer``, ``float``, ``string``, ``boolean``, ``null``, ``void``
* Compuestos: ``ArrayType`` (``T[]``), ``ClassType``, ``FunctionType``
* Centinela: ``ErrorType`` — se propaga silenciosamente para evitar cascadas
  de errores derivados de un único error real.

Tamaños
-------
Cada tipo conoce su ``size`` en bytes. Esa información no la necesita el
análisis semántico, pero sí la fase de generación de código intermedio (TAC)
y la de MIPS, y se almacena desde ya en la tabla de símbolos tal como pide el
requerimiento 5 del enunciado.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

#: Tamaño de una palabra en la arquitectura objetivo (MIPS de 32 bits).
WORD = 4


# ===========================================================================
# Jerarquía de tipos
# ===========================================================================

class Type:
    """Clase base de todos los tipos."""

    name: str = "<type>"
    size: int = WORD
    #: ``True`` si los valores se manejan por referencia (puntero).
    is_reference: bool = False

    # -- identidad ----------------------------------------------------------
    def equals(self, other: "Type") -> bool:
        # ErrorType es compatible con todo: corta las cascadas de errores.
        if self.is_error or other.is_error:
            return True
        return self is other or (type(self) is type(other) and self.name == other.name)

    # -- predicados ---------------------------------------------------------
    @property
    def is_error(self) -> bool:
        return isinstance(self, ErrorType)

    @property
    def is_numeric(self) -> bool:
        return self is INTEGER or self is FLOAT

    @property
    def is_void(self) -> bool:
        return self is VOID

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:  # pragma: no cover - depuración
        return f"<{self.__class__.__name__} {self.name}>"

    def to_dict(self) -> dict:
        return {"kind": self.__class__.__name__, "name": self.name, "size": self.size}


class PrimitiveType(Type):
    """Tipo primitivo indivisible (``integer``, ``string``, ...)."""

    def __init__(self, name: str, size: int, is_reference: bool = False) -> None:
        self.name = name
        self.size = size
        self.is_reference = is_reference


class ErrorType(Type):
    """Tipo centinela producido por una expresión mal formada.

    Es compatible con cualquier otro tipo en ambos sentidos, de modo que un
    único error real no genere veinte errores derivados aguas arriba.
    """

    name = "<error>"
    size = 0

    def equals(self, other: "Type") -> bool:
        return True


class ArrayType(Type):
    """Arreglo homogéneo ``T[]``. Se representa como puntero."""

    is_reference = True
    size = WORD

    def __init__(self, element: Type) -> None:
        self.element = element
        self.name = f"{element.name}[]"

    def equals(self, other: "Type") -> bool:
        if other.is_error:
            return True
        return isinstance(other, ArrayType) and self.element.equals(other.element)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["element"] = self.element.to_dict()
        return d


class FunctionType(Type):
    """Firma de una función: tipos de parámetros y tipo de retorno."""

    is_reference = True
    size = WORD

    def __init__(
        self,
        params: Sequence[Type],
        return_type: Type,
        *,
        param_names: Optional[Sequence[str]] = None,
    ) -> None:
        self.params: list[Type] = list(params)
        self.return_type = return_type
        self.param_names: list[str] = list(param_names or [])
        self.name = "(" + ", ".join(p.name for p in self.params) + ") -> " + return_type.name

    def equals(self, other: "Type") -> bool:
        if other.is_error:
            return True
        if not isinstance(other, FunctionType):
            return False
        if len(self.params) != len(other.params):
            return False
        if not self.return_type.equals(other.return_type):
            return False
        return all(a.equals(b) for a, b in zip(self.params, other.params))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["params"] = [p.to_dict() for p in self.params]
        d["returnType"] = self.return_type.to_dict()
        return d


class ClassType(Type):
    """Tipo de una instancia de clase. Se representa como puntero al heap."""

    is_reference = True
    size = WORD

    def __init__(self, name: str) -> None:
        self.name = name
        self.superclass: Optional[ClassType] = None
        #: ``nombre -> Type`` de los atributos **propios** (sin heredar).
        self.fields: dict[str, Type] = {}
        #: ``nombre -> FunctionType`` de los métodos **propios**.
        self.methods: dict[str, FunctionType] = {}
        #: Referencia al ``ClassSymbol`` correspondiente (evita import circular).
        self.symbol: Any = None
        #: Tamaño total de una instancia, con atributos heredados incluidos.
        self.instance_size: int = 0

    # -- resolución de miembros a lo largo de la cadena de herencia ---------
    def lookup_field(self, name: str) -> Optional[Type]:
        klass: Optional[ClassType] = self
        while klass is not None:
            if name in klass.fields:
                return klass.fields[name]
            klass = klass.superclass
        return None

    def lookup_method(self, name: str) -> Optional[FunctionType]:
        klass: Optional[ClassType] = self
        while klass is not None:
            if name in klass.methods:
                return klass.methods[name]
            klass = klass.superclass
        return None

    def lookup_member(self, name: str) -> Optional[Type]:
        return self.lookup_field(name) or self.lookup_method(name)

    def owner_of(self, name: str) -> Optional["ClassType"]:
        """Clase de la cadena de herencia que define realmente ``name``."""
        klass: Optional[ClassType] = self
        while klass is not None:
            if name in klass.fields or name in klass.methods:
                return klass
            klass = klass.superclass
        return None

    def all_field_names(self) -> list[str]:
        """Atributos heredados primero, luego los propios (orden de layout)."""
        base = self.superclass.all_field_names() if self.superclass else []
        return base + [f for f in self.fields if f not in base]

    def is_subclass_of(self, other: "ClassType") -> bool:
        klass: Optional[ClassType] = self
        while klass is not None:
            if klass.name == other.name:
                return True
            klass = klass.superclass
        return False

    def ancestors(self) -> list[str]:
        out: list[str] = []
        klass = self.superclass
        while klass is not None:
            out.append(klass.name)
            klass = klass.superclass
        return out

    def equals(self, other: "Type") -> bool:
        if other.is_error:
            return True
        return isinstance(other, ClassType) and self.name == other.name

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["superclass"] = self.superclass.name if self.superclass else None
        d["instanceSize"] = self.instance_size
        return d


# ===========================================================================
# Instancias singleton de los tipos primitivos
# ===========================================================================

INTEGER = PrimitiveType("integer", 4)
FLOAT = PrimitiveType("float", 8)
BOOLEAN = PrimitiveType("boolean", 1)
STRING = PrimitiveType("string", WORD, is_reference=True)
NULL = PrimitiveType("null", WORD, is_reference=True)
VOID = PrimitiveType("void", 0)
ERROR = ErrorType()

#: Nombres reservados de tipo que puede escribir el usuario en una anotación.
PRIMITIVE_BY_NAME: dict[str, Type] = {
    "integer": INTEGER,
    "float": FLOAT,
    "boolean": BOOLEAN,
    "string": STRING,
}


# ===========================================================================
# Reglas de compatibilidad
# ===========================================================================

def is_assignable(target: Type, source: Type) -> bool:
    """¿Puede almacenarse un valor de tipo ``source`` en un destino ``target``?

    Reglas:

    * ``ErrorType`` es compatible con todo (corta las cascadas de errores).
    * Identidad: ``T`` acepta ``T``.
    * Ensanchamiento numérico: ``float`` acepta ``integer`` (no al revés).
    * ``null`` es asignable a cualquier tipo por referencia
      (``string``, arreglos, clases, funciones).
    * Covarianza de clases: una subclase es asignable a su superclase.
    * Los arreglos son **invariantes**: ``integer[]`` no acepta ``float[]``.
    """
    if target.is_error or source.is_error:
        return True
    if target.equals(source):
        return True
    if target is FLOAT and source is INTEGER:
        return True
    if source is NULL and target.is_reference:
        return True
    if isinstance(target, ClassType) and isinstance(source, ClassType):
        return source.is_subclass_of(target)
    return False


def unify(a: Type, b: Type) -> Optional[Type]:
    """Tipo común más específico entre ``a`` y ``b``, o ``None`` si no existe.

    Se usa para inferir el tipo de un literal de arreglo y el de las ramas de
    un operador ternario.
    """
    if a.is_error:
        return b
    if b.is_error:
        return a
    if a.equals(b):
        return a
    # Ensanchamiento numérico
    if a.is_numeric and b.is_numeric:
        return FLOAT
    # null se absorbe en el tipo por referencia acompañante
    if a is NULL and b.is_reference:
        return b
    if b is NULL and a.is_reference:
        return a
    # Ancestro común entre clases
    if isinstance(a, ClassType) and isinstance(b, ClassType):
        klass: Optional[ClassType] = a
        while klass is not None:
            if b.is_subclass_of(klass):
                return klass
            klass = klass.superclass
    return None


def is_comparable(a: Type, b: Type) -> bool:
    """¿Se pueden comparar con ``==`` / ``!=``?"""
    if a.is_error or b.is_error:
        return True
    if a.is_numeric and b.is_numeric:
        return True
    if a is NULL or b is NULL:
        return (a is NULL and b is NULL) or a.is_reference or b.is_reference
    if isinstance(a, ClassType) and isinstance(b, ClassType):
        return a.is_subclass_of(b) or b.is_subclass_of(a)
    return a.equals(b)


def is_ordered(t: Type) -> bool:
    """¿Admite ``<``, ``<=``, ``>``, ``>=``?

    Se aceptan los numéricos y ``string`` (comparación lexicográfica).
    """
    return t.is_error or t.is_numeric or t is STRING


def arithmetic_result(op: str, left: Type, right: Type) -> Optional[Type]:
    """Tipo resultante de ``left op right``, o ``None`` si la operación es inválida.

    * ``+``  numérico + numérico -> numérico; si algún operando es ``string``
      y el otro es imprimible, la operación es una **concatenación**.
    * ``-``, ``*``, ``/``  exigen ambos operandos numéricos.
    * ``%``  exige ambos operandos ``integer``.
    """
    if left.is_error or right.is_error:
        return ERROR

    if op == "%":
        if left is INTEGER and right is INTEGER:
            return INTEGER
        return None

    if op == "+":
        if left is STRING or right is STRING:
            other = right if left is STRING else left
            if other is STRING or other.is_numeric or other is BOOLEAN:
                return STRING
            return None

    if left.is_numeric and right.is_numeric:
        return FLOAT if (left is FLOAT or right is FLOAT) else INTEGER

    return None


def size_of(t: Type) -> int:
    """Bytes que ocupa un valor de tipo ``t`` (dato para las fases de código)."""
    return t.size


def align(offset: int, boundary: int = WORD) -> int:
    """Alinea ``offset`` al siguiente múltiplo de ``boundary``."""
    if boundary <= 1:
        return offset
    remainder = offset % boundary
    return offset if remainder == 0 else offset + (boundary - remainder)
