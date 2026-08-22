// Casos fallidos de clases y objetos (E5xx).

class Animal {
  let nombre: string;

  function constructor(nombre: string) {
    this.nombre = nombre;
  }

  function hablar(): string {
    return this.nombre + " hace ruido";
  }
}

let inexistente = new NoExisteEstaClase(); // @error E501

class HeredaDeFantasma : Fantasma { }      // @error E501

let animal: Animal = new Animal("Rex");
print(animal.noEsAtributo);                // @error E502
print(animal.volar());                     // @error E502
animal.hablar = 5;                         // @error E502

print(this);                               // @error E503

let sinArgumentos: Animal = new Animal();  // @error E504
let demasiados: Animal = new Animal("a", "b");  // @error E504

class Ciclica : OtraCiclica { }            // @error E505
class OtraCiclica : Ciclica { }

class MiembroRepetido {
  let campo: integer;
  let campo: integer;                      // @error E506
}

let numero: integer = 1;
print(numero.propiedad);                   // @error E507

class Base {
  function metodo(a: integer): integer { return a; }
}

class Derivada : Base {
  function metodo(a: string): integer {    // @error E508
    return 1;
  }
}

class TipoIncompatible {
  let campo: integer;
  function asignarMal() {
    this.campo = "texto";                  // @error E105
  }
}
