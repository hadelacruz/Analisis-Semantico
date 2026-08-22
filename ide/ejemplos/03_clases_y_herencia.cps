// Clases: atributos, constructor, metodos, 'this' y herencia en cadena.

class Figura {
  let nombre: string;
  let lados: integer;

  function constructor(nombre: string, lados: integer) {
    this.nombre = nombre;
    this.lados = lados;
  }

  function describir(): string {
    return this.nombre + " tiene " + this.lados + " lados";
  }

  function esPoligono(): boolean {
    return this.lados > 2;
  }
}

class Rectangulo : Figura {
  let ancho: integer;
  let alto: integer;

  function constructor(ancho: integer, alto: integer) {
    this.nombre = "rectangulo";
    this.lados = 4;
    this.ancho = ancho;
    this.alto = alto;
  }

  function area(): integer {
    return this.ancho * this.alto;
  }

  // Sobrescritura con la misma firma que la superclase
  function describir(): string {
    return "rectangulo de " + this.ancho + "x" + this.alto;
  }
}

class Cuadrado : Rectangulo {
  function constructor(lado: integer) {
    this.nombre = "cuadrado";
    this.lados = 4;
    this.ancho = lado;
    this.alto = lado;
  }

  function esRegular(): boolean {
    return this.ancho == this.alto;
  }
}

// Instanciacion y despacho
let figura: Figura = new Figura("triangulo", 3);
let rectangulo: Rectangulo = new Rectangulo(3, 4);
let cuadrado: Cuadrado = new Cuadrado(5);

// Una subclase es asignable donde se espera la superclase
let comoFigura: Figura = cuadrado;

print(figura.describir());
print(rectangulo.describir() + " area=" + rectangulo.area());
print(cuadrado.describir() + " regular=" + cuadrado.esRegular());
print(comoFigura.describir());

// Atributos heredados accesibles desde la subclase
print(cuadrado.nombre + " " + cuadrado.lados + " " + cuadrado.ancho);
print(cuadrado.esPoligono());

// Asignacion a atributos
rectangulo.ancho = 10;
print(rectangulo.area());

// Arreglo de objetos
let figuras: Figura[] = [figura, rectangulo, cuadrado];
foreach (f in figuras) {
  print(f.describir());
}

// Clase usada antes de declararse
let tardia: Tardia = new Tardia(7);
print(tardia.valor);

class Tardia {
  let valor: integer;
  function constructor(valor: integer) { this.valor = valor; }
}
