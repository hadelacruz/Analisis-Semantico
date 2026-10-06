"""Asignación y **reciclaje** de variables temporales.

El enunciado pide explícitamente "un algoritmo para asignación y reciclaje de
variables temporales durante la transformación de expresiones aritméticas".

El problema
-----------
Traducir una expresión a código de tres direcciones obliga a inventar nombres
para los resultados parciales. Si nunca se reutilizan, una expresión mediana
consume una cantidad absurda de ellos::

    (a + b) * (c + d) - (e + f) * (g + h)

    t0 = a + b      t1 = c + d      t2 = t0 * t1
    t3 = e + f      t4 = g + h      t5 = t3 * t4
    t6 = t2 - t5                    -> 7 temporales

Cada temporal ocupa una ranura del registro de activación, así que
desperdiciarlos encarece cada llamada a función.

La solución
-----------
Un **pool con lista de libres**. Un temporal se pide con :meth:`alloc` y se
devuelve con :meth:`free` en cuanto su valor ya fue consumido. Como los
resultados parciales mueren en cuanto el operador padre los usa, casi todos se
pueden reciclar de inmediato::

    t0 = a + b      ; pide t0
    t1 = c + d      ; pide t1
    t0 = t0 * t1    ; consume t0 y t1, libera t1, reutiliza t0
    t1 = e + f      ; t1 estaba libre -> se reutiliza
    t2 = g + h      ; pide t2
    t1 = t1 * t2    ; consume t1 y t2, libera t2, reutiliza t1
    t0 = t0 - t1    ; consume ambos                 -> 3 temporales

La lista de libres es una **pila** (LIFO) a propósito: reutilizar siempre el
último liberado mantiene los números bajos y agrupados, lo que hace el código
intermedio mucho más legible que una cola.

Dos métricas importantes
------------------------
* ``created`` — cuántos nombres distintos se llegaron a inventar.
* ``peak`` — cuántos estuvieron vivos **a la vez**. Éste es el que importa:
  es el número de ranuras que hay que reservar en el registro de activación.
"""
from __future__ import annotations

from typing import Iterable, Optional

from ..types import Type
from .quadruple import Operand


class TempPool:
    """Administra los temporales de **una** rutina.

    Se reinicia con :meth:`reset` al empezar cada función: los temporales de
    una rutina viven en su propio marco, así que los nombres se pueden repetir
    entre rutinas distintas sin ningún conflicto.
    """

    def __init__(self, prefix: str = "t") -> None:
        self.prefix = prefix
        self._next_id = 0
        self._free: list[str] = []      # pila de nombres reutilizables
        self._live: set[str] = set()    # temporales en uso ahora mismo
        self.created = 0                # nombres distintos inventados
        self.peak = 0                   # máximo de temporales vivos a la vez

    # -- ciclo de vida --------------------------------------------------------
    def alloc(self, type_: Optional[Type] = None) -> Operand:
        """Entrega un temporal libre, reutilizando uno si lo hay."""
        if self._free:
            name = self._free.pop()
        else:
            name = f"{self.prefix}{self._next_id}"
            self._next_id += 1
            self.created += 1
        self._live.add(name)
        self.peak = max(self.peak, len(self._live))
        return Operand.temp(name, type_)

    def free(self, operand: Optional[Operand]) -> None:
        """Devuelve un temporal al pool. Ignora lo que no sea un temporal vivo.

        Es deliberadamente tolerante: el generador llama a ``free`` sobre
        cualquier operando que acaba de consumir, sin tener que comprobar antes
        si era un temporal, una variable o una constante.
        """
        if operand is None or not operand.is_temp:
            return
        name = str(operand.value)
        if name not in self._live:
            return                       # ya estaba libre; liberar dos veces no rompe nada
        self._live.discard(name)
        self._free.append(name)

    def free_many(self, operands: Iterable[Optional[Operand]]) -> None:
        for operand in operands:
            self.free(operand)

    def reset(self) -> None:
        """Empieza una rutina nueva: todos los nombres vuelven a estar libres."""
        self._next_id = 0
        self._free.clear()
        self._live.clear()
        self.created = 0
        self.peak = 0

    # -- consulta --------------------------------------------------------------
    @property
    def live(self) -> set[str]:
        """Temporales ocupados en este momento (útil para depurar y testear)."""
        return set(self._live)

    @property
    def live_count(self) -> int:
        return len(self._live)

    def has_leaks(self) -> bool:
        """``True`` si quedaron temporales sin liberar al terminar una rutina.

        Una fuga no genera código incorrecto, pero sí desperdicia ranuras del
        marco: es señal de que al generador se le olvidó un ``free``.
        """
        return bool(self._live)

    def __repr__(self) -> str:  # pragma: no cover - depuración
        return (
            f"<TempPool vivos={sorted(self._live)} libres={self._free} "
            f"creados={self.created} pico={self.peak}>"
        )


class LabelFactory:
    """Genera etiquetas únicas para los saltos.

    Las etiquetas llevan un prefijo con la construcción que las originó
    (``L_if_3``, ``L_while_fin_7``) porque el código intermedio se lee mucho
    mejor así que con ``L1``, ``L2``, ``L3``.
    """

    def __init__(self) -> None:
        self._counter = 0

    def new(self, hint: str = "L") -> str:
        self._counter += 1
        return f"L_{hint}_{self._counter}" if hint != "L" else f"L{self._counter}"

    def many(self, *hints: str) -> tuple[str, ...]:
        """Varias etiquetas de una vez: ``verdad, falso = etiquetas('si', 'no')``."""
        return tuple(self.new(h) for h in hints)

    @property
    def count(self) -> int:
        return self._counter
