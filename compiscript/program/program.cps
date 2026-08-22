// Global constants and variables
const PI: integer = 314;
let greeting: string = "Hello, Compiscript!";
let flag: boolean;
let numbers: integer[] = [1, 2, 3, 4, 5];
let matrix: integer[][] = [[1, 2], [3, 4]];

// Simple closure-style function (no nested type signatures)
function makeAdder(x: integer): integer {
  return x + 1;
}

let addFive: integer = (makeAdder(5));
print("5 + 1 = " + addFive);

// Control structures
if (addFive > 5) {
  print("Greater than 5");
} else {
  print("5 or less");
}

while (addFive < 10) {
  addFive = addFive + 1;
}

do {
  print("Result is now " + addFive);
  addFive = addFive - 1;
} while (addFive > 7);

for (let i: integer = 0; i < 3; i = i + 1) {
  print("Loop index: " + i);
}

foreach (n in numbers) {
  if (n == 3) {
    continue;
  }
  print("Number: " + n);
  if (n > 4) {
    break;
  }
}

// Switch-case structure
switch (addFive) {
  case 7:
    print("It's seven");
  case 6:
    print("It's six");
  default:
    print("Something else");
}

// Try-catch structure
try {
  let risky: integer = numbers[10];
  print("Risky access: " + risky);
} catch (err) {
  print("Caught an error: " + err);
}

// Class definition and usage
class Animal {
  let name: string;

  function constructor(name: string) {
    this.name = name;
  }

  function speak(): string {
    return this.name + " makes a sound.";
  }
}

class Dog : Animal {
  function speak(): string {
    return this.name + " barks.";
  }
}

let dog: Dog = new Dog("Rex");
print(dog.speak());

// Object property access and array indexing
let first: integer = numbers[0];
print("First number: " + first);

// Function returning an array
function getMultiples(n: integer): integer[] {
  let result: integer[] = [n * 1, n * 2, n * 3, n * 4, n * 5];
  return result;
}

let multiples: integer[] = getMultiples(2);
print("Multiples of 2: " + multiples[0] + ", " + multiples[1]);

// Recursion
function factorial(n: integer): integer {
  if (n <= 1) {
    return 1;
  }
  return n * factorial(n - 1);
}

// Program end
print("Program finished.");
