// Casos fallidos del sistema de tipos (E1xx).
// Cada linea marcada con @error debe producir ese diagnostico.

let malAritmetica = 1 + true;              // @error E101
let malResta = "texto" - 1;                // @error E101
let malLogica = 1 && true;                 // @error E102
let malOr = "x" || false;                  // @error E102
let malIgualdad = 1 == "uno";              // @error E103
let malRelacional = true < false;          // @error E104
let malAsignacion: integer = "hola";       // @error E105
let malEstrechamiento: integer = 1.5;      // @error E105

const CONSTANTE: integer = 1;
CONSTANTE = 2;                             // @error E107

let malNegacion = -"texto";                // @error E108
let malNot = !42;                          // @error E109
let malTipo: TipoInexistente = null;       // @error E110
let malLista = [1, "dos", true];           // @error E111
let sinTipoNiValor;                        // @error E112
let ternarioMalaCondicion = 5 ? 1 : 2;     // @error E113
let ternarioMalasRamas = true ? 1 : "x";   // @error E114
let malModulo = 7 % 2.5;                   // @error E115
