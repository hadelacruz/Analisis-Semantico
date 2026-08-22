// Funciones: hoisting, recursion, anidamiento y closures.

// Se puede llamar antes de la declaracion textual (hoisting).
print(factorial(5));
print(fibonacci(10));

function factorial(n: integer): integer {
  if (n <= 1) {
    return 1;
  }
  return n * factorial(n - 1);
}

function fibonacci(n: integer): integer {
  if (n < 2) {
    return n;
  }
  return fibonacci(n - 1) + fibonacci(n - 2);
}

// Recursion mutua
function esPar(n: integer): boolean {
  if (n == 0) { return true; }
  return esImpar(n - 1);
}

function esImpar(n: integer): boolean {
  if (n == 0) { return false; }
  return esPar(n - 1);
}

// Closure: la funcion anidada captura el parametro y la variable local
function crearAcumulador(inicial: integer): integer {
  let acumulado: integer = inicial;

  function agregar(cantidad: integer): integer {
    return acumulado + cantidad + inicial;
  }

  return agregar(10) + agregar(20);
}

// Captura a traves de tres niveles de anidamiento
function nivel1(a: integer): integer {
  function nivel2(b: integer): integer {
    function nivel3(c: integer): integer {
      return a + b + c;
    }
    return nivel3(3);
  }
  return nivel2(2);
}

// Procedimiento sin tipo de retorno
function saludar(quien: string) {
  print("Hola, " + quien);
}

// Funciones que reciben y devuelven arreglos
function duplicar(valores: integer[]): integer[] {
  let salida: integer[] = [valores[0] * 2, valores[1] * 2];
  return salida;
}

// Todos los caminos devuelven valor
function clasificar(n: integer): string {
  if (n < 0) {
    return "negativo";
  } else {
    if (n == 0) {
      return "cero";
    } else {
      return "positivo";
    }
  }
}

saludar("Compiscript");
print(esPar(4));
print(esImpar(7));
print(crearAcumulador(1));
print(nivel1(1));
print(duplicar([3, 4])[1]);
print(clasificar(-2));
