"""Máquina virtual del código de tres direcciones.

Ejecuta el TAC generado. No forma parte del compilador en sentido estricto,
pero cumple dos funciones importantes:

1. **Demuestra que el código generado es correcto.** Un test que sólo compara
   el texto del TAC comprueba que se parece a lo esperado; ejecutarlo comprueba
   que ``factorial(5)`` da realmente ``120``.
2. **Documenta el modelo de ejecución** que la fase de MIPS tendrá que
   reproducir: pila de registros de activación con enlaces de control y de
   acceso, heap con objetos y arreglos, tablas de métodos y manejadores de
   excepciones.

Es un modelo, no un emulador de bytes: los enteros y las cadenas se guardan
como valores de Python. Lo que sí es fiel es **el direccionamiento**: cada
local y cada parámetro se lee y se escribe en su desplazamiento respecto de
``fp``, y cada atributo en su desplazamiento dentro del objeto, exactamente
como dice la tabla de símbolos. Si un offset estuviera mal calculado, el
programa daría un resultado incorrecto aquí.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..symbols import PARAM_BASE_OFFSET
from ..types import ARRAY_LENGTH_OFFSET
from . import runtime as rt
from .quadruple import Op, OperandKind, TACProgram


class TACRuntimeError(Exception):
    """Fallo en tiempo de ejecución: lo puede atrapar un ``try``/``catch``."""


class TACAbort(Exception):
    """Fallo irrecuperable de la propia máquina (no lo atrapa el programa)."""


# ===========================================================================
# Memoria dinámica
# ===========================================================================

class Heap:
    """Montículo con asignación lineal, direccionado por bytes."""

    def __init__(self, base: int = 0x1000) -> None:
        self.cells: dict[int, Any] = {}
        self._next = base
        self.allocated = 0

    def alloc(self, size: int) -> int:
        direccion = self._next
        self._next += max(int(size), 4)
        self.allocated += max(int(size), 4)
        return direccion

    def read(self, address: int, offset: int) -> Any:
        if address is None:
            raise TACRuntimeError("acceso a una referencia nula")
        return self.cells.get(address + offset)

    def write(self, address: int, offset: int, value: Any) -> None:
        if address is None:
            raise TACRuntimeError("acceso a una referencia nula")
        self.cells[address + offset] = value


@dataclass
class Frame:
    """Registro de activación."""

    label: str
    #: ``desplazamiento respecto de fp -> valor``. Parámetros y locales.
    mem: dict[int, Any] = field(default_factory=dict)
    #: Temporales de la rutina, por nombre.
    temps: dict[str, Any] = field(default_factory=dict)
    #: Marco del llamador (enlace de control).
    control_link: Optional["Frame"] = None
    #: Marco del padre léxico (enlace de acceso); sostiene los closures.
    access_link: Optional["Frame"] = None
    #: Objeto receptor si la rutina es un método.
    this: Any = None
    #: Instrucción a la que volver.
    return_to: int = 0
    #: Dónde dejar el valor devuelto.
    result: Any = None


# ===========================================================================
# Máquina
# ===========================================================================

class TACVirtualMachine:
    """Intérprete del código de tres direcciones."""

    def __init__(self, program: TACProgram, *, max_steps: int = 2_000_000) -> None:
        self.program = program
        self.max_steps = max_steps

        self.labels = program.labels()
        self.entries = {f.label: f.start for f in program.functions}
        self.functions = {f.label: f for f in program.functions}

        self.globals: dict[int, Any] = {}      # variables globales, por offset
        self.named: dict[str, Any] = {}        # vtables y registros con nombre
        self.heap = Heap()
        self.output: list[str] = []

        self.frames: list[Frame] = []
        self.handlers: list[tuple[int, int]] = []   # (indice de la etiqueta, profundidad)
        self.pending_params: list[Any] = []
        self.pending_access_link: Optional[Frame] = None
        self.exception_message: str = ""
        self.steps = 0

    # ======================================================================
    # Lectura y escritura de operandos
    # ======================================================================
    @property
    def frame(self) -> Optional[Frame]:
        return self.frames[-1] if self.frames else None

    def read(self, operand) -> Any:
        if operand is None:
            return None
        if operand.kind is OperandKind.CONST:
            return operand.value
        if operand.kind in (OperandKind.LABEL, OperandKind.FUNC):
            return str(operand.value)
        if operand.kind is OperandKind.TEMP:
            return self.frame.temps.get(str(operand.value)) if self.frame else None

        nombre = str(operand.value)
        if nombre == "fp":
            return self.frame
        if nombre == "this":
            return self.frame.this if self.frame else None
        if operand.symbol is None:
            return self.named.get(nombre)

        simbolo = operand.symbol
        if simbolo.storage.value == "global":
            return self.globals.get(simbolo.offset or 0)
        return self.frame.mem.get(self._frame_offset(simbolo)) if self.frame else None

    def write(self, operand, value: Any) -> None:
        if operand is None:
            return
        if operand.kind is OperandKind.TEMP:
            if self.frame is not None:
                self.frame.temps[str(operand.value)] = value
            return

        nombre = str(operand.value)
        if nombre == "this":
            if self.frame is not None:
                self.frame.this = value
            return
        if operand.symbol is None:
            self.named[nombre] = value
            return

        simbolo = operand.symbol
        if simbolo.storage.value == "global":
            self.globals[simbolo.offset or 0] = value
        elif self.frame is not None:
            self.frame.mem[self._frame_offset(simbolo)] = value

    @staticmethod
    def _frame_offset(symbol) -> int:
        from ..symbols import LOCAL_BASE_OFFSET, StorageKind

        if symbol.storage is StorageKind.PARAM:
            return PARAM_BASE_OFFSET + (symbol.offset or 0)
        return LOCAL_BASE_OFFSET - (symbol.offset or 0)

    # ======================================================================
    # Ejecución
    # ======================================================================
    def run(self, entry: str = "main") -> list[str]:
        """Ejecuta desde ``entry`` y devuelve las líneas impresas."""
        if entry not in self.entries:
            raise TACAbort(f"no existe la rutina de entrada '{entry}'")

        self.frames.append(Frame(label=entry, return_to=-1))
        pc = self.entries[entry]

        while 0 <= pc < len(self.program.instructions):
            self.steps += 1
            if self.steps > self.max_steps:
                raise TACAbort("limite de pasos excedido (posible bucle infinito)")
            quad = self.program.instructions[pc]
            try:
                siguiente = self._execute(quad, pc)
            except TACRuntimeError as error:
                siguiente = self._raise(str(error))
            if siguiente is None:
                break
            pc = siguiente
        return self.output

    def _execute(self, quad, pc: int) -> Optional[int]:
        op = quad.op

        if op in (Op.LABEL, Op.COMMENT, Op.FUNC_BEGIN, Op.FUNC_END):
            return pc + 1

        if op is Op.ASSIGN:
            self.write(quad.result, self.read(quad.arg1))
            return pc + 1

        if op is Op.BINARY:
            self.write(
                quad.result,
                self._binary(quad.operator, self.read(quad.arg1), self.read(quad.arg2)),
            )
            return pc + 1

        if op is Op.UNARY:
            valor = self.read(quad.arg1)
            self.write(quad.result, -valor if quad.operator == "-" else not valor)
            return pc + 1

        if op is Op.INDEX_LOAD:
            base = self.read(quad.arg1)
            desplazamiento = int(self.read(quad.arg2) or 0)
            self.write(quad.result, self._load(base, desplazamiento))
            return pc + 1

        if op is Op.INDEX_STORE:
            base = self.read(quad.result)
            desplazamiento = int(self.read(quad.arg1) or 0)
            self._store(base, desplazamiento, self.read(quad.arg2))
            return pc + 1

        if op is Op.GOTO:
            return self._target(quad.arg1)

        if op is Op.IF_GOTO:
            return self._target(quad.arg2) if self._truth(self.read(quad.arg1)) else pc + 1

        if op is Op.IFFALSE_GOTO:
            return pc + 1 if self._truth(self.read(quad.arg1)) else self._target(quad.arg2)

        if op is Op.IF_REL_GOTO:
            resultado = self._binary(
                quad.operator, self.read(quad.arg1), self.read(quad.arg2)
            )
            return self._target(quad.result) if resultado else pc + 1

        if op is Op.PARAM:
            self.pending_params.append(self.read(quad.arg1))
            return pc + 1

        if op is Op.SET_ACCESS_LINK:
            self.pending_access_link = self.read(quad.arg1)
            return pc + 1

        if op in (Op.CALL, Op.CALL_INDIRECT):
            return self._call(quad, pc)

        if op is Op.RETURN:
            return self._return(quad)

        if op is Op.PUSH_HANDLER:
            self.handlers.append((self._target(quad.arg1), len(self.frames)))
            return pc + 1

        if op is Op.POP_HANDLER:
            if self.handlers:
                self.handlers.pop()
            return pc + 1

        raise TACAbort(f"instruccion no soportada: {op}")  # pragma: no cover

    # -- operaciones -------------------------------------------------------------
    @staticmethod
    def _truth(value: Any) -> bool:
        return bool(value)

    def _binary(self, operator: str, izquierdo: Any, derecho: Any) -> Any:
        if operator in ("/", "%") and derecho == 0:
            raise TACRuntimeError("division entre cero")
        try:
            if operator == "+":
                return izquierdo + derecho
            if operator == "-":
                return izquierdo - derecho
            if operator == "*":
                return izquierdo * derecho
            if operator == "/":
                # La division entre enteros se mantiene entera, como en MIPS.
                if isinstance(izquierdo, int) and isinstance(derecho, int):
                    return int(izquierdo / derecho)
                return izquierdo / derecho
            if operator == "%":
                return izquierdo % derecho
            if operator == "<":
                return izquierdo < derecho
            if operator == "<=":
                return izquierdo <= derecho
            if operator == ">":
                return izquierdo > derecho
            if operator == ">=":
                return izquierdo >= derecho
            if operator == "==":
                return izquierdo == derecho
            if operator == "!=":
                return izquierdo != derecho
        except TypeError as error:
            raise TACRuntimeError(f"operacion invalida: {error}") from error
        raise TACAbort(f"operador desconocido: {operator}")  # pragma: no cover

    def _load(self, base: Any, offset: int) -> Any:
        if isinstance(base, Frame):
            if offset == -4:
                return base.access_link
            if offset == 0:
                return base.control_link
            return base.mem.get(offset)
        if base is None:
            raise TACRuntimeError("acceso a una referencia nula")
        return self.heap.read(int(base), offset)

    def _store(self, base: Any, offset: int, value: Any) -> None:
        if isinstance(base, Frame):
            base.mem[offset] = value
            return
        if base is None:
            raise TACRuntimeError("acceso a una referencia nula")
        self.heap.write(int(base), offset, value)

    def _target(self, operand) -> int:
        nombre = str(operand.value)
        if nombre not in self.labels:
            raise TACAbort(f"etiqueta inexistente: {nombre}")
        return self.labels[nombre]

    # -- llamadas -----------------------------------------------------------------
    def _call(self, quad, pc: int) -> Optional[int]:
        destino = (
            str(self.read(quad.arg1)) if quad.op is Op.CALL_INDIRECT else str(quad.arg1.value)
        )
        argumentos = self.pending_params
        self.pending_params = []
        enlace = self.pending_access_link
        self.pending_access_link = None

        if rt.is_intrinsic(destino):
            valor = self._intrinsic(destino, argumentos)
            self.write(quad.result, valor)
            return pc + 1

        if destino not in self.entries:
            raise TACAbort(f"no existe la rutina '{destino}'")

        funcion = self.functions[destino]
        marco = Frame(
            label=destino,
            control_link=self.frame,
            access_link=enlace,
            return_to=pc + 1,
            result=quad.result,
        )

        # 'this' es siempre el primer argumento de un metodo. Se enlaza antes
        # de mirar el simbolo porque las rutinas sinteticas (los
        # inicializadores de atributos) no tienen FunctionSymbol asociado.
        if funcion.is_method and argumentos:
            marco.this = argumentos.pop(0)
        simbolo = funcion.symbol
        if simbolo is not None:
            for parametro, valor in zip(simbolo.params, argumentos):
                marco.mem[self._frame_offset(parametro)] = valor

        self.frames.append(marco)
        return self.entries[destino]

    def _return(self, quad) -> Optional[int]:
        valor = self.read(quad.arg1) if quad.arg1 is not None else None
        marco = self.frames.pop()
        if not self.frames or marco.return_to < 0:
            return None
        if marco.result is not None:
            self.write(marco.result, valor)
        return marco.return_to

    # -- excepciones ----------------------------------------------------------------
    def _raise(self, message: str) -> Optional[int]:
        self.exception_message = message
        if not self.handlers:
            raise TACAbort(f"excepcion no atrapada: {message}")
        destino, profundidad = self.handlers.pop()
        while len(self.frames) > profundidad:
            self.frames.pop()
        self.pending_params = []
        return destino

    # -- biblioteca de apoyo -----------------------------------------------------------
    def _intrinsic(self, name: str, args: list[Any]) -> Any:
        if name == rt.PRINT.name:
            self.output.append(self._format(args[0]))
            return None
        if name == rt.CONCAT.name:
            return f"{args[0]}{args[1]}"
        if name == rt.TO_STRING.name:
            return self._format(args[0])
        if name == rt.ALLOC.name:
            return self.heap.alloc(int(args[0]))
        if name == rt.ARRAY_NEW.name:
            longitud, tam = int(args[0]), int(args[1])
            direccion = self.heap.alloc(4 + longitud * tam)
            self.heap.write(direccion, ARRAY_LENGTH_OFFSET, longitud)
            return direccion
        if name == rt.LENGTH.name:
            if args[0] is None:
                raise TACRuntimeError("acceso a una referencia nula")
            return self.heap.read(int(args[0]), ARRAY_LENGTH_OFFSET) or 0
        if name == rt.CHECK_BOUNDS.name:
            arreglo, indice = args[0], int(args[1])
            if arreglo is None:
                raise TACRuntimeError("acceso a una referencia nula")
            longitud = self.heap.read(int(arreglo), ARRAY_LENGTH_OFFSET) or 0
            if indice < 0 or indice >= longitud:
                raise TACRuntimeError(
                    f"indice {indice} fuera del rango del arreglo (0..{longitud - 1})"
                )
            return None
        if name == rt.THROW.name:
            raise TACRuntimeError(str(args[0]))
        if name == rt.EXC_MESSAGE.name:
            return self.exception_message
        raise TACAbort(f"rutina del runtime no implementada: {name}")  # pragma: no cover

    @staticmethod
    def _format(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            # Se redondea a 6 decimales y se quitan los ceros sobrantes, para
            # que 100.0 * 1.12 se imprima "112" y no "112.00000000000001".
            return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
        return str(value)


def run(program: TACProgram, *, entry: str = "main", max_steps: int = 2_000_000) -> list[str]:
    """Ejecuta ``program`` y devuelve las líneas que imprimió."""
    return TACVirtualMachine(program, max_steps=max_steps).run(entry)
