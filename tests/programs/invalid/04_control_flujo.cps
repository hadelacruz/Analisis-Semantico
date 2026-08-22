// Casos fallidos del control de flujo (E4xx).

if (1) {                                   // @error E401
  print("condicion no booleana");
}

while ("texto") {                          // @error E401
  break;
}

let n: integer = 3;
do {
  n = n - 1;
} while (n);                               // @error E401

for (let i: integer = 0; i + 1; i = i + 1) {  // @error E401
  break;
}

break;                                     // @error E402
continue;                                  // @error E403 @warning W902
return 1;                                  // @error E404 @warning W902

function conBreakSuelto() {               // @warning W902
  break;                                   // @error E402
}

switch (1) {
  case "texto":                            // @error E405
    print(1);
  default:
    print(2);
}

foreach (elemento in 42) {                 // @error E406
  print(elemento);
}

let noArreglo: string = "cadena";
foreach (letra in noArreglo) {             // @error E406
  print(letra);
}
