"""Validador estructural del código intermedio.

El análisis semántico garantiza que el **programa fuente** tiene sentido; este
validador garantiza que el **código generado** está bien formado. Son dos cosas
distintas: un error del generador (una etiqueta a la que nadie salta, un
``param`` de más, un temporal que se lee antes de escribirse) produce TAC
sintácticamente válido pero incorrecto, y no lo detectaría ningún test que sólo
compare texto.

Tener este validador es lo que permite escribir **casos fallidos** en la batería
de pruebas de esta fase: se construye a mano un programa TAC mal formado y se
comprueba que el validador lo detecta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import runtime as rt
from .quadruple import (
    BINARY_OPERATORS,
    RELATIONAL_OPERATORS,
    UNARY_OPERATORS,
    Op,
    OperandKind,
    TACProgram,
)

#: ``codigo -> descripcion`` de los problemas que detecta el validador.
CATALOG: dict[str, str] = {
    "T001": "Salto a una etiqueta que no existe",
    "T002": "Etiqueta definida mas de una vez",
    "T003": "Operador no valido para la instruccion",
    "T004": "El numero de 'param' no coincide con la aridad de la llamada",
    "T005": "Llamada a una rutina que no existe",
    "T006": "Aridad incorrecta en una rutina del runtime",
    "T007": "Temporal leido antes de escribirse",
    "T008": "Rutina sin 'begin_func' o sin 'end_func'",
    "T009": "Una rutina no termina en 'return'",
    "T010": "Instruccion con operandos incompletos",
}


@dataclass(frozen=True)
class TACIssue:
    """Un problema encontrado en el código intermedio."""

    code: str
    message: str
    index: int
    function: str = ""

    def __str__(self) -> str:
        donde = f" en {self.function}" if self.function else ""
        return f"[{self.code}] instruccion {self.index}{donde}: {self.message}"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "index": self.index,
            "function": self.function,
        }


class TACValidator:
    """Comprueba las invariantes del código intermedio generado."""

    def __init__(self, program: TACProgram) -> None:
        self.program = program
        self.issues: list[TACIssue] = []

    # -- registro --------------------------------------------------------------
    def _add(self, code: str, message: str, index: int) -> None:
        function = self.program.function_at(index)
        self.issues.append(TACIssue(code, message, index, function.label if function else ""))

    # -- ejecución --------------------------------------------------------------
    def validate(self) -> list[TACIssue]:
        self.issues = []
        etiquetas = self._check_labels()
        self._check_operators()
        self._check_calls(etiquetas)
        self._check_temporaries()
        self._check_routines()
        return self.issues

    # -- comprobaciones ----------------------------------------------------------
    def _check_labels(self) -> set[str]:
        """T001/T002 — toda etiqueta se define una vez y todo salto la encuentra."""
        definidas: set[str] = set()
        for indice, quad in enumerate(self.program.instructions):
            if quad.op is Op.LABEL and quad.arg1 is not None:
                nombre = str(quad.arg1)
                if nombre in definidas:
                    self._add("T002", f"la etiqueta '{nombre}' ya estaba definida", indice)
                definidas.add(nombre)

        for indice, quad in enumerate(self.program.instructions):
            destino = self._jump_target(quad)
            if destino is not None and destino not in definidas:
                self._add("T001", f"salto a la etiqueta inexistente '{destino}'", indice)
        return definidas

    @staticmethod
    def _jump_target(quad) -> Optional[str]:
        if quad.op in (Op.GOTO, Op.PUSH_HANDLER):
            return str(quad.arg1) if quad.arg1 is not None else None
        if quad.op in (Op.IF_GOTO, Op.IFFALSE_GOTO):
            return str(quad.arg2) if quad.arg2 is not None else None
        if quad.op is Op.IF_REL_GOTO:
            return str(quad.result) if quad.result is not None else None
        return None

    def _check_operators(self) -> None:
        """T003/T010 — cada instruccion lleva el operador y los operandos que le tocan."""
        for indice, quad in enumerate(self.program.instructions):
            if quad.op is Op.BINARY:
                if quad.operator not in BINARY_OPERATORS:
                    self._add("T003", f"'{quad.operator}' no es un operador binario", indice)
                if quad.arg1 is None or quad.arg2 is None or quad.result is None:
                    self._add("T010", "a la operacion binaria le faltan operandos", indice)
            elif quad.op is Op.UNARY:
                if quad.operator not in UNARY_OPERATORS:
                    self._add("T003", f"'{quad.operator}' no es un operador unario", indice)
            elif quad.op is Op.IF_REL_GOTO:
                if quad.operator not in RELATIONAL_OPERATORS:
                    self._add("T003", f"'{quad.operator}' no es un operador relacional", indice)
            elif quad.op in (Op.INDEX_LOAD, Op.INDEX_STORE):
                if quad.arg1 is None or quad.result is None:
                    self._add("T010", "al acceso indexado le faltan operandos", indice)
            elif quad.op is Op.ASSIGN:
                if quad.arg1 is None or quad.result is None:
                    self._add("T010", "a la copia le faltan operandos", indice)

    def _check_calls(self, etiquetas: set[str]) -> None:
        """T004/T005/T006 — los ``param`` cuadran con la aridad declarada."""
        rutinas = {f.label for f in self.program.functions}
        pendientes = 0
        for indice, quad in enumerate(self.program.instructions):
            if quad.op is Op.PARAM:
                pendientes += 1
                continue
            if quad.op not in (Op.CALL, Op.CALL_INDIRECT):
                # Una etiqueta o un salto cortan la secuencia de 'param'.
                if quad.op in (Op.LABEL, Op.GOTO, Op.RETURN, Op.FUNC_END):
                    pendientes = 0
                continue

            declarados = int(quad.arg2.value) if quad.arg2 is not None else 0
            if declarados != pendientes:
                self._add(
                    "T004",
                    f"la llamada declara {declarados} argumento(s) pero se apilaron {pendientes}",
                    indice,
                )
            pendientes = 0

            if quad.op is Op.CALL and quad.arg1 is not None:
                nombre = str(quad.arg1)
                if rt.is_intrinsic(nombre):
                    esperado = rt.INTRINSICS[nombre].arity
                    if esperado != declarados:
                        self._add(
                            "T006",
                            f"'{nombre}' espera {esperado} argumento(s), no {declarados}",
                            indice,
                        )
                elif nombre not in rutinas:
                    self._add("T005", f"no existe la rutina '{nombre}'", indice)

    def _check_temporaries(self) -> None:
        """T007 — todo temporal que se lee se escribe en algún punto de su rutina.

        No se exige que la escritura sea *textualmente anterior*: con saltos
        hacia atrás y con el código por saltos de las condiciones, una
        definición perfectamente válida puede quedar después de la lectura en
        el listado. Lo que sí es siempre un error del generador es leer un
        temporal que **nunca** se escribe en esa rutina.
        """
        for function in self.program.functions:
            rango = range(function.start, function.end + 1)
            definidos = {
                str(destino.value)
                for indice in rango
                for destino in [self.program.instructions[indice].defines()]
                if destino is not None and destino.kind is OperandKind.TEMP
            }
            avisados: set[str] = set()
            for indice in rango:
                for operando in self.program.instructions[indice].operands():
                    nombre = str(operando.value)
                    if (
                        operando.kind is OperandKind.TEMP
                        and nombre not in definidos
                        and nombre not in avisados
                    ):
                        self._add(
                            "T007",
                            f"el temporal '{nombre}' se lee sin haberse escrito nunca",
                            indice,
                        )
                        avisados.add(nombre)

    def _check_routines(self) -> None:
        """T008/T009 — cada rutina esta bien delimitada y termina en 'return'."""
        for function in self.program.functions:
            inicio = self.program.instructions[function.start]
            fin = self.program.instructions[function.end]
            if inicio.op is not Op.FUNC_BEGIN or fin.op is not Op.FUNC_END:
                self._add("T008", f"la rutina '{function.label}' esta mal delimitada", function.start)
                continue
            anterior = self.program.instructions[function.end - 1]
            if anterior.op is not Op.RETURN:
                self._add(
                    "T009",
                    f"la rutina '{function.label}' no termina con 'return'",
                    function.end - 1,
                )


def validate(program: TACProgram) -> list[TACIssue]:
    """Atajo: valida ``program`` y devuelve la lista de problemas."""
    return TACValidator(program).validate()
