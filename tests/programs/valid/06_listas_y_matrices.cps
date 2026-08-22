// Listas: literales homogeneos, indexacion, matrices y arreglos de objetos.

let enteros: integer[] = [1, 2, 3, 4, 5];
let textos: string[] = ["alfa", "beta", "gamma"];
let reales: float[] = [1, 2.5, 3];          // unifica a float
let vacio: integer[] = [];                  // el tipo viene de la anotacion
let matriz: integer[][] = [[1, 2, 3], [4, 5, 6]];
let cubo: integer[][][] = [[[1], [2]], [[3], [4]]];

// Lectura y escritura de elementos
let primero: integer = enteros[0];
enteros[1] = 20;
matriz[0][2] = 30;

// Indices calculados
let indice: integer = 2;
print(enteros[indice] + enteros[indice - 1] + enteros[1 + 1]);

// Recorridos
foreach (valor in enteros) {
  print(valor);
}

foreach (fila in matriz) {
  foreach (celda in fila) {
    print(celda);
  }
}

for (let i: integer = 0; i < 3; i = i + 1) {
  print(textos[i]);
}

// Arreglos como parametros y como valores de retorno
function sumarTodos(valores: integer[]): integer {
  let total: integer = 0;
  foreach (v in valores) {
    total = total + v;
  }
  return total;
}

function construir(base: integer): integer[] {
  let salida: integer[] = [base, base * 2, base * 3];
  return salida;
}

function primeraFila(m: integer[][]): integer[] {
  return m[0];
}

// Arreglo de objetos
class Punto {
  let x: integer;
  let y: integer;
  function constructor(x: integer, y: integer) { this.x = x; this.y = y; }
  function suma(): integer { return this.x + this.y; }
}

let puntos: Punto[] = [new Punto(1, 2), new Punto(3, 4)];
print(puntos[0].suma() + puntos[1].x);

print(primero);
print(sumarTodos(enteros));
print(construir(3)[2]);
print(primeraFila(matriz)[0]);
print(reales[1]);
print(cubo[0][1][0]);
print(vacio);
