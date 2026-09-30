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
    refrescarArbol();
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
  //
  // Dos ejes independientes:
  //   * detalle : "compacto" (sin la cascada de precedencia de ANTLR) o
  //               "completo" (todos los nodos de la gramatica).
  //   * vista   : "indentado" (arbol plegable) o "grafico" (SVG con nodos
  //               y aristas, con zoom, desplazamiento y seleccion).
  // El backend manda los dos arboles en la misma respuesta, asi que cambiar
  // de modo es instantaneo y no vuelve a analizar.
  // =========================================================================
  let modoArbol = "compacto";       // compacto | completo
  let subvistaArbol = "indentado";  // indentado | grafico

  /** Arbol que corresponde al modo activo. */
  function arbolActivo() {
    if (!ultimoResultado) return null;
    if (modoArbol === "compacto") {
      // treeCompact solo falta si el backend es de una version anterior.
      return ultimoResultado.treeCompact || ultimoResultado.tree;
    }
    return ultimoResultado.tree;
  }

  function contarNodos(nodo) {
    if (!nodo) return 0;
    return 1 + nodo.children.reduce((total, hijo) => total + contarNodos(hijo), 0);
  }

  /** Repinta la vista de arbol activa y actualiza el contador de nodos. */
  function refrescarArbol() {
    const arbol = arbolActivo();

    const conteo = $("conteo-nodos");
    if (conteo) {
      if (!arbol) {
        conteo.textContent = "";
      } else if (modoArbol === "compacto" && ultimoResultado.tree) {
        const compactos = contarNodos(arbol);
        const completos = contarNodos(ultimoResultado.tree);
        const ahorro = completos ? Math.round((1 - compactos / completos) * 100) : 0;
        conteo.textContent = `${compactos} nodos (${ahorro}% menos que el completo)`;
      } else {
        conteo.textContent = `${contarNodos(arbol)} nodos`;
      }
    }

    pintarArbolIndentado(arbol);
    if (subvistaArbol === "grafico") pintarArbolGrafico(arbol);
  }

  function pintarArbolIndentado(arbol) {
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

    // En modo compacto: cuantas reglas de precedencia absorbio este nodo.
    if (nodo.collapsed && nodo.collapsed.length) {
      const insignia = document.createElement("span");
      insignia.className = "pos-nodo";
      insignia.textContent = `+${nodo.collapsed.length}`;
      insignia.title = "Reglas colapsadas:\n" + nodo.collapsed.join("\n");
      linea.appendChild(insignia);
    }

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
  // Arbol sintactico — vista grafica (SVG con nodos y aristas)
  //
  // Disposicion: recorrido en dos fases. Primero se mide cada subarbol
  // (ancho = max(ancho propio, suma de los anchos de los hijos + separacion));
  // luego se colocan los hijos dentro de la banda de su padre y el padre se
  // centra sobre ellos. Con eso ningun nodo se solapa con sus hermanos.
  // =========================================================================
  const SVG_NS = "http://www.w3.org/2000/svg";
  const ALTO_NODO = 26;
  const SEP_HORIZONTAL = 16;
  const SEP_VERTICAL = 62;
  const ANCHO_MINIMO = 46;
  const MAX_NODOS_GRAFICO = 3500;   // por encima de esto el SVG deja de ser util

  const ESCALA_MINIMA_AJUSTE = 0.25;  // por debajo de esto no se lee nada

  let vista = { escala: 1, x: 0, y: 0 };
  let lienzoG = null;               // <g> que recibe la transformacion
  let nodoSeleccionado = null;
  let geometria = null;             // { ancho, alto, raizX } del dibujo actual
  let ajustePendiente = false;      // se dibujo con el panel oculto

  function textoDelNodo(nodo, conTipo) {
    let texto = nodo.kind === "rule" ? nodo.label : `"${nodo.label}"`;
    if (conTipo && nodo.type) texto += " : " + nodo.type;
    return texto;
  }

  /** Ancho aproximado de la caja para un rotulo monoespaciado de 11px. */
  function anchoDeTexto(texto) {
    return Math.max(ANCHO_MINIMO, texto.length * 6.7 + 20);
  }

  function medirSubarbol(nodo, conTipo) {
    const texto = textoDelNodo(nodo, conTipo);
    const propio = anchoDeTexto(texto);
    const hijos = nodo.children.map((h) => medirSubarbol(h, conTipo));
    const anchoHijos = hijos.length
      ? hijos.reduce((total, h) => total + h.ancho, 0) + (hijos.length - 1) * SEP_HORIZONTAL
      : 0;
    return { datos: nodo, texto, propio, hijos, anchoHijos, ancho: Math.max(propio, anchoHijos) };
  }

  function colocarSubarbol(medida, izquierda, profundidad) {
    medida.y = profundidad * SEP_VERTICAL;
    if (medida.hijos.length) {
      let cursor = izquierda + (medida.ancho - medida.anchoHijos) / 2;
      medida.hijos.forEach((hijo) => {
        colocarSubarbol(hijo, cursor, profundidad + 1);
        cursor += hijo.ancho + SEP_HORIZONTAL;
      });
      const primero = medida.hijos[0];
      const ultimo = medida.hijos[medida.hijos.length - 1];
      // Centrado sobre los hijos, pero sin salirse de la banda reservada: si un
      // hijo es mucho mas ancho que otro el centro se desplaza y la caja del
      // padre invadiria la del hermano de al lado.
      const centro = (primero.x + ultimo.x) / 2;
      const minimo = izquierda + medida.propio / 2;
      const maximo = izquierda + medida.ancho - medida.propio / 2;
      medida.x = Math.min(Math.max(centro, minimo), maximo);
    } else {
      medida.x = izquierda + medida.ancho / 2;
    }
  }

  function aplanar(medida, salida) {
    salida.push(medida);
    medida.hijos.forEach((hijo) => aplanar(hijo, salida));
    return salida;
  }

  function pintarArbolGrafico(arbol) {
    const contenedor = $("grafico");
    contenedor.innerHTML = "";
    lienzoG = null;
    nodoSeleccionado = null;

    if (!arbol) {
      contenedor.innerHTML = '<div class="aviso-grafico">No hay arbol que mostrar.</div>';
      return;
    }

    const total = contarNodos(arbol);
    if (total > MAX_NODOS_GRAFICO) {
      contenedor.innerHTML =
        '<div class="aviso-grafico">El arbol tiene ' + total + " nodos: demasiados para " +
        "dibujarlos de forma legible.<br>Cambia a <strong>Compacto</strong> o usa la vista " +
        "<strong>Indentado</strong>.</div>";
      return;
    }

    const conTipo = $("chk-tipos").checked;
    const raiz = medirSubarbol(arbol, conTipo);
    colocarSubarbol(raiz, 0, 0);
    const medidas = aplanar(raiz, []);

    const margen = 30;
    const ancho = raiz.ancho + margen * 2;
    const alto = Math.max(...medidas.map((m) => m.y)) + ALTO_NODO + margen * 2;

    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");

    const grupo = document.createElementNS(SVG_NS, "g");
    svg.appendChild(grupo);
    lienzoG = grupo;

    // Aristas primero, para que queden por debajo de las cajas.
    medidas.forEach((m) => {
      m.hijos.forEach((h) => {
        const arista = document.createElementNS(SVG_NS, "path");
        const x1 = m.x + margen;
        const y1 = m.y + ALTO_NODO + margen;
        const x2 = h.x + margen;
        const y2 = h.y + margen;
        const medio = (y1 + y2) / 2;
        arista.setAttribute("d", `M ${x1} ${y1} C ${x1} ${medio}, ${x2} ${medio}, ${x2} ${y2}`);
        arista.setAttribute("class", "arista");
        grupo.appendChild(arista);
      });
    });

    medidas.forEach((m) => {
      const nodo = m.datos;
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute("class", "nodo-g");

      const caja = document.createElementNS(SVG_NS, "rect");
      caja.setAttribute("class", "caja " + nodo.kind);
      caja.setAttribute("x", m.x - m.propio / 2 + margen);
      caja.setAttribute("y", m.y + margen);
      caja.setAttribute("width", m.propio);
      caja.setAttribute("height", ALTO_NODO);
      caja.setAttribute("rx", 6);
      g.appendChild(caja);

      const rotulo = document.createElementNS(SVG_NS, "text");
      rotulo.setAttribute("class", "rotulo " + (nodo.kind === "rule" ? "regla" : "token"));
      rotulo.setAttribute("x", m.x + margen);
      rotulo.setAttribute("y", m.y + ALTO_NODO / 2 + margen);
      rotulo.textContent = m.texto;
      g.appendChild(rotulo);

      const ayuda = document.createElementNS(SVG_NS, "title");
      const partes = [nodo.label];
      if (nodo.type) partes.push("tipo: " + nodo.type);
      if (nodo.line) partes.push("linea " + nodo.line + ", columna " + nodo.column);
      if (nodo.collapsed && nodo.collapsed.length)
        partes.push("reglas colapsadas: " + nodo.collapsed.join(" > "));
      ayuda.textContent = partes.join("\n");
      g.appendChild(ayuda);

      g.addEventListener("click", (evento) => {
        evento.stopPropagation();
        if (nodoSeleccionado) nodoSeleccionado.classList.remove("seleccionado");
        g.classList.add("seleccionado");
        nodoSeleccionado = g;
        if (nodo.line) irALinea(nodo.line, nodo.column || 1);
      });

      grupo.appendChild(g);
    });

    contenedor.appendChild(svg);
    geometria = { ancho, alto, raizX: raiz.x + margen };
    ajustarGrafico();
  }

  function aplicarTransformacion() {
    if (!lienzoG) return;
    lienzoG.setAttribute(
      "transform",
      `translate(${vista.x}, ${vista.y}) scale(${vista.escala})`
    );
    $("nivel-zoom").textContent = Math.round(vista.escala * 100) + "%";
  }

  /** Encaja el arbol en el lienzo, sin bajar de una escala legible.
   *
   * Un parse tree es muchisimo mas ancho que alto (el de `program.cps` mide
   * ~48.000 px de ancho), asi que "ajustar" al ancho dejaria una escala del
   * 0,6 % en la que no se lee nada. Cuando eso pasa se ajusta al **alto**, se
   * respeta una escala minima y se arranca centrado en la raiz, que es por
   * donde uno empieza a leer; el resto se alcanza arrastrando.
   */
  function ajustarGrafico() {
    const contenedor = $("grafico");
    const caja = contenedor.getBoundingClientRect();
    if (!geometria) return;
    if (!caja.width || !caja.height) {
      // El panel esta oculto (otra pestana activa): no se puede medir todavia.
      // Se reintenta en cuanto vuelva a tener tamano.
      ajustePendiente = true;
      return;
    }
    ajustePendiente = false;

    const porAncho = caja.width / geometria.ancho;
    const porAlto = caja.height / geometria.alto;
    vista.escala = Math.min(Math.max(Math.min(porAncho, porAlto), ESCALA_MINIMA_AJUSTE), 1.4);

    const anchoDibujado = geometria.ancho * vista.escala;
    vista.x =
      anchoDibujado <= caja.width
        ? (caja.width - anchoDibujado) / 2            // cabe entero: se centra
        : caja.width / 2 - geometria.raizX * vista.escala;  // no cabe: raiz al centro
    vista.y = 12;
    aplicarTransformacion();
  }

  function ampliar(factor, centroX, centroY) {
    if (!lienzoG) return;
    const caja = $("grafico").getBoundingClientRect();
    const cx = centroX === undefined ? caja.width / 2 : centroX;
    const cy = centroY === undefined ? caja.height / 2 : centroY;
    const nueva = Math.min(Math.max(vista.escala * factor, 0.08), 4);
    // Se mantiene fijo el punto bajo el cursor.
    vista.x = cx - ((cx - vista.x) * nueva) / vista.escala;
    vista.y = cy - ((cy - vista.y) * nueva) / vista.escala;
    vista.escala = nueva;
    aplicarTransformacion();
  }

  function conectarGrafico() {
    const contenedor = $("grafico");

    contenedor.addEventListener(
      "wheel",
      (evento) => {
        evento.preventDefault();
        const caja = contenedor.getBoundingClientRect();
        ampliar(
          evento.deltaY < 0 ? 1.12 : 1 / 1.12,
          evento.clientX - caja.left,
          evento.clientY - caja.top
        );
      },
      { passive: false }
    );

    contenedor.addEventListener("mousedown", (inicio) => {
      if (inicio.button !== 0) return;
      const desdeX = inicio.clientX - vista.x;
      const desdeY = inicio.clientY - vista.y;
      contenedor.classList.add("arrastrando");

      const mover = (evento) => {
        vista.x = evento.clientX - desdeX;
        vista.y = evento.clientY - desdeY;
        aplicarTransformacion();
      };
      const soltar = () => {
        contenedor.classList.remove("arrastrando");
        window.removeEventListener("mousemove", mover);
        window.removeEventListener("mouseup", soltar);
      };
      window.addEventListener("mousemove", mover);
      window.addEventListener("mouseup", soltar);
    });

    $("btn-zoom-mas").addEventListener("click", () => ampliar(1.25));
    $("btn-zoom-menos").addEventListener("click", () => ampliar(1 / 1.25));
    $("btn-zoom-ajustar").addEventListener("click", () => ajustarGrafico());

    // Si el arbol se dibujo mientras el panel estaba oculto (el usuario estaba
    // en otra pestana), se encuadra en cuanto vuelve a tener tamano.
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => {
        if (ajustePendiente) ajustarGrafico();
      }).observe(contenedor);
    }
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

    // El modo del arbol se recuerda entre sesiones; compacto por defecto.
    const guardado = localStorage.getItem("compiscript:modoArbol");
    if (guardado === "completo" || guardado === "compacto") modoArbol = guardado;
    $("modo-arbol")
      .querySelectorAll(".segmento")
      .forEach((b) => b.classList.toggle("activo", b.dataset.modo === modoArbol));

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
    $("chk-tipos").addEventListener("change", refrescarArbol);

    // Interruptor Compacto / Completo
    $("modo-arbol").addEventListener("click", (evento) => {
      const boton = evento.target.closest(".segmento");
      if (!boton || boton.dataset.modo === modoArbol) return;
      modoArbol = boton.dataset.modo;
      $("modo-arbol")
        .querySelectorAll(".segmento")
        .forEach((b) => b.classList.toggle("activo", b.dataset.modo === modoArbol));
      localStorage.setItem("compiscript:modoArbol", modoArbol);
      refrescarArbol();
    });

    // Sub-pestanas Indentado / Grafico
    $("subpestanas-arbol").addEventListener("click", (evento) => {
      const boton = evento.target.closest(".subpestana");
      if (!boton) return;
      subvistaArbol = boton.dataset.sub;
      $("subpestanas-arbol")
        .querySelectorAll(".subpestana")
        .forEach((b) => b.classList.toggle("activa", b === boton));
      document
        .querySelectorAll("#vista-arbol .subvista")
        .forEach((v) => v.classList.toggle("activa", v.id === "subvista-" + subvistaArbol));
      if (subvistaArbol === "grafico") pintarArbolGrafico(arbolActivo());
    });

    conectarGrafico();

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
