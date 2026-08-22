# 📋 Catálogo de reglas semánticas

> Documento **generado** por `tools/generar_doc_reglas.py` a partir de
> `src/compiscript/diagnostics.py`. No editar a mano.

El compilador implementa **53 reglas**: 48 errores y 5 advertencias.

Cada regla tiene un **código estable**. Ese código es el que aparece en
el mensaje de la consola, el que subraya el IDE y el que verifican los
tests, de modo que la trazabilidad *regla → implementación → test* sea
comprobable.

**Errores** impiden la compilación (código de salida `1`).
**Advertencias** (`W9xx`) no la impiden: señalan código sospechoso pero
legal, como un índice constante fuera de rango, que en Compiscript es un
fallo de ejecución atrapable con `try`/`catch`.

---

## Índice

- [Errores léxicos y sintácticos](#errores-lexicos-y-sintacticos) — `E001`–`E002`
- [Sistema de tipos](#sistema-de-tipos) — `E101`–`E115` + `W904`
- [Manejo de ámbito](#manejo-de-ambito) — `E201`–`E203` + `W905`
- [Funciones y procedimientos](#funciones-y-procedimientos) — `E301`–`E310`
- [Control de flujo](#control-de-flujo) — `E401`–`E406`
- [Clases y objetos](#clases-y-objetos) — `E501`–`E508`
- [Listas y estructuras de datos](#listas-y-estructuras-de-datos) — `E601`–`E602` + `W903`
- [Reglas generales](#reglas-generales) — `E701`–`E702` + `W901`, `W902`

---

## Errores léxicos y sintácticos

Los detecta ANTLR. Si aparece alguno, el análisis semántico no llega a ejecutarse porque el árbol está incompleto.

### `E001` — Error léxico: carácter o token no reconocido

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
let x = 1 @ 2;
```

### `E002` — Error sintáctico: la entrada no encaja con la gramática

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
let x: integer = ;
```

---

## Sistema de tipos

Enunciado, sección 2.1.

### `E101` — Operación aritmética sobre operandos no numéricos

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = 1 + true;
```

### `E102` — Operación lógica sobre operandos no booleanos

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = 1 && true;
```

### `E103` — Comparación de igualdad entre tipos incompatibles

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = 1 == "uno";
```

### `E104` — Comparación relacional sobre tipos no ordenables

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = true < false;
```

### `E105` — Asignación de un valor cuyo tipo no coincide con el declarado

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a: integer = "hola";
```

### `E106` — Constante declarada sin inicializador

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
const PI: integer;
```

### `E107` — Asignación a una constante

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
const K: integer = 1; K = 2;
```

### `E108` — Operador unario '-' sobre un operando no numérico

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = -"texto";
```

### `E109` — Operador unario '!' sobre un operando no booleano

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = !42;
```

### `E110` — Anotación de tipo desconocida

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a: NoExiste = null;
```

### `E111` — Literal de arreglo con elementos de tipos incompatibles

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = [1, "dos"];
```

### `E112` — No se puede inferir el tipo de la variable

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a;
```

### `E113` — Condición del operador ternario no booleana

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = 5 ? 1 : 2;
```

### `E114` — Ramas del operador ternario con tipos incompatibles

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = true ? 1 : "x";
```

### `E115` — Operador '%' sobre operandos que no son integer

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_types.py`

```cps
let a = 7 % 2.5;
```

### `W904` — División o módulo entre la constante cero

*Severidad:* **advertencia** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
let x: integer = 10 / 0;
```

---

## Manejo de ámbito

Enunciado, sección 2.2.

### `E201` — Uso de un identificador no declarado

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_scopes.py`

```cps
print(noDeclarada);
```

### `E202` — Redeclaración de un identificador en el mismo ámbito

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_scopes.py`

```cps
let x: integer = 1; let x: integer = 2;
```

### `E203` — El identificador no nombra un valor utilizable

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_scopes.py`

```cps
class C {} let x = C;
```

### `W905` — Variable local declarada y nunca utilizada

*Severidad:* **advertencia** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
function f(): integer { let sinUsar: integer = 1; return 2; }
```

---

## Funciones y procedimientos

Enunciado, sección 2.3.

### `E301` — Número incorrecto de argumentos en la llamada

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(a: integer): integer { return a; } f(1, 2);
```

### `E302` — Tipo de argumento incompatible con el parámetro

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(a: string): integer { return 1; } f(5);
```

### `E303` — Se intenta invocar algo que no es una función

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
let x: integer = 1; x();
```

### `E304` — El valor retornado no coincide con el tipo declarado

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(): integer { return "x"; }
```

### `E305` — 'return' con o sin valor de forma incompatible con la firma

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f() { return 5; }
```

### `E306` — Función ya declarada (el lenguaje no soporta sobrecarga)

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(): integer { return 1; }
function f(): integer { return 2; }
```

### `E307` — Parámetro duplicado

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(a: integer, a: integer): integer { return a; }
```

### `E308` — No todos los caminos de la función retornan un valor

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(n: integer): integer { if (n > 0) { return 1; } }
```

### `E309` — Uso de una función como valor sin invocarla

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(): integer { return 1; } let x = f;
```

### `E310` — Parámetro sin anotación de tipo

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_functions.py`

```cps
function f(a): integer { return 1; }
```

---

## Control de flujo

Enunciado, sección 2.4.

### `E401` — La condición debe ser de tipo boolean

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_control_flow.py`

```cps
if (1) { print(1); }
```

### `E402` — 'break' fuera de un bucle o switch

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_control_flow.py`

```cps
break;
```

### `E403` — 'continue' fuera de un bucle

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_control_flow.py`

```cps
continue;
```

### `E404` — 'return' fuera del cuerpo de una función

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_control_flow.py`

```cps
return 1;
```

### `E405` — El tipo del 'case' no es comparable con el del 'switch'

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_control_flow.py`

```cps
switch (1) { case "x": print(1); }
```

### `E406` — 'foreach' sobre una expresión que no es un arreglo

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_control_flow.py`

```cps
foreach (x in 42) { print(x); }
```

---

## Clases y objetos

Enunciado, sección 2.5.

### `E501` — Clase no declarada

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
let a = new NoExiste();
```

### `E502` — El atributo o método no existe en la clase

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
class C {} let c: C = new C(); print(c.nada);
```

### `E503` — 'this' usado fuera de un método de clase

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
print(this);
```

### `E504` — Llamada al constructor con argumentos incorrectos

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
class C { function constructor(a: integer) { } } let c: C = new C();
```

### `E505` — Herencia cíclica entre clases

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
class A : B { } class B : A { }
```

### `E506` — Miembro de clase duplicado

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
class C { let x: integer; let x: integer; }
```

### `E507` — Acceso con '.' sobre un valor que no es un objeto

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
let n: integer = 1; print(n.algo);
```

### `E508` — Sobrescritura de método con firma incompatible

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_classes.py`

```cps
class A { function f(a: integer): integer { return a; } }
class B : A { function f(a: string): integer { return 1; } }
```

---

## Listas y estructuras de datos

Enunciado, sección 2.6.

### `E601` — El índice de un arreglo debe ser de tipo integer

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_arrays.py`

```cps
let xs: integer[] = [1]; print(xs["a"]);
```

### `E602` — Indexación sobre un valor que no es un arreglo

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_arrays.py`

```cps
let n: integer = 1; print(n[0]);
```

### `W903` — Índice constante fuera del rango conocido del arreglo

*Severidad:* **advertencia** &nbsp;·&nbsp; *Tests:* `tests/test_arrays.py`

```cps
let xs: integer[] = [1, 2]; print(xs[99]);
```

---

## Reglas generales

Enunciado, sección 2.7.

### `E701` — La expresión no tiene sentido semántico

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
5 + 3;
```

### `E702` — 'print' no puede imprimir un valor de tipo void

*Severidad:* **error** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
function p() { } print(p());
```

### `W901` — Uso de una variable posiblemente no inicializada

*Severidad:* **advertencia** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
let x: integer; print(x);
```

### `W902` — Código muerto: instrucción inalcanzable

*Severidad:* **advertencia** &nbsp;·&nbsp; *Tests:* `tests/test_general.py`

```cps
function f(): integer { return 1; print("nunca"); }
```

---

## Cómo se prueba cada regla

Cada regla tiene, como mínimo, **un test de caso exitoso y uno de caso
fallido**:

```bash
python -m pytest tests/ -v            # las 364 pruebas
python -m pytest tests/ -m tipos      # sólo el sistema de tipos
python -m pytest tests/ -m clases     # sólo clases y objetos
```

Además, `tests/programs/invalid/*.cps` son programas completos con el
código esperado anotado en cada línea:

```cps
let malAritmetica = 1 + true;              // @error E101
let malAsignacion: integer = "hola";       // @error E105
```

`tests/test_programs.py` comprueba que **aparezca exactamente** el
diagnóstico anotado en esa línea y **ningún otro sin anotar**, de modo
que la batería también detecta falsos positivos.
