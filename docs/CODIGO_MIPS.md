# ⚙️ Generación de código MIPS

Diseño de la fase final: cómo se baja del código de tres direcciones al
ensamblador de MIPS, con el convenio de llamada, el algoritmo de asignación de
registros y la biblioteca de apoyo.

---

## 1. Qué queda por resolver

El TAC ya aplanó todo lo que Compiscript tenía de alto nivel. Lo que queda son
tres problemas, y los tres son de **máquina**, no de lenguaje:

| Problema | Por qué aparece |
| --- | --- |
| **Registros** | El TAC supone temporales ilimitados; MIPS tiene 32 registros |
| **Llamadas** | El TAC dice `call f, 2`; MIPS necesita construir y destruir un marco de pila sin perder el estado |
| **Representación** | La máquina virtual del TAC podía guardar una cadena como un valor; aquí hay que decidir cuántos bytes ocupa |

---

## 2. Convenio de llamada

### Distribución del marco

```
        direcciones altas
        +-----------------------------+
 fp+8+k | parametro k                 |  los empuja el LLAMADOR
        | ...                         |
 fp+8   | parametro 0                 |  en un metodo, aqui va 'this'
 fp+4   | direccion de retorno ($ra)  |
 fp+0   | $fp del llamador            |  <- fp
 fp-4   | enlace de acceso            |  solo en rutinas anidadas
 fp-8   | variables locales           |
        | ...                         |
        | temporales                  |
        +-----------------------------+  <- sp
        direcciones bajas
```

Coincide con la distribución que ya guardaba la tabla de símbolos desde la
fase 1 (`ActivationRecord`), más el `$ra` que MIPS obliga a salvar.

### El llamador

```mips
    addiu $sp, $sp, -8          # zona de argumentos
    li    $t0, 3
    sw    $t0, 0($sp)           # primer argumento en la direccion mas baja
    li    $t1, 4
    sw    $t1, 4($sp)
    jal   func_suma
    addiu $sp, $sp, 8           # retira los argumentos
    move  $t0, $v0              # resultado
```

El primer argumento queda en la dirección **más baja** de la zona, que tras el
prólogo del callee es exactamente `fp+8`.

### El callee: prólogo

```mips
func_suma:
    addiu $sp, $sp, -8          # espacio para $ra y el $fp viejo
    sw    $ra, 4($sp)           # -> fp+4
    sw    $fp, 0($sp)           # -> fp+0
    move  $fp, $sp              # fp apunta al enlace de control
    addiu $sp, $sp, -16         # enlace de acceso + locales + temporales
```

Los 16 bytes salen de `4 (enlace de acceso) + local_size + temporales × 8`.
Se reservan **8 bytes por temporal** y no 4 porque un temporal puede contener
un doble.

### El callee: epílogo

```mips
    move  $v0, $t2              # valor de retorno ($f0 si es un doble)
    move  $sp, $fp              # libera locales y temporales
    lw    $ra, 4($sp)
    lw    $fp, 0($sp)           # restaura el marco del llamador
    addiu $sp, $sp, 8
    jr    $ra
```

`main` termina distinto: `li $v0, 10` + `syscall`, que es la salida del
programa.

### Métodos y despacho dinámico

`this` viaja como primer argumento, así que ocupa `fp+8` y los parámetros
declarados se corren a `fp+12`. La llamada a un método se resuelve en
ejecución:

```mips
    lw    $t0, 0($t1)           # puntero a la tabla de metodos del objeto
    lw    $t2, 4($t0)           # ranura del metodo
    addiu $sp, $sp, -4
    sw    $t1, 0($sp)           # this
    jalr  $t2                   # llamada indirecta
```

### Funciones anidadas

El enlace de acceso viaja en `$t8`, que está reservado justo para eso. El
llamador lo deja preparado y el prólogo del callee lo guarda:

```mips
    move  $t8, $fp              # el padre lexico es este mismo marco
    jal   func_externa__interna
...
func_externa__interna:
    ...
    sw    $t8, -4($fp)          # enlace de acceso
```

---

## 3. `getReg()`: asignación de registros

Implementado en `mips/registers.py`.

### Qué registros se reparten

| Banco | Registros | Cuántos |
| --- | --- | --- |
| Enteros | `$t0`–`$t7`, `$s0`–`$s7` | 16 |
| Flotantes | `$f4`, `$f6`, … `$f30` | 14 |

Sólo los **pares** en el banco flotante: la doble precisión usa parejas de
registros y la pareja tiene que empezar en uno par.

Reservados, nunca se reparten:

| Registro | Para qué |
| --- | --- |
| `$t8` | Enlace de acceso en las llamadas a funciones anidadas |
| `$t9` | Borrador del generador: calcular direcciones, cargar etiquetas |
| `$v0` | Valor de retorno y selector de `syscall` |
| `$a0`–`$a3` | Argumentos de las rutinas de apoyo y de los `syscall` |
| `$f0`, `$f2` | Retorno flotante y borrador de conversión |

### El algoritmo

Es el clásico de los **descriptores** (Dragon Book, cap. 8):

* El **descriptor de registro** dice qué valor contiene cada registro.
* El **descriptor de dirección** dice dónde vive cada valor.

Al pedir un registro para un valor:

1. Si **ya está en un registro**, se devuelve ese y no se lee memoria.
2. Si hay un **registro libre**, se toma.
3. Si no, se **expulsa el menos usado recientemente** (LRU). Si estaba sucio
   —su valor aún no se escribió— primero se vuelca a su posición en el marco:
   eso es el *spilling*.

Los operandos de la instrucción en curso se **fijan** para que no se expulsen
a sí mismos. Si todo está fijado y aún falta sitio, el generador falla con un
error explícito en vez de emitir código corrupto.

### Bordes de bloque básico

En una etiqueta, un salto o una llamada se vuelcan todos los registros sucios
y se vacían los descriptores. Es lo que hace correcta una asignación local:
tras un salto no se puede suponer nada sobre lo que contienen los registros, y
tras un `jal` hay que asumir que el callee los pisó.

> Como el llamador vuelca todo antes de cada llamada, los `$s` no necesitan
> que el callee los preserve: se usan simplemente como ocho registros más.

### Por qué local y no global

Una asignación global necesitaría análisis de vivacidad y coloreado de grafos.
La local captura la mayor parte del beneficio —los resultados intermedios de
una expresión no tocan memoria— con un algoritmo verificable instrucción a
instrucción.

El efecto se mide: `--regs` informa de cuántos accesos se sirvieron desde un
registro.

```
  valores servidos desde un registro : 153
  cargas desde memoria               : 79
  volcados por falta de registros    : 164
  tasa de acierto                    : 65.9%
```

Y dentro de una sola expresión no hay ningún volcado:

```mips
func_suma:
    lw    $t0, 8($fp)           # a   <- unica lectura
    lw    $t1, 12($fp)          # b   <- unica lectura
    addu  $t2, $t0, $t1
    move  $t3, $t2
    li    $t4, 2
    mul   $t2, $t3, $t4         # todo en registros
    move  $v0, $t2
```

---

## 4. Estructura del archivo generado

```mips
    .data
__globals:      .space N            # variables globales
vtable_Clase:   .word 0             # punteros a las tablas de metodos
__str0:         .asciiz "..."       # literales de cadena
    .align 3
__dbl0:         .double 3.14        # literales flotantes
__handlers:     .space 384          # pila de manejadores de excepciones
__buf:          .space 64           # buffers de las conversiones

    .text
    .globl main
main:           ...                 # programa principal
func_*:         ...                 # funciones del usuario
Clase_*:        ...                 # metodos
__alloc:        ...                 # biblioteca de apoyo
```

El generador hace **dos pasadas** sobre el programa TAC:

1. **Recolección.** No emite código: recorre las cuádruplas juntando literales
   de cadena y de punto flotante, y recorre la tabla de símbolos para saber
   cuánto espacio reservar a las globales. De ahí sale `.data`.
2. **Traducción.** Por cada rutina: etiqueta, prólogo, una cuádrupla a la vez
   pidiendo registros a `getReg()`, epílogo. De ahí sale `.text`.

Se emite a **dos buffers separados** y se concatenan, porque el orden en que
se descubren las cosas no es el orden en que hay que escribirlas.

---

## 5. Traducción de cada instrucción

| TAC | MIPS |
| --- | --- |
| `x = y` | `move` / `mov.d` |
| `x = y + z` (enteros) | `addu` |
| `x = y + z` (dobles) | `add.d` |
| `x = y - z`, `* `, `/`, `%` | `subu`, `mul`, `div`, `rem` |
| `x = y < z` (enteros) | `slt` (y `sle`, `sgt`, `sge`, `seq`, `sne`) |
| `x = y < z` (dobles) | `c.lt.d` + `bc1t` sobre un `li` |
| `x = -y` | `negu` / `neg.d` |
| `x = !y` | `xori x, y, 1` |
| `x = y[i]` | `lw` / `l.d` con desplazamiento |
| `x[i] = y` | `sw` / `s.d` |
| `goto L` | `j L` |
| `if x goto L` | `bne x, $zero, L` |
| `ifFalse x goto L` | `beq x, $zero, L` |
| `if x < y goto L` | `blt` (y `ble`, `bgt`, `bge`, `beq`, `bne`) |
| `param x` | se acumula; se escribe en la zona de argumentos al llegar al `call` |
| `x = call f, n` | `jal f` + `move x, $v0` |
| `x = call *t, n` | `jalr t` |
| `return x` | `move $v0, x` + epílogo |
| `set_access_link x` | `move $t8, x` |
| `push_handler L` | `la $a0, L` + `jal __handler_push` |
| `pop_handler` | `jal __handler_pop` |

### Mezcla de enteros y dobles

Una expresión como `1 + IVA` mezcla un literal entero con un doble. La
conversión es explícita:

```mips
    mtc1    $t0, $f2            # el entero entra al coprocesador
    cvt.d.w $f4, $f2            # y se convierte a doble
    add.d   $f6, $f4, $f8
```

### División entre cero

Se emite una comprobación antes de dividir, salvo cuando el divisor es una
constante distinta de cero y el compilador ya sabe que no puede fallar:

```mips
    beq  $t1, $zero, __div_zero
    div  $t2, $t0, $t1
```

Así una división entre cero se puede atrapar con `try`/`catch`, igual que en
la máquina virtual del TAC.

---

## 6. Biblioteca de apoyo

Las nueve rutinas que invoca el código intermedio, escritas una sola vez en
ensamblador (`mips/runtime.py`).

| Rutina | Qué hace |
| --- | --- |
| `__alloc` | Reserva memoria con `sbrk` (syscall 9), alineada a 8 |
| `__array_new` | Reserva la cabecera con la longitud más los elementos |
| `__length` | Lee la longitud de la cabecera |
| `__check_bounds` | Comprueba el índice y, si se sale, construye el mensaje y lanza |
| `__concat` | Concatena dos cadenas en memoria nueva |
| `__itoa` / `__ftoa` / `__btoa` | Conversión a texto |
| `__str_cmp` | Comparación de cadenas; de ahí salen las seis comparaciones |
| `__handler_push` / `__handler_pop` / `__throw` | Excepciones |
| `__print_*` | Una variante por tipo, elegida en compilación |

### Impresión especializada en compilación

El TAC dice `call __print, 1`. Como cada operando lleva su tipo, el generador
sabe cuál llamar y no hace falta una rutina polimórfica:

| Tipo | Rutina |
| --- | --- |
| `integer` | `__print_int` (syscall 1) |
| `float` | `__print_float` (convierte con `__ftoa` y usa syscall 4) |
| `string` | `__print_str` (syscall 4) |
| `boolean` | `__print_bool` (`"true"` / `"false"`) |
| `null` | `__print_null` |

### Conversión de dobles a texto

`__ftoa` reproduce el formato de la máquina virtual del TAC: parte entera
truncada, parte fraccionaria redondeada a seis decimales y recorte de los
ceros finales y del punto suelto. Contempla el desbordamiento del redondeo
(`0.9999999` → `1000000`), que obliga a incrementar la parte entera.

Es lo que hace que `100.0 * 1.12` se imprima `112` y no `112.00000000000001`.

### Excepciones

La pila de manejadores guarda, por cada `try` activo, la dirección del `catch`
y los punteros de pila y de marco de ese momento. Al lanzar se restauran y se
salta, lo que descarta de golpe todos los marcos intermedios: por eso una
excepción lanzada dentro de una función llega al `catch` de quien la llamó.

---

## 7. Representación de los datos

Lo que la máquina virtual del TAC podía dejar sin decidir:

| Tipo | Representación | Notas |
| --- | --- | --- |
| `integer` | 4 bytes, palabra | |
| `float` | 8 bytes, IEEE doble | `.align 3` en datos estáticos; en memoria se mueve en dos palabras (ver §10) |
| `boolean` | palabra con 0 o 1 | se guarda en palabra aunque ocupe 1 byte |
| `string` | puntero a bytes terminados en `\0` | inmutable; `__concat` reserva memoria nueva |
| `null` | puntero 0 | las rutinas de cadena lo tratan como `"null"` |
| arreglo | puntero; `[0]` es la longitud | |
| objeto | puntero; `[0]` es la tabla de métodos | |

---

## 8. Ejecutar el código

### En MARS

**Es el simulador con el que está verificado el ensamblador** (MARS 4.5; ver
§10). Hay que descargarlo aparte: es un `.jar` y necesita Java.

Basta dejarlo en la raíz del proyecto o en `tools/` y el compilador lo
encuentra solo:

```bash
python -m compiscript programa.cps --sim
```

La búsqueda, en orden: la variable `MARS_JAR`, un `Mars*.jar` en la raíz o en
`tools/`, y por último `spim` en el `PATH`.

Para abrirlo en la interfaz gráfica —lo más útil para inspeccionar registros y
memoria paso a paso— hay que guardar el `.asm` primero:

```bash
python -m compiscript programa.cps --mips-out programa.asm
java -jar Mars4_5.jar nc programa.asm        # 'nc' quita el banner
```

El mismo texto que muestra la pestaña *Código MIPS* del IDE, que también tiene
un botón para descargarlo.

### En SPIM

```bash
spim -file programa.asm
```

### Con el emulador incluido

```bash
python -m compiscript programa.cps --run-mips
```

---

## 9. El emulador incluido

`mips/emulator.py`. No sustituye a MARS: existe por dos motivos concretos.

1. **La batería de tests es autocontenida.** Sin él no habría forma de
   comprobar automáticamente que el `.asm` calcula lo correcto, porque MARS no
   se distribuye con el proyecto.
2. **Valida el artefacto de verdad.** No ejecuta estructuras internas: parsea
   **el mismo texto** que recibiría MARS, así que un error de impresión del
   generador se detecta igual.

Soporta exactamente el subconjunto de MIPS que emite el compilador. Cualquier
instrucción fuera de ese subconjunto levanta un error en vez de ignorarse, de
modo que un hueco del emulador nunca se confunde con un programa correcto.

### La prueba más fuerte

Los tests comprueban que **las dos representaciones dan el mismo resultado**:
se ejecuta el mismo programa en la máquina virtual del TAC y en el emulador de
MIPS, y la salida tiene que coincidir línea por línea.

```
01_tipos_y_operadores.cps    5 lineas identicas
02_ambitos_y_bloques.cps    11 lineas identicas
03_funciones_y_closures.cps  9 lineas identicas
04_clases_y_herencia.cps    11 lineas identicas
05_control_de_flujo.cps     13 lineas identicas
06_listas_y_matrices.cps    23 lineas identicas (*)
07_programa_completo.cps    13 lineas identicas
program.cps (del curso)     20 lineas identicas
```

(*) Salvo una línea: `print` de un arreglo imprime su **dirección**, que
depende de dónde la coloque cada runtime. Es la única diferencia posible y
está contemplada en el test.

---

## 10. Validación contra MARS

Las secciones anteriores se validan con el emulador incluido. Eso **no basta**:
el generador y el emulador los escribió la misma persona, así que un
malentendido compartido sobre lo que hace una instrucción pasa los dos filtros
sin que nadie lo note. Por eso el ensamblador se ejecuta además en **MARS
4.5**, que no comparte ningún supuesto con este proyecto.

```
$ python -m compiscript programa.cps --sim
```

El resultado, en los ocho programas, es idéntico al del emulador. Pero llegar
ahí costó tres correcciones, y las tres son el argumento de por qué hacía
falta un juez externo: **ninguna la detectaba el emulador**.

### Lo que MARS encontró

**1. Dobles sin alinear** — `address not aligned on doubleword boundary 0x1001002c`

`l.d`/`s.d` se expanden a `ldc1`/`sdc1`, que exigen una dirección múltiplo de
8. Los desplazamientos que asigna el análisis semántico no lo garantizan (un
`float` puede caer en el desplazamiento 44) y `$sp` tampoco llega alineado a 8
en MARS. Ahora los dobles se mueven en **dos palabras** (`lwc1`/`swc1`), que
sólo necesitan alineación de 4.

**2. Datos sin alinear** — `store address not aligned on word boundary 0x10010041`

Un `.asciiz` de longitud impar deja el cursor de `.data` sin alinear, y MARS no
realinea por su cuenta. Con `__globals` de 48 bytes más dos cadenas de 9 y 8,
`__handlers` caía en `0x10010041` y el primer `sw` abortaba. Ahora se emite
`.align 2` antes de cada bloque que se accede por palabras.

**3. Redondeo distinto** — `pi=3.141599` en vez de `pi=3.1416`

`cvt.w.d` usa el modo de redondeo del FCSR, que arranca en *round-to-nearest*.
**MARS no implementa el FCSR y trunca.** `3.1416` en binario es
`3.14159999…`, así que multiplicado por 10⁶ da `141599.9999…`: redondeado es
`141600` (y el texto queda `3.1416`), truncado es `141599` (`3.141599`). El
redondeo se hace ahora **explícito** —sumar 0.5 y `trunc.w.d`— sin depender
del FCSR.

Los dos primeros son errores propios: ensamblador que ningún MIPS ejecutaría.
El tercero es más sutil, porque el emulador seguía la norma y MARS no, pero da
igual quién tenga razón: **el código tiene que dar lo mismo en los dos**, así
que no puede depender de un modo de redondeo.

### El emulador quedó tan estricto como MARS

La lección de los dos primeros fallos no era sólo arreglarlos, sino que el
emulador **no volviera a ser más permisivo que el simulador externo**. Ahora
comprueba la alineación en cada acceso a memoria y aborta igual que MARS
(`_exigir_alineacion`, en `mips/emulator.py`).

Sin eso, los tests seguirían dando luz verde a ensamblador que MARS rechaza, y
toda la batería valdría menos de lo que parece.

### Qué cubre la batería

`tests/test_mips_simulador.py`. Las comprobaciones sobre el texto generado
—alineación de `.data`, movimiento de dobles en pares, ausencia de `cvt.w.d`—
corren **siempre**, aunque no haya simulador instalado. Las que ejecutan en
MARS se saltan solas si no lo encuentra, así que el proyecto sigue siendo
comprobable en una máquina sin él.

## 11. Supuestos de esta fase

| Supuesto | Justificación |
| --- | --- |
| **Asignación local de registros** | Una global exigiría coloreado de grafos; la local ya evita que los parciales de una expresión toquen memoria |
| **El llamador vuelca todo antes de `jal`** | Hace innecesario que el callee preserve los `$s`, y es lo correcto si no se analiza qué registros usa la rutina llamada |
| **8 bytes por temporal en el marco** | Un temporal puede contener un doble; reservar 4 sería incorrecto y reservar según el tipo complicaría el cálculo del marco |
| **`this` es el primer argumento** | Evita inventar un registro dedicado y encaja con la zona de argumentos que ya existe |
| **Las cadenas son inmutables** | `__concat` siempre reserva memoria nueva, así que nunca hay aliasing que gestionar |
| **No se libera memoria** | `__alloc` sólo avanza. Un recolector de basura queda fuera del alcance del curso |
| **Sólo se comprueba la división entera entre cero** | En punto flotante IEEE define el resultado (infinito) en vez de un fallo |
| **Las tablas de métodos se construyen en ejecución** | Se traduce el TAC tal cual lo emitió la fase anterior; emitirlas estáticas en `.data` sería una optimización, no una traducción |
| **Los dobles se mueven en dos palabras** | `ldc1`/`sdc1` exigirían alineación de 8, que los desplazamientos de la fase 1 no garantizan. Cuesta una instrucción más por acceso y evita rediseñar la asignación de desplazamientos |
| **El redondeo de dobles a texto es explícito** | `cvt.w.d` depende del FCSR, que MARS no implementa. Sumar 0.5 y truncar da el mismo resultado en cualquier simulador |

---

## 12. De dónde sale cada cosa

| Lo que pide el enunciado | Dónde está |
| --- | --- |
| Secuencias de llamada y retorno | `mips/generator.py` — `_prologo`, `_epilogo`, `_t_call` |
| `getReg()` y uso de la pila | `mips/registers.py` |
| Código MIPS funcional y simulado | `mips/runtime.py`, `mips/emulator.py`, `mips/simulator.py` |
| Batería de tests | `tests/test_mips_*.py` — 170 pruebas |
| IDE | Pestaña *Código MIPS* y botón *Ejecutar* |
| Documentación | Este documento y `ARQUITECTURA.md` |
