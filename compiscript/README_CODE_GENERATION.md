# 🧪 Fase de Compilación: Generación de Código

## 📋 Descripción General

Hemos llegado al final del camino! Ahora, nos toca trabajar en la fase final del diseño de nuestro compilador, la cual es la generación de código de máquina, o lenguaje ensamblador. Ya que han realizado un robusto análisis semántico (análisis de tipos), acompañado de la generación de un código intermedio (TAC), llega el momento de utilizar esta representación intermedia y traducirla a un código de bajo nivel. En este caso, estaremos utilizando MIPS, el cual es un lenguaje assembly utilizado convencionalmente de forma educativa para aterrizar en conceptos de compilación.

* Lea atentamente el README.md en este directorio, en dónde encotrará las generalidades del lenguaje.
* En el directorio ``program`` encontrará la gramática de este lenguaje en ANTLR y en BNF. Se le otorga un playground similar a los laboratorios para que usted pueda experimentar inicialmente.
* **Modalidad: Grupos de 3 integrantes.**

## 📋 Requerimientos

* Implementar un algoritmo de generación de secuencias de llamadas y secuencia de retornos de procedimientos, i.e., traducir el Código de Tres Direcciones a código de MIPS que sea capaz de hacer saltos hacia y desde procedimientos (funciones) sin perder el estado general de la memoria, i.e., manejo del stack pointer.
* Implementar un algoritmo de asignación de registros o uso de pila, i.e., implementar la famosa función `getReg()` para asignar registros libres en los que puedan traducir su código intermedio a MIPS y realizar la asignación apropiada y adecuada para los tipos de registros que existen de MIPS, tales como los `$t`, `$s`, etc., así como la opción de utilizar el stack para guardar todas sus operaciones, i.e., manejo de la memoria y registros como tal.
* Generar código assembler en MIPS para su posterior ejecución por medio de una tercera herramienta, i.e., utilizar un simulador de MIPS para correr el código y validar que este se ejecute correctamente.
* **Para los puntos anteriores, deberá de escribir una batería de tests para validar casos exitosos y casos fallidos en cada una de los casos que crea convenientes.**
* Al momento de presentar su trabajo, esta batería de tests debe estar presente y será tomada en cuenta para validar el funcionamiento de su compilador.
* **Deberá desarrollar un IDE que permita a los usuarios escribir su propio código y compilarlo.**
* **Deberá crear **documentación asociada a la arquitectura de su implementación** y **documentación de las generalidades de cómo ejecutar su compilador**.**
* **Entregar su repositorio de GitHub.**
  * **Se validan los commits y contribuciones de cada integrante, no se permite "compartir" commits en conjunto, debe notarse claramente qué porción de código implementó cada integrante.**

## 📋 Ponderación

| Componente                                                               | Puntos               |
| ------------------------------------------------------------------------ | -------------------- |
| Algoritmo de generación de secuencias de llamadas y retornos            | 20 puntos            |
| Algoritmo de asignación de registros                                    | 20 puntos            |
| Generación de Código MIPS funcional y simulado en un simulador de MIPS | 60 puntos            |
| **Total**                                                          | **100 puntos** |
