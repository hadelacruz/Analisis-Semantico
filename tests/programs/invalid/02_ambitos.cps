// Casos fallidos del manejo de ambito (E2xx).

print(noDeclarada);                        // @error E201
sinDeclarar = 5;                           // @error E201

let repetida: integer = 1;
let repetida: integer = 2;                 // @error E202

let choque: integer = 1;
const choque: string = "x";                // @error E202

{
  let soloEnElBloque: integer = 1;
  print(soloEnElBloque);
}
print(soloEnElBloque);                     // @error E201

function conParametro(p: integer): integer {
  let p: integer = 2;                      // @error E202
  return p;
}

for (let i: integer = 0; i < 3; i = i + 1) {
  print(i);
}
print(i);                                  // @error E201

class Clase { }
let Clase: integer = 1;                    // @error E202
let usoDeClase = Clase;                    // @error E203
