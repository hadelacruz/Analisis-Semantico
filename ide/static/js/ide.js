/* ==========================================================================
   IDE de Compiscript — logica de la interfaz.

   Responsabilidades:
     1. Arrancar el editor Monaco con el lenguaje Compiscript.
     2. Enviar el codigo a POST /api/analizar y pintar la respuesta.
     3. Subrayar los errores en el editor y listarlos en el panel inferior.
     4. Renderizar el arbol sintactico, la tabla de simbolos y los tokens.
   ========================================================================== */

(function () {
  "use strict";

  const CODIGO_INICIAL = `// Bienvenido al IDE de Compiscript.
// Escribe codigo y pulsa "Compilar" (o Ctrl+Enter).

const IVA: float = 0.12;

class Producto {
  let nombre: string;
  let precio: float;

  function constructor(nombre: string, precio: float) {
    this.nombre = nombre;
    this.precio = precio;
  }

  function conImpuesto(): float {
    return this.precio * (1 + IVA);
  }
}

function total(items: Producto[]): float {
  let suma: float = 0.0;
  foreach (item in items) {
    suma = suma + item.conImpuesto();
  }
  return suma;
}

let carrito: Producto[] = [
  new Producto("teclado", 250.0),
  new Producto("mouse", 120.5)
];

print("Total: " + total(carrito));
`;

  // Estado -----------------------------------------------------------------
  let editor = null;
  let ultimoResultado = null;
  let temporizador = null;
  let decoraciones = [];
  let sucio = false;

  const $ = (id) => document.getElementById(id);
  const escapar = (texto) =>
    String(texto).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  // =========================================================================
  // Arranque del editor
  // =========================================================================
  require.config({ paths: { vs: window.RUTA_MONACO + "/vs" } });

  require(["vs/editor/editor.main"], function () {
    definirLenguajeCompiscript(monaco);

    editor = monaco.editor.create($("editor"), {
      value: localStorage.getItem("compiscript:codigo") || CODIGO_INICIAL,
      language: "compiscript",
      theme: "compiscript-oscuro",
      automaticLayout: true,
      fontSize: 14,
      fontFamily: '"JetBrains Mono", "Cascadia Code", Consolas, monospace',
      fontLigatures: true,
      minimap: { enabled: true, scale: 1 },
      scrollBeyondLastLine: false,
      renderWhitespace: "selection",
      tabSize: 2,
      insertSpaces: true,
      smoothScrolling: true,
      cursorBlinking: "smooth",
      bracketPairColorization: { enabled: true },
      "semanticHighlighting.enabled": true
    });

    editor.onDidChangeModelContent(() => {
      marcarSucio(true);
      localStorage.setItem("compiscript:codigo", editor.getValue());
      if ($("chk-auto").checked) {
        clearTimeout(temporizador);
        temporizador = setTimeout(analizar, 450);
      }
    });

    editor.onDidChangeCursorPosition((e) => {
      $("posicion-cursor").textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
    });

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, analizar);
    editor.addCommand(monaco.KeyCode.F5, analizar);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, guardar);

    conectarInterfaz();
    cargarEjemplos();
    cargarReglas();
    analizar();
  });

  // =========================================================================
  // Comunicacion con el backend
  // =========================================================================
  async function analizar() {
    if (!editor) return;
    const inicio = performance.now();
    ponerEstado("Analizando...", "trabajando");

    try {
      const respuesta = await fetch("/api/analizar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codigo: editor.getValue(), nombre: $("nombre-archivo").textContent })
      });
      if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);

      ultimoResultado = await respuesta.json();
      const ms = Math.round(performance.now() - inicio);
      pintarResultado(ultimoResultado, ms);
      marcarSucio(false);
    } catch (error) {
      ponerEstado("Error de conexion con el servidor", "fallo");
      $("salida").textContent = "No se pudo contactar al analizador:\n" + error;
    }
  }

  function pintarResultado(resultado, ms) {
    pintarMarcadores(resultado.diagnostics);
    pintarProblemas(resultado.diagnostics);
    pintarArbol(resultado.tree);
    pintarSimbolos(resultado.symbols);
    pintarTokens(resultado.tokens);
    pintarSalida(resultado, ms);

    const errores = resultado.errorCount;
    const avisos = resultado.warningCount;

    $("conteo-errores").textContent = `${errores} error${errores === 1 ? "" : "es"}`;
    $("conteo-errores").classList.toggle("activo", errores > 0);
    $("conteo-avisos").textContent = `${avisos} aviso${avisos === 1 ? "" : "s"}`;
    $("conteo-avisos").classList.toggle("activo", avisos > 0);
    $("tiempo").textContent = `${ms} ms`;

    const insignia = $("insignia-problemas");
    insignia.textContent = errores + avisos;
    insignia.className = "insignia" + (errores ? " hay-errores" : avisos ? " hay-avisos" : "");

    if (errores === 0) {
      ponerEstado(avisos ? "Compilado con advertencias" : "Compilacion exitosa", "ok");
    } else {
      ponerEstado(`Compilacion fallida (${errores})`, "fallo");
    }
  }

  // =========================================================================
  // Marcadores dentro del editor
  // =========================================================================
  function pintarMarcadores(diagnosticos) {
    const modelo = editor.getModel();
    const marcadores = diagnosticos.map((d) => ({
      severity:
        d.severity === "error"
          ? monaco.MarkerSeverity.Error
          : monaco.MarkerSeverity.Warning,
      message: `[${d.code}] ${d.message}`,
      source: d.category,
      code: d.code,
      startLineNumber: d.line,
      startColumn: d.column,
      endLineNumber: d.endLine,
      endColumn: Math.max(d.endColumn, d.column + 1)
    }));
    monaco.editor.setModelMarkers(modelo, "compiscript", marcadores);
  }

  function irALinea(linea, columna) {
    editor.revealLineInCenter(linea);
    editor.setPosition({ lineNumber: linea, column: columna });
    editor.focus();

    decoraciones = editor.deltaDecorations(decoraciones, [
      {
        range: new monaco.Range(linea, 1, linea, 1),
        options: { isWholeLine: true, className: "linea-resaltada" }
      }
    ]);
    setTimeout(() => { decoraciones = editor.deltaDecorations(decoraciones, []); }, 1400);
  }

  // =========================================================================
  // Panel de problemas
  // =========================================================================
  function pintarProblemas(diagnosticos) {
    const contenedor = $("problemas");
    if (!diagnosticos.length) {
      contenedor.innerHTML =
        '<div class="vacio"><span class="grande">&#10004;</span>' +
        "Sin errores ni advertencias.</div>";
      return;
    }

    contenedor.innerHTML = diagnosticos
      .map(
        (d) => `
        <div class="problema ${d.severity}" data-linea="${d.line}" data-columna="${d.column}">
          <span class="icono-problema">${d.severity === "error" ? "&#10006;" : "&#9888;"}</span>
          <span class="codigo-problema">${d.code}</span>
          <div class="cuerpo-problema">
            <div class="mensaje-problema">${escapar(d.message)}</div>
            <div class="detalle-problema">
              <span>linea ${d.line}, columna ${d.column}</span>
              <span>${escapar(d.category)}</span>
            </div>
          </div>
        </div>`
      )
      .join("");

    contenedor.querySelectorAll(".problema").forEach((nodo) => {
      nodo.addEventListener("click", () =>
        irALinea(Number(nodo.dataset.linea), Number(nodo.dataset.columna))
      );
    });
  }

  // =========================================================================
  // Arbol sintactico
  // =========================================================================
  function pintarArbol(arbol) {
    const contenedor = $("arbol");
    if (!arbol) {
      contenedor.innerHTML = '<div class="vacio">No hay arbol que mostrar.</div>';
      return;
    }
    contenedor.innerHTML = "";
    contenedor.appendChild(construirNodo(arbol, 0));
  }

  function construirNodo(nodo, profundidad) {
    const elemento = document.createElement("div");
    elemento.className = "nodo";
    // Se colapsan por defecto los niveles profundos para no saturar la vista.
    if (profundidad > 3 && nodo.children.length) elemento.classList.add("colapsado");

    const linea = document.createElement("div");
    linea.className = "nodo-linea";

    const flecha = document.createElement("span");
    flecha.className = "flecha" + (nodo.children.length ? "" : " vacia");
    flecha.textContent = "▾";
    linea.appendChild(flecha);

    const etiqueta = document.createElement("span");
    etiqueta.className =
      nodo.kind === "rule" ? "etiqueta-regla" : nodo.kind === "error" ? "etiqueta-error" : "etiqueta-token";
    etiqueta.textContent = nodo.kind === "rule" ? nodo.label : `"${nodo.label}"`;
    linea.appendChild(etiqueta);

    if (nodo.type && $("chk-tipos").checked) {
      const tipo = document.createElement("span");
      tipo.className = "tipo-nodo";
      tipo.textContent = nodo.type;
      linea.appendChild(tipo);
    }

    if (nodo.kind !== "rule") {
      const posicion = document.createElement("span");
      posicion.className = "pos-nodo";
      posicion.textContent = `${nodo.line}:${nodo.column}`;
      linea.appendChild(posicion);
    }

    linea.addEventListener("click", (evento) => {
      evento.stopPropagation();
      if (nodo.children.length) elemento.classList.toggle("colapsado");
      if (nodo.line) irALinea(nodo.line, nodo.column || 1);
    });

    elemento.appendChild(linea);

    if (nodo.children.length) {
      const hijos = document.createElement("div");
      hijos.className = "hijos";
      nodo.children.forEach((hijo) => hijos.appendChild(construirNodo(hijo, profundidad + 1)));
      elemento.appendChild(hijos);
    }
    return elemento;
  }

  // =========================================================================
  // Tabla de simbolos
  // =========================================================================
  function pintarSimbolos(ambito) {
    const contenedor = $("simbolos");
    if (!ambito) {
      contenedor.innerHTML =
        '<div class="vacio">La tabla de simbolos se construye cuando el programa no tiene errores de sintaxis.</div>';
      return;
    }
    const filtro = $("filtro-simbolos").value.trim().toLowerCase();
    contenedor.innerHTML = "";
    const nodo = construirAmbito(ambito, filtro);
    if (nodo) contenedor.appendChild(nodo);
    else contenedor.innerHTML = '<div class="vacio">Ningun simbolo coincide con el filtro.</div>';
  }

  function construirAmbito(ambito, filtro) {
    const simbolos = filtro
      ? ambito.symbols.filter(
          (s) =>
            s.name.toLowerCase().includes(filtro) ||
            s.type.toLowerCase().includes(filtro) ||
            s.category.toLowerCase().includes(filtro)
        )
      : ambito.symbols;

    const hijos = ambito.children
      .map((hijo) => construirAmbito(hijo, filtro))
      .filter(Boolean);

    if (filtro && !simbolos.length && !hijos.length) return null;

    const elemento = document.createElement("div");
    elemento.className = "ambito";

    const cabecera = document.createElement("div");
    cabecera.className = "ambito-cabecera";
    cabecera.innerHTML =
      `<span class="flecha">▾</span>` +
      `<span class="chip chip-${ambito.kind}">${ambito.kind}</span>` +
      `<span class="ambito-nombre">${escapar(ambito.name)}</span>` +
      `<span class="ambito-meta">#${ambito.id} &middot; ${simbolos.length} simbolo(s)` +
      (ambito.frameSize ? ` &middot; marco ${ambito.frameSize}B` : "") +
      `</span>`;
    cabecera.addEventListener("click", () => elemento.classList.toggle("colapsado"));
    elemento.appendChild(cabecera);

    const cuerpo = document.createElement("div");
    cuerpo.className = "ambito-cuerpo";

    if (simbolos.length) cuerpo.appendChild(construirTablaSimbolos(simbolos));

    if (hijos.length) {
      const contenedorHijos = document.createElement("div");
      contenedorHijos.className = "ambito-anidados";
      hijos.forEach((h) => contenedorHijos.appendChild(h));
      cuerpo.appendChild(contenedorHijos);
    }

    elemento.appendChild(cuerpo);
    return elemento;
  }

  function construirTablaSimbolos(simbolos) {
    const tabla = document.createElement("table");
    tabla.className = "simbolos";
    tabla.innerHTML =
      "<thead><tr>" +
      "<th>Nombre</th><th>Categoria</th><th>Tipo</th><th>Ln</th>" +
      "<th>Almacen</th><th>Offset</th><th>Tam</th><th>Notas</th>" +
      "</tr></thead><tbody></tbody>";

    const cuerpo = tabla.querySelector("tbody");
    simbolos.forEach((s) => {
      const notas = [];
      if (s.captured) notas.push('<span class="nota nota-capturada">capturada</span>');
      if (s.isRecursive) notas.push('<span class="nota nota-recursiva">recursiva</span>');
      if (s.captures && s.captures.length)
        notas.push(`<span class="nota nota-closure">closure[${s.captures.join(", ")}]</span>`);
      if (s.superclass) notas.push(`<span class="nota">hereda de ${escapar(s.superclass)}</span>`);
      if (s.instanceSize) notas.push(`<span class="nota">instancia ${s.instanceSize}B</span>`);
      if (s.label) notas.push(`<span class="nota">${escapar(s.label)}</span>`);
      if (!s.initialized && (s.category === "variable" || s.category === "atributo"))
        notas.push('<span class="nota nota-aviso">sin inicializar</span>');
      if (!s.used && s.category !== "clase")
        notas.push('<span class="nota nota-aviso">no usada</span>');

      const fila = document.createElement("tr");
      fila.innerHTML =
        `<td class="col-nombre">${escapar(s.name)}</td>` +
        `<td class="col-cat">${escapar(s.category)}</td>` +
        `<td class="col-tipo">${escapar(s.type)}</td>` +
        `<td class="col-num">${s.line}</td>` +
        `<td>${escapar(s.storage)}</td>` +
        `<td class="col-num">${s.offset === null ? "-" : s.offset}</td>` +
        `<td class="col-num">${s.size}</td>` +
        `<td>${notas.join("")}</td>`;
      fila.addEventListener("click", () => irALinea(s.line, s.column || 1));
      cuerpo.appendChild(fila);
    });
    return tabla;
  }

  // =========================================================================
  // Tokens
  // =========================================================================
  function pintarTokens(tokens) {
    const contenedor = $("tokens");
    if (!tokens || !tokens.length) {
      contenedor.innerHTML = '<div class="vacio">Sin tokens.</div>';
      return;
    }
    contenedor.innerHTML =
      '<table class="rejilla"><thead><tr><th>#</th><th>Tipo</th><th>Texto</th><th>Ln:Col</th>' +
      "</tr></thead><tbody>" +
      tokens
        .map(
          (t, i) =>
            `<tr data-linea="${t.line}" data-columna="${t.column}">` +
            `<td class="col-num">${i + 1}</td>` +
            `<td class="tipo-token">${escapar(t.type)}</td>` +
            `<td class="texto-token">${escapar(t.text)}</td>` +
            `<td class="col-num">${t.line}:${t.column}</td></tr>`
        )
        .join("") +
      "</tbody></table>";

    contenedor.querySelectorAll("tr[data-linea]").forEach((fila) => {
      fila.addEventListener("click", () =>
        irALinea(Number(fila.dataset.linea), Number(fila.dataset.columna))
      );
    });
  }

  // =========================================================================
  // Catalogo de reglas
  // =========================================================================
  let reglasCargadas = [];

  async function cargarReglas() {
    try {
      reglasCargadas = await (await fetch("/api/reglas")).json();
      pintarReglas();
    } catch (_) {
      $("reglas").innerHTML = '<div class="vacio">No se pudo cargar el catalogo.</div>';
    }
  }

  function pintarReglas() {
    const filtro = $("filtro-reglas").value.trim().toLowerCase();
    const visibles = reglasCargadas.filter(
      (r) =>
        !filtro ||
        r.codigo.toLowerCase().includes(filtro) ||
        r.descripcion.toLowerCase().includes(filtro) ||
        r.categoria.toLowerCase().includes(filtro)
    );
    $("reglas").innerHTML =
      '<table class="rejilla"><thead><tr><th>Codigo</th><th>Categoria</th><th>Descripcion</th>' +
      "</tr></thead><tbody>" +
      visibles
        .map(
          (r) =>
            `<tr><td class="codigo-regla ${r.severidad === "warning" ? "aviso" : ""}">${r.codigo}</td>` +
            `<td>${escapar(r.categoria)}</td><td>${escapar(r.descripcion)}</td></tr>`
        )
        .join("") +
      "</tbody></table>";
  }

  // =========================================================================
  // Salida textual
  // =========================================================================
  function pintarSalida(resultado, ms) {
    const lineas = [];
    lineas.push(`Archivo   : ${resultado.filename}`);
    lineas.push(`Resultado : ${resultado.ok ? "VALIDO" : "CON ERRORES"}`);
    lineas.push(`Errores   : ${resultado.errorCount}`);
    lineas.push(`Avisos    : ${resultado.warningCount}`);
    lineas.push(`Tokens    : ${resultado.tokens ? resultado.tokens.length : 0}`);
    lineas.push(`Tiempo    : ${ms} ms`);
    if (!resultado.semanticRan) {
      lineas.push("");
      lineas.push("El analisis semantico no se ejecuto: primero hay que corregir");
      lineas.push("los errores de sintaxis (el arbol esta incompleto).");
    }
    if (resultado.diagnostics.length) {
      lineas.push("");
      lineas.push("--- diagnosticos ---");
      resultado.diagnostics.forEach((d) => {
        lineas.push(
          `${String(d.line).padStart(4)}:${String(d.column).padEnd(3)} ` +
            `${d.severity === "error" ? "error " : "aviso "} [${d.code}] ${d.message}`
        );
      });
    }
    $("salida").textContent = lineas.join("\n");
  }

  // =========================================================================
  // Interfaz
  // =========================================================================
  function ponerEstado(texto, clase) {
    const nodo = $("estado");
    nodo.textContent = texto;
    nodo.className = "estado " + (clase || "");
  }

  function marcarSucio(valor) {
    sucio = valor;
    $("marca-sucio").hidden = !valor;
  }

  function guardar() {
    const contenido = editor.getValue();
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(new Blob([contenido], { type: "text/plain" }));
    enlace.download = $("nombre-archivo").textContent || "programa.cps";
    enlace.click();
    URL.revokeObjectURL(enlace.href);
  }

  function conectarInterfaz() {
    $("btn-compilar").addEventListener("click", analizar);

    // Pestanas (lateral e inferior)
    document.querySelectorAll(".pestanas").forEach((grupo) => {
      grupo.addEventListener("click", (evento) => {
        const boton = evento.target.closest(".pestana");
        if (!boton) return;
        const contenedor = grupo.parentElement;
        grupo.querySelectorAll(".pestana").forEach((b) => b.classList.remove("activa"));
        boton.classList.add("activa");
        contenedor.querySelectorAll(".vista").forEach((v) => v.classList.remove("activa"));
        contenedor.querySelector("#vista-" + boton.dataset.vista).classList.add("activa");
      });
    });

    // Arbol
    $("btn-expandir").addEventListener("click", () =>
      document.querySelectorAll("#arbol .nodo").forEach((n) => n.classList.remove("colapsado"))
    );
    $("btn-colapsar").addEventListener("click", () =>
      document
        .querySelectorAll("#arbol .nodo")
        .forEach((n, i) => i > 0 && n.classList.add("colapsado"))
    );
    $("chk-tipos").addEventListener("change", () => {
      if (ultimoResultado) pintarArbol(ultimoResultado.tree);
    });

    // Filtros
    $("filtro-simbolos").addEventListener("input", () => {
      if (ultimoResultado) pintarSimbolos(ultimoResultado.symbols);
    });
    $("filtro-reglas").addEventListener("input", pintarReglas);

    // Archivos
    $("btn-abrir").addEventListener("click", () => $("input-archivo").click());
    $("input-archivo").addEventListener("change", (evento) => {
      const archivo = evento.target.files[0];
      if (!archivo) return;
      const lector = new FileReader();
      lector.onload = () => {
        editor.setValue(lector.result);
        $("nombre-archivo").textContent = archivo.name;
        analizar();
      };
      lector.readAsText(archivo);
      evento.target.value = "";
    });
    $("btn-guardar").addEventListener("click", guardar);

    // Tema
    $("btn-tema").addEventListener("click", () => {
      const raiz = document.documentElement;
      const oscuro = raiz.dataset.tema === "oscuro";
      raiz.dataset.tema = oscuro ? "claro" : "oscuro";
      monaco.editor.setTheme(oscuro ? "compiscript-claro" : "compiscript-oscuro");
      $("btn-tema").innerHTML = oscuro ? "&#9789;" : "&#9788;";
    });

    // Ejemplos
    $("sel-ejemplos").addEventListener("change", async (evento) => {
      const archivo = evento.target.value;
      if (!archivo) return;
      const datos = await (await fetch("/api/ejemplos/" + archivo)).json();
      editor.setValue(datos.codigo);
      $("nombre-archivo").textContent = datos.archivo;
      evento.target.value = "";
      analizar();
    });

    configurarSeparadores();

    window.addEventListener("beforeunload", (evento) => {
      if (sucio) evento.preventDefault();
    });
  }

  async function cargarEjemplos() {
    try {
      const ejemplos = await (await fetch("/api/ejemplos")).json();
      const selector = $("sel-ejemplos");
      ejemplos.forEach((e) => {
        const opcion = document.createElement("option");
        opcion.value = e.archivo;
        opcion.textContent = e.nombre;
        selector.appendChild(opcion);
      });
    } catch (_) { /* sin ejemplos disponibles */ }
  }

  /** Permite arrastrar los separadores para redimensionar los paneles. */
  function configurarSeparadores() {
    const raiz = document.documentElement;

    arrastrar($("separador-v"), (evento) => {
      const ancho = Math.min(Math.max(window.innerWidth - evento.clientX, 260), window.innerWidth - 360);
      raiz.style.setProperty("--ancho-lateral", ancho + "px");
    });

    arrastrar($("separador-h"), (evento) => {
      const alto = Math.min(Math.max(window.innerHeight - evento.clientY - 26, 90), window.innerHeight - 240);
      raiz.style.setProperty("--alto-inferior", alto + "px");
    });
  }

  function arrastrar(manija, alMover) {
    if (!manija) return;
    manija.addEventListener("mousedown", (inicio) => {
      inicio.preventDefault();
      document.body.style.userSelect = "none";
      const mover = (evento) => alMover(evento);
      const soltar = () => {
        document.body.style.userSelect = "";
        window.removeEventListener("mousemove", mover);
        window.removeEventListener("mouseup", soltar);
      };
      window.addEventListener("mousemove", mover);
      window.addEventListener("mouseup", soltar);
    });
  }
})();
