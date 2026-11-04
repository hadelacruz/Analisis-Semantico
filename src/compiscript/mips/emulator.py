"""Emulador de MIPS para validar el código generado.

El enunciado pide ejecutar el ensamblador en un simulador. MARS y SPIM son
programas externos que hay que instalar aparte, así que este emulador cumple
dos funciones distintas y complementarias:

1. **Hace que la batería de tests sea autocontenida.** Sin él no habría forma
   de comprobar automáticamente que el ``.asm`` generado calcula lo correcto.
2. **Valida el artefacto de verdad.** No ejecuta estructuras internas: parsea
   **el mismo texto** que recibiría MARS, así que un error de impresión del
   generador se detecta aquí.

Soporta exactamente el subconjunto de MIPS que emite el compilador (más las
pseudoinstrucciones que usa la biblioteca de runtime). Cualquier instrucción
fuera de ese subconjunto levanta un error en vez de ignorarse en silencio, de
modo que un hueco del emulador nunca se confunde con un programa correcto.

Para ejecutar en el simulador de verdad, ver ``simulator.py``.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Optional

#: Donde empieza el segmento de codigo (el mismo valor que usa MARS).
#: Las etiquetas de rutina tienen direccion real porque el programa las carga
#: con ``la`` para guardarlas en las tablas de metodos y en los manejadores.
BASE_CODIGO = 0x00400000
#: Donde empieza la seccion de datos (el mismo valor que usa MARS).
BASE_DATOS = 0x10010000
#: Tamano del espacio de memoria emulado.
TAM_MEMORIA = 8 * 1024 * 1024
#: Tope de la pila; crece hacia abajo.
TOPE_PILA = BASE_DATOS + TAM_MEMORIA - 16

MASCARA = 0xFFFFFFFF


class MipsError(Exception):
    """Fallo irrecuperable durante la emulación."""


def u32(valor: int) -> int:
    return valor & MASCARA


def s32(valor: int) -> int:
    valor &= MASCARA
    return valor - (1 << 32) if valor & 0x80000000 else valor


@dataclass
class Instruccion:
    op: str
    args: list[str]
    linea: int = 0
    texto: str = ""


@dataclass
class Programa:
    """Resultado de ensamblar el texto."""

    instrucciones: list[Instruccion] = field(default_factory=list)
    etiquetas: dict[str, int] = field(default_factory=dict)   # etiqueta -> indice
    datos: dict[str, int] = field(default_factory=dict)       # etiqueta -> direccion
    memoria_inicial: bytearray = field(default_factory=bytearray)
    fin_datos: int = BASE_DATOS


# ===========================================================================
# Ensamblador
# ===========================================================================

_CADENA = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _desescapar(texto: str) -> str:
    salida, i = [], 0
    while i < len(texto):
        if texto[i] == "\\" and i + 1 < len(texto):
            siguiente = texto[i + 1]
            salida.append({"n": "\n", "t": "\t", "0": "\0", "\\": "\\", '"': '"'}.get(siguiente, siguiente))
            i += 2
        else:
            salida.append(texto[i])
            i += 1
    return "".join(salida)


def ensamblar(fuente: str) -> Programa:
    """Convierte el texto del ``.asm`` en un programa ejecutable."""
    programa = Programa()
    memoria = bytearray()
    seccion = "text"
    direccion = BASE_DATOS
    pendientes_texto: list[tuple[str, list[str], int, str]] = []

    for numero, linea_cruda in enumerate(fuente.splitlines(), start=1):
        linea = linea_cruda.split("#")[0].strip()
        while linea:
            if linea.startswith(".data"):
                seccion = "data"
                linea = linea[5:].strip()
                continue
            if linea.startswith(".text"):
                seccion = "text"
                linea = linea[5:].strip()
                continue
            if linea.startswith(".globl"):
                linea = ""
                continue

            # Etiqueta al principio de la linea
            coincidencia = re.match(r"^([A-Za-z_][\w.]*)\s*:\s*", linea)
            if coincidencia:
                nombre = coincidencia.group(1)
                if seccion == "data":
                    programa.datos[nombre] = direccion
                else:
                    programa.etiquetas[nombre] = len(pendientes_texto)
                linea = linea[coincidencia.end():].strip()
                continue

            if seccion == "data":
                direccion, memoria = _dato(linea, direccion, memoria)
                linea = ""
                continue

            partes = linea.split(None, 1)
            op = partes[0]
            resto = partes[1] if len(partes) > 1 else ""
            args = [a.strip() for a in resto.split(",")] if resto else []
            pendientes_texto.append((op, args, numero, linea))
            linea = ""

    programa.instrucciones = [
        Instruccion(op, args, numero, texto) for op, args, numero, texto in pendientes_texto
    ]
    programa.fin_datos = direccion
    programa.memoria_inicial = memoria
    return programa


def _dato(linea: str, direccion: int, memoria: bytearray) -> tuple[int, bytearray]:
    """Procesa una directiva de la seccion de datos."""
    def rellenar(hasta: int) -> None:
        while len(memoria) < hasta - BASE_DATOS:
            memoria.append(0)

    if linea.startswith(".align"):
        potencia = int(linea.split()[1])
        alineacion = 1 << potencia
        if direccion % alineacion:
            direccion += alineacion - (direccion % alineacion)
        rellenar(direccion)
        return direccion, memoria

    if linea.startswith(".space"):
        cantidad = int(linea.split()[1])
        direccion += cantidad
        rellenar(direccion)
        return direccion, memoria

    if linea.startswith(".asciiz"):
        texto = _desescapar(_CADENA.search(linea).group(1))
        rellenar(direccion)
        memoria.extend(texto.encode("utf-8"))
        memoria.append(0)
        return BASE_DATOS + len(memoria), memoria

    if linea.startswith(".word"):
        rellenar(direccion)
        for parte in linea[5:].split(","):
            memoria.extend(struct.pack("<i", int(parte.strip(), 0)))
        return BASE_DATOS + len(memoria), memoria

    if linea.startswith(".double"):
        if direccion % 8:
            direccion += 8 - (direccion % 8)
        rellenar(direccion)
        for parte in linea[7:].split(","):
            memoria.extend(struct.pack("<d", float(parte.strip())))
        return BASE_DATOS + len(memoria), memoria

    raise MipsError(f"directiva de datos no soportada: {linea}")  # pragma: no cover


# ===========================================================================
# Emulador
# ===========================================================================

class MipsEmulator:
    """Ejecuta el subconjunto de MIPS que produce el compilador."""

    REGISTROS = (
        ["$zero", "$at", "$v0", "$v1"]
        + [f"$a{i}" for i in range(4)]
        + [f"$t{i}" for i in range(8)]
        + [f"$s{i}" for i in range(8)]
        + ["$t8", "$t9", "$k0", "$k1", "$gp", "$sp", "$fp", "$ra"]
    )

    def __init__(self, fuente: str, *, max_pasos: int = 20_000_000) -> None:
        self.programa = ensamblar(fuente)
        self.max_pasos = max_pasos

        self.regs: dict[str, int] = {nombre: 0 for nombre in self.REGISTROS}
        self.fregs: dict[int, int] = {i: 0 for i in range(32)}
        self.lo = 0
        self.hi = 0
        self.fpcond = False

        self.memoria = bytearray(TAM_MEMORIA)
        inicial = self.programa.memoria_inicial
        self.memoria[0: len(inicial)] = inicial

        self.heap = self._alinear(self.programa.fin_datos, 8)
        self.regs["$sp"] = TOPE_PILA
        self.regs["$fp"] = TOPE_PILA
        self.regs["$gp"] = BASE_DATOS

        self.salida: list[str] = []
        self._buffer = ""
        self.pasos = 0
        self.terminado = False

    # -- memoria -------------------------------------------------------------
    @staticmethod
    def _alinear(direccion: int, a: int) -> int:
        resto = direccion % a
        return direccion if resto == 0 else direccion + (a - resto)

    def _indice(self, direccion: int) -> int:
        indice = direccion - BASE_DATOS
        if not 0 <= indice < TAM_MEMORIA - 8:
            raise MipsError(f"acceso a memoria fuera de rango: 0x{direccion:08x}")
        return indice

    def leer_palabra(self, direccion: int) -> int:
        i = self._indice(direccion)
        return struct.unpack_from("<I", self.memoria, i)[0]

    def escribir_palabra(self, direccion: int, valor: int) -> None:
        struct.pack_into("<I", self.memoria, self._indice(direccion), u32(valor))

    def leer_byte(self, direccion: int) -> int:
        return self.memoria[self._indice(direccion)]

    def escribir_byte(self, direccion: int, valor: int) -> None:
        self.memoria[self._indice(direccion)] = valor & 0xFF

    def leer_doble(self, direccion: int) -> float:
        return struct.unpack_from("<d", self.memoria, self._indice(direccion))[0]

    def escribir_doble(self, direccion: int, valor: float) -> None:
        struct.pack_into("<d", self.memoria, self._indice(direccion), valor)

    def leer_cadena(self, direccion: int) -> str:
        bytes_ = bytearray()
        while True:
            byte = self.leer_byte(direccion)
            if byte == 0:
                break
            bytes_.append(byte)
            direccion += 1
        return bytes_.decode("utf-8", errors="replace")

    # -- registros -------------------------------------------------------------
    def leer(self, nombre: str) -> int:
        if nombre == "$zero":
            return 0
        if nombre not in self.regs:
            raise MipsError(f"registro desconocido: {nombre}")
        return self.regs[nombre]

    def escribir(self, nombre: str, valor: int) -> None:
        if nombre == "$zero":
            return
        if nombre not in self.regs:
            raise MipsError(f"registro desconocido: {nombre}")
        self.regs[nombre] = u32(valor)

    @staticmethod
    def _indice_f(nombre: str) -> int:
        return int(nombre[2:])

    def leer_d(self, nombre: str) -> float:
        i = self._indice_f(nombre)
        return struct.unpack("<d", struct.pack("<II", self.fregs[i], self.fregs[i + 1]))[0]

    def escribir_d(self, nombre: str, valor: float) -> None:
        i = self._indice_f(nombre)
        bajo, alto = struct.unpack("<II", struct.pack("<d", valor))
        self.fregs[i] = bajo
        self.fregs[i + 1] = alto

    # -- operandos -----------------------------------------------------------------
    def inmediato(self, texto: str) -> int:
        texto = texto.strip()
        if texto in self.regs or texto == "$zero":
            return self.leer(texto)
        if texto in self.programa.datos:
            return self.programa.datos[texto]
        try:
            return int(texto, 0)
        except ValueError as error:
            raise MipsError(f"operando no reconocido: {texto}") from error

    def direccion(self, texto: str) -> int:
        """Resuelve ``12($fp)``, ``etiqueta`` o ``etiqueta+8``."""
        texto = texto.strip()
        coincidencia = re.match(r"^(-?\w+)?\((\$\w+)\)$", texto)
        if coincidencia:
            desplazamiento = int(coincidencia.group(1) or 0)
            return u32(self.leer(coincidencia.group(2)) + desplazamiento)
        if "+" in texto:
            base, mas = texto.split("+", 1)
            return u32(self.direccion(base) + int(mas, 0))
        if texto in self.programa.datos:
            return self.programa.datos[texto]
        if texto in self.programa.etiquetas:
            return self.direccion_de_codigo(self.programa.etiquetas[texto])
        raise MipsError(f"direccion no reconocida: {texto}")  # pragma: no cover

    @staticmethod
    def direccion_de_codigo(indice: int) -> int:
        """Direccion que le corresponde a la instruccion numero ``indice``."""
        return BASE_CODIGO + indice * 4

    @staticmethod
    def indice_de_codigo(direccion: int) -> int:
        indice = (u32(direccion) - BASE_CODIGO) // 4
        if indice < 0:
            raise MipsError(f"salto a una direccion que no es codigo: 0x{direccion:08x}")
        return indice

    # ======================================================================
    # Ejecucion
    # ======================================================================
    def run(self, entrada: str = "main") -> list[str]:
        if entrada not in self.programa.etiquetas:
            raise MipsError(f"no existe la etiqueta de entrada '{entrada}'")
        pc = self.programa.etiquetas[entrada]

        while not self.terminado:
            self.pasos += 1
            if self.pasos > self.max_pasos:
                raise MipsError("limite de pasos excedido (posible bucle infinito)")
            if not 0 <= pc < len(self.programa.instrucciones):
                raise MipsError(f"el contador de programa se salio del codigo: {pc}")
            instruccion = self.programa.instrucciones[pc]
            siguiente = self.ejecutar(instruccion, pc)
            pc = pc + 1 if siguiente is None else siguiente

        if self._buffer:
            self.salida.append(self._buffer)
            self._buffer = ""
        return self.salida

    def _destino(self, etiqueta: str) -> int:
        etiqueta = etiqueta.strip()
        if etiqueta not in self.programa.etiquetas:
            raise MipsError(f"etiqueta inexistente: {etiqueta}")
        return self.programa.etiquetas[etiqueta]

    def ejecutar(self, ins: Instruccion, pc: int) -> Optional[int]:
        op, a = ins.op, ins.args
        metodo = getattr(self, f"_i_{op.replace('.', '_')}", None)
        if metodo is None:
            raise MipsError(f"instruccion no soportada por el emulador: '{ins.texto}'")
        return metodo(a, pc)

    # -- aritmetica entera -----------------------------------------------------------
    def _i_add(self, a, pc):
        self.escribir(a[0], s32(self.leer(a[1])) + s32(self.inmediato(a[2])))

    _i_addu = _i_add

    def _i_addiu(self, a, pc):
        self.escribir(a[0], s32(self.leer(a[1])) + int(a[2], 0))

    def _i_sub(self, a, pc):
        self.escribir(a[0], s32(self.leer(a[1])) - s32(self.inmediato(a[2])))

    _i_subu = _i_sub

    def _i_mul(self, a, pc):
        self.escribir(a[0], s32(self.leer(a[1])) * s32(self.inmediato(a[2])))

    def _i_div(self, a, pc):
        if len(a) == 2:
            divisor = s32(self.leer(a[1]))
            if divisor == 0:
                raise MipsError("division entre cero")
            dividendo = s32(self.leer(a[0]))
            self.lo = u32(int(dividendo / divisor))
            self.hi = u32(dividendo - int(dividendo / divisor) * divisor)
            return None
        divisor = s32(self.inmediato(a[2]))
        if divisor == 0:
            raise MipsError("division entre cero")
        self.escribir(a[0], int(s32(self.leer(a[1])) / divisor))

    def _i_divu(self, a, pc):
        divisor = self.leer(a[1])
        if divisor == 0:
            raise MipsError("division entre cero")
        dividendo = self.leer(a[0])
        self.lo = u32(dividendo // divisor)
        self.hi = u32(dividendo % divisor)

    def _i_rem(self, a, pc):
        divisor = s32(self.inmediato(a[2]))
        if divisor == 0:
            raise MipsError("division entre cero")
        dividendo = s32(self.leer(a[1]))
        self.escribir(a[0], dividendo - int(dividendo / divisor) * divisor)

    def _i_negu(self, a, pc):
        self.escribir(a[0], -s32(self.leer(a[1])))

    def _i_mflo(self, a, pc):
        self.escribir(a[0], self.lo)

    def _i_mfhi(self, a, pc):
        self.escribir(a[0], self.hi)

    def _i_srl(self, a, pc):
        self.escribir(a[0], self.leer(a[1]) >> int(a[2], 0))

    def _i_sll(self, a, pc):
        self.escribir(a[0], self.leer(a[1]) << int(a[2], 0))

    def _i_xori(self, a, pc):
        self.escribir(a[0], self.leer(a[1]) ^ int(a[2], 0))

    # -- comparaciones ---------------------------------------------------------------
    def _comparar(self, a, operacion) -> None:
        self.escribir(a[0], 1 if operacion(s32(self.leer(a[1])), s32(self.inmediato(a[2]))) else 0)

    def _i_slt(self, a, pc):
        self._comparar(a, lambda x, y: x < y)

    def _i_sle(self, a, pc):
        self._comparar(a, lambda x, y: x <= y)

    def _i_sgt(self, a, pc):
        self._comparar(a, lambda x, y: x > y)

    def _i_sge(self, a, pc):
        self._comparar(a, lambda x, y: x >= y)

    def _i_seq(self, a, pc):
        self._comparar(a, lambda x, y: x == y)

    def _i_sne(self, a, pc):
        self._comparar(a, lambda x, y: x != y)

    # -- movimiento y memoria -----------------------------------------------------------
    def _i_li(self, a, pc):
        self.escribir(a[0], int(a[1], 0))

    def _i_la(self, a, pc):
        self.escribir(a[0], self.direccion(a[1]))

    def _i_move(self, a, pc):
        self.escribir(a[0], self.leer(a[1]))

    def _i_lw(self, a, pc):
        self.escribir(a[0], self.leer_palabra(self.direccion(a[1])))

    def _i_sw(self, a, pc):
        self.escribir_palabra(self.direccion(a[1]), self.leer(a[0]))

    def _i_lb(self, a, pc):
        byte = self.leer_byte(self.direccion(a[1]))
        self.escribir(a[0], byte - 256 if byte & 0x80 else byte)

    def _i_sb(self, a, pc):
        self.escribir_byte(self.direccion(a[1]), self.leer(a[0]))

    # -- saltos -------------------------------------------------------------------------
    def _i_j(self, a, pc):
        return self._destino(a[0])

    def _i_jal(self, a, pc):
        self.escribir("$ra", self.direccion_de_codigo(pc + 1))
        return self._destino(a[0])

    def _i_jr(self, a, pc):
        return self.indice_de_codigo(self.leer(a[0]))

    def _i_jalr(self, a, pc):
        destino = self.indice_de_codigo(self.leer(a[0]))
        self.escribir("$ra", self.direccion_de_codigo(pc + 1))
        return destino

    def _saltar_si(self, condicion: bool, etiqueta: str) -> Optional[int]:
        return self._destino(etiqueta) if condicion else None

    def _i_beq(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) == s32(self.inmediato(a[1])), a[2])

    def _i_bne(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) != s32(self.inmediato(a[1])), a[2])

    def _i_blt(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) < s32(self.inmediato(a[1])), a[2])

    def _i_ble(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) <= s32(self.inmediato(a[1])), a[2])

    def _i_bgt(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) > s32(self.inmediato(a[1])), a[2])

    def _i_bge(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) >= s32(self.inmediato(a[1])), a[2])

    def _i_bltz(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) < 0, a[1])

    def _i_bgez(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) >= 0, a[1])

    def _i_blez(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) <= 0, a[1])

    def _i_bgtz(self, a, pc):
        return self._saltar_si(s32(self.leer(a[0])) > 0, a[1])

    # -- punto flotante ---------------------------------------------------------------------
    def _i_l_d(self, a, pc):
        direccion = self.direccion(a[1])
        self._exigir_alineacion(direccion, 8, a[1])
        self.escribir_d(a[0], self.leer_doble(direccion))

    def _i_s_d(self, a, pc):
        direccion = self.direccion(a[1])
        self._exigir_alineacion(direccion, 8, a[1])
        self.escribir_doble(direccion, self.leer_d(a[0]))

    def _i_lwc1(self, a, pc):
        """Carga media palabra del par de doble precision."""
        direccion = self.direccion(a[1])
        self._exigir_alineacion(direccion, 4, a[1])
        self.fregs[self._indice_f(a[0])] = self.leer_palabra(direccion)

    def _i_swc1(self, a, pc):
        direccion = self.direccion(a[1])
        self._exigir_alineacion(direccion, 4, a[1])
        self.escribir_palabra(direccion, self.fregs[self._indice_f(a[0])])

    def _exigir_alineacion(self, direccion: int, multiplo: int, texto: str) -> None:
        """MARS aborta si la direccion no esta alineada; el emulador tambien.

        Sin esta comprobacion el emulador seria mas permisivo que el simulador
        externo y dejaria pasar ensamblador que MARS rechaza.
        """
        if direccion % multiplo:
            raise MipsError(
                f"direccion no alineada a {multiplo} bytes: {texto} = 0x{direccion:08x}"
            )

    def _i_mov_d(self, a, pc):
        self.escribir_d(a[0], self.leer_d(a[1]))

    def _i_add_d(self, a, pc):
        self.escribir_d(a[0], self.leer_d(a[1]) + self.leer_d(a[2]))

    def _i_sub_d(self, a, pc):
        self.escribir_d(a[0], self.leer_d(a[1]) - self.leer_d(a[2]))

    def _i_mul_d(self, a, pc):
        self.escribir_d(a[0], self.leer_d(a[1]) * self.leer_d(a[2]))

    def _i_div_d(self, a, pc):
        divisor = self.leer_d(a[2])
        if divisor == 0.0:
            raise MipsError("division entre cero")
        self.escribir_d(a[0], self.leer_d(a[1]) / divisor)

    def _i_neg_d(self, a, pc):
        self.escribir_d(a[0], -self.leer_d(a[1]))

    def _i_c_lt_d(self, a, pc):
        self.fpcond = self.leer_d(a[0]) < self.leer_d(a[1])

    def _i_c_le_d(self, a, pc):
        self.fpcond = self.leer_d(a[0]) <= self.leer_d(a[1])

    def _i_c_eq_d(self, a, pc):
        self.fpcond = self.leer_d(a[0]) == self.leer_d(a[1])

    def _i_bc1t(self, a, pc):
        return self._saltar_si(self.fpcond, a[0])

    def _i_bc1f(self, a, pc):
        return self._saltar_si(not self.fpcond, a[0])

    def _i_mtc1(self, a, pc):
        self.fregs[self._indice_f(a[1])] = self.leer(a[0])

    def _i_mfc1(self, a, pc):
        self.escribir(a[0], self.fregs[self._indice_f(a[1])])

    def _i_cvt_d_w(self, a, pc):
        entero = s32(self.fregs[self._indice_f(a[1])])
        self.escribir_d(a[0], float(entero))

    def _i_cvt_w_d(self, a, pc):
        valor = self.leer_d(a[1])
        # cvt.w.d redondea al entero mas cercano (modo por defecto).
        self.fregs[self._indice_f(a[0])] = u32(int(_redondear(valor)))

    def _i_trunc_w_d(self, a, pc):
        self.fregs[self._indice_f(a[0])] = u32(int(self.leer_d(a[1])))

    # -- llamadas al sistema -------------------------------------------------------------------
    def _i_syscall(self, a, pc):
        servicio = self.leer("$v0")
        if servicio == 1:                                   # imprimir entero
            self._imprimir(str(s32(self.leer("$a0"))))
        elif servicio == 4:                                 # imprimir cadena
            self._imprimir(self.leer_cadena(self.leer("$a0")))
        elif servicio == 3:                                 # imprimir doble
            self._imprimir(repr(self.leer_d("$f12")))
        elif servicio == 11:                                # imprimir caracter
            self._imprimir(chr(self.leer("$a0") & 0xFF))
        elif servicio == 9:                                 # sbrk
            cantidad = self.leer("$a0")
            direccion = self.heap
            self.heap = self._alinear(self.heap + max(cantidad, 4), 8)
            if self.heap >= TOPE_PILA - 1024:
                raise MipsError("monticulo agotado")
            self.escribir("$v0", direccion)
        elif servicio == 10:                                # salir
            self.terminado = True
        else:
            raise MipsError(f"syscall no soportada: {servicio}")
        return None

    def _imprimir(self, texto: str) -> None:
        self._buffer += texto
        while "\n" in self._buffer:
            linea, self._buffer = self._buffer.split("\n", 1)
            self.salida.append(linea)


def _redondear(valor: float) -> int:
    """Redondeo al entero mas cercano, como hace ``cvt.w.d``."""
    import math

    piso = math.floor(valor)
    resto = valor - piso
    if resto > 0.5:
        return piso + 1
    if resto < 0.5:
        return piso
    return piso if piso % 2 == 0 else piso + 1


def run(fuente: str, *, entrada: str = "main", max_pasos: int = 20_000_000) -> list[str]:
    """Ensambla y ejecuta ``fuente``; devuelve las lineas impresas."""
    return MipsEmulator(fuente, max_pasos=max_pasos).run(entrada)
