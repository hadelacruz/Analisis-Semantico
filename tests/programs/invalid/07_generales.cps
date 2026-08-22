// Casos fallidos generales y advertencias (E7xx, W9xx).

5 + 3;                                     // @error E701

let variable: integer = 1;
variable;                                  // @error E701

function procedimiento() {
  print("sin retorno");
}
print(procedimiento());                    // @error E702

// El enunciado lo menciona explicitamente: no se pueden "multiplicar funciones"
function unaFuncion(): integer { return 1; }
function otraFuncion(): integer { return 2; }
let multiplicacionInvalida = unaFuncion * otraFuncion;  // @error E309

function conCodigoMuerto(): integer {
  return 1;
  print("nunca se ejecuta");               // @warning W902
}

let sinInicializar: integer;
print(sinInicializar);                     // @warning W901

let divisionPorCero = 10 / 0;              // @warning W904

function conVariableSinUsar(): integer {
  let jamasUsada: integer = 1;             // @warning W905
  return 2;
}
