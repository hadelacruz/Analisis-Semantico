"""Asignación de registros: la función ``getReg()``.

El código de tres direcciones supone **temporales ilimitados**; MIPS tiene 32
registros. Este módulo resuelve esa diferencia.

El algoritmo
------------
Es el clásico de los **descriptores** (Dragon Book, cap. 8), con asignación
local a cada bloque básico:

* El **descriptor de registro** dice qué valor contiene cada registro.
* El **descriptor de dirección** dice dónde vive cada valor: en un registro, en
  memoria, o en ambos.

Cuando se pide un registro para un valor:

1. Si el valor ya está en un registro, se devuelve ese (no se recarga nada).
2. Si hay un registro libre, se toma.
3. Si no hay ninguno libre, se **expulsa** el menos usado recientemente
   (*LRU*). Si estaba sucio —su valor aún no se escribió en memoria— primero se
   vuelca a su posición en el marco: eso es el *spilling*.

En los bordes de bloque básico (una etiqueta, un salto, una llamada) se
vuelcan todos los registros sucios y se vacían los descriptores, porque a
partir de ahí no se puede suponer nada sobre lo que contienen.

Por qué local y no global
-------------------------
Una asignación global de registros necesitaría análisis de vivacidad y
coloreado de grafos. La asignación local captura la mayor parte del beneficio
—los resultados intermedios de una expresión no tocan memoria— con un
algoritmo que se puede verificar instrucción a instrucción.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

#: Registros enteros que el asignador puede repartir.
#: ``$t0``–``$t7`` son de usar y tirar; ``$s0``–``$s7`` los preserva el callee.
REGISTROS_ENTEROS = [f"$t{i}" for i in range(8)] + [f"$s{i}" for i in range(8)]

#: Registros de punto flotante. Sólo los **pares**: la doble precisión usa
#: parejas de registros y MIPS exige que empiecen en uno par.
REGISTROS_FLOTANTES = [f"$f{i}" for i in range(4, 31, 2)]

#: Reservados, nunca se reparten.
#:   ``$t8`` lleva el enlace de acceso en las llamadas a funciones anidadas.
#:   ``$t9`` es el borrador del generador para calcular direcciones.
#:   ``$v0`` devuelve resultados y selecciona el ``syscall``.
#:   ``$a0``–``$a3`` pasan argumentos a los ``syscall``.
#:   ``$f0`` devuelve los resultados flotantes y ``$f2`` es el borrador.
ENLACE_ACCESO = "$t8"
BORRADOR = "$t9"
BORRADOR_FLOTANTE = "$f2"
RETORNO = "$v0"
RETORNO_FLOTANTE = "$f0"


@dataclass
class Descriptor:
    """Lo que el asignador sabe de un registro en un momento dado."""

    #: Clave del valor que contiene, o ``None`` si está libre.
    valor: Optional[str] = None
    #: ``True`` si el valor todavía no se escribió en su posición de memoria.
    sucio: bool = False
    #: Marca de tiempo del último uso, para la expulsión por LRU.
    ultimo_uso: int = 0
    #: ``True`` mientras el registro está en uso dentro de la instrucción
    #: actual, para que no se expulse a sí mismo.
    fijado: bool = False


class RegisterAllocator:
    """Reparte los registros de MIPS entre los valores del código intermedio.

    No emite código por su cuenta: recibe dos funciones de vuelta, una para
    cargar un valor desde memoria y otra para volcarlo, y las llama cuando hace
    falta. Así toda la emisión queda en el generador.
    """

    def __init__(
        self,
        cargar: Callable[[str, str], None],
        volcar: Callable[[str, str], None],
        *,
        enteros: Optional[list[str]] = None,
        flotantes: Optional[list[str]] = None,
    ) -> None:
        self._cargar = cargar
        self._volcar = volcar

        self.enteros = list(enteros if enteros is not None else REGISTROS_ENTEROS)
        self.flotantes = list(flotantes if flotantes is not None else REGISTROS_FLOTANTES)

        self.descriptores: dict[str, Descriptor] = {
            registro: Descriptor() for registro in self.enteros + self.flotantes
        }
        self._es_flotante = set(self.flotantes)
        #: ``clave del valor -> registro`` (descriptor de dirección).
        self.en_registro: dict[str, str] = {}

        self._reloj = 0
        # --- métricas, para poder demostrar que el asignador sirve de algo ---
        self.reutilizaciones = 0   # veces que un valor ya estaba en registro
        self.cargas = 0            # veces que hubo que traerlo de memoria
        self.volcados = 0          # veces que hubo que expulsar uno sucio

    # ======================================================================
    # Consulta
    # ======================================================================
    def _banco(self, flotante: bool) -> list[str]:
        return self.flotantes if flotante else self.enteros

    def esta_en_registro(self, clave: str) -> Optional[str]:
        return self.en_registro.get(clave)

    # ======================================================================
    # getReg
    # ======================================================================
    def get_reg(self, clave: str, *, flotante: bool = False, cargar: bool = True) -> str:
        """Devuelve un registro que contenga (o vaya a contener) ``clave``.

        Con ``cargar=False`` el registro se reserva como **destino**: no se
        trae nada de memoria porque se va a sobrescribir igualmente.
        """
        existente = self.en_registro.get(clave)
        if existente is not None:
            if (existente in self._es_flotante) == flotante:
                self.reutilizaciones += 1
                self._tocar(existente)
                return existente
            # El mismo nombre de temporal ha cambiado de banco: el generador
            # de codigo intermedio recicla los temporales, asi que 't0' pudo
            # ser un doble y ahora ser un entero. El valor anterior ya murio,
            # de modo que se suelta sin volcarlo.
            self.descriptores[existente] = Descriptor()
            self.en_registro.pop(clave, None)

        registro = self._registro_libre(flotante)
        self._vincular(registro, clave)
        if cargar:
            self.cargas += 1
            self._cargar(registro, clave)
        else:
            self.descriptores[registro].sucio = True
        return registro

    def destino(self, clave: str, *, flotante: bool = False) -> str:
        """Registro donde se va a **escribir** ``clave``."""
        registro = self.get_reg(clave, flotante=flotante, cargar=False)
        self.descriptores[registro].sucio = True
        return registro

    def marcar_sucio(self, registro: str) -> None:
        if registro in self.descriptores:
            self.descriptores[registro].sucio = True

    # ======================================================================
    # Fijado: proteger los operandos de la instrucción en curso
    # ======================================================================
    def fijar(self, *registros: str) -> None:
        for registro in registros:
            if registro in self.descriptores:
                self.descriptores[registro].fijado = True

    def soltar_todos(self) -> None:
        for descriptor in self.descriptores.values():
            descriptor.fijado = False

    # ======================================================================
    # Liberación y volcado
    # ======================================================================
    def olvidar(self, clave: str) -> None:
        """El valor murió: su registro queda libre sin escribir nada."""
        registro = self.en_registro.pop(clave, None)
        if registro is not None:
            self.descriptores[registro] = Descriptor()

    def volcar_todo(self) -> None:
        """Escribe en memoria los registros sucios y olvida los descriptores.

        Se llama en los bordes de bloque básico: tras una etiqueta o un salto
        no se puede suponer nada sobre el contenido de los registros, y antes
        de una llamada hay que asumir que el callee los pisa.
        """
        for registro, descriptor in self.descriptores.items():
            if descriptor.valor is not None and descriptor.sucio:
                self.volcados += 1
                self._volcar(registro, descriptor.valor)
        self.descriptores = {
            registro: Descriptor() for registro in self.enteros + self.flotantes
        }
        self.en_registro.clear()

    def invalidar(self) -> None:
        """Olvida los descriptores **sin** volcar (tras un salto incondicional)."""
        self.descriptores = {
            registro: Descriptor() for registro in self.enteros + self.flotantes
        }
        self.en_registro.clear()

    # ======================================================================
    # Interior
    # ======================================================================
    def _tocar(self, registro: str) -> None:
        self._reloj += 1
        self.descriptores[registro].ultimo_uso = self._reloj

    def _vincular(self, registro: str, clave: str) -> None:
        self.descriptores[registro] = Descriptor(valor=clave, fijado=True)
        self.en_registro[clave] = registro
        self._tocar(registro)

    def _registro_libre(self, flotante: bool) -> str:
        banco = self._banco(flotante)

        # 1. ¿Hay alguno sin usar?
        for registro in banco:
            if self.descriptores[registro].valor is None:
                return registro

        # 2. Expulsar el menos usado recientemente que no esté fijado.
        candidatos = [r for r in banco if not self.descriptores[r].fijado]
        if not candidatos:  # pragma: no cover - solo con expresiones absurdas
            raise RuntimeError(
                "no quedan registros libres: la expresion necesita mas de "
                f"{len(banco)} valores vivos a la vez"
            )
        victima = min(candidatos, key=lambda r: self.descriptores[r].ultimo_uso)
        descriptor = self.descriptores[victima]
        if descriptor.valor is not None:
            if descriptor.sucio:
                self.volcados += 1
                self._volcar(victima, descriptor.valor)
            self.en_registro.pop(descriptor.valor, None)
        self.descriptores[victima] = Descriptor()
        return victima

    # ======================================================================
    # Métricas
    # ======================================================================
    def estadisticas(self) -> dict:
        total = self.reutilizaciones + self.cargas
        return {
            "reutilizaciones": self.reutilizaciones,
            "cargas": self.cargas,
            "volcados": self.volcados,
            "aciertos": round(100 * self.reutilizaciones / total, 1) if total else 0.0,
        }
