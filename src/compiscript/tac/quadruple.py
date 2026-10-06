"""Representación del código de tres direcciones (TAC) de Compiscript.

Una **cuádrupla** es la unidad del código intermedio. Su nombre viene de que
guarda cuatro campos: ``(operador, argumento 1, argumento 2, resultado)``.
Toda instrucción del lenguaje intermedio encaja en esa forma::

    x = y + z        ->  (BINARY '+', y, z, x)
    goto L3          ->  (GOTO, L3, -, -)
    param a          ->  (PARAM, a, -, -)
    t0 = call f, 2   ->  (CALL, f, 2, t0)

Trabajar con objetos en vez de con cadenas de texto tiene tres ventajas:
el validador puede comprobar invariantes, la máquina virtual puede ejecutar
el programa, y la fase de MIPS podrá recorrer las instrucciones sin volver a
parsear nada. El texto se genera al final, sólo para mostrarlo.

Ver ``docs/CODIGO_INTERMEDIO.md`` para la descripción completa del lenguaje.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from ..symbols import FunctionSymbol, StorageKind, Symbol
from ..types import Type


# ===========================================================================
# Operadores
# ===========================================================================

class Op(str, Enum):
    """Repertorio de instrucciones del lenguaje intermedio."""

    # --- movimiento de datos ---------------------------------------------
    ASSIGN = "assign"              # x = y
    BINARY = "binary"              # x = y op z
    UNARY = "unary"                # x = op y
    INDEX_LOAD = "index_load"      # x = y[i]        i en bytes
    INDEX_STORE = "index_store"    # x[i] = y        i en bytes

    # --- control de flujo -------------------------------------------------
    LABEL = "label"                # label L
    GOTO = "goto"                  # goto L
    IF_GOTO = "if_goto"            # if x goto L
    IFFALSE_GOTO = "iffalse_goto"  # ifFalse x goto L
    IF_REL_GOTO = "if_rel_goto"    # if x relop y goto L

    # --- funciones ---------------------------------------------------------
    FUNC_BEGIN = "func_begin"      # begin_func etiqueta, tamaño_marco
    FUNC_END = "func_end"          # end_func etiqueta
    PARAM = "param"                # param x
    CALL = "call"                  # x = call f, n
    CALL_INDIRECT = "call_ind"     # x = call *t, n   (despacho por vtable)
    RETURN = "return"              # return [x]
    SET_ACCESS_LINK = "set_link"   # set_access_link x  (marco del padre lexico)

    # --- excepciones -------------------------------------------------------
    PUSH_HANDLER = "push_handler"  # push_handler L
    POP_HANDLER = "pop_handler"    # pop_handler

    # --- documentación -----------------------------------------------------
    COMMENT = "comment"            # ; texto

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Operadores binarios que admite ``Op.BINARY``.
BINARY_OPERATORS = {"+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "!="}
#: Operadores de comparación, los únicos válidos en ``Op.IF_REL_GOTO``.
RELATIONAL_OPERATORS = {"<", "<=", ">", ">=", "==", "!="}
#: Operadores unarios que admite ``Op.UNARY``.
UNARY_OPERATORS = {"-", "!"}


# ===========================================================================
# Operandos
# ===========================================================================

class OperandKind(str, Enum):
    """Qué clase de cosa es un operando."""

    TEMP = "temp"        # temporal generado por el compilador (t0, t1, ...)
    VAR = "var"          # variable del programa; lleva su símbolo
    CONST = "const"      # literal (integer, float, string, boolean, null)
    LABEL = "label"      # destino de un salto
    FUNC = "func"        # etiqueta de una rutina o de una vtable

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Operand:
    """Un argumento de una cuádrupla."""

    kind: OperandKind
    value: Any
    #: Sólo para ``VAR``: el símbolo de la tabla, que dice dónde vive el dato.
    symbol: Optional[Symbol] = None
    #: Tipo estático, cuando se conoce. Lo usará la fase de MIPS para elegir
    #: entre instrucciones enteras y de punto flotante.
    type: Optional[Type] = None

    # -- constructores cómodos ---------------------------------------------
    @staticmethod
    def temp(name: str, type_: Optional[Type] = None) -> "Operand":
        return Operand(OperandKind.TEMP, name, type=type_)

    @staticmethod
    def var(symbol: Symbol) -> "Operand":
        return Operand(OperandKind.VAR, symbol.name, symbol=symbol, type=symbol.type)

    @staticmethod
    def const(value: Any, type_: Optional[Type] = None) -> "Operand":
        return Operand(OperandKind.CONST, value, type=type_)

    @staticmethod
    def special(name: str, type_: Optional[Type] = None) -> "Operand":
        """Registro con nombre fijo del runtime: ``fp`` o ``this``."""
        return Operand(OperandKind.VAR, name, type=type_)

    @staticmethod
    def label(name: str) -> "Operand":
        return Operand(OperandKind.LABEL, name)

    @staticmethod
    def func(name: str) -> "Operand":
        return Operand(OperandKind.FUNC, name)

    # -- consultas ----------------------------------------------------------
    @property
    def is_temp(self) -> bool:
        return self.kind is OperandKind.TEMP

    @property
    def is_const(self) -> bool:
        return self.kind is OperandKind.CONST

    @property
    def storage(self) -> Optional[StorageKind]:
        return self.symbol.storage if self.symbol is not None else None

    def __str__(self) -> str:
        if self.kind is OperandKind.CONST:
            if self.value is None:
                return "null"
            if isinstance(self.value, bool):
                return "true" if self.value else "false"
            if isinstance(self.value, str):
                escaped = self.value.replace("\\", "\\\\").replace('"', '\\"')
                return f'"{escaped}"'
            return str(self.value)
        return str(self.value)


# ===========================================================================
# Cuádruplas
# ===========================================================================

@dataclass
class Quadruple:
    """Una instrucción del código intermedio."""

    op: Op
    arg1: Optional[Operand] = None
    arg2: Optional[Operand] = None
    result: Optional[Operand] = None
    #: Operador concreto de ``BINARY`` / ``UNARY`` / ``IF_REL_GOTO``.
    operator: str = ""
    #: Comentario que se imprime a la derecha; sólo documentación.
    comment: str = ""
    #: Línea del código fuente que originó la instrucción.
    line: int = 0

    def operands(self) -> list[Operand]:
        """Operandos que la instrucción **lee**."""
        leidos: list[Operand] = []
        for operand in (self.arg1, self.arg2):
            if operand is not None and operand.kind in (OperandKind.TEMP, OperandKind.VAR):
                leidos.append(operand)
        # En un almacén indexado el 'result' también se lee: es la base.
        if self.op is Op.INDEX_STORE and self.result is not None:
            leidos.append(self.result)
        return leidos

    def defines(self) -> Optional[Operand]:
        """Operando que la instrucción **escribe**, si escribe alguno."""
        if self.op in (
            Op.ASSIGN, Op.BINARY, Op.UNARY, Op.INDEX_LOAD, Op.CALL, Op.CALL_INDIRECT
        ):
            return self.result
        return None

    # -- representación textual ---------------------------------------------
    def text(self) -> str:
        """La instrucción en la sintaxis del lenguaje intermedio."""
        a1, a2, res = self.arg1, self.arg2, self.result

        if self.op is Op.COMMENT:
            return f"; {self.comment}"
        if self.op is Op.LABEL:
            return f"{a1}:"
        if self.op is Op.ASSIGN:
            return f"{res} = {a1}"
        if self.op is Op.BINARY:
            return f"{res} = {a1} {self.operator} {a2}"
        if self.op is Op.UNARY:
            return f"{res} = {self.operator}{a1}"
        if self.op is Op.INDEX_LOAD:
            return f"{res} = {a1}[{a2}]"
        if self.op is Op.INDEX_STORE:
            return f"{res}[{a1}] = {a2}"
        if self.op is Op.GOTO:
            return f"goto {a1}"
        if self.op is Op.IF_GOTO:
            return f"if {a1} goto {a2}"
        if self.op is Op.IFFALSE_GOTO:
            return f"ifFalse {a1} goto {a2}"
        if self.op is Op.IF_REL_GOTO:
            return f"if {a1} {self.operator} {a2} goto {res}"
        if self.op is Op.FUNC_BEGIN:
            return f"begin_func {a1}, marco={a2}"
        if self.op is Op.FUNC_END:
            return f"end_func {a1}"
        if self.op is Op.PARAM:
            return f"param {a1}"
        if self.op is Op.CALL:
            return f"{res} = call {a1}, {a2}" if res is not None else f"call {a1}, {a2}"
        if self.op is Op.CALL_INDIRECT:
            return f"{res} = call *{a1}, {a2}" if res is not None else f"call *{a1}, {a2}"
        if self.op is Op.SET_ACCESS_LINK:
            return f"set_access_link {a1}"
        if self.op is Op.RETURN:
            return f"return {a1}" if a1 is not None else "return"
        if self.op is Op.PUSH_HANDLER:
            return f"push_handler {a1}"
        if self.op is Op.POP_HANDLER:
            return "pop_handler"
        return f"<{self.op}>"  # pragma: no cover - defensivo

    def __str__(self) -> str:
        texto = self.text()
        if self.comment and self.op is not Op.COMMENT:
            return f"{texto:<44}; {self.comment}"
        return texto

    def to_dict(self) -> dict:
        return {
            "op": self.op.value,
            "text": self.text(),
            "operator": self.operator,
            "comment": self.comment,
            "line": self.line,
            "arg1": str(self.arg1) if self.arg1 is not None else None,
            "arg2": str(self.arg2) if self.arg2 is not None else None,
            "result": str(self.result) if self.result is not None else None,
        }


# ===========================================================================
# Agrupación en rutinas y en el programa completo
# ===========================================================================

@dataclass
class TACFunction:
    """Las instrucciones de una rutina, con los datos de su marco."""

    name: str
    label: str
    symbol: Optional[FunctionSymbol] = None
    start: int = 0          # índice de la primera cuádrupla en el programa
    end: int = 0            # índice de la última (inclusive)
    #: Temporales simultáneos máximos: lo que hay que reservar en el marco.
    temp_count: int = 0
    #: Bytes de parámetros, locales y temporales.
    param_size: int = 0
    local_size: int = 0
    frame_size: int = 0
    is_method: bool = False
    owner: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "tempCount": self.temp_count,
            "paramSize": self.param_size,
            "localSize": self.local_size,
            "frameSize": self.frame_size,
            "isMethod": self.is_method,
            "owner": self.owner,
        }


@dataclass
class TACProgram:
    """El programa completo en código intermedio."""

    instructions: list[Quadruple] = field(default_factory=list)
    functions: list[TACFunction] = field(default_factory=list)
    #: Literales de cadena que hay que reservar en el área de datos.
    strings: dict[str, str] = field(default_factory=dict)
    #: Clase -> etiqueta de su tabla de métodos.
    vtables: dict[str, str] = field(default_factory=dict)
    #: Total de temporales distintos creados (antes de reciclar).
    temps_created: int = 0
    #: Temporales que llegaron a existir a la vez (tras reciclar).
    temps_peak: int = 0

    def append(self, quad: Quadruple) -> Quadruple:
        self.instructions.append(quad)
        return quad

    def __len__(self) -> int:
        return len(self.instructions)

    def function_at(self, index: int) -> Optional[TACFunction]:
        """Rutina a la que pertenece la instrucción ``index``."""
        for function in self.functions:
            if function.start <= index <= function.end:
                return function
        return None

    def labels(self) -> dict[str, int]:
        """``etiqueta -> índice`` de todas las etiquetas definidas."""
        return {
            str(q.arg1): i
            for i, q in enumerate(self.instructions)
            if q.op is Op.LABEL and q.arg1 is not None
        }

    # -- representación ------------------------------------------------------
    def text(self, *, numbered: bool = False, comments: bool = True) -> str:
        """El programa en texto, listo para mostrar o guardar en un ``.tac``."""
        lineas: list[str] = []
        for i, quad in enumerate(self.instructions):
            if not comments and quad.op is Op.COMMENT:
                continue
            cuerpo = str(quad) if comments else quad.text()
            # Las etiquetas y los comentarios van sin sangría; el resto con ella.
            if quad.op in (Op.LABEL, Op.COMMENT, Op.FUNC_BEGIN, Op.FUNC_END):
                texto = cuerpo
            else:
                texto = "    " + cuerpo
            lineas.append(f"{i:>4}  {texto}" if numbered else texto)
        return "\n".join(lineas)

    def to_dict(self) -> dict:
        return {
            "instructions": [q.to_dict() for q in self.instructions],
            "functions": [f.to_dict() for f in self.functions],
            "strings": self.strings,
            "vtables": self.vtables,
            "instructionCount": len([q for q in self.instructions if q.op is not Op.COMMENT]),
            "tempsCreated": self.temps_created,
            "tempsPeak": self.temps_peak,
            "text": self.text(),
        }
