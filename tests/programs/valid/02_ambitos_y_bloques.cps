// Manejo de ambito: anidamiento, sombreado y visibilidad.

let global: integer = 1;
let compartida: string = "exterior";

{
  // Un bloque ve el ambito exterior...
  let interna: integer = global + 1;

  // ...y puede sombrear un nombre sin afectar al de afuera.
  let compartida: integer = 99;
  print(compartida + interna);

  {
    let masProfunda: integer = compartida + global;
    print(masProfunda);
  }
}

// Aqui 'compartida' vuelve a ser el string exterior.
print(compartida);

function conAmbitoPropio(parametro: integer): integer {
  let local: integer = parametro * 2;
  {
    let deBloque: integer = local + global;
    local = deBloque;
  }
  return local;
}

// Cada estructura de control abre su propio entorno.
for (let i: integer = 0; i < 3; i = i + 1) {
  let dentroDelFor: integer = i * 2;
  print(dentroDelFor);
}

let lista: integer[] = [1, 2, 3];
foreach (elemento in lista) {
  let dentroDelForeach: integer = elemento + 1;
  print(dentroDelForeach);
}

while (global < 3) {
  let dentroDelWhile: integer = global;
  global = global + dentroDelWhile;
}

try {
  print(lista[0]);
} catch (mensaje) {
  print("fallo: " + mensaje);
}

print(conAmbitoPropio(5));
