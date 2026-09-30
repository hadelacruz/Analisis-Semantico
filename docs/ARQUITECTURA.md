# 🏗️ Arquitectura del compilador de Compiscript

Documento de diseño de la fase de análisis semántico: cómo está organizado el
compilador, por qué se tomó cada decisión y qué supuestos se hicieron sobre el
lenguaje.

---

## 1. Visión general

El front-end convierte un archivo `.cps` en dos artefactos: una **lista de
diagnósticos** y una **tabla de símbolos**. La generación de código intermedio
(fase siguiente) consumirá ambos.

```
                       codigo.cps
                            │
        ┌───────────────────▼───────────────────┐
        │  ANTLR 4.13.1  (generado, no editar)  │
        │  CompiscriptLexer  →  tokens          │  E001
        │  CompiscriptParser →  parse tree      │  E002
        └───────────────────┬───────────────────┘
                            │  parse tree
        ┌───────────────────▼───────────────────┐
        │  PASADA 1 · DeclarationCollector      │
        │  (Listener sobre listas de sentencias)│
        │  · nombres de clases                  │
        │  · herencia y ciclos                  │  E501 E505
        │  · miembros y layout de instancia     │  E506 E508
        │  · firmas de funciones y parametros   │  E306 E307 E310
        └───────────────────┬───────────────────┘
                            │  tabla de simbolos con las declaraciones
        ┌───────────────────▼───────────────────┐
        │  PASADA 2 · SemanticChecker           │
        │  (Visitor: cada expresion → Type)     │
        │  · tipos de expresiones y asignaciones│  E1xx
        │  · resolucion de nombres y ambitos    │  E2xx
        │  · llamadas, retornos, closures       │  E3xx
        │  · condiciones, break/continue/return │  E4xx
        │  · atributos, metodos, this           │  E5xx
        │  · indices y elementos                │  E6xx
        │  · codigo muerto, expresiones inutiles│  E7xx W9xx
        └───────────────────┬───────────────────┘
                            │
                     AnalysisResult
              (diagnosticos + tabla + arbol)
                   │              │
              ┌────▼────┐    ┌────▼────┐
              │   CLI   │    │   IDE   │
              └─────────┘    └─────────┘
```

El punto de entrada único es `compiscript.analyze(source)`. **El CLI, el IDE y
la batería de tests llaman a esa misma función**, así que los tres observan
exactamente el mismo comportamiento; no hay una "versión del IDE" que pueda
divergir.

---

## 2. Módulos

| Módulo | Responsabilidad |
| --- | --- |
| `generated/` | Lexer, parser, listener y visitor producidos por ANTLR desde `grammar/Compiscript.g4`. **No se editan a mano.** |
| `syntax.py` | Puente con ANTLR: sustituye el `ErrorListener` por uno que vuelca los errores en nuestro reporter y los traduce al español. |
| `diagnostics.py` | Catálogo de las 53 reglas (`CATALOG`), la clase `Diagnostic` y el `ErrorReporter`. |
| `types.py` | Jerarquía de tipos y **todas** las reglas de compatibilidad. |
| `symbols.py` | `Symbol`, `VariableSymbol`, `FunctionSymbol`, `ClassSymbol`. |
| `scope.py` | `Scope` (árbol de entornos) y `SymbolTable` (fachada + asignación de memoria). |
| `collector.py` | Pasada 1. También resuelve las anotaciones de tipo (`resolve_type`). |
| `checker.py` | Pasada 2. El grueso de las reglas semánticas. |
| `tree_export.py` | Árbol sintáctico → JSON (IDE), DOT (Graphviz) y texto (consola). |
| `analysis.py` | Orquestador y `AnalysisResult`. |
| `cli.py` | Interfaz de línea de comandos. |

---

## 3. ¿Por qué Visitor y no Listener?

El enunciado admite ambos. Se eligió **Visitor** para el chequeo porque cada
nodo de expresión tiene que **devolver su tipo** al nodo padre:

```python
def visitAdditiveExpr(self, ctx):
    izquierdo = self.visit(ctx.multiplicativeExpr(0))   # -> Type
    derecho   = self.visit(ctx.multiplicativeExpr(1))   # -> Type
    return arithmetic_result("+", izquierdo, derecho)   # -> Type
```

Un `Listener` no retorna valores: habría que acumular los tipos en una pila
paralela indexada por nodo, que es exactamente lo que el Visitor hace de forma
natural.

La pasada 1, en cambio, **sí** es un recorrido plano sobre listas de
sentencias, porque sólo necesita registrar declaraciones sin evaluar nada.

---

## 4. Las dos pasadas y el *hoisting*

### El problema

Este programa es válido y aparece en el ejemplo del curso:

```cps
print(factorial(5));                                  // se usa antes...

function factorial(n: integer): integer { ... }       // ...de declararse
```

Si se recorriera el árbol de una sola pasada, `factorial` sería un
identificador no declarado.

### La solución

Antes de visitar cada **lista de sentencias** (el programa, el cuerpo de una
función, un bloque, la rama de un `case`), se ejecuta la pasada 1 sobre esa
lista y se registran sus clases y funciones. El orden interno importa:

1. **Nombres de clases.** Permite que dos clases se referencien mutuamente.
2. **Enlace de herencia** y detección de ciclos (`E505`). El ciclo se **rompe**
   al detectarlo, para que el resto del análisis no entre en bucle infinito.
3. **Miembros de las clases en orden topológico**: una subclase se construye
   siempre después de su superclase, así su layout de instancia continúa donde
   termina el heredado.
4. **Firmas de las funciones.** Sus cuerpos se revisan en la pasada 2.

El *hoisting* es **por ámbito**: una función anidada no se ve desde fuera.

### Ámbitos pre-creados

La pasada 1 crea el `Scope` de cada función y clase y declara ahí sus
parámetros y miembros. La pasada 2 **vuelve a entrar** en ese ámbito
(`SymbolTable.enter`) en vez de crear uno nuevo. Sin esto, los parámetros se
declararían dos veces.

---

## 5. Sistema de tipos

### Jerarquía

```
Type
├── PrimitiveType      integer · float · boolean · string · null · void
├── ArrayType(T)       T[]  — puntero, invariante en T
├── ClassType          instancia — puntero, covariante (subclase → superclase)
├── FunctionType       (T1, T2) -> R
└── ErrorType          centinela
```

### `ErrorType`: cómo se evitan las cascadas

Un error de tipos no debe generar veinte errores derivados. Cuando una
expresión falla se devuelve `ERROR`, un tipo **compatible con todo**:

```cps
let x: integer = "mal";     // E105  <- el unico error real
let y: integer = x + 1;     // sin error: x sigue siendo integer
let z: integer = y * 2;     // sin error
```

`Type.equals` devuelve `True` en cuanto uno de los dos operandos es `ErrorType`,
y `is_assignable` hace lo mismo. A esto se suma la **deduplicación** por
`(código, línea, columna)` en el `ErrorReporter`.

Está verificado en `test_general.py::test_las_cadenas_no_generan_cascadas_de_errores`.

### Reglas de asignación (`is_assignable`)

| Destino | Origen | ¿Se permite? |
| --- | --- | --- |
| `T` | `T` | Sí |
| `float` | `integer` | Sí — ensanchamiento |
| `integer` | `float` | **No** — se perdería precisión |
| tipo por referencia | `null` | Sí (`string`, arreglos, clases) |
| `integer`, `float`, `boolean` | `null` | **No** |
| `Superclase` | `Subclase` | Sí |
| `Subclase` | `Superclase` | **No** |
| `T[]` | `U[]` con `U ≠ T` | **No** — los arreglos son invariantes |
| cualquiera | `ErrorType` | Sí — corta la cascada |

Los arreglos son **invariantes** a propósito: si `float[]` aceptara `integer[]`,
escribir un `float` en el arreglo corrompería los enteros del original.

### Operadores

| Operador | Reglas | Error |
| --- | --- | --- |
| `+` | numérico+numérico → numérico; si un operando es `string` y el otro es imprimible → **concatenación** | `E101` |
| `-` `*` `/` | ambos numéricos; el resultado es `float` si alguno lo es | `E101` |
| `%` | ambos `integer` | `E115` |
| `&&` `\|\|` `!` | todos `boolean` | `E102` / `E109` |
| `==` `!=` | tipos comparables (`is_comparable`) | `E103` |
| `<` `<=` `>` `>=` | numéricos o `string` (lexicográfico) | `E104` |
| `-` unario | numérico | `E108` |
| `? :` | condición `boolean`; las ramas deben unificar | `E113` / `E114` |

La concatenación con `+` **no** es un capricho: el propio `program.cps` del
curso hace `print("5 + 1 = " + addFive)` con `addFive: integer`.

---

## 6. Tabla de símbolos y manejo de entornos

### Árbol de ámbitos

Un `Scope` nuevo por cada:

| Construcción | Tipo de ámbito |
| --- | --- |
| programa | `GLOBAL` |
| función y método | `FUNCTION` — contiene parámetros **y** cuerpo |
| clase | `CLASS` — contiene atributos y métodos |
| `{ … }`, `if`, `while`, `for`, `foreach`, `try`, `catch`, `case` | `BLOCK` |

La resolución sube por `parent` hasta el global. Eso implementa a la vez el
anidamiento, el **sombreado** y la captura de closures.

El cuerpo de una función **comparte** el ámbito de la función (no abre uno
propio). Es deliberado: así una variable local con el mismo nombre que un
parámetro se detecta como redeclaración (`E202`).

### Contenido de un símbolo

Además de lo que necesita esta fase (nombre, categoría, tipo, línea, si está
inicializado, si se usó), cada símbolo guarda **lo que pedirán las fases
siguientes**, tal como exige el requerimiento 5 del enunciado:

| Campo | Para qué |
| --- | --- |
| `storage` | `global` · `local` · `parametro` · `atributo` · `codigo` |
| `offset` | desplazamiento en el área de datos o en el registro de activación |
| `size` | bytes del tipo (`integer` 4, `float` 8, `boolean` 1, referencias 4) |
| `label` | etiqueta de ensamblador: `func_f`, `Punto_norma`, `func_f__anidada` |
| `captured` | el símbolo lo captura un closure → no puede vivir sólo en un registro |
| `frame_size` / `param_size` | tamaño del registro de activación de la función |
| `instance_size` / `vtable` | layout de una instancia y despacho de métodos |

### Asignación de memoria

Los ámbitos de bloque **no tienen marco propio**: comparten el registro de
activación de la función que los contiene (`Scope.frame_owner()`). Por eso los
offsets se piden siempre al `FUNCTION` o `GLOBAL` más cercano.

```cps
function acumular(inicio: integer, paso: float): float {
  let total: float = inicio;
  ...
}
```

| Símbolo | storage | offset | size |
| --- | --- | --- | --- |
| `inicio` | parametro | 0 | 4 |
| `paso` | parametro | 4 | 8 |
| `total` | local | 0 | 8 |

`param_size = 12`, `frame_size = 8`.

### Layout de clases

Los atributos heredados van primero; los propios continúan a partir de
`superclase.instance_size`. La `vtable` copia la de la superclase y sobrescribe
las entradas redefinidas:

```cps
class Base     { function f() {...} function g() {...} }
class Derivada : Base { function f() {...} }
```

```
Derivada.vtable = { "f": "Derivada_f",   // sobrescrito
                    "g": "Base_g" }      // heredado
```

### Detección de closures

Al resolver un nombre (`resolve_with_capture`), si el símbolo vive en el marco
de una función **exterior** a la actual, se marca `captured = True` y se
registra en la lista `captures` de la función actual **y de todas las
intermedias**:

```cps
function nivel1(a: integer): integer {
  function nivel2(b: integer): integer {
    function nivel3(c: integer): integer { return a + b + c; }
    return nivel3(3);
  }
  return nivel2(2);
}
```

```
nivel3.captures = {a, b}
nivel2.captures = {a}          // a atraviesa nivel2 para llegar a nivel3
```

Los globales, las funciones y las clases no se capturan: no viven en un
registro de activación.

---

## 7. Análisis de flujo

Dos funciones recursivas sobre el árbol:

- **`_terminator(sentencia)`** → `"return"`, `"break"`, `"continue"` o `None`.
  Detecta **código muerto** (`W902`). Un bloque termina si alguna de sus
  sentencias termina; un `if` termina sólo si **tiene `else`** y ambas ramas
  terminan.

- **`_always_returns(sentencia)`** → `bool`. Verifica que toda ruta de una
  función con tipo de retorno devuelva un valor (`E308`). Contempla `if/else`,
  `do-while` (el cuerpo se ejecuta al menos una vez), `try/catch` (ambos
  bloques) y `switch` (todos los `case` **y** el `default`).

`break` y `continue` se controlan con dos contadores (`loop_depth`,
`switch_depth`) que se **reinician al entrar en una función**: un `break`
dentro de una función anidada declarada dentro de un bucle no pertenece a ese
bucle.

---

## 8. Decisiones de diseño y supuestos del lenguaje

Puntos que el enunciado no fija y que hubo que resolver. Todos están cubiertos
por tests.

| Decisión | Justificación |
| --- | --- |
| **Se añade `float` a la gramática** | El enunciado exige validar aritmética sobre `integer` **o `float`**, pero la gramática original no tenía `float`. El cambio es retrocompatible. |
| **`break` es válido dentro de un `switch`** aunque no haya bucle | Es el comportamiento convencional del constructo y aparece así en el ejemplo del curso. `continue`, en cambio, exige un bucle de verdad. |
| **La condición del `switch` NO se exige `boolean`** | El enunciado agrupa `switch` con `if`/`while`/`for` («la condición debe evaluar a `boolean`»), pero un `switch` cuyo sujeto fuera `boolean` sólo admitiría dos casos y haría inútil el constructo — el propio ejemplo del README oficial hace `switch (x)` sobre un `integer`. Lo que se valida, que es la comprobación equivalente y la útil, es que **cada `case` sea comparable con el sujeto** (`E405`), usando las mismas reglas que `==`. La condición sí se exige `boolean` en `if`, `while`, `do-while` y `for` (`E401`). |
| **`string + valor` es concatenación** | `program.cps` del curso hace `print("5 + 1 = " + addFive)`. |
| **La variable de `catch` es un `string`** | La gramática no permite anotarle un tipo y el ejemplo del curso la concatena con un string: `print("Caught an error: " + err)`. |
| **El índice constante fuera de rango es *advertencia*, no error** | El ejemplo del curso accede a `numbers[10]` **a propósito** dentro de un `try` para provocar la excepción. Marcarlo como error rechazaría un programa válido. |
| **Dentro de un método se puede usar el nombre del atributo sin `this.`** | El ámbito de la clase es padre del ámbito del método, así que la resolución lo encuentra de forma natural (como en Java). `this.x` sigue siendo la forma recomendada. |
| **El constructor no se somete a la comprobación de sobrescritura (`E508`)** | No es un método polimórfico: cada clase declara el suyo con los parámetros que necesita. Si no lo declara, hereda el de su superclase. |
| **Una función sin `: T` es un procedimiento (`void`)** | La gramática hace opcional el tipo de retorno. `return` con valor en ese caso es `E305`. |
| **Si hay errores de sintaxis, no se ejecuta el análisis semántico** | El árbol que devuelve ANTLR tras recuperarse está incompleto; analizarlo sólo produciría errores derivados sin valor. `AnalysisResult.semantic_ran` lo indica. |
| **Los parámetros requieren anotación de tipo (`E310`)** | La gramática la hace opcional, pero sin ella no se puede verificar la llamada. |
| **`W905` (variable sin usar) sólo aplica a ámbitos no globales** | En el ámbito global es normal declarar constantes de configuración que no se usan en el mismo archivo. |

---

## 9. Extensión a la gramática

Único cambio frente a `compiscript/program/Compiscript.g4`:

```diff
- baseType: 'boolean' | 'integer' | 'string' | Identifier;
+ baseType: 'boolean' | 'integer' | 'float' | 'string' | Identifier;

  Literal
-   : IntegerLiteral
+   : FloatLiteral
+   | IntegerLiteral
    | StringLiteral
    ;

+ FloatLiteral: [0-9]+ '.' [0-9]+;
```

`FloatLiteral` va **antes** que `IntegerLiteral` para que el lexer haga
*maximal munch* y `3.14` sea un solo token.

`Literal` es una **regla léxica compuesta** (así venía en el original): como se
declara primero, todo literal se emite con el tipo de token `Literal`, y el
analizador distingue `integer`/`float`/`string` inspeccionando el texto en
`checker.py::visitLiteralExpr`.

Comprobación de retrocompatibilidad: `compiscript/program/program.cps`, escrito
para la gramática original, se analiza sin errores
(`test_programs.py::test_el_ejemplo_del_curso_es_valido`).

---

## 10. El IDE

```
        navegador                          servidor Flask
┌───────────────────────┐            ┌──────────────────────┐
│  Monaco Editor        │            │  ide/app.py          │
│  · Monarch para .cps  │  POST      │                      │
│  · marcadores/errores │ ─────────► │  /api/analizar       │
│  · autocompletado     │  {codigo}  │        │             │
│                       │            │        ▼             │
│  Paneles:             │  ◄───────  │  compiscript.analyze │
│  · Problemas          │   JSON     │        │             │
│  · Arbol sintactico   │            │        ▼             │
│  · Tabla de simbolos  │            │  AnalysisResult      │
│  · Tokens / Reglas    │            │   .to_dict()         │
└───────────────────────┘            └──────────────────────┘
```

El backend es deliberadamente delgado (unas 90 líneas): sólo traduce HTTP a
llamadas a `analyze`. Toda la lógica vive en el compilador.

Monaco está **vendorizado** en `ide/static/vendor/monaco/` (sólo los archivos
imprescindibles, 4.4 MB) para que el IDE funcione **sin conexión a internet**.

### El panel del árbol sintáctico

El requerimiento 2 pide el árbol «con una representación visual». El panel tiene
**dos ejes independientes**:

| Eje | Opciones | Para qué |
| --- | --- | --- |
| **Detalle** | `Compacto` (por defecto) · `Completo` | Compacto colapsa la cascada de precedencia; Completo muestra la gramática entera |
| **Vista** | `Indentado` · `Gráfico` | Indentado es el árbol plegable; Gráfico dibuja nodos y aristas en SVG |

**Por qué hace falta el modo compacto.** La gramática codifica la precedencia
como una cascada de reglas. Una expresión que no usa un nivel deja igualmente su
nodo, con un solo hijo. Para `let x: integer = 5 + 3;`:

```
completo (33 nodos)                    compacto (18 nodos)
expression                             initializer
└── assignmentExpr: ExprNoAssign       ├── '='
    └── conditionalExpr: TernaryExpr   └── additiveExpr : integer  [+7]
        └── logicalOrExpr                  ├── literalExpr : integer  [+3]
            └── logicalAndExpr              │   └── '5'
                └── equalityExpr            ├── '+'
                    └── relationalExpr      └── literalExpr : integer  [+3]
                        └── additiveExpr        └── '3'
                            └── ...
```

En `compiscript/program/program.cps` (108 líneas) la reducción es de **1758 a
774 nodos, un 56 %**.

El colapso lo implementa `tree_export.collapse_chain`: recorre las cadenas de
nodos-regla con **exactamente un hijo que también es un nodo-regla**, conserva el
más profundo (el que tiene contenido real) y **le transfiere el tipo inferido**
del eslabón más profundo que lo tuviera, de modo que no se pierde información de
tipos. El nodo superviviente guarda en `collapsed` los nombres de las reglas
absorbidas, que el IDE muestra como `[+7]` y en el tooltip.

El backend manda los **dos** árboles (`tree` y `treeCompact`) en la misma
respuesta, así que el interruptor del IDE cambia de vista al instante sin
reanalizar. El mismo colapso está disponible en el CLI (`--tree` compacto,
`--tree-completo` verboso) y en la exportación a DOT.

**La vista gráfica** dibuja el árbol en SVG generado en el cliente:

* Disposición en dos fases. Primero se mide cada subárbol
  (`ancho = max(ancho propio, Σ anchos de los hijos + separación)`); luego se
  colocan los hijos dentro de la banda de su padre y el padre se centra sobre
  ellos, **acotado a su banda** para que su caja no invada la del hermano.
* Zoom con la rueda (anclado al puntero), desplazamiento arrastrando y un botón
  *Ajustar*. Como un parse tree es muchísimo más ancho que alto (el de
  `program.cps` mide ~48 000 px), *Ajustar* no baja de una escala legible: si el
  árbol no cabe, encuadra por el alto y centra la **raíz**.
* Al hacer clic en un nodo se resalta y el editor **salta a su línea y columna**.
* Por encima de 3500 nodos el SVG deja de ser legible y el panel sugiere el modo
  compacto o la vista indentada, en vez de dibujar algo inservible.

---

## 11. Estrategia de pruebas

377 tests en dos niveles:

**Nivel 1 — unitario, por regla.** Cada una de las 53 reglas tiene al menos un
caso exitoso y uno fallido, con fragmentos mínimos:

```python
def test_e105_asignacion_invalida():
    assert_error('let a: integer = "hola";', "E105")
```

**Nivel 2 — programas completos.** `tests/programs/valid/` (7 programas que
deben compilar limpios) y `tests/programs/invalid/` (7 programas con el
diagnóstico esperado anotado línea por línea):

```cps
let malAritmetica = 1 + true;              // @error E101
```

`test_programs.py` exige que aparezca **exactamente** lo anotado y **nada más**.
Esa segunda mitad es la importante: hace que la batería detecte también los
**falsos positivos**, no sólo los errores que se dejan de detectar. Dos bugs
reales (`E508` disparándose en constructores y `W903` comparando el índice de
una matriz contra el número de filas) se encontraron así.
