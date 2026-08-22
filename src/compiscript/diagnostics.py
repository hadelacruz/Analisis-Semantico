"""Diagnósticos (errores y advertencias) del compilador de Compiscript.

Cada regla semántica del enunciado tiene un **código único y estable**
(``E1xx``, ``E2xx``, ...). Ese código es lo que verifica la batería de tests y
lo que muestra el IDE, de modo que la trazabilidad
regla <-> implementación <-> test sea explícita y verificable.

Familias de códigos
-------------------
=========  ==========================================================
Prefijo    Categoría
=========  ==========================================================
``E0xx``   Errores léxicos y sintácticos (los detecta ANTLR)
``E1xx``   Sistema de tipos
``E2xx``   Manejo de ámbito y declaraciones
``E3xx``   Funciones y procedimientos
``E4xx``   Control de flujo
``E5xx``   Clases y objetos
``E6xx``   Listas y estructuras de datos
``E7xx``   Generales
``W9xx``   Advertencias (no impiden la compilación)
=========  ==========================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional


class Severity(str, Enum):
    """Gravedad de un diagnóstico."""

    ERROR = "error"
    WARNING = "warning"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# Catálogo de códigos
# ---------------------------------------------------------------------------

#: ``code -> (severidad por defecto, categoría, descripción corta)``.
#: ``docs/REGLAS_SEMANTICAS.md`` se genera a partir de esta tabla.
CATALOG: dict[str, tuple[Severity, str, str]] = {
    # --- E0xx: léxico / sintaxis -------------------------------------------
    "E001": (Severity.ERROR, "Sintaxis", "Error léxico: carácter o token no reconocido"),
    "E002": (Severity.ERROR, "Sintaxis", "Error sintáctico: la entrada no encaja con la gramática"),

    # --- E1xx: sistema de tipos ---------------------------------------------
    "E101": (Severity.ERROR, "Tipos", "Operación aritmética sobre operandos no numéricos"),
    "E102": (Severity.ERROR, "Tipos", "Operación lógica sobre operandos no booleanos"),
    "E103": (Severity.ERROR, "Tipos", "Comparación de igualdad entre tipos incompatibles"),
    "E104": (Severity.ERROR, "Tipos", "Comparación relacional sobre tipos no ordenables"),
    "E105": (Severity.ERROR, "Tipos", "Asignación de un valor cuyo tipo no coincide con el declarado"),
    "E106": (Severity.ERROR, "Tipos", "Constante declarada sin inicializador"),
    "E107": (Severity.ERROR, "Tipos", "Asignación a una constante"),
    "E108": (Severity.ERROR, "Tipos", "Operador unario '-' sobre un operando no numérico"),
    "E109": (Severity.ERROR, "Tipos", "Operador unario '!' sobre un operando no booleano"),
    "E110": (Severity.ERROR, "Tipos", "Anotación de tipo desconocida"),
    "E111": (Severity.ERROR, "Tipos", "Literal de arreglo con elementos de tipos incompatibles"),
    "E112": (Severity.ERROR, "Tipos", "No se puede inferir el tipo de la variable"),
    "E113": (Severity.ERROR, "Tipos", "Condición del operador ternario no booleana"),
    "E114": (Severity.ERROR, "Tipos", "Ramas del operador ternario con tipos incompatibles"),
    "E115": (Severity.ERROR, "Tipos", "Operador '%' sobre operandos que no son integer"),

    # --- E2xx: ámbito --------------------------------------------------------
    "E201": (Severity.ERROR, "Ambito", "Uso de un identificador no declarado"),
    "E202": (Severity.ERROR, "Ambito", "Redeclaración de un identificador en el mismo ámbito"),
    "E203": (Severity.ERROR, "Ambito", "El identificador no nombra un valor utilizable"),

    # --- E3xx: funciones ------------------------------------------------------
    "E301": (Severity.ERROR, "Funciones", "Número incorrecto de argumentos en la llamada"),
    "E302": (Severity.ERROR, "Funciones", "Tipo de argumento incompatible con el parámetro"),
    "E303": (Severity.ERROR, "Funciones", "Se intenta invocar algo que no es una función"),
    "E304": (Severity.ERROR, "Funciones", "El valor retornado no coincide con el tipo declarado"),
    "E305": (Severity.ERROR, "Funciones", "'return' con o sin valor de forma incompatible con la firma"),
    "E306": (Severity.ERROR, "Funciones", "Función ya declarada (el lenguaje no soporta sobrecarga)"),
    "E307": (Severity.ERROR, "Funciones", "Parámetro duplicado"),
    "E308": (Severity.ERROR, "Funciones", "No todos los caminos de la función retornan un valor"),
    "E309": (Severity.ERROR, "Funciones", "Uso de una función como valor sin invocarla"),
    "E310": (Severity.ERROR, "Funciones", "Parámetro sin anotación de tipo"),

    # --- E4xx: control de flujo ------------------------------------------------
    "E401": (Severity.ERROR, "Control de flujo", "La condición debe ser de tipo boolean"),
    "E402": (Severity.ERROR, "Control de flujo", "'break' fuera de un bucle o switch"),
    "E403": (Severity.ERROR, "Control de flujo", "'continue' fuera de un bucle"),
    "E404": (Severity.ERROR, "Control de flujo", "'return' fuera del cuerpo de una función"),
    "E405": (Severity.ERROR, "Control de flujo", "El tipo del 'case' no es comparable con el del 'switch'"),
    "E406": (Severity.ERROR, "Control de flujo", "'foreach' sobre una expresión que no es un arreglo"),

    # --- E5xx: clases y objetos -------------------------------------------------
    "E501": (Severity.ERROR, "Clases", "Clase no declarada"),
    "E502": (Severity.ERROR, "Clases", "El atributo o método no existe en la clase"),
    "E503": (Severity.ERROR, "Clases", "'this' usado fuera de un método de clase"),
    "E504": (Severity.ERROR, "Clases", "Llamada al constructor con argumentos incorrectos"),
    "E505": (Severity.ERROR, "Clases", "Herencia cíclica entre clases"),
    "E506": (Severity.ERROR, "Clases", "Miembro de clase duplicado"),
    "E507": (Severity.ERROR, "Clases", "Acceso con '.' sobre un valor que no es un objeto"),
    "E508": (Severity.ERROR, "Clases", "Sobrescritura de método con firma incompatible"),

    # --- E6xx: listas -------------------------------------------------------------
    "E601": (Severity.ERROR, "Listas", "El índice de un arreglo debe ser de tipo integer"),
    "E602": (Severity.ERROR, "Listas", "Indexación sobre un valor que no es un arreglo"),

    # --- E7xx: generales -----------------------------------------------------------
    "E701": (Severity.ERROR, "Generales", "La expresión no tiene sentido semántico"),
    "E702": (Severity.ERROR, "Generales", "'print' no puede imprimir un valor de tipo void"),

    # --- W9xx: advertencias ----------------------------------------------------------
    "W901": (Severity.WARNING, "Generales", "Uso de una variable posiblemente no inicializada"),
    "W902": (Severity.WARNING, "Generales", "Código muerto: instrucción inalcanzable"),
    "W903": (Severity.WARNING, "Listas", "Índice constante fuera del rango conocido del arreglo"),
    "W904": (Severity.WARNING, "Tipos", "División o módulo entre la constante cero"),
    "W905": (Severity.WARNING, "Ambito", "Variable local declarada y nunca utilizada"),
}


@dataclass(frozen=True)
class Diagnostic:
    """Un error o advertencia con su ubicación exacta en el código fuente."""

    code: str
    severity: Severity
    message: str
    line: int
    column: int
    end_line: int = 0
    end_column: int = 0

    @property
    def category(self) -> str:
        return CATALOG.get(self.code, (Severity.ERROR, "Desconocida", ""))[1]

    def __str__(self) -> str:
        tag = "error" if self.severity is Severity.ERROR else "advertencia"
        return f"[{self.code}] {tag} en linea {self.line}:{self.column} - {self.message}"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "category": self.category,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "endLine": self.end_line or self.line,
            "endColumn": self.end_column or self.column + 1,
        }


class ErrorReporter:
    """Acumula los diagnósticos producidos durante el análisis.

    El análisis nunca aborta en el primer error: se recolectan todos para que
    el IDE pueda subrayarlos en una sola pasada. Para evitar cascadas de
    errores derivados se combinan dos mecanismos:

    1. :class:`~compiscript.types.ErrorType`, un tipo centinela que es
       compatible con todo y por tanto no vuelve a disparar errores.
    2. Deduplicación por la tupla ``(código, línea, columna)``.
    """

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []
        self._seen: set[tuple[str, int, int]] = set()

    # -- registro ------------------------------------------------------------
    def report(
        self,
        code: str,
        message: str,
        line: int,
        column: int,
        *,
        end_line: int = 0,
        end_column: int = 0,
        severity: Optional[Severity] = None,
    ) -> None:
        if severity is None:
            severity = CATALOG.get(code, (Severity.ERROR, "", ""))[0]
        key = (code, line, column)
        if key in self._seen:
            return
        self._seen.add(key)
        self._diagnostics.append(
            Diagnostic(code, severity, message, line, column, end_line, end_column)
        )

    def error(self, code: str, message: str, line: int, column: int, **kw) -> None:
        self.report(code, message, line, column, severity=Severity.ERROR, **kw)

    def warning(self, code: str, message: str, line: int, column: int, **kw) -> None:
        self.report(code, message, line, column, severity=Severity.WARNING, **kw)

    # -- consulta -------------------------------------------------------------
    @property
    def diagnostics(self) -> list[Diagnostic]:
        return sorted(self._diagnostics, key=lambda d: (d.line, d.column, d.code))

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self._diagnostics)

    def codes(self) -> list[str]:
        return [d.code for d in self.diagnostics]

    def extend(self, others: Iterable[Diagnostic]) -> None:
        for d in others:
            key = (d.code, d.line, d.column)
            if key not in self._seen:
                self._seen.add(key)
                self._diagnostics.append(d)

    def __len__(self) -> int:
        return len(self._diagnostics)
