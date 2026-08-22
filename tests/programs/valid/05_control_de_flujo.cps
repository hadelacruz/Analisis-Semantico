// Control de flujo completo: condiciones booleanas y saltos bien ubicados.

let n: integer = 7;
let acumulado: integer = 0;
let numeros: integer[] = [4, 8, 15, 16, 23, 42];

if (n > 10) {
  print("mayor a 10");
} else {
  print("10 o menos");
}

// if anidados
if (n > 0) {
  if (n % 2 == 0) {
    print("positivo par");
  } else {
    print("positivo impar");
  }
}

while (acumulado < 20) {
  acumulado = acumulado + n;
}

do {
  acumulado = acumulado - 1;
} while (acumulado > 15);

for (let i: integer = 0; i < 10; i = i + 1) {
  if (i % 2 == 0) {
    continue;
  }
  if (i > 7) {
    break;
  }
  acumulado = acumulado + i;
}

// for sin inicializador ni actualizacion
let contador: integer = 0;
for (; contador < 3;) {
  contador = contador + 1;
}

foreach (valor in numeros) {
  if (valor < 10) {
    continue;
  }
  if (valor > 40) {
    break;
  }
  print("valor: " + valor);
}

// Bucles anidados con break y continue en cada nivel
for (let i: integer = 0; i < 3; i = i + 1) {
  for (let j: integer = 0; j < 3; j = j + 1) {
    if (j == 1) { continue; }
    if (j == 2) { break; }
    print(i * 10 + j);
  }
}

switch (n) {
  case 1:
    print("uno");
  case 7:
    print("siete");
    break;
  default:
    print("otro");
}

// switch dentro de un bucle: 'break' aplica al switch
while (contador < 5) {
  switch (contador) {
    case 3:
      print("tres");
      break;
    default:
      print("avanza");
  }
  contador = contador + 1;
}

try {
  let riesgo: integer = numeros[0];
  print("acceso: " + riesgo);
} catch (error) {
  print("se atrapo: " + error);
}

print(acumulado);
