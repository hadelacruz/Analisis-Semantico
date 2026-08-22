#!/usr/bin/env python3
"""Genera ``docs/REGLAS_SEMANTICAS.md`` a partir del catálogo del compilador.

La tabla de reglas se construye desde ``compiscript.diagnostics.CATALOG``, de
modo que la documentación no pueda desincronizarse del código: si se añade un
código nuevo y no se le escribe un ejemplo aquí, el script avisa.

Uso::

    python tools/generar_doc_reglas.py
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from compiscript.diagnostics import CATALOG, Severity  # noqa: E402

DESTINO = ROOT / "docs" / "REGLAS_SEMANTICAS.md"

#: ``codigo -> (ejemplo que falla, modulo de tests que lo cubre)``
EJEMPLOS: dict[str, tuple[str, str]] = {
    "E001": ('let x = 1 @ 2;', "test_general.py"),
    "E002": ('let x: integer = ;', "test_general.py"),

    "E101": ('let a = 1 + true;', "test_types.py"),
    "E102": ('let a = 1 && true;', "test_types.py"),
    "E103": ('let a = 1 == "uno";', "test_types.py"),
    "E104": ('let a = true < false;', "test_types.py"),
    "E105": ('let a: integer = "hola";', "test_types.py"),
    "E106": ('const PI: integer;', "test_types.py"),
    "E107": ('const K: integer = 1; K = 2;', "test_types.py"),
    "E108": ('let a = -"texto";', "test_types.py"),
    "E109": ('let a = !42;', "test_types.py"),
    "E110": ('let a: NoExiste = null;', "test_types.py"),
    "E111": ('let a = [1, "dos"];', "test_types.py"),
    "E112": ('let a;', "test_types.py"),
    "E113": ('let a = 5 ? 1 : 2;', "test_types.py"),
    "E114": ('let a = true ? 1 : "x";', "test_types.py"),
    "E115": ('let a = 7 % 2.5;', "test_types.py"),

    "E201": ('print(noDeclarada);', "test_scopes.py"),
    "E202": ('let x: integer = 1; let x: integer = 2;', "test_scopes.py"),
    "E203": ('class C {} let x = C;', "test_scopes.py"),

    "E301": ('function f(a: integer): integer { return a; } f(1, 2);', "test_functions.py"),
    "E302": ('function f(a: string): integer { return 1; } f(5);', "test_functions.py"),
    "E303": ('let x: integer = 1; x();', "test_functions.py"),
    "E304": ('function f(): integer { return "x"; }', "test_functions.py"),
    "E305": ('function f() { return 5; }', "test_functions.py"),
    "E306": ('function f(): integer { return 1; }\nfunction f(): integer { return 2; }', "test_functions.py"),
    "E307": ('function f(a: integer, a: integer): integer { return a; }', "test_functions.py"),
    "E308": ('function f(n: integer): integer { if (n > 0) { return 1; } }', "test_functions.py"),
    "E309": ('function f(): integer { return 1; } let x = f;', "test_functions.py"),
    "E310": ('function f(a): integer { return 1; }', "test_functions.py"),

    "E401": ('if (1) { print(1); }', "test_control_flow.py"),
    "E402": ('break;', "test_control_flow.py"),
    "E403": ('continue;', "test_control_flow.py"),
    "E404": ('return 1;', "test_control_flow.py"),
    "E405": ('switch (1) { case "x": print(1); }', "test_control_flow.py"),
    "E406": ('foreach (x in 42) { print(x); }', "test_control_flow.py"),

    "E501": ('let a = new NoExiste();', "test_classes.py"),
    "E502": ('class C {} let c: C = new C(); print(c.nada);', "test_classes.py"),
    "E503": ('print(this);', "test_classes.py"),
    "E504": ('class C { function constructor(a: integer) { } } let c: C = new C();', "test_classes.py"),
    "E505": ('class A : B { } class B : A { }', "test_classes.py"),
    "E506": ('class C { let x: integer; let x: integer; }', "test_classes.py"),
    "E507": ('let n: integer = 1; print(n.algo);', "test_classes.py"),
    "E508": (
        'class A { function f(a: integer): integer { return a; } }\n'
        'class B : A { function f(a: string): integer { return 1; } }',
        "test_classes.py",
    ),

    "E601": ('let xs: integer[] = [1]; print(xs["a"]);', "test_arrays.py"),
    "E602": ('let n: integer = 1; print(n[0]);', "test_arrays.py"),

    "E701": ('5 + 3;', "test_general.py"),
    "E702": ('function p() { } print(p());', "test_general.py"),

    "W901": ('let x: integer; print(x);', "test_general.py"),
    "W902": ('function f(): integer { return 1; print("nunca"); }', "test_general.py"),
    "W903": ('let xs: integer[] = [1, 2]; print(xs[99]);', "test_arrays.py"),
    "W904": ('let x: integer = 10 / 0;', "test_general.py"),
    "W905": ('function f(): integer { let sinUsar: integer = 1; return 2; }', "test_general.py"),
}

CATEGORIAS = [
    ("Sintaxis", "Errores léxicos y sintácticos", "Los detecta ANTLR. Si aparece alguno, el análisis semántico no llega a ejecutarse porque el árbol está incompleto."),
    ("Tipos", "Sistema de tipos", "Enunciado, sección 2.1."),
    ("Ambito", "Manejo de ámbito", "Enunciado, sección 2.2."),
    ("Funciones", "Funciones y procedimientos", "Enunciado, sección 2.3."),
    ("Control de flujo", "Control de flujo", "Enunciado, sección 2.4."),
    ("Clases", "Clases y objetos", "Enunciado, sección 2.5."),
    ("Listas", "Listas y estructuras de datos", "Enunciado, sección 2.6."),
    ("Generales", "Reglas generales", "Enunciado, sección 2.7."),
]


def _ancla(titulo: str) -> str:
    """Ancla estilo GitHub: minúsculas, sin acentos y con guiones."""
    normalizado = unicodedata.normalize("NFKD", titulo.lower())
    sin_acentos = "".join(c for c in normalizado if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "-" for c in sin_acentos)


def main() -> int:
    faltantes = sorted(set(CATALOG) - set(EJEMPLOS))
    if faltantes:
        print(f"[!] Faltan ejemplos para: {', '.join(faltantes)}", file=sys.stderr)

    errores = sum(1 for s, _, _ in CATALOG.values() if s is Severity.ERROR)
    avisos = len(CATALOG) - errores

    lineas: list[str] = [
        "# 📋 Catálogo de reglas semánticas",
        "",
        "> Documento **generado** por `tools/generar_doc_reglas.py` a partir de",
        "> `src/compiscript/diagnostics.py`. No editar a mano.",
        "",
        f"El compilador implementa **{len(CATALOG)} reglas**: {errores} errores y "
        f"{avisos} advertencias.",
        "",
        "Cada regla tiene un **código estable**. Ese código es el que aparece en",
        "el mensaje de la consola, el que subraya el IDE y el que verifican los",
        "tests, de modo que la trazabilidad *regla → implementación → test* sea",
        "comprobable.",
        "",
        "**Errores** impiden la compilación (código de salida `1`).",
        "**Advertencias** (`W9xx`) no la impiden: señalan código sospechoso pero",
        "legal, como un índice constante fuera de rango, que en Compiscript es un",
        "fallo de ejecución atrapable con `try`/`catch`.",
        "",
        "---",
        "",
        "## Índice",
        "",
    ]

    for categoria, titulo, _ in CATEGORIAS:
        codigos = sorted(c for c, (_, cat, _) in CATALOG.items() if cat == categoria)
        errs = [c for c in codigos if c.startswith("E")]
        warns = [c for c in codigos if c.startswith("W")]
        detalle = f"`{errs[0]}`–`{errs[-1]}`" if len(errs) > 1 else f"`{errs[0]}`" if errs else ""
        if warns:
            detalle += (" + " if detalle else "") + ", ".join(f"`{w}`" for w in warns)
        lineas.append(f"- [{titulo}](#{_ancla(titulo)}) — {detalle}")
    lineas += ["", "---", ""]

    for categoria, titulo, nota in CATEGORIAS:
        codigos = sorted(c for c, (_, cat, _) in CATALOG.items() if cat == categoria)
        if not codigos:
            continue
        lineas += [f"## {titulo}", "", nota, ""]
        for codigo in codigos:
            severidad, _, descripcion = CATALOG[codigo]
            ejemplo, modulo = EJEMPLOS.get(codigo, ("(sin ejemplo)", "-"))
            etiqueta = "error" if severidad is Severity.ERROR else "advertencia"
            lineas += [
                f"### `{codigo}` — {descripcion}",
                "",
                f"*Severidad:* **{etiqueta}** &nbsp;·&nbsp; *Tests:* `tests/{modulo}`",
                "",
                "```cps",
                ejemplo,
                "```",
                "",
            ]
        lineas += ["---", ""]

    lineas += [
        "## Cómo se prueba cada regla",
        "",
        "Cada regla tiene, como mínimo, **un test de caso exitoso y uno de caso",
        "fallido**:",
        "",
        "```bash",
        "python -m pytest tests/ -v            # las 364 pruebas",
        "python -m pytest tests/ -m tipos      # sólo el sistema de tipos",
        "python -m pytest tests/ -m clases     # sólo clases y objetos",
        "```",
        "",
        "Además, `tests/programs/invalid/*.cps` son programas completos con el",
        "código esperado anotado en cada línea:",
        "",
        "```cps",
        "let malAritmetica = 1 + true;              // @error E101",
        "let malAsignacion: integer = \"hola\";       // @error E105",
        "```",
        "",
        "`tests/test_programs.py` comprueba que **aparezca exactamente** el",
        "diagnóstico anotado en esa línea y **ningún otro sin anotar**, de modo",
        "que la batería también detecta falsos positivos.",
        "",
    ]

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text("\n".join(lineas), encoding="utf-8")
    print(f"[OK] {DESTINO.relative_to(ROOT)} — {len(CATALOG)} reglas documentadas")
    return 1 if faltantes else 0


if __name__ == "__main__":
    raise SystemExit(main())
