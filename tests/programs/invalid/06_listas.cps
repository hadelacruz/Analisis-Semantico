// Casos fallidos de listas y estructuras de datos (E6xx, W903).

let numeros: integer[] = [1, 2, 3];

print(numeros["cero"]);                    // @error E601
print(numeros[true]);                      // @error E601
print(numeros[1.5]);                       // @error E601

let escalar: integer = 5;
print(escalar[0]);                         // @error E602

let texto: string = "cadena";
print(texto[0]);                           // @error E602

let heterogeneo = [1, "dos"];              // @error E111

let tipoDeElementoMal: string = numeros[0];  // @error E105

numeros[0] = "texto";                      // @error E105

let matriz: integer[][] = [[1, 2]];
let filaMal: integer = matriz[0];          // @error E105

print(numeros[99]);                        // @warning W903
print(numeros[-1]);                        // @warning W903

let sinAnotacion = [];                     // @error E112
