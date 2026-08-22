// Sistema de tipos: primitivos, operadores y conversiones permitidas.

const PI: float = 3.1416;
const MAX: integer = 100;

let entero: integer = 42;
let real: float = 2.5;
let texto: string = "Compiscript";
let bandera: boolean = true;
let nulo: string = null;

// Aritmetica homogenea y con ensanchamiento integer -> float
let suma: integer = entero + MAX;
let resta: integer = MAX - entero;
let producto: float = real * PI;
let division: float = entero / real;
let modulo: integer = entero % 5;
let negativo: integer = -entero;

// Precedencia y agrupamiento
let precedencia: integer = 2 + 3 * 4;        // 14
let agrupado: integer = (2 + 3) * 4;         // 20

// Concatenacion: string + cualquier valor imprimible
let reporte: string = texto + " v" + 1 + "." + 0 + " pi=" + PI + " ok=" + bandera;

// Operadores logicos y relacionales
let comparacion: boolean = entero < MAX && real >= 2.0;
let igualdad: boolean = texto == "Compiscript";
let distinto: boolean = entero != 0;
let negacion: boolean = !bandera;
let ordenTextos: boolean = "abc" < "abd";

// Operador ternario con unificacion de ramas
let etiqueta: string = entero > 50 ? "grande" : "chico";
let numerico: float = bandera ? 1 : 2.5;     // integer y float unifican en float

print(suma + resta + producto + division + modulo + negativo);
print(precedencia + agrupado);
print(reporte);
print(comparacion && igualdad && distinto && negacion && ordenTextos);
print(etiqueta + numerico + nulo);
