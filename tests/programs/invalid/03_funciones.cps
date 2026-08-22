// Casos fallidos de funciones y procedimientos (E3xx).

function dosParametros(a: integer, b: integer): integer {
  return a + b;
}

print(dosParametros(1));                   // @error E301
print(dosParametros(1, 2, 3));             // @error E301

function esperaTexto(s: string): integer {
  return 1;
}
print(esperaTexto(42));                    // @error E302

let noEsFuncion: integer = 1;
print(noEsFuncion());                      // @error E303

function retornoIncorrecto(): integer {
  return "no soy entero";                  // @error E304
}

function procedimiento() {
  return 5;                                // @error E305
}

function faltaValor(): integer {
  return;                                  // @error E305
}

function duplicada(): integer { return 1; }
function duplicada(): integer { return 2; } // @error E306

function parametroRepetido(x: integer, x: integer): integer {  // @error E307
  return x;
}

function noRetornaSiempre(n: integer): integer {  // @error E308
  if (n > 0) {
    return 1;
  }
}

function usadaComoValor(): integer { return 1; }
let referencia = usadaComoValor;           // @error E309

function sinTipoDeParametro(p): integer {  // @error E310
  return 1;
}
