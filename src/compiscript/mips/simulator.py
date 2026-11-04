"""Ejecución del código generado en un simulador externo (MARS o SPIM).

El enunciado pide validar el ensamblador "por medio de una tercera
herramienta". Este módulo localiza el simulador y le pasa el ``.asm``.

Ninguno de los dos simuladores se distribuye con el proyecto: hay que
instalarlos aparte (ver ``docs/CODIGO_MIPS.md``). Si no están disponibles, el
compilador usa su propio emulador (``emulator.py``), que ejecuta exactamente
el mismo texto.

Dónde se busca el simulador
---------------------------
1. La variable de entorno ``MARS_JAR`` apuntando al ``.jar``.
2. Un ``Mars*.jar`` en la raíz del proyecto o en ``tools/``.
3. El ejecutable ``spim`` en el ``PATH``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parents[3]


@dataclass
class Simulador:
    """Un simulador de MIPS disponible en el sistema."""

    nombre: str
    tipo: str          # "mars" o "spim"
    ruta: str

    def comando(self, archivo: str) -> list[str]:
        if self.tipo == "mars":
            # 'nc' quita el banner, 'me' manda los errores a stderr.
            return ["java", "-jar", self.ruta, "nc", "me", archivo]
        return [self.ruta, "-file", archivo]


def buscar_simulador() -> Optional[Simulador]:
    """Localiza MARS o SPIM, o devuelve ``None`` si no hay ninguno."""
    jar = os.environ.get("MARS_JAR")
    if jar and Path(jar).is_file():
        return Simulador("MARS", "mars", jar)

    for directorio in (RAIZ, RAIZ / "tools"):
        if not directorio.is_dir():
            continue
        for candidato in sorted(directorio.glob("[Mm]ars*.jar")):
            return Simulador("MARS", "mars", str(candidato))

    spim = shutil.which("spim")
    if spim:
        return Simulador("SPIM", "spim", spim)
    return None


def ejecutar_en_simulador(
    asm: str, *, simulador: Optional[Simulador] = None, timeout: int = 30
) -> tuple[list[str], Optional[str]]:
    """Ejecuta ``asm`` en el simulador externo.

    Devuelve ``(lineas_impresas, error)``. El error es ``None`` si todo fue
    bien, o un texto explicando por qué no se pudo ejecutar.
    """
    simulador = simulador or buscar_simulador()
    if simulador is None:
        return [], (
            "No se encontro ningun simulador de MIPS. Instala MARS y exporta "
            "MARS_JAR=/ruta/Mars4_5.jar, o instala spim. Mientras tanto puedes "
            "usar el emulador propio con --run-mips."
        )

    if simulador.tipo == "mars" and shutil.which("java") is None:
        return [], "MARS necesita Java y 'java' no esta en el PATH."

    with tempfile.TemporaryDirectory() as carpeta:
        archivo = Path(carpeta) / "programa.asm"
        archivo.write_text(asm, encoding="utf-8")
        try:
            proceso = subprocess.run(
                simulador.comando(str(archivo)),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return [], f"{simulador.nombre} supero el tiempo limite de {timeout}s."
        except OSError as error:  # pragma: no cover - depende del sistema
            return [], f"No se pudo lanzar {simulador.nombre}: {error}"

    salida = proceso.stdout.splitlines()
    if proceso.returncode != 0 and proceso.stderr.strip():
        return salida, f"{simulador.nombre} informo: {proceso.stderr.strip()}"
    return salida, None
