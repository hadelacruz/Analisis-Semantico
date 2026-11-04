"""Generación de código MIPS a partir del código de tres direcciones.

Cuarta y última pasada del compilador. Recorre el :class:`TACProgram` que
produjo la fase anterior y emite ensamblador MIPS compatible con **MARS** y
**SPIM**.

Lo que resuelve esta fase
-------------------------
* **Registros.** El TAC supone temporales ilimitados; aquí los reparte
  ``getReg()`` (ver ``registers.py``) y lo que no cabe se vuelca a la pila.
* **Secuencias de llamada y retorno.** Prólogo y epílogo de cada rutina,
  gestión de ``$sp`` y ``$fp``, y paso de argumentos sin perder el estado.
* **Representación física de los datos.** Lo que la máquina virtual del TAC
  podía tratar como valores de Python —cadenas, dobles, objetos— aquí tiene
  que ocupar bytes concretos.

Distribución del marco
----------------------
Coincide con la que ya describía la tabla de símbolos, más el ``$ra`` que
MIPS obliga a guardar::

    direcciones altas
    +---------------------------+
    | parametro n               |   los empuja el llamador
    | ...                       |
    | parametro 0               |   fp+8  (si es metodo, aqui va 'this')
    | direccion de retorno ($ra)|   fp+4
    | $fp del llamador          |   fp+0   <- fp
    | enlace de acceso          |   fp-4
    | variables locales         |   fp-8 ...
    | temporales                |
    +---------------------------+   <- sp
    direcciones bajas
"""
from __future__ import annotations

from typing import Optional

from ..scope import SymbolTable
from ..symbols import (
    LOCAL_BASE_OFFSET,
    PARAM_BASE_OFFSET,
    StorageKind,
)
from ..tac import runtime as rt
from ..tac.quadruple import Op, Operand, OperandKind, Quadruple, TACFunction, TACProgram
from ..types import BOOLEAN, FLOAT, INTEGER, STRING
from .asm import MipsProgram, escapar_cadena
from .registers import (
    BORRADOR,
    BORRADOR_FLOTANTE,
    ENLACE_ACCESO,
    RETORNO,
    RETORNO_FLOTANTE,
    RegisterAllocator,
)
from .runtime import BIBLIOTECA

#: Bytes que ocupa cada temporal en el marco. Se reservan 8 y no 4 porque un
#: temporal puede contener un doble.
BYTES_POR_TEMPORAL = 8
#: Bytes que el prólogo guarda por encima de ``fp``: ``$ra`` y el ``$fp`` viejo.
AREA_GUARDADA = 8
#: Etiqueta del bloque de variables globales.
ETIQUETA_GLOBALES = "__globals"
#: Etiqueta de la pila de manejadores de excepciones.
ETIQUETA_MANEJADORES = "__handlers"
#: Profundidad máxima de ``try`` anidados.
MAX_MANEJADORES = 32


class MipsGenerator:
    """Traduce un programa TAC a ensamblador MIPS."""

    def __init__(
        self,
        tac: TACProgram,
        table: Optional[SymbolTable] = None,
        *,
        comments: bool = True,
    ) -> None:
        self.tac = tac
        self.table = table
        self.with_comments = comments
        self.out = MipsProgram()
        self.out.with_comments = comments

        self.regs = RegisterAllocator(self._cargar, self._volcar)

        # --- tablas de la seccion de datos --------------------------------
        self.cadenas: dict[str, str] = {}      # texto -> etiqueta
        self.dobles: dict[float, str] = {}     # valor -> etiqueta
        self.especiales: set[str] = set()      # vtable_X y similares
        self.tam_globales = 0

        # --- estado del recorrido -------------------------------------------
        self.funcion: Optional[TACFunction] = None
        self.params_pendientes: list[Operand] = []
        self._contador_interno = 0
        #: Totales del asignador, sumando todas las rutinas.
        self._totales = {"reutilizaciones": 0, "cargas": 0, "volcados": 0}

    # ======================================================================
    # Claves y posiciones de los valores
    # ======================================================================
    @staticmethod
    def es_flotante(operando: Optional[Operand]) -> bool:
        return operando is not None and operando.type is FLOAT

    @staticmethod
    def clave(operando: Operand) -> str:
        """Identificador estable de un valor, para los descriptores."""
        if operando.kind is OperandKind.TEMP:
            return f"t:{operando.value}"
        if operando.kind is OperandKind.VAR:
            if operando.symbol is not None:
                return f"v:{id(operando.symbol)}"
            return f"s:{operando.value}"
        return f"c:{operando.value}"

    def _indice_temporal(self, nombre: str) -> int:
        return int(str(nombre)[1:]) if str(nombre)[1:].isdigit() else 0

    def _desplazamiento_parametro(self, offset: int) -> int:
        """Los métodos reciben ``this`` como primer argumento."""
        extra = 4 if (self.funcion is not None and self.funcion.is_method) else 0
        return PARAM_BASE_OFFSET + extra + offset

    def posicion(self, operando: Operand) -> tuple[str, str]:
        """Dónde vive un valor: ``(modo, expresion)``.

        ``modo`` es ``"marco"`` (desplazamiento sobre ``$fp``), ``"global"``
        (etiqueta en ``.data``) o ``"registro"`` (``$fp``, que no se guarda).
        """
        if operando.kind is OperandKind.TEMP:
            base = LOCAL_BASE_OFFSET - self._local_size()
            indice = self._indice_temporal(operando.value)
            return "marco", str(base - indice * BYTES_POR_TEMPORAL)

        if operando.kind is OperandKind.VAR:
            if operando.symbol is None:
                nombre = str(operando.value)
                if nombre == "fp":
                    return "registro", "$fp"
                if nombre == "this":
                    return "marco", str(PARAM_BASE_OFFSET)
                self.especiales.add(nombre)
                return "global", nombre

            simbolo = operando.symbol
            if simbolo.storage is StorageKind.GLOBAL:
                return "global_off", str(simbolo.offset or 0)
            if simbolo.storage is StorageKind.PARAM:
                return "marco", str(self._desplazamiento_parametro(simbolo.offset or 0))
            return "marco", str(LOCAL_BASE_OFFSET - (simbolo.offset or 0))

        raise RuntimeError(f"operando sin posicion: {operando}")  # pragma: no cover

    def _local_size(self) -> int:
        return self.funcion.local_size if self.funcion is not None else 0

    # ======================================================================
    # Carga y volcado (los que usa el asignador de registros)
    # ======================================================================
    def _operando_de_clave(self, clave: str) -> Optional[Operand]:
        return self._mapa_claves.get(clave)

    def _recordar(self, operando: Operand) -> str:
        clave = self.clave(operando)
        self._mapa_claves[clave] = operando
        return clave

    # -- movimiento de dobles ------------------------------------------------------
    @staticmethod
    def _registro_alto(registro: str) -> str:
        """La mitad alta del par de doble precision: ``$f4`` -> ``$f5``."""
        return f"$f{int(registro[2:]) + 1}"

    @staticmethod
    def _desplazar(memoria: str, delta: int) -> str:
        """``44($t9)`` -> ``48($t9)``."""
        desplazamiento, _, base = memoria.partition("(")
        return f"{int(desplazamiento or 0) + delta}({base}"

    def _mover_doble(
        self, guardar: bool, registro: str, memoria: str, comentario: str = ""
    ) -> None:
        """Mueve un doble entre un registro y la memoria, en dos palabras.

        ``l.d``/``s.d`` se expanden a ``ldc1``/``sdc1``, que exigen una
        direccion multiplo de 8; MARS aborta si no lo es. Los desplazamientos
        que asigna el analisis semantico no lo garantizan (un ``float`` puede
        caer en un desplazamiento 44), y ``$sp`` tampoco llega alineado a 8 en
        MARS. Dos transferencias de palabra solo necesitan alineacion de 4, que
        si esta garantizada. En little-endian la palabra baja va en el registro
        par y la alta en el impar.
        """
        operacion = "swc1" if guardar else "lwc1"
        self.out.emit(operacion, registro, memoria, comentario=comentario)
        self.out.emit(
            operacion, self._registro_alto(registro), self._desplazar(memoria, 4)
        )

    def _cargar(self, registro: str, clave: str) -> None:
        operando = self._operando_de_clave(clave)
        if operando is None:  # pragma: no cover - defensivo
            return
        modo, lugar = self.posicion(operando)
        flotante = self.es_flotante(operando)

        if modo == "registro":
            self.out.emit("move", registro, lugar)
        elif modo == "marco":
            if flotante:
                self._mover_doble(False, registro, f"{lugar}($fp)", self._nota(operando))
            else:
                self.out.emit("lw", registro, f"{lugar}($fp)", comentario=self._nota(operando))
        elif modo == "global":
            self.out.emit("lw", registro, lugar, comentario=self._nota(operando))
        else:  # global_off
            self.out.emit("la", BORRADOR, ETIQUETA_GLOBALES)
            if flotante:
                self._mover_doble(
                    False, registro, f"{lugar}({BORRADOR})", self._nota(operando)
                )
            else:
                self.out.emit(
                    "lw", registro, f"{lugar}({BORRADOR})", comentario=self._nota(operando)
                )

    def _volcar(self, registro: str, clave: str) -> None:
        operando = self._operando_de_clave(clave)
        if operando is None:  # pragma: no cover - defensivo
            return
        modo, lugar = self.posicion(operando)
        flotante = self.es_flotante(operando)
        nota = f"vuelca {self._nota(operando)}"

        if modo == "registro":
            self.out.emit("move", lugar, registro)
        elif modo == "marco":
            if flotante:
                self._mover_doble(True, registro, f"{lugar}($fp)", nota)
            else:
                self.out.emit("sw", registro, f"{lugar}($fp)", comentario=nota)
        elif modo == "global":
            self.out.emit("sw", registro, lugar, comentario=nota)
        else:  # global_off
            self.out.emit("la", BORRADOR, ETIQUETA_GLOBALES)
            if flotante:
                self._mover_doble(True, registro, f"{lugar}({BORRADOR})", nota)
            else:
                self.out.emit("sw", registro, f"{lugar}({BORRADOR})", comentario=nota)

    def _nota(self, operando: Operand) -> str:
        if not self.with_comments:
            return ""
        if operando.kind is OperandKind.VAR and operando.symbol is not None:
            return operando.symbol.name
        return str(operando.value)

    # ======================================================================
    # Materialización de operandos en registros
    # ======================================================================
    def valor(self, operando: Operand) -> str:
        """Registro que contiene el valor de ``operando``."""
        if operando.kind is OperandKind.CONST:
            return self._constante(operando)
        if operando.kind in (OperandKind.LABEL, OperandKind.FUNC):
            registro = self.regs.get_reg(f"lbl:{operando.value}", cargar=False)
            self.out.emit("la", registro, str(operando.value))
            return registro
        clave = self._recordar(operando)
        return self.regs.get_reg(clave, flotante=self.es_flotante(operando))

    def destino(self, operando: Operand) -> str:
        """Registro donde se va a escribir ``operando``."""
        clave = self._recordar(operando)
        return self.regs.destino(clave, flotante=self.es_flotante(operando))

    def _constante(self, operando: Operand) -> str:
        valor = operando.value
        if isinstance(valor, bool):
            registro = self.regs.get_reg(f"c:bool:{valor}", cargar=False)
            self.out.emit("li", registro, "1" if valor else "0")
            return registro
        if valor is None:
            registro = self.regs.get_reg("c:null", cargar=False)
            self.out.emit("li", registro, "0", comentario="null")
            return registro
        if isinstance(valor, float) or operando.type is FLOAT:
            etiqueta = self._literal_doble(float(valor))
            registro = self.regs.get_reg(f"c:f:{valor}", flotante=True, cargar=False)
            self.out.emit("la", BORRADOR, etiqueta)
            self.out.emit("l.d", registro, f"0({BORRADOR})", comentario=str(valor))
            return registro
        if isinstance(valor, str):
            etiqueta = self._literal_cadena(valor)
            registro = self.regs.get_reg(f"c:s:{etiqueta}", cargar=False)
            self.out.emit("la", registro, etiqueta, comentario=escapar_cadena(valor)[:28])
            return registro
        registro = self.regs.get_reg(f"c:i:{valor}", cargar=False)
        self.out.emit("li", registro, str(int(valor)))
        return registro

    def _literal_cadena(self, texto: str) -> str:
        if texto not in self.cadenas:
            self.cadenas[texto] = f"__str{len(self.cadenas)}"
        return self.cadenas[texto]

    def _literal_doble(self, valor: float) -> str:
        if valor not in self.dobles:
            self.dobles[valor] = f"__dbl{len(self.dobles)}"
        return self.dobles[valor]

    def _etiqueta_interna(self, pista: str) -> str:
        """Etiqueta auxiliar dentro de la expansión de una sola instrucción."""
        self._contador_interno += 1
        return f"__{pista}{self._contador_interno}"

    # ======================================================================
    # Punto de entrada
    # ======================================================================
    def generate(self) -> MipsProgram:
        """Traduce el programa TAC completo."""
        self._mapa_claves: dict[str, Operand] = {}

        self._recolectar()
        self._emitir_datos()

        for funcion in self.tac.functions:
            self._emitir_funcion(funcion)

        self.out.separador("Biblioteca de apoyo (runtime)")
        for linea in BIBLIOTECA.splitlines():
            self.out.bruto(linea)
        return self.out

    # ----------------------------------------------------------------------
    # Pasada A: recoleccion
    # ----------------------------------------------------------------------
    def _recolectar(self) -> None:
        """Recorre el TAC juntando literales y nombres que iran en ``.data``."""
        for quad in self.tac.instructions:
            for operando in (quad.arg1, quad.arg2, quad.result):
                if operando is None:
                    continue
                if operando.kind is OperandKind.CONST:
                    valor = operando.value
                    if isinstance(valor, str):
                        self._literal_cadena(valor)
                    elif isinstance(valor, float) or (
                        operando.type is FLOAT and valor is not None and not isinstance(valor, bool)
                    ):
                        self._literal_doble(float(valor))
                elif operando.kind is OperandKind.VAR and operando.symbol is None:
                    nombre = str(operando.value)
                    if nombre not in ("fp", "this"):
                        self.especiales.add(nombre)

        if self.table is not None:
            self.tam_globales = max(self.table.global_scope.next_local_offset, 4)
        else:  # pragma: no cover - solo si se usa el generador suelto
            self.tam_globales = 1024

    def _emitir_datos(self) -> None:
        """Seccion .data: globales, literales y estructuras del runtime."""
        self.out.comentario_dato("variables globales del programa")
        self.out.dato(".align 2")
        self.out.etiqueta_dato(ETIQUETA_GLOBALES)
        self.out.dato(f".space {self.tam_globales}")

        if self.especiales:
            self.out.dato("")
            self.out.comentario_dato("punteros a las tablas de metodos")
            self.out.dato(".align 2")
            for nombre in sorted(self.especiales):
                self.out.etiqueta_dato(nombre)
                self.out.dato(".word 0")

        if self.cadenas:
            self.out.dato("")
            self.out.comentario_dato("literales de cadena")
            for texto, etiqueta in self.cadenas.items():
                self.out.etiqueta_dato(etiqueta)
                self.out.dato(f".asciiz {escapar_cadena(texto)}")

        if self.dobles:
            self.out.dato("")
            self.out.comentario_dato("literales de punto flotante")
            self.out.dato(".align 3")
            for valor, etiqueta in self.dobles.items():
                self.out.etiqueta_dato(etiqueta)
                self.out.dato(f".double {valor!r}")

        self.out.dato("")
        self.out.comentario_dato("pila de manejadores de excepciones")
        self.out.dato(".align 2")
        self.out.etiqueta_dato(ETIQUETA_MANEJADORES)
        self.out.dato(f".space {MAX_MANEJADORES * 12}")
        self.out.etiqueta_dato("__handler_sp")
        self.out.dato(".word 0")
        self.out.etiqueta_dato("__exc_msg")
        self.out.dato(".word 0")

        self.out.dato("")
        self.out.comentario_dato("tope del monticulo (lo mueve __alloc)")
        self.out.dato(".align 2")
        self.out.etiqueta_dato("__heap_ptr")
        self.out.dato(".word 0")

        self.out.dato("")
        self.out.comentario_dato("mensajes del runtime")
        self.out.etiqueta_dato("__msg_true")
        self.out.dato('.asciiz "true"')
        self.out.etiqueta_dato("__msg_false")
        self.out.dato('.asciiz "false"')
        self.out.etiqueta_dato("__msg_null")
        self.out.dato('.asciiz "null"')
        self.out.etiqueta_dato("__msg_uncaught")
        self.out.dato('.asciiz "Excepcion no atrapada: "')
        self.out.etiqueta_dato("__msg_nl")
        self.out.dato('.asciiz "\\n"')
        self.out.etiqueta_dato("__msg_idx1")
        self.out.dato('.asciiz "indice "')
        self.out.etiqueta_dato("__msg_idx2")
        self.out.dato('.asciiz " fuera del rango del arreglo (0.."')
        self.out.etiqueta_dato("__msg_idx3")
        self.out.dato('.asciiz ")"')
        self.out.etiqueta_dato("__msg_divzero")
        self.out.dato('.asciiz "division entre cero"')
        self.out.dato(".align 2")
        self.out.etiqueta_dato("__buf")
        self.out.dato(".space 64")
        self.out.etiqueta_dato("__buf2")
        self.out.dato(".space 32")

    # ----------------------------------------------------------------------
    # Pasada B: una rutina
    # ----------------------------------------------------------------------
    def _emitir_funcion(self, funcion: TACFunction) -> None:
        self.funcion = funcion
        self.regs = RegisterAllocator(self._cargar, self._volcar)
        self.params_pendientes = []

        titulo = f"rutina {funcion.label}"
        if funcion.is_method:
            titulo += f"   (metodo de {funcion.owner})"
        self.out.separador(titulo)

        self._prologo(funcion)
        for indice in range(funcion.start, funcion.end + 1):
            quad = self.tac.instructions[indice]
            if quad.op in (Op.FUNC_BEGIN, Op.FUNC_END):
                continue
            self._traducir(quad)

        # Cada rutina usa su propio asignador (los registros no sobreviven a
        # una llamada), asi que las cifras se van sumando aqui.
        for clave in self._totales:
            self._totales[clave] += getattr(self.regs, clave)
        self.funcion = None

    def marco_bajo_fp(self, funcion: TACFunction) -> int:
        """Bytes que el prologo reserva por debajo de ``fp``."""
        return 4 + funcion.local_size + funcion.temp_count * BYTES_POR_TEMPORAL

    def _prologo(self, funcion: TACFunction) -> None:
        self.out.etiqueta(funcion.label)
        self.out.emit("addiu", "$sp", "$sp", "-8", comentario="espacio para $ra y el $fp viejo")
        self.out.emit("sw", "$ra", "4($sp)", comentario="fp+4 = direccion de retorno")
        self.out.emit("sw", "$fp", "0($sp)", comentario="fp+0 = enlace de control")
        self.out.emit("move", "$fp", "$sp", comentario="fp apunta al enlace de control")

        bajo = self.marco_bajo_fp(funcion)
        if bajo:
            self.out.emit(
                "addiu", "$sp", "$sp", f"-{bajo}",
                comentario=f"enlace de acceso + {funcion.local_size}B locales + "
                           f"{funcion.temp_count} temporales",
            )
        simbolo = funcion.symbol
        if simbolo is not None and simbolo.nesting_level > 0:
            self.out.emit(
                "sw", ENLACE_ACCESO, "-4($fp)", comentario="enlace de acceso (marco del padre)"
            )

    def _epilogo(self) -> None:
        if self.funcion is not None and self.funcion.label == "main":
            self.out.emit("li", RETORNO, "10", comentario="fin del programa")
            self.out.emit("syscall")
            return
        self.out.emit("move", "$sp", "$fp", comentario="libera locales y temporales")
        self.out.emit("lw", "$ra", "4($sp)")
        self.out.emit("lw", "$fp", "0($sp)", comentario="restaura el marco del llamador")
        self.out.emit("addiu", "$sp", "$sp", "8")
        self.out.emit("jr", "$ra")

    # ======================================================================
    # Traduccion instruccion a instruccion
    # ======================================================================
    def _traducir(self, quad: Quadruple) -> None:
        if quad.op is Op.COMMENT:
            if self.with_comments and quad.comment:
                self.out.comentario(quad.comment)
            return

        if self.with_comments and quad.op not in (Op.LABEL, Op.PARAM):
            self.out.comentario(quad.text())

        manejador = {
            Op.ASSIGN: self._t_assign,
            Op.BINARY: self._t_binary,
            Op.UNARY: self._t_unary,
            Op.INDEX_LOAD: self._t_index_load,
            Op.INDEX_STORE: self._t_index_store,
            Op.LABEL: self._t_label,
            Op.GOTO: self._t_goto,
            Op.IF_GOTO: self._t_if_goto,
            Op.IFFALSE_GOTO: self._t_iffalse_goto,
            Op.IF_REL_GOTO: self._t_if_rel_goto,
            Op.PARAM: self._t_param,
            Op.CALL: self._t_call,
            Op.CALL_INDIRECT: self._t_call,
            Op.RETURN: self._t_return,
            Op.SET_ACCESS_LINK: self._t_set_access_link,
            Op.PUSH_HANDLER: self._t_push_handler,
            Op.POP_HANDLER: self._t_pop_handler,
        }.get(quad.op)
        if manejador is None:  # pragma: no cover - defensivo
            raise RuntimeError(f"instruccion TAC sin traduccion: {quad.op}")
        manejador(quad)
        self.regs.soltar_todos()

    # -- movimiento de datos -------------------------------------------------
    def _t_assign(self, quad: Quadruple) -> None:
        flotante = self.es_flotante(quad.result)
        if flotante:
            origen = self._como_doble(quad.arg1)
            self.regs.fijar(origen)
            destino = self.destino(quad.result)
            self.out.emit("mov.d", destino, origen)
            return
        origen = self.valor(quad.arg1)
        self.regs.fijar(origen)
        destino = self.destino(quad.result)
        self.out.emit("move", destino, origen)

    # -- aritmetica y comparaciones -------------------------------------------
    ENTERAS = {"+": "addu", "-": "subu", "*": "mul", "/": "div", "%": "rem"}
    COMPARACIONES = {"<": "slt", "<=": "sle", ">": "sgt", ">=": "sge", "==": "seq", "!=": "sne"}
    SALTOS = {"<": "blt", "<=": "ble", ">": "bgt", ">=": "bge", "==": "beq", "!=": "bne"}
    #: Para flotantes MIPS solo tiene tres comparaciones; el resto se obtiene
    #: intercambiando los operandos o negando el resultado.
    COMPARACIONES_DOBLES = {
        "<": ("c.lt.d", False, False),
        "<=": ("c.le.d", False, False),
        ">": ("c.lt.d", True, False),
        ">=": ("c.le.d", True, False),
        "==": ("c.eq.d", False, False),
        "!=": ("c.eq.d", False, True),
    }

    def _operacion_es_doble(self, quad: Quadruple) -> bool:
        if quad.result is not None and quad.result.type is FLOAT:
            return True
        if quad.operator in self.COMPARACIONES:
            return self.es_flotante(quad.arg1) or self.es_flotante(quad.arg2)
        return False

    def _operacion_es_cadena(self, quad: Quadruple) -> bool:
        return (quad.arg1 is not None and quad.arg1.type is STRING) or (
            quad.arg2 is not None and quad.arg2.type is STRING
        )

    def _como_doble(self, operando: Operand) -> str:
        """Registro de punto flotante con el valor de ``operando``.

        Si el operando es entero lo convierte: una suma como ``1 + IVA`` mezcla
        un literal entero con un doble.
        """
        if self.es_flotante(operando):
            return self.valor(operando)
        entero = self.valor(operando)
        self.regs.fijar(entero)
        destino = self.regs.get_reg(f"conv:{self.clave(operando)}", flotante=True, cargar=False)
        self.out.emit("mtc1", entero, BORRADOR_FLOTANTE, comentario="entero -> FPU")
        self.out.emit("cvt.d.w", destino, BORRADOR_FLOTANTE, comentario="entero -> doble")
        return destino

    def _t_binary(self, quad: Quadruple) -> None:
        operador = quad.operator

        if self._operacion_es_cadena(quad) and operador in self.COMPARACIONES:
            self._comparar_cadenas(quad)
            return
        if self._operacion_es_doble(quad):
            self._binaria_doble(quad)
            return

        izquierdo = self.valor(quad.arg1)
        self.regs.fijar(izquierdo)
        derecho = self.valor(quad.arg2)
        self.regs.fijar(izquierdo, derecho)
        destino = self.destino(quad.result)

        if operador in ("/", "%") and not (
            quad.arg2.kind is OperandKind.CONST and quad.arg2.value not in (0, 0.0, None)
        ):
            # Una division entre cero tiene que poder atraparse con try/catch,
            # asi que se comprueba salvo cuando el divisor es una constante
            # distinta de cero y el compilador ya sabe que no puede fallar.
            self.out.emit("beq", derecho, "$zero", "__div_zero")

        if operador in self.ENTERAS:
            self.out.emit(self.ENTERAS[operador], destino, izquierdo, derecho)
        else:
            self.out.emit(self.COMPARACIONES[operador], destino, izquierdo, derecho)

    def _binaria_doble(self, quad: Quadruple) -> None:
        operador = quad.operator
        izquierdo = self._como_doble(quad.arg1)
        self.regs.fijar(izquierdo)
        derecho = self._como_doble(quad.arg2)
        self.regs.fijar(izquierdo, derecho)

        if operador in self.ENTERAS:
            destino = self.destino(quad.result)
            sufijo = {"+": "add.d", "-": "sub.d", "*": "mul.d", "/": "div.d"}[operador]
            self.out.emit(sufijo, destino, izquierdo, derecho)
            return

        # Comparacion: el resultado es un entero 0/1.
        instruccion, intercambiar, negar = self.COMPARACIONES_DOBLES[operador]
        a, b = (derecho, izquierdo) if intercambiar else (izquierdo, derecho)
        destino = self.destino(quad.result)
        fin = self._etiqueta_interna("cmp")
        self.out.emit("li", destino, "1" if not negar else "0")
        self.out.emit(instruccion, a, b)
        self.out.emit("bc1t", fin)
        self.out.emit("li", destino, "0" if not negar else "1")
        self.out.etiqueta(fin)

    def _comparar_cadenas(self, quad: Quadruple) -> None:
        """Las comparaciones de cadenas se delegan en ``__str_cmp``."""
        izquierdo = self.valor(quad.arg1)
        self.regs.fijar(izquierdo)
        derecho = self.valor(quad.arg2)
        self.out.emit("move", "$a0", izquierdo)
        self.out.emit("move", "$a1", derecho)
        self.regs.volcar_todo()
        self.out.emit("jal", "__str_cmp", comentario="compara dos cadenas")
        destino = self.destino(quad.result)
        self.out.emit(self.COMPARACIONES[quad.operator], destino, RETORNO, "$zero")

    def _t_unary(self, quad: Quadruple) -> None:
        if quad.operator == "-":
            if self.es_flotante(quad.result):
                origen = self._como_doble(quad.arg1)
                self.regs.fijar(origen)
                destino = self.destino(quad.result)
                self.out.emit("neg.d", destino, origen)
                return
            origen = self.valor(quad.arg1)
            self.regs.fijar(origen)
            destino = self.destino(quad.result)
            self.out.emit("negu", destino, origen)
            return
        origen = self.valor(quad.arg1)
        self.regs.fijar(origen)
        destino = self.destino(quad.result)
        self.out.emit("xori", destino, origen, "1", comentario="negacion logica")

    # -- acceso a memoria -------------------------------------------------------
    def _registro_base(self, operando: Operand) -> str:
        """Registro que sirve de base en un acceso indexado."""
        if (
            operando.kind is OperandKind.VAR
            and operando.symbol is None
            and str(operando.value) == "fp"
        ):
            return "$fp"
        return self.valor(operando)

    def _direccion(self, base: Operand, indice: Operand) -> tuple[str, str]:
        """``(instruccion_base, operando_de_memoria)`` de ``base[indice]``."""
        registro_base = self._registro_base(base)
        self.regs.fijar(registro_base)
        if indice.kind is OperandKind.CONST:
            return registro_base, f"{int(indice.value)}({registro_base})"
        registro_indice = self.valor(indice)
        self.out.emit("addu", BORRADOR, registro_base, registro_indice)
        return BORRADOR, f"0({BORRADOR})"

    def _t_index_load(self, quad: Quadruple) -> None:
        _, memoria = self._direccion(quad.arg1, quad.arg2)
        flotante = self.es_flotante(quad.result)
        destino = self.destino(quad.result)
        if flotante:
            self._mover_doble(False, destino, memoria)
        else:
            self.out.emit("lw", destino, memoria)

    def _t_index_store(self, quad: Quadruple) -> None:
        flotante = self.es_flotante(quad.arg2)
        origen = self._como_doble(quad.arg2) if flotante else self.valor(quad.arg2)
        self.regs.fijar(origen)
        _, memoria = self._direccion(quad.result, quad.arg1)
        if flotante:
            self._mover_doble(True, origen, memoria)
        else:
            self.out.emit("sw", origen, memoria)

    # -- control de flujo ----------------------------------------------------------
    def _t_label(self, quad: Quadruple) -> None:
        self.regs.volcar_todo()
        self.out.etiqueta(str(quad.arg1))

    def _t_goto(self, quad: Quadruple) -> None:
        self.regs.volcar_todo()
        self.out.emit("j", str(quad.arg1))
        self.regs.invalidar()

    def _t_if_goto(self, quad: Quadruple) -> None:
        registro = self.valor(quad.arg1)
        self.regs.volcar_todo()
        self.out.emit("bne", registro, "$zero", str(quad.arg2))

    def _t_iffalse_goto(self, quad: Quadruple) -> None:
        registro = self.valor(quad.arg1)
        self.regs.volcar_todo()
        self.out.emit("beq", registro, "$zero", str(quad.arg2))

    def _t_if_rel_goto(self, quad: Quadruple) -> None:
        destino = str(quad.result)

        if self._operacion_es_cadena(quad):
            izquierdo = self.valor(quad.arg1)
            self.regs.fijar(izquierdo)
            derecho = self.valor(quad.arg2)
            self.out.emit("move", "$a0", izquierdo)
            self.out.emit("move", "$a1", derecho)
            self.regs.volcar_todo()
            self.out.emit("jal", "__str_cmp")
            self.out.emit(self.SALTOS[quad.operator], RETORNO, "$zero", destino)
            return

        if self.es_flotante(quad.arg1) or self.es_flotante(quad.arg2):
            izquierdo = self._como_doble(quad.arg1)
            self.regs.fijar(izquierdo)
            derecho = self._como_doble(quad.arg2)
            instruccion, intercambiar, negar = self.COMPARACIONES_DOBLES[quad.operator]
            a, b = (derecho, izquierdo) if intercambiar else (izquierdo, derecho)
            self.regs.volcar_todo()
            self.out.emit(instruccion, a, b)
            self.out.emit("bc1f" if negar else "bc1t", destino)
            return

        izquierdo = self.valor(quad.arg1)
        self.regs.fijar(izquierdo)
        derecho = self.valor(quad.arg2)
        self.regs.volcar_todo()
        self.out.emit(self.SALTOS[quad.operator], izquierdo, derecho, destino)

    # -- llamadas ------------------------------------------------------------------
    def _t_param(self, quad: Quadruple) -> None:
        self.params_pendientes.append(quad.arg1)

    def _tam_argumento(self, operando: Operand) -> int:
        return 8 if self.es_flotante(operando) else 4

    def _t_call(self, quad: Quadruple) -> None:
        argumentos = self.params_pendientes
        self.params_pendientes = []
        indirecta = quad.op is Op.CALL_INDIRECT
        nombre = "" if indirecta else str(quad.arg1)

        if not indirecta and rt.is_intrinsic(nombre):
            self._llamar_intrinseca(nombre, argumentos, quad)
            return

        registro_destino = None
        if indirecta:
            registro_destino = self.valor(quad.arg1)
            self.regs.fijar(registro_destino)

        self._empujar_argumentos(argumentos)
        total = sum(self._tam_argumento(a) for a in argumentos)

        if indirecta:
            # El volcado se hace ANTES de saltar: emite 'sw' y, para las
            # globales, un 'la $t9'. Si la direccion del metodo estuviera en
            # $t9 se perderia. El registro donde esta sigue siendo valido
            # despues del volcado porque volcar solo escribe en memoria.
            self.regs.volcar_todo()
            self.out.emit("jalr", registro_destino, comentario="despacho dinamico")
        else:
            self.regs.volcar_todo()
            self.out.emit("jal", nombre)

        if total:
            self.out.emit("addiu", "$sp", "$sp", str(total), comentario="retira los argumentos")
        self._recoger_resultado(quad)

    def _empujar_argumentos(self, argumentos: list[Operand]) -> None:
        """Deja los argumentos en la pila, el primero en la direccion mas baja."""
        total = sum(self._tam_argumento(a) for a in argumentos)
        if not total:
            return
        self.out.emit("addiu", "$sp", "$sp", f"-{total}", comentario="zona de argumentos")
        desplazamiento = 0
        for argumento in argumentos:
            if self.es_flotante(argumento):
                registro = self._como_doble(argumento)
                self._mover_doble(True, registro, f"{desplazamiento}($sp)")
            else:
                registro = self.valor(argumento)
                self.out.emit("sw", registro, f"{desplazamiento}($sp)")
            desplazamiento += self._tam_argumento(argumento)

    def _recoger_resultado(self, quad: Quadruple) -> None:
        if quad.result is None:
            return
        if self.es_flotante(quad.result):
            destino = self.destino(quad.result)
            self.out.emit("mov.d", destino, RETORNO_FLOTANTE, comentario="resultado")
        else:
            destino = self.destino(quad.result)
            self.out.emit("move", destino, RETORNO, comentario="resultado")

    def _llamar_intrinseca(self, nombre: str, argumentos: list[Operand], quad: Quadruple) -> None:
        """Las rutinas de apoyo se especializan segun el tipo del argumento."""
        if nombre == rt.PRINT.name:
            self._llamar_simple(self._variante_impresion(argumentos), argumentos, quad)
            return
        if nombre == rt.TO_STRING.name:
            self._llamar_simple(self._variante_conversion(argumentos), argumentos, quad)
            return
        self._llamar_simple(nombre, argumentos, quad)

    @staticmethod
    def _variante_impresion(argumentos: list[Operand]) -> str:
        tipo = argumentos[0].type if argumentos else None
        if tipo is FLOAT:
            return "__print_float"
        if tipo is STRING:
            return "__print_str"
        if tipo is BOOLEAN:
            return "__print_bool"
        if tipo is not None and tipo.name == "null":
            return "__print_null"
        return "__print_int"

    @staticmethod
    def _variante_conversion(argumentos: list[Operand]) -> str:
        tipo = argumentos[0].type if argumentos else None
        if tipo is FLOAT:
            return "__ftoa"
        if tipo is BOOLEAN:
            return "__btoa"
        if tipo is STRING:
            return "__str_dup"
        return "__itoa"

    def _llamar_simple(self, etiqueta: str, argumentos: list[Operand], quad: Quadruple) -> None:
        """Llamada a una rutina del runtime: argumentos en ``$a0``/``$a1``/``$f12``."""
        registros = []
        for indice, argumento in enumerate(argumentos):
            if self.es_flotante(argumento):
                registro = self._como_doble(argumento)
                self.out.emit("mov.d", "$f12" if indice == 0 else "$f14", registro)
            else:
                registro = self.valor(argumento)
                self.out.emit("move", f"$a{indice}", registro)
            registros.append(registro)
            self.regs.fijar(*registros)
        self.regs.volcar_todo()
        self.out.emit("jal", etiqueta)
        self._recoger_resultado(quad)

    # -- retorno y enlaces -----------------------------------------------------------
    def _t_return(self, quad: Quadruple) -> None:
        if quad.arg1 is not None:
            if self.es_flotante(quad.arg1):
                registro = self._como_doble(quad.arg1)
                self.out.emit("mov.d", RETORNO_FLOTANTE, registro, comentario="valor de retorno")
            else:
                registro = self.valor(quad.arg1)
                self.out.emit("move", RETORNO, registro, comentario="valor de retorno")
        self._epilogo()
        self.regs.invalidar()

    def _t_set_access_link(self, quad: Quadruple) -> None:
        registro = self._registro_base(quad.arg1)
        self.out.emit("move", ENLACE_ACCESO, registro, comentario="marco del padre lexico")

    # -- excepciones -------------------------------------------------------------------
    def _t_push_handler(self, quad: Quadruple) -> None:
        self.regs.volcar_todo()
        self.out.emit("la", "$a0", str(quad.arg1), comentario="direccion del catch")
        self.out.emit("jal", "__handler_push")

    def _t_pop_handler(self, quad: Quadruple) -> None:
        self.regs.volcar_todo()
        self.out.emit("jal", "__handler_pop")

    # ======================================================================
    # Metricas
    # ======================================================================
    def estadisticas(self) -> dict:
        """Cifras acumuladas de getReg() en todo el programa."""
        total = self._totales["reutilizaciones"] + self._totales["cargas"]
        return {
            **self._totales,
            "aciertos": round(100 * self._totales["reutilizaciones"] / total, 1) if total else 0.0,
            "instrucciones": self.out.instruction_count,
        }


def generate_mips(
    tac: TACProgram,
    table: Optional[SymbolTable] = None,
    *,
    comments: bool = True,
) -> MipsProgram:
    """Traduce un programa TAC a ensamblador MIPS."""
    return MipsGenerator(tac, table, comments=comments).generate()
