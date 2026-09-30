# ▶️ Guía de ejecución

Cómo instalar, ejecutar y extender el compilador de Compiscript.

---

## 1. Requisitos

| Para… | Necesitas |
| --- | --- |
| Ejecutar el compilador, el IDE y los tests | **Python 3.10+** |
| Regenerar el lexer/parser desde la gramática | **Java 11+** (sólo para ANTLR) |
| Usar los contenedores | **Docker** |

El código generado por ANTLR está versionado en `src/compiscript/generated/`,
así que **para usar el proyecto no hace falta Java**. Sólo se necesita si se
modifica `grammar/Compiscript.g4`.

---

## 2. Instalación local

```bash
git clone <url-del-repositorio>
cd Analisis-Semantico

python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### Opcional: instalarlo como comando

```bash
pip install -e .
compiscript mi_programa.cps        # ya disponible en el PATH
```

Sin instalarlo, hay que indicarle a Python dónde está el paquete:

```bash
# Linux / macOS
PYTHONPATH=src python -m compiscript mi_programa.cps

# Windows PowerShell
$env:PYTHONPATH="src"; python -m compiscript mi_programa.cps
```

---

## 3. Analizar un archivo (CLI)

```bash
python -m compiscript programa.cps
```

Salida de un programa correcto:

```
OK  El programa es semanticamente valido.
```

Salida con errores — cada uno señala la línea, la columna exacta y el código de
la regla:

```
programa.cps:4:25: error [E101] El operador '+' no puede aplicarse a 'integer'
                                y 'boolean'; se esperaban valores numericos.
    4 | let malAritmetica = 1 + true;
                                ^^^^
Resultado: 1 error(es).
```

### Opciones

| Opción | Qué hace |
| --- | --- |
| `--symbols`, `-s` | Imprime la tabla de símbolos completa |
| `--tree`, `-t` | Imprime el árbol sintáctico en texto, en **modo compacto**: se colapsan las cadenas de precedencia de ANTLR (`expression` → `assignmentExpr` → … → `primaryExpr`) conservando el nodo con contenido real y su tipo inferido |
| `--tree-completo`, `-T` | Igual, pero con **todos** los nodos de la gramática, sin colapsar |
| `--tokens` | Imprime el flujo de tokens |
| `--dot ARCHIVO` | Escribe el árbol (compacto) en formato Graphviz DOT |
| `--dot-completo` | Con `--dot`, exporta el árbol completo en vez del compacto |
| `--json` | Emite todo el resultado en JSON |
| `--quiet`, `-q` | Sólo el código de salida |
| `--no-color` | Desactiva los colores ANSI |

**Código de salida:** `0` si el programa es válido, `1` si hay errores, `2` si
no se encontró el archivo. Las advertencias no cambian el código de salida, lo
que permite usarlo en scripts:

```bash
python -m compiscript programa.cps --quiet && echo "compila"
```

### Ejemplos

```bash
# Tabla de símbolos con offsets y closures
python -m compiscript tests/programs/valid/03_funciones_y_closures.cps --symbols

# Árbol sintáctico a imagen (requiere Graphviz instalado)
python -m compiscript programa.cps --dot arbol.dot --quiet
dot -Tsvg arbol.dot -o arbol.svg

# Integración con otras herramientas
python -m compiscript programa.cps --json | jq '.diagnostics[].code'
```

---

## 4. El IDE

```bash
python ide/app.py
```

Abre **http://127.0.0.1:5000**. Opciones: `--port 8080`, `--host 0.0.0.0`,
`--debug`.

### Atajos de teclado

| Atajo | Acción |
| --- | --- |
| `Ctrl+Enter` o `F5` | Compilar |
| `Ctrl+S` | Descargar el archivo |
| `Ctrl+Espacio` | Autocompletado |
| `Ctrl+/` | Comentar la línea |

### Qué ofrece

- **Editor** Monaco con resaltado propio de Compiscript, autocompletado y
  snippets (`function`, `class`, `for`, `foreach`, `switch`, `trycatch`).
- **Análisis automático** mientras se escribe (se puede desactivar con la
  casilla *Auto*).
- **Problemas**: errores y advertencias con código, categoría y ubicación. Al
  hacer clic, el editor salta a esa línea.
- **Árbol sintáctico** plegable, con el tipo inferido de cada expresión.
- **Tabla de símbolos** por ámbitos anidados, con filtro de búsqueda.
- **Tokens** y **catálogo de reglas** consultables.
- Ejemplos precargados, abrir/guardar archivos y tema claro/oscuro.
- Los paneles se redimensionan arrastrando los separadores.

El IDE funciona **sin conexión a internet**: Monaco está incluido en el
repositorio.

---

## 5. Batería de tests

```bash
python -m pytest tests/            # las 364 pruebas
python -m pytest tests/ -v         # con el nombre de cada una
```

### Por categoría

```bash
python -m pytest tests/ -m tipos       # sistema de tipos (E1xx)
python -m pytest tests/ -m ambito      # manejo de ambito (E2xx)
python -m pytest tests/ -m funciones   # funciones (E3xx)
python -m pytest tests/ -m flujo       # control de flujo (E4xx)
python -m pytest tests/ -m clases      # clases y objetos (E5xx)
python -m pytest tests/ -m listas      # listas (E6xx)
python -m pytest tests/ -m generales   # generales y avisos (E7xx, W9xx)
python -m pytest tests/ -m tabla       # tabla de simbolos
```

### Cobertura

```bash
pip install pytest-cov
python -m pytest tests/ --cov=compiscript --cov-report=html
# abre htmlcov/index.html
```

### Añadir un caso de prueba

La forma más rápida es un programa `.cps` anotado. Crea el archivo en
`tests/programs/invalid/` y marca en cada línea el diagnóstico esperado:

```cps
// mi_caso.cps
let x: integer = "texto";      // @error E105
let y = 1 + true;              // @error E101
```

`test_programs.py` lo recoge automáticamente y verifica que aparezcan
**exactamente** esos diagnósticos y ninguno más.

Para un programa que debe compilar limpio, ponlo en `tests/programs/valid/`.

---

## 6. Docker

```bash
docker build -t compiscript .
```

| Comando | Qué hace |
| --- | --- |
| `docker run --rm compiscript` | Ejecuta la batería de tests (por defecto) |
| `docker run --rm -p 5000:5000 compiscript ide` | Levanta el IDE |
| `docker run --rm -v "$PWD:/trabajo" compiscript cli /trabajo/prog.cps` | Analiza un archivo del host |
| `docker run --rm -it compiscript shell` | Abre una shell dentro del contenedor |
| `docker run --rm compiscript grammar` | Regenera el parser |

### Con docker compose

```bash
docker compose up ide                 # IDE en http://localhost:5000
docker compose run --rm test          # tests
docker compose run --rm cli programa.cps
```

> **Windows (Git Bash):** al montar volúmenes, Git Bash reescribe las rutas que
> empiezan por `/`. Usa `MSYS_NO_PATHCONV=1` delante del comando:
>
> ```bash
> MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/trabajo" compiscript cli /trabajo/programa.cps
> ```

---

## 7. Modificar la gramática

Sólo si hace falta cambiar el lenguaje. Requiere **Java 11+**.

1. Edita `grammar/Compiscript.g4`.
2. Regenera el lexer, el parser y el visitor:

   ```bash
   python tools/generate_parser.py
   ```

   El script usa el jar que provee el curso
   (`compiscript/antlr-4.13.1-complete.jar`); para usar otro,
   `export ANTLR_JAR=/ruta/al/jar`.

3. Ajusta `collector.py` / `checker.py` si aparecen reglas o contextos nuevos.
4. Ejecuta la batería completa: `python -m pytest tests/`.

Los archivos de `src/compiscript/generated/` **no se editan a mano**: cualquier
cambio se pierde en la siguiente regeneración.

---

## 8. Añadir una regla semántica

1. **Registra el código** en `CATALOG`, en `src/compiscript/diagnostics.py`:

   ```python
   "E116": (Severity.ERROR, "Tipos", "Descripcion corta de la regla"),
   ```

2. **Impleméntala** en el `visitXxx` correspondiente de `checker.py`:

   ```python
   self._err("E116", f"Mensaje concreto para el usuario.", ctx)
   ```

3. **Escribe los dos tests** (caso exitoso y caso fallido) en el módulo de su
   categoría:

   ```python
   def test_e116_caso_valido():
       assert_ok("...")

   def test_e116_caso_invalido():
       assert_error("...", "E116")
   ```

4. **Añade el ejemplo** a `EJEMPLOS` en `tools/generar_doc_reglas.py` y
   regenera la documentación:

   ```bash
   python tools/generar_doc_reglas.py
   ```

   Si olvidas este paso el script avisa de que falta el ejemplo.

El código nuevo aparece automáticamente en el panel *Reglas* del IDE, porque se
sirve desde el mismo `CATALOG`.

---

## 9. Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| `ModuleNotFoundError: No module named 'compiscript'` | Falta la ruta al paquete: `PYTHONPATH=src` o `pip install -e .` |
| `ModuleNotFoundError: No module named 'antlr4'` | `pip install -r requirements.txt` |
| `ImportError` desde `compiscript.generated` | Regenera el parser: `python tools/generate_parser.py` |
| `'java' no esta en el PATH` al regenerar | Instala un JDK 11+ o usa `docker run --rm compiscript grammar` |
| El IDE carga pero el editor no aparece | Falta `ide/static/vendor/monaco/`; comprueba que se clonó completo |
| Acentos mal en la consola de Windows | `chcp 65001` antes de ejecutar, o usa `--json` |
| El puerto 5000 está ocupado | `python ide/app.py --port 8080` |
