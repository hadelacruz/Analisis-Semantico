"""Rutinas del *runtime* que supone el lenguaje intermedio.

Hay operaciones de Compiscript que no se pueden expresar con tres direcciones
sin inventar decenas de instrucciones: concatenar cadenas, reservar memoria en
el heap, comprobar un índice. La solución estándar es suponer una **biblioteca
de apoyo**: el código intermedio las invoca como funciones normales y la fase
de MIPS las implementará una sola vez en ensamblador.

Que estén aquí declaradas —con su aridad y si devuelven valor— permite además
que el validador detecte llamadas mal formadas y que la máquina virtual sepa
qué hacer con cada una.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Intrinsic:
    """Una rutina del runtime."""

    name: str
    arity: int
    returns: bool
    description: str


#: Imprime un valor por la salida estándar.
PRINT = Intrinsic("__print", 1, False, "Imprime un valor y un salto de linea")
#: Concatena dos cadenas y devuelve una nueva.
CONCAT = Intrinsic("__concat", 2, True, "Concatena dos cadenas")
#: Convierte cualquier valor a su representación textual.
TO_STRING = Intrinsic("__to_string", 1, True, "Convierte un valor a cadena")
#: Reserva ``n`` bytes en el heap y devuelve el puntero.
ALLOC = Intrinsic("__alloc", 1, True, "Reserva n bytes en el heap")
#: Reserva un arreglo de ``n`` elementos de ``tam`` bytes cada uno.
ARRAY_NEW = Intrinsic("__array_new", 2, True, "Reserva un arreglo de n elementos")
#: Longitud de un arreglo (la guarda su cabecera).
LENGTH = Intrinsic("__length", 1, True, "Devuelve la longitud de un arreglo")
#: Aborta si el índice se sale del arreglo.
CHECK_BOUNDS = Intrinsic("__check_bounds", 2, False, "Comprueba que el indice este en rango")
#: Lanza una excepción con un mensaje.
THROW = Intrinsic("__throw", 1, False, "Lanza una excepcion")
#: Mensaje de la excepción que se está atendiendo (lo usa ``catch``).
EXC_MESSAGE = Intrinsic("__exc_message", 0, True, "Mensaje de la excepcion actual")

#: Todas las rutinas, indexadas por nombre.
INTRINSICS: dict[str, Intrinsic] = {
    i.name: i
    for i in (PRINT, CONCAT, TO_STRING, ALLOC, ARRAY_NEW, LENGTH, CHECK_BOUNDS, THROW, EXC_MESSAGE)
}


def is_intrinsic(name: str) -> bool:
    return name in INTRINSICS


# ===========================================================================
# Distribución de la memoria dinámica
# ===========================================================================
# Se definen en ``types`` porque el análisis semántico ya las necesita para
# calcular el layout de los objetos; aquí se reexportan por comodidad.

from ..types import (  # noqa: E402  (reexportación deliberada)
    ARRAY_HEADER_SIZE,
    ARRAY_LENGTH_OFFSET,
    OBJECT_HEADER_SIZE,
    VTABLE_POINTER_OFFSET,
)

__all__ = [
    "Intrinsic", "INTRINSICS", "is_intrinsic",
    "PRINT", "CONCAT", "TO_STRING", "ALLOC", "ARRAY_NEW", "LENGTH",
    "CHECK_BOUNDS", "THROW", "EXC_MESSAGE",
    "OBJECT_HEADER_SIZE", "VTABLE_POINTER_OFFSET",
    "ARRAY_HEADER_SIZE", "ARRAY_LENGTH_OFFSET",
]
