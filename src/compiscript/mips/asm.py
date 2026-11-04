"""Representación de un programa en ensamblador MIPS.

Un archivo de MIPS convencional tiene dos secciones y el orden en que se
descubren las cosas no coincide con el orden en que hay que escribirlas: los
literales de cadena aparecen en medio del código pero van en ``.data``. Por eso
se emite a **dos buffers separados** que se concatenan al final.

El resultado es texto compatible con **MARS** y **SPIM**: sólo se usan
instrucciones y pseudoinstrucciones que ambos aceptan.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def escapar_cadena(texto: str) -> str:
    """Convierte una cadena de Compiscript en un literal ``.asciiz``."""
    salida = []
    for caracter in texto:
        if caracter == "\\":
            salida.append("\\\\")
        elif caracter == '"':
            salida.append('\\"')
        elif caracter == "\n":
            salida.append("\\n")
        elif caracter == "\t":
            salida.append("\\t")
        else:
            salida.append(caracter)
    return '"' + "".join(salida) + '"'


@dataclass
class MipsProgram:
    """Programa en ensamblador, dividido en sus dos secciones."""

    #: Líneas de la sección de datos estáticos.
    data: list[str] = field(default_factory=list)
    #: Líneas de la sección de código.
    text: list[str] = field(default_factory=list)
    #: Cuántas instrucciones reales se emitieron (sin etiquetas ni comentarios).
    instruction_count: int = 0
    #: Si es ``False``, se omiten todos los comentarios que genera el
    #: compilador. Los de la biblioteca de runtime se conservan porque van
    #: como texto literal y documentan cada rutina.
    with_comments: bool = True

    # -- sección de datos ----------------------------------------------------
    def dato(self, linea: str, comentario: str = "") -> None:
        self.data.append(self._con_comentario(linea, comentario))

    def _activo(self, comentario: str) -> str:
        return comentario if self.with_comments else ""

    def etiqueta_dato(self, nombre: str, comentario: str = "") -> None:
        self.data.append(
            self._con_comentario(f"{nombre}:", self._activo(comentario), sangria="")
        )

    def comentario_dato(self, texto: str) -> None:
        if self.with_comments:
            self.data.append(f"    # {texto}")

    # -- sección de código ----------------------------------------------------
    def emit(self, op: str, *args: str, comentario: str = "") -> None:
        """Emite una instrucción. ``emit("add", "$t0", "$t1", "$t2")``."""
        cuerpo = f"{op} {', '.join(str(a) for a in args)}" if args else op
        self.text.append(self._con_comentario(cuerpo, self._activo(comentario)))
        self.instruction_count += 1

    def etiqueta(self, nombre: str, comentario: str = "") -> None:
        self.text.append(
            self._con_comentario(f"{nombre}:", self._activo(comentario), sangria="")
        )

    def comentario(self, texto: str) -> None:
        if self.with_comments:
            self.text.append(f"    # {texto}")

    def separador(self, titulo: str) -> None:
        if not self.with_comments:
            self.text.append("")
            return
        self.text.append("")
        self.text.append(f"# {'=' * 66}")
        self.text.append(f"# {titulo}")
        self.text.append(f"# {'=' * 66}")

    def en_blanco(self) -> None:
        self.text.append("")

    def bruto(self, linea: str) -> None:
        """Inserta una línea tal cual (para la biblioteca de runtime)."""
        self.text.append(linea)

    # -- utilidades ------------------------------------------------------------
    @staticmethod
    def _con_comentario(cuerpo: str, comentario: str, sangria: str = "    ") -> str:
        linea = f"{sangria}{cuerpo}"
        if comentario:
            relleno = max(1, 44 - len(linea))
            return f"{linea}{' ' * relleno}# {comentario}"
        return linea

    def render(self) -> str:
        """El archivo ``.asm`` completo."""
        partes: list[str] = [
            "# " + "=" * 66,
            "# Codigo MIPS generado por el compilador de Compiscript",
            "# Compatible con MARS 4.5 y SPIM.",
            "# " + "=" * 66,
            "",
            "    .data",
            *self.data,
            "",
            "    .text",
            "    .globl main",
            *self.text,
            "",
        ]
        return "\n".join(partes)

    def __str__(self) -> str:  # pragma: no cover - comodidad
        return self.render()
