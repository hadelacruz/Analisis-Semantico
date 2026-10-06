# 🧱 El lenguaje intermedio de Compiscript

Diseño del **código de tres direcciones (TAC)** al que traduce el compilador,
con el esquema de traducción de cada construcción del lenguaje y los supuestos
que se tomaron por el camino.

> La sintaxis del código intermedio es, según el enunciado, "a discreción del
> diseñador". La que sigue está basada en la notación del *Dragon Book*
> (Aho, Lam, Sethi y Ullman), con las extensiones mínimas que Compiscript
> necesita: despacho dinámico, closures y excepciones.

---

## 1. Por qué un código intermedio

Compiscript tiene clases, herencia, closures, `foreach` y excepciones. MIPS
tiene registros, saltos y direcciones. Traducir directamente de uno al otro
mezclaría dos problemas muy distintos: *qué significa cada construcción* y
*cómo se escribe en esta máquina concreta*.

El TAC resuelve el primero. Después de esta fase ya no quedan clases ni bucles:
sólo una lista plana de instrucciones donde cada una hace **una operación** con
**como máximo tres direcciones**.

```cps
let c: integer = (a + b) * (a - b);
```
```tac
t0 = a + b
t1 = a - b
t1 = t0 * t1
c = t1
```

Traducir `t0 = a + b` a `add $t0, $t1, $t2` es casi mecánico. Ahí está la
ganancia.

---

## 2. Repertorio de instrucciones

Diecisiete instrucciones, agrupadas por función.

### Movimiento de datos

| Instrucción | Significado |
| --- | --- |
| `x = y` | copia |
| `x = y op z` | `op` ∈ `+ - * / % < <= > >= == !=` |
| `x = op y` | `op` ∈ `- !` |
| `x = y[i]` | carga indexada; **`i` está en bytes** |
| `x[i] = y` | almacén indexado |

`y[i]` es el único modo de acceso a memoria dinámica. Sirve igual para un
elemento de un arreglo, un atributo de un objeto o una ranura de una tabla de
métodos: sólo cambia cómo se calcula `i`.

### Control de flujo

| Instrucción | Significado |
| --- | --- |
| `L:` | define la etiqueta `L` |
| `goto L` | salto incondicional |
| `if x goto L` | salta si `x` es cierto |
| `ifFalse x goto L` | salta si `x` es falso |
| `if x relop y goto L` | compara y salta; `relop` es un operador relacional |

`if x relop y goto L` existe para no tener que materializar el booleano
intermedio: es una sola instrucción y se traduce a un `beq`/`slt` de MIPS.

### Rutinas

| Instrucción | Significado |
| --- | --- |
| `begin_func f, marco=n` | entrada de la rutina `f`; su marco ocupa `n` bytes |
| `end_func f` | fin de la rutina |
| `param x` | apila un argumento |
| `x = call f, n` | llama a `f` con los `n` argumentos apilados |
| `x = call *t, n` | **llamada indirecta**: la dirección está en `t` |
| `return` / `return x` | vuelve al llamador |
| `set_access_link x` | fija el enlace de acceso del marco que se va a crear |

### Excepciones

| Instrucción | Significado |
| --- | --- |
| `push_handler L` | instala un manejador en `L` |
| `pop_handler` | retira el último manejador instalado |

### Comentarios

`; texto` — no ejecuta nada; el generador los emite para que el listado se
pueda leer. Se pueden desactivar.

---

## 3. Modelo de memoria

Tres zonas:

```
   +---------------------------+
   | codigo                    |  rutinas; se direccionan por etiqueta
   +---------------------------+
   | datos estaticos           |  variables globales, por desplazamiento
   +---------------------------+
   | pila                      |  registros de activacion; crece hacia abajo
   |            |              |
   |            v              |
   |                           |
   |            ^              |
   |            |              |
   | monticulo (heap)          |  objetos y arreglos; crece hacia arriba
   +---------------------------+
```

Cada símbolo sabe en cuál vive: la tabla de símbolos guarda su `storage`
(`global`, `local`, `parametro`, `atributo`, `codigo`) y su `offset` en bytes.

### Tamaños

| Tipo | Bytes | Representación |
| --- | --- | --- |
| `integer` | 4 | valor |
| `float` | 8 | valor |
| `boolean` | 1 | valor |
| `string` | 4 | puntero |
| arreglo `T[]` | 4 | puntero |
| instancia de clase | 4 | puntero |
| `null` | 4 | puntero nulo |

---

## 4. Registro de activación

Cada llamada crea un marco en la pila. `fp` (*frame pointer*) apunta al enlace
de control; todo lo demás se direcciona respecto de él.

```
        direcciones altas
        +-----------------------------+
 fp+8+k | parametro k                 |  los deja el LLAMADOR
        | ...                         |
 fp+4   | direccion de retorno        |
 fp+0   | enlace de control (fp ant.) |  <- fp
 fp-4   | enlace de acceso (estatico) |  <- hace posibles los closures
 fp-8-k | variable local k            |
        | ...                         |
        | temporales                  |  <- sp
        +-----------------------------+
        direcciones bajas
```

* **Enlace de control** — el `fp` del llamador. Sirve para volver.
* **Enlace de acceso** — el marco del **padre léxico**, no del llamador. Es lo
  que permite que una función anidada encuentre las variables que captura.
  Sólo lo llevan las rutinas anidadas.

El tamaño que reserva el prólogo es
`enlaces (8) + locales + temporales`; los parámetros los pone el llamador.
`begin_func f, marco=n` lo declara explícitamente.

La tabla de símbolos guarda toda esta información en
`FunctionSymbol.activation_record` (ver `symbols.py :: ActivationRecord`), y el
CLI la imprime con `--frames`:

```
  func_crearAcumulador   marco=20B  parametros=4B  locales=4B  temporales=2
      fp+4     direccion de retorno         4 B
      fp+0     enlace de control (fp)       4 B
      fp-8     variables locales            4 B
      fp-12    temporales (2)               8 B
```

---

## 5. Asignación y reciclaje de temporales

Requisito explícito del enunciado. El algoritmo vive en
`tac/temporaries.py :: TempPool`.

### El problema

```cps
(a + b) * (c + d) - (e + f) * (g + h)
```

Sin reutilizar nada hacen falta **7** temporales, y cada uno ocupa una ranura
del marco en **cada llamada**.

### El algoritmo

Un pool con **lista de libres**:

* `alloc()` — devuelve un nombre de la lista de libres; si está vacía, inventa
  uno nuevo.
* `free(t)` — devuelve `t` a la lista en cuanto su valor ya se consumió.

El generador libera los dos operandos justo antes de pedir el temporal del
resultado, que por tanto **reutiliza uno de ellos**:

```python
def _binary(self, operator, left, right, type_):
    self.temps.free(left)        # su valor ya se consumio
    self.temps.free(right)
    result = self.temps.alloc(type_)   # reutiliza uno de los dos
    self.emit(Op.BINARY, left, right, result, operator=operator)
    return result
```

La lista de libres es una **pila** (LIFO) a propósito: reutilizar el último
liberado mantiene los números bajos y agrupados, lo que hace el listado mucho
más legible que con una cola.

Resultado sobre la expresión de arriba: **3 temporales** en vez de 7.

```tac
t0 = a + b
t1 = c + d
t0 = t0 * t1      ; consume t0 y t1, reutiliza t0
t1 = e + f        ; t1 estaba libre
t2 = g + h
t1 = t1 * t2      ; consume t1 y t2, reutiliza t1
t0 = t0 - t1
```

### Dos métricas

* `created` — cuántos nombres distintos se inventaron.
* `peak` — cuántos vivieron **a la vez**. Éste es el que dimensiona el marco,
  y el que aparece en `begin_func`.

Los temporales se reinician en cada rutina: viven en su marco, así que los
nombres se repiten entre rutinas sin ningún conflicto.

---

## 6. Esquemas de traducción

### 6.1 Expresiones

Se recorren en postorden. Cada subexpresión deja su valor en un operando, y el
operador padre lo consume.

```cps
let c: integer = a + b * 2;
```
```tac
t0 = b * 2
t0 = a + t0
c = t0
```

### 6.2 Condiciones: código por saltos

Una condición **no se evalúa a un valor**: se traduce directamente a saltos.
Es el tratamiento clásico, y da el **cortocircuito** sin ningún esfuerzo extra.

`gen_condition(E, verdadero, falso)` genera código que salta a `verdadero` si
`E` es cierta y a `falso` si es falsa. Una de las dos etiquetas puede ser
"caer a la siguiente instrucción", lo que ahorra un `goto`.

| Forma | Traducción |
| --- | --- |
| `a && b` | `cond(a, _, falso)` · `cond(b, verdadero, falso)` |
| `a \|\| b` | `cond(a, verdadero, _)` · `cond(b, verdadero, falso)` |
| `!a` | `cond(a, falso, verdadero)` — se intercambian los destinos |
| `a relop b` | `if a relop b goto verdadero` |
| otra | evaluar a un valor y `if t goto verdadero` |

```cps
if (a > 0 && a < 10) { print(1); } else { print(2); }
```
```tac
    if a <= 0 goto L_else_1        ; se invierte la comparacion
    if a >= 10 goto L_else_1       ; para ahorrar el goto
    param 1
    call __print, 1
    goto L_fin_if_2
L_else_1:
    param 2
    call __print, 1
L_fin_if_2:
```

**El segundo operando no se evalúa si el primero ya decide**: eso es el
cortocircuito, y aquí sale gratis.

Cuando el booleano **sí** hace falta como valor (`let b = x && y;`), se
materializa con `_materialize_condition`: se usa el mismo código por saltos y
se asigna `true` o `false` en cada destino.

### 6.3 Bucles

```cps
while (i < 3) { print(i); i = i + 1; }
```
```tac
L_while_1:
    if i >= 3 goto L_fin_while_2
    param i
    call __print, 1
    t0 = i + 1
    i = t0
    goto L_while_1
L_fin_while_2:
```

El `for` es igual, pero con una etiqueta más: la **actualización** va al final
del cuerpo y con etiqueta propia, porque es ahí donde tiene que saltar
`continue`.

```cps
for (let i: integer = 0; i < 3; i = i + 1) { print(i); }
```
```tac
    i = 0
L_for_1:
    if i >= 3 goto L_fin_for_3
    param i
    call __print, 1
L_paso_for_2:                    ; <- destino de 'continue'
    t0 = i + 1
    i = t0
    goto L_for_1
L_fin_for_3:                     ; <- destino de 'break'
```

El `do-while` coloca la condición **al final**, que es justo su semántica.

`break` y `continue` se traducen consultando dos pilas de etiquetas que el
generador mantiene; se reinician al entrar en una función, porque un `break`
no cruza la frontera de una rutina.

### 6.4 `foreach`

Se expande a un bucle con índice explícito:

```cps
foreach (v in xs) { print(v); }
```
```tac
    param xs
    t0 = call __length, 1
    t1 = 0
L_foreach_1:
    if t1 >= t0 goto L_fin_foreach_3
    t2 = t1 * 4          ; tamano del elemento
    t2 = t2 + 4          ; salta la cabecera del arreglo
    t3 = xs[t2]
    v = t3
    param v
    call __print, 1
L_paso_foreach_2:
    t1 = t1 + 1
    goto L_foreach_1
L_fin_foreach_3:
```

### 6.5 `switch`

Primero **todas** las comparaciones, después **todos** los cuerpos seguidos:

```tac
    if n == 1 goto L_case_1
    if n == 2 goto L_case_2
    goto L_default_3
L_case_1:
    ...cuerpo del caso 1...      ; sin salto al final: CAE al siguiente
L_case_2:
    ...cuerpo del caso 2...
L_default_3:
    ...
L_fin_switch_4:
```

> **Supuesto de traducción.** Se implementa **cascada estilo C**: sin `break`,
> la ejecución continúa en el siguiente caso. Es la lectura coherente con que
> la gramática permita `break` dentro del `switch`; si cada caso terminara
> solo, ese `break` no tendría ningún propósito. Con `break` se emite
> `goto L_fin_switch`.

### 6.6 Rutinas

El llamador apila los argumentos y llama; el callee devuelve.

```cps
function suma(a: integer, b: integer): integer { return a + b; }
print(suma(1, 2));
```
```tac
    param 1
    param 2
    t0 = call func_suma, 2
    param t0
    call __print, 1
...
begin_func func_suma, marco=12
    t0 = a + b
    return t0
end_func func_suma
```

Las etiquetas se derivan de la tabla de símbolos: `func_<nombre>` para las
funciones globales, `<Clase>_<metodo>` para los métodos, y
`<padre>__<nombre>` para las anidadas.

**La recursión no necesita nada especial**: cada llamada crea su propio marco,
así que los parámetros y locales de cada nivel están separados por
construcción.

Toda rutina termina con `return`, aunque el programador no lo escriba.

### 6.7 Closures

Una función anidada necesita llegar a las variables de la función que la
contiene. El mecanismo es el **enlace de acceso**.

Al llamar, el llamador deja preparado el marco del padre léxico:

```tac
    set_access_link fp         ; el padre lexico de 'interna' es este marco
    param 1
    t0 = call func_externa__interna, 1
```

Y dentro, leer una variable capturada es subir por el enlace y aplicar el
desplazamiento que ya tenía en la tabla de símbolos:

```cps
function externa(base: integer): integer {
  let extra: integer = 5;
  function interna(x: integer): integer { return base + extra + x; }
  return interna(1);
}
```
```tac
begin_func func_externa__interna, marco=20
    t0 = fp[-4]        ; enlace de acceso -> marco de 'externa'
    t1 = t0[8]         ; 'base' es el parametro 0  -> fp+8
    t0 = fp[-4]
    t2 = t0[-8]        ; 'extra' es la local 0     -> fp-8
    t2 = t1 + t2
    t2 = t2 + x
    return t2
end_func func_externa__interna
```

Si la captura atraviesa varios niveles, se recorre el enlace tantas veces como
diga la diferencia de profundidades léxicas (`nesting_level`), que el análisis
semántico ya calculó.

> **Supuesto.** Los enlaces de acceso bastan porque en Compiscript **una
> función no puede escapar de su ámbito**: el análisis semántico rechaza usar
> el nombre de una función como valor (`E309`), así que un closure sólo puede
> invocarse mientras el marco de su padre sigue vivo. Un lenguaje que
> permitiera devolver funciones necesitaría cerrar el entorno en el heap.

### 6.8 Clases y despacho dinámico

**Layout del objeto.** Todo objeto empieza con un puntero a su tabla de
métodos; los atributos van detrás, y los heredados conservan su
desplazamiento:

```
   Animal                     Perro : Animal
   +--------------------+     +--------------------+
 0 | -> vtable_Animal   |   0 | -> vtable_Perro    |
 4 | nombre             |   4 | nombre   (heredado)|
 8 | patas              |   8 | patas    (heredado)|
   +--------------------+  12 | raza               |
   instancia = 12 bytes      +--------------------+
                             instancia = 16 bytes
```

Que `nombre` esté en el byte 4 en **ambas** clases es lo que permite tratar un
`Perro` como un `Animal` sin convertir nada.

**Tabla de métodos.** Una ranura por método. Una subclase hereda las ranuras y
sólo sustituye la entrada de los métodos que redefine:

```tac
    param 8
    vtable_Animal = call __alloc, 1
    vtable_Animal[0] = Animal_constructor
    vtable_Animal[4] = Animal_hablar
    param 8
    vtable_Perro = call __alloc, 1
    vtable_Perro[0] = Animal_constructor    ; heredado
    vtable_Perro[4] = Perro_hablar          ; sobrescrito
```

**Instanciación.**

```cps
let p: Animal = new Perro("Rex");
```
```tac
    param 12
    t0 = call __alloc, 1           ; new Perro (12 bytes)
    t0[0] = vtable_Perro           ; enlaza su tabla de metodos
    param t0                       ; this
    param "Rex"
    call Animal_constructor, 2     ; constructor heredado
    p = t0
```

**Llamada a método.** Se resuelve en ejecución, mirando la tabla del objeto:

```cps
print(p.hablar());
```
```tac
    t0 = p[0]          ; puntero a la tabla de metodos del objeto
    t1 = t0[4]         ; ranura de 'hablar'
    param p            ; this
    t0 = call *t1, 1   ; llamada indirecta
```

Aunque `p` esté declarada como `Animal`, si el objeto es un `Perro` se llama a
`Perro_hablar`. **Eso es polimorfismo de verdad**, no despacho por el tipo
declarado.

`this` es siempre el primer argumento, y dentro del método se accede a los
atributos por su desplazamiento: `this[4]`, `this[8]`, …

### 6.9 Arreglos

Cabecera de 4 bytes con la longitud; los elementos van detrás.

```
   +----------+----------+----------+----------+
   | longitud | elem 0   | elem 1   | ...      |
   +----------+----------+----------+----------+
   0          4          4+tam      4+2*tam
```

```cps
let xs: integer[] = [10, 20, 30];
```
```tac
    param 3            ; numero de elementos
    param 4            ; bytes por elemento
    t0 = call __array_new, 2
    t0[4] = 10
    t0[8] = 20
    t0[12] = 30
    xs = t0
```

Indexar escala por el tamaño del elemento y salta la cabecera:

```cps
print(xs[i]);
```
```tac
    param xs
    param i
    call __check_bounds, 2    ; aborta si i se sale del arreglo
    t0 = i * 4
    t0 = t0 + 4
    t1 = xs[t0]
```

La comprobación de rango se emite por defecto; se puede omitir con
`--sin-chequeos` (o `bounds_checks=False`).

Un arreglo de `float` escala por 8 en vez de por 4: el tamaño sale del tipo
del elemento, que el análisis semántico ya conoce.

### 6.10 Cadenas

`+` sobre cadenas no es una instrucción aritmética: es una llamada al runtime.
Si algún operando no es cadena, se convierte antes.

```cps
let s: string = "n = " + n;
```
```tac
    param n
    t0 = call __to_string, 1
    param "n = "
    param t0
    t0 = call __concat, 2
    s = t0
```

### 6.11 `try` / `catch`

```tac
    push_handler L_catch_1
    ...cuerpo del try...
    pop_handler
    goto L_fin_try_2
L_catch_1:
    t0 = call __exc_message, 0
    e = t0
    ...cuerpo del catch...
L_fin_try_2:
```

Los manejadores forman una pila. Cuando algo falla, el runtime desapila hasta
el manejador más reciente, descarta los marcos que queden por encima y salta a
su etiqueta. Por eso una excepción lanzada dentro de una función llega al
`catch` de quien la llamó.

---

## 7. Biblioteca de apoyo (*runtime*)

Operaciones que no se pueden expresar con tres direcciones sin inventar decenas
de instrucciones. El código intermedio las invoca como funciones normales; la
fase de MIPS las implementará una sola vez en ensamblador.

| Rutina | Aridad | Devuelve | Qué hace |
| --- | --- | --- | --- |
| `__print` | 1 | no | imprime un valor y un salto de línea |
| `__concat` | 2 | sí | concatena dos cadenas |
| `__to_string` | 1 | sí | convierte cualquier valor a cadena |
| `__alloc` | 1 | sí | reserva *n* bytes en el heap |
| `__array_new` | 2 | sí | reserva un arreglo de *n* elementos |
| `__length` | 1 | sí | longitud de un arreglo |
| `__check_bounds` | 2 | no | aborta si el índice se sale |
| `__throw` | 1 | no | lanza una excepción |
| `__exc_message` | 0 | sí | mensaje de la excepción que se atiende |

Están declaradas en `tac/runtime.py`, lo que permite que el validador
compruebe su aridad y que la máquina virtual las ejecute.

**División entre cero y desreferencia de `null`** no llevan comprobación
explícita: las detecta la propia operación, como haría el hardware. Ambas
lanzan una excepción atrapable.

---

## 8. Supuestos de traducción

Decisiones que el enunciado no fija y que hubo que tomar. Todas están cubiertas
por tests.

| Supuesto | Justificación |
| --- | --- |
| **El `switch` tiene cascada estilo C** | Si cada caso terminara solo, el `break` que la gramática permite dentro del `switch` no tendría propósito. |
| **Despacho dinámico por tabla de métodos** | Sin él, `let a: Animal = new Perro(); a.hablar();` llamaría a `Animal.hablar`, que es semánticamente incorrecto. |
| **Todo objeto lleva una cabecera de 4 bytes** | Es el precio del despacho dinámico. Desplaza los atributos, pero los mantiene en el mismo sitio en toda la jerarquía. |
| **Closures con enlace de acceso, no con entorno en el heap** | En Compiscript una función no puede escapar de su ámbito, así que el marco del padre siempre está vivo. |
| **`this` se pasa como primer argumento** | Es la convención habitual y evita inventar un registro dedicado. |
| **Una variable sin inicializador se pone a su valor neutro** | `0`, `false` o `null` según el tipo. Así el código generado nunca lee memoria indeterminada. |
| **El `+` con cadenas se resuelve en el runtime** | La concatenación necesita reservar memoria; no cabe en una instrucción de tres direcciones. |
| **La división entera trunca** | `7 / 2` da `3`, como el `div` de MIPS. |
| **Las comprobaciones de rango se emiten por defecto** | El propio ejemplo del curso accede fuera de rango dentro de un `try`; sin la comprobación, ese programa no funcionaría. |
| **No se genera código si hay errores semánticos** | Traducir un programa con errores produciría basura. |

---

## 9. Validación del código generado

El análisis semántico garantiza que el **programa fuente** tiene sentido. El
validador (`tac/validator.py`) garantiza que el **código generado** está bien
formado, que es otra cosa: un fallo del generador produce TAC sintácticamente
correcto pero incorrecto.

| Código | Qué detecta |
| --- | --- |
| `T001` | salto a una etiqueta que no existe |
| `T002` | etiqueta definida dos veces |
| `T003` | operador inválido para la instrucción |
| `T004` | los `param` no cuadran con la aridad de la llamada |
| `T005` | llamada a una rutina inexistente |
| `T006` | aridad incorrecta en una rutina del runtime |
| `T007` | temporal leído sin escribirse nunca |
| `T008` | rutina mal delimitada |
| `T009` | rutina que no termina en `return` |
| `T010` | instrucción con operandos incompletos |

Esto es lo que permite escribir **casos fallidos** en la batería de esta fase:
se construye a mano un programa TAC roto y se comprueba que el validador lo
detecta (`tests/test_tac_validador.py`).

---

## 10. Máquina virtual

`tac/vm.py` ejecuta el código intermedio. No forma parte del compilador, pero
cumple dos funciones:

1. **Demuestra que la traducción es correcta.** Un test que compara texto
   comprueba que el TAC *se parece* a lo esperado; ejecutarlo comprueba que
   `factorial(5)` da realmente `120`.
2. **Documenta el modelo de ejecución** que MIPS tendrá que reproducir: pila de
   marcos con enlaces de control y de acceso, heap con objetos y arreglos,
   tablas de métodos y pila de manejadores.

Es un **modelo**, no un emulador de bytes: los enteros y las cadenas se guardan
como valores. Lo que sí es fiel es el **direccionamiento**: cada local y cada
parámetro se lee en su desplazamiento respecto de `fp`, y cada atributo en su
desplazamiento dentro del objeto, exactamente como dice la tabla de símbolos.
**Si un offset estuviera mal calculado, el programa daría otro resultado y el
test fallaría.**

```bash
python -m compiscript programa.cps --run
```

---

## 11. Qué queda para la fase de MIPS

El TAC está diseñado para que la última fase sea, en su mayor parte, una
traducción local:

| Del TAC | A MIPS |
| --- | --- |
| `x = y + z` | `lw` + `add` + `sw`, con `getReg()` eligiendo registros |
| `if x < y goto L` | `slt` + `bne` |
| `param x` / `call f, n` | escribir el marco y `jal` |
| `begin_func f, marco=n` | prólogo: guardar `$ra`, `$fp`, restar `n` a `$sp` |
| `return x` | epílogo: valor en `$v0`, restaurar y `jr $ra` |
| `x = y[i]` | `add` + `lw` |
| `call *t, n` | `jalr` |
| rutinas `__*` | una implementación en ensamblador, escrita una sola vez |

La información que necesitará ya está toda en la tabla de símbolos:
desplazamientos, tamaños, etiquetas, tamaño de cada marco y número de
temporales.
