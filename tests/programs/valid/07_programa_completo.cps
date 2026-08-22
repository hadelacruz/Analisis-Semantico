// Programa integrador: gestion de inventario.
// Ejercita a la vez tipos, ambitos, funciones, closures, clases, herencia,
// control de flujo y listas.

const IVA: float = 0.12;
const LIMITE_STOCK: integer = 5;

class Producto {
  let nombre: string;
  let precio: float;
  let cantidad: integer;

  function constructor(nombre: string, precio: float, cantidad: integer) {
    this.nombre = nombre;
    this.precio = precio;
    this.cantidad = cantidad;
  }

  function total(): float {
    return this.precio * this.cantidad;
  }

  function conImpuesto(): float {
    return this.total() * (1 + IVA);
  }

  function describir(): string {
    return this.nombre + " x" + this.cantidad + " = " + this.total();
  }

  function necesitaReposicion(): boolean {
    return this.cantidad < LIMITE_STOCK;
  }
}

class Perecedero : Producto {
  let diasParaVencer: integer;

  function constructor(nombre: string, precio: float, cantidad: integer, dias: integer) {
    this.nombre = nombre;
    this.precio = precio;
    this.cantidad = cantidad;
    this.diasParaVencer = dias;
  }

  function estaPorVencer(): boolean {
    return this.diasParaVencer < 3;
  }

  function describir(): string {
    return this.nombre + " (vence en " + this.diasParaVencer + " dias)";
  }
}

// Closure: la funcion anidada captura el descuento del entorno
function aplicarDescuento(porcentaje: float): float {
  let factor: float = 1 - porcentaje;

  function calcular(monto: float): float {
    return monto * factor;
  }

  return calcular(100.0) + calcular(200.0);
}

function contarCriticos(items: Producto[]): integer {
  let criticos: integer = 0;
  foreach (item in items) {
    if (item.necesitaReposicion()) {
      criticos = criticos + 1;
    }
  }
  return criticos;
}

function categoria(cantidad: integer): string {
  if (cantidad == 0) {
    return "agotado";
  } else {
    if (cantidad < LIMITE_STOCK) {
      return "bajo";
    } else {
      return "normal";
    }
  }
}

function acumuladoRecursivo(items: Producto[], indice: integer, tope: integer): float {
  if (indice >= tope) {
    return 0.0;
  }
  return items[indice].conImpuesto() + acumuladoRecursivo(items, indice + 1, tope);
}

// --- programa principal ---------------------------------------------------

let leche: Perecedero = new Perecedero("leche", 12.5, 3, 2);
let arroz: Producto = new Producto("arroz", 8.0, 20);
let pan: Perecedero = new Perecedero("pan", 3.25, 4, 1);

let inventario: Producto[] = [leche, arroz, pan];

foreach (producto in inventario) {
  print(producto.describir());
  print("categoria: " + categoria(producto.cantidad));
}

let totalGeneral: float = acumuladoRecursivo(inventario, 0, 3);
print("total con impuesto: " + totalGeneral);
print("productos criticos: " + contarCriticos(inventario));
print("descuento aplicado: " + aplicarDescuento(0.15));

if (leche.estaPorVencer() && pan.estaPorVencer()) {
  print("hay productos por vencer");
}

let reporte: string = "";
for (let i: integer = 0; i < 3; i = i + 1) {
  let actual: Producto = inventario[i];
  if (actual.cantidad == 0) {
    continue;
  }
  reporte = reporte + actual.nombre + ";";
}
print(reporte);

switch (contarCriticos(inventario)) {
  case 0:
    print("inventario saludable");
  case 1:
    print("revisar un producto");
    break;
  default:
    print("reposicion urgente");
}

try {
  print(inventario[0].nombre);
} catch (error) {
  print("error de inventario: " + error);
}
