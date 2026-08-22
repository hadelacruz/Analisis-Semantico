/* ==========================================================================
   Definicion del lenguaje Compiscript para el editor Monaco.

   - Tokenizador Monarch: colorea palabras clave, tipos, literales y comentarios
     siguiendo exactamente las reglas lexicas de grammar/Compiscript.g4.
   - Configuracion del lenguaje: comentarios, pares de simbolos, indentacion.
   - Dos temas (oscuro y claro) a juego con la hoja de estilos del IDE.
   - Autocompletado basico con las construcciones del lenguaje.
   ========================================================================== */

const COMPISCRIPT_ID = "compiscript";

const PALABRAS_CLAVE = [
  "let", "var", "const", "function", "class", "new", "this", "return",
  "if", "else", "while", "do", "for", "foreach", "in",
  "switch", "case", "default", "break", "continue",
  "try", "catch", "print", "null", "true", "false"
];

const TIPOS = ["boolean", "integer", "float", "string"];

function definirLenguajeCompiscript(monaco) {
  monaco.languages.register({ id: COMPISCRIPT_ID, extensions: [".cps"], aliases: ["Compiscript", "cps"] });

  monaco.languages.setLanguageConfiguration(COMPISCRIPT_ID, {
    comments: { lineComment: "//", blockComment: ["/*", "*/"] },
    brackets: [["{", "}"], ["[", "]"], ["(", ")"]],
    autoClosingPairs: [
      { open: "{", close: "}" },
      { open: "[", close: "]" },
      { open: "(", close: ")" },
      { open: '"', close: '"', notIn: ["string"] }
    ],
    surroundingPairs: [
      { open: "{", close: "}" }, { open: "[", close: "]" },
      { open: "(", close: ")" }, { open: '"', close: '"' }
    ],
    indentationRules: {
      increaseIndentPattern: /^.*\{[^}"']*$/,
      decreaseIndentPattern: /^\s*\}/
    }
  });

  monaco.languages.setMonarchTokensProvider(COMPISCRIPT_ID, {
    defaultToken: "",
    palabrasClave: PALABRAS_CLAVE,
    tipos: TIPOS,
    operadores: [
      "=", "==", "!=", "<", "<=", ">", ">=",
      "+", "-", "*", "/", "%", "&&", "||", "!", "?", ":"
    ],
    simbolos: /[=><!~?:&|+\-*\/^%]+/,

    tokenizer: {
      root: [
        // Declaracion de clase o de tipo: resalta el identificador que sigue
        [/\b(class)(\s+)([A-Za-z_]\w*)/, ["keyword", "", "type.identifier"]],
        [/\b(new)(\s+)([A-Za-z_]\w*)/, ["keyword", "", "type.identifier"]],
        [/\b(function)(\s+)([A-Za-z_]\w*)/, ["keyword", "", "entity.name.function"]],

        // Llamada a funcion
        [/[A-Za-z_]\w*(?=\s*\()/, "entity.name.function"],

        // Identificadores, palabras clave y tipos
        [/[A-Za-z_]\w*/, {
          cases: {
            "@tipos": "type",
            "@palabrasClave": "keyword",
            "@default": "identifier"
          }
        }],

        { include: "@espacios" },

        // Delimitadores y operadores
        [/[{}()\[\]]/, "@brackets"],
        [/@simbolos/, { cases: { "@operadores": "operator", "@default": "" } }],

        // Numeros: el float debe ir antes que el entero
        [/\d+\.\d+/, "number.float"],
        [/\d+/, "number"],

        [/[;,.]/, "delimiter"],

        // Cadenas (la gramatica no admite saltos de linea dentro)
        [/"([^"\\]|\\.)*$/, "string.invalid"],
        [/"/, { token: "string.quote", bracket: "@open", next: "@cadena" }]
      ],

      espacios: [
        [/[ \t\r\n]+/, ""],
        [/\/\*/, "comment", "@comentario"],
        [/\/\/.*$/, "comment"]
      ],

      comentario: [
        [/[^\/*]+/, "comment"],
        [/\*\//, "comment", "@pop"],
        [/[\/*]/, "comment"]
      ],

      cadena: [
        [/[^\\"]+/, "string"],
        [/"/, { token: "string.quote", bracket: "@close", next: "@pop" }]
      ]
    }
  });

  // --- temas --------------------------------------------------------------
  monaco.editor.defineTheme("compiscript-oscuro", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "keyword", foreground: "cba6f7", fontStyle: "bold" },
      { token: "type", foreground: "89b4fa" },
      { token: "type.identifier", foreground: "f9e2af" },
      { token: "entity.name.function", foreground: "89dceb" },
      { token: "identifier", foreground: "cdd6f4" },
      { token: "number", foreground: "fab387" },
      { token: "number.float", foreground: "fab387" },
      { token: "string", foreground: "a6e3a1" },
      { token: "string.quote", foreground: "a6e3a1" },
      { token: "string.invalid", foreground: "f38ba8", fontStyle: "underline" },
      { token: "comment", foreground: "6c7086", fontStyle: "italic" },
      { token: "operator", foreground: "94e2d5" },
      { token: "delimiter", foreground: "9399b2" }
    ],
    colors: {
      "editor.background": "#1e1e2e",
      "editor.foreground": "#cdd6f4",
      "editorLineNumber.foreground": "#45475a",
      "editorLineNumber.activeForeground": "#89b4fa",
      "editor.lineHighlightBackground": "#28283d",
      "editor.selectionBackground": "#414160",
      "editorCursor.foreground": "#89b4fa",
      "editorIndentGuide.background1": "#313244",
      "editorGutter.background": "#1e1e2e"
    }
  });

  monaco.editor.defineTheme("compiscript-claro", {
    base: "vs",
    inherit: true,
    rules: [
      { token: "keyword", foreground: "8839ef", fontStyle: "bold" },
      { token: "type", foreground: "1e66f5" },
      { token: "type.identifier", foreground: "df8e1d" },
      { token: "entity.name.function", foreground: "179299" },
      { token: "number", foreground: "fe640b" },
      { token: "number.float", foreground: "fe640b" },
      { token: "string", foreground: "40a02b" },
      { token: "string.quote", foreground: "40a02b" },
      { token: "comment", foreground: "9ca0b0", fontStyle: "italic" },
      { token: "operator", foreground: "179299" }
    ],
    colors: {
      "editor.background": "#ffffff",
      "editor.foreground": "#4c4f69",
      "editor.lineHighlightBackground": "#f2f2f7"
    }
  });

  // --- autocompletado ------------------------------------------------------
  monaco.languages.registerCompletionItemProvider(COMPISCRIPT_ID, {
    provideCompletionItems: (modelo, posicion) => {
      const palabra = modelo.getWordUntilPosition(posicion);
      const rango = {
        startLineNumber: posicion.lineNumber,
        endLineNumber: posicion.lineNumber,
        startColumn: palabra.startColumn,
        endColumn: palabra.endColumn
      };
      const K = monaco.languages.CompletionItemKind;
      const R = monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet;

      const sugerencias = [
        ...PALABRAS_CLAVE.map((p) => ({ label: p, kind: K.Keyword, insertText: p, range: rango })),
        ...TIPOS.map((t) => ({ label: t, kind: K.TypeParameter, insertText: t, range: rango })),
        {
          label: "function", kind: K.Snippet, range: rango, insertTextRules: R,
          detail: "Declaracion de funcion",
          insertText: "function ${1:nombre}(${2:param}: ${3:integer}): ${4:integer} {\n\t$0\n}"
        },
        {
          label: "class", kind: K.Snippet, range: rango, insertTextRules: R,
          detail: "Declaracion de clase con constructor",
          insertText:
            "class ${1:Nombre} {\n\tlet ${2:campo}: ${3:integer};\n\n" +
            "\tfunction constructor(${2:campo}: ${3:integer}) {\n\t\tthis.${2:campo} = ${2:campo};\n\t}\n}"
        },
        {
          label: "if", kind: K.Snippet, range: rango, insertTextRules: R,
          detail: "Condicional con else",
          insertText: "if (${1:condicion}) {\n\t$2\n} else {\n\t$0\n}"
        },
        {
          label: "for", kind: K.Snippet, range: rango, insertTextRules: R,
          detail: "Bucle for clasico",
          insertText: "for (let ${1:i}: integer = 0; ${1:i} < ${2:10}; ${1:i} = ${1:i} + 1) {\n\t$0\n}"
        },
        {
          label: "foreach", kind: K.Snippet, range: rango, insertTextRules: R,
          detail: "Recorrido de un arreglo",
          insertText: "foreach (${1:elemento} in ${2:arreglo}) {\n\t$0\n}"
        },
        {
          label: "while", kind: K.Snippet, range: rango, insertTextRules: R,
          insertText: "while (${1:condicion}) {\n\t$0\n}"
        },
        {
          label: "switch", kind: K.Snippet, range: rango, insertTextRules: R,
          insertText: "switch (${1:valor}) {\n\tcase ${2:1}:\n\t\t$3\n\t\tbreak;\n\tdefault:\n\t\t$0\n}"
        },
        {
          label: "trycatch", kind: K.Snippet, range: rango, insertTextRules: R,
          detail: "Bloque try/catch",
          insertText: "try {\n\t$1\n} catch (${2:error}) {\n\tprint(${2:error});\n}"
        },
        {
          label: "print", kind: K.Snippet, range: rango, insertTextRules: R,
          insertText: "print($0);"
        }
      ];
      return { suggestions: sugerencias };
    }
  });
}
