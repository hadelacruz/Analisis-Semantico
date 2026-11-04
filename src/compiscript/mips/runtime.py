"""Biblioteca de apoyo del compilador, escrita en ensamblador MIPS.

El código de tres direcciones invoca nueve rutinas que no se pueden expresar
con instrucciones de tres direcciones: reservar memoria, concatenar cadenas,
convertir números a texto, comprobar índices y lanzar excepciones. Aquí están
implementadas **una sola vez**, y el generador las anexa al final de cada
programa.

Convenciones
------------
* Argumentos enteros en ``$a0``/``$a1``; dobles en ``$f12``.
* Resultado entero (o puntero) en ``$v0``; doble en ``$f0``.
* **Ninguna rutina toca ``$fp``**: el marco del llamador queda intacto. El
  generador ya volcó sus registros antes del ``jal``, así que ``$t*`` y
  ``$s*`` se pueden usar libremente.

Todo lo que sigue usa sólo instrucciones y pseudoinstrucciones que aceptan
tanto **MARS 4.5** como **SPIM**.
"""
from __future__ import annotations

BIBLIOTECA = r"""
# ----------------------------------------------------------------------
# __alloc($a0 = bytes) -> $v0 = puntero
#   Reserva memoria del monticulo con sbrk, alineada a 8 bytes para que
#   los dobles queden bien alineados.
# ----------------------------------------------------------------------
__alloc:
    addiu $a0, $a0, 7
    srl   $a0, $a0, 3
    sll   $a0, $a0, 3
    li    $v0, 9
    syscall
    jr    $ra

# ----------------------------------------------------------------------
# __array_new($a0 = n, $a1 = bytes por elemento) -> $v0
#   Reserva la cabecera (la longitud) mas los elementos.
# ----------------------------------------------------------------------
__array_new:
    addiu $sp, $sp, -8
    sw    $ra, 0($sp)
    sw    $a0, 4($sp)
    mul   $a0, $a0, $a1
    addiu $a0, $a0, 4
    jal   __alloc
    lw    $t0, 4($sp)
    sw    $t0, 0($v0)
    lw    $ra, 0($sp)
    addiu $sp, $sp, 8
    jr    $ra

# ----------------------------------------------------------------------
# __length($a0 = arreglo) -> $v0
# ----------------------------------------------------------------------
__length:
    lw    $v0, 0($a0)
    jr    $ra

# ----------------------------------------------------------------------
# __check_bounds($a0 = arreglo, $a1 = indice)
#   Lanza una excepcion si el indice se sale del arreglo.
# ----------------------------------------------------------------------
__check_bounds:
    bltz  $a1, __cb_error
    lw    $t0, 0($a0)
    bge   $a1, $t0, __cb_error
    jr    $ra
# Construye el mismo mensaje que da la maquina virtual del TAC:
#   "indice 10 fuera del rango del arreglo (0..4)"
__cb_error:
    addiu $sp, $sp, -16
    sw    $ra, 0($sp)
    sw    $a0, 4($sp)
    sw    $a1, 8($sp)

    lw    $a0, 8($sp)
    jal   __itoa
    move  $a1, $v0
    la    $a0, __msg_idx1
    jal   __concat
    sw    $v0, 12($sp)

    lw    $a0, 12($sp)
    la    $a1, __msg_idx2
    jal   __concat
    sw    $v0, 12($sp)

    lw    $a0, 4($sp)
    lw    $a0, 0($a0)
    addiu $a0, $a0, -1
    jal   __itoa
    move  $a1, $v0
    lw    $a0, 12($sp)
    jal   __concat
    sw    $v0, 12($sp)

    lw    $a0, 12($sp)
    la    $a1, __msg_idx3
    jal   __concat

    move  $a0, $v0
    addiu $sp, $sp, 16
    j     __throw

# ----------------------------------------------------------------------
# __div_zero: destino de los saltos cuando un divisor vale cero.
# ----------------------------------------------------------------------
__div_zero:
    la    $a0, __msg_divzero
    j     __throw

# ----------------------------------------------------------------------
# Impresion. Cada variante imprime el valor y un salto de linea.
# ----------------------------------------------------------------------
__print_str:
    bne   $a0, $zero, __ps_imprime
    la    $a0, __msg_null
__ps_imprime:
    li    $v0, 4
    syscall
    la    $a0, __msg_nl
    li    $v0, 4
    syscall
    jr    $ra

__print_int:
    li    $v0, 1
    syscall
    la    $a0, __msg_nl
    li    $v0, 4
    syscall
    jr    $ra

__print_bool:
    beq   $a0, $zero, __pb_falso
    la    $a0, __msg_true
    j     __print_str
__pb_falso:
    la    $a0, __msg_false
    j     __print_str

__print_null:
    la    $a0, __msg_null
    j     __print_str

__print_float:
    addiu $sp, $sp, -8
    sw    $ra, 0($sp)
    jal   __ftoa
    move  $a0, $v0
    lw    $ra, 0($sp)
    addiu $sp, $sp, 8
    j     __print_str

# ----------------------------------------------------------------------
# __str_len($a0) -> $v0
# ----------------------------------------------------------------------
__str_len:
    beq   $a0, $zero, __sl_nula
    li    $v0, 0
__sl_bucle:
    add   $t0, $a0, $v0
    lb    $t1, 0($t0)
    beq   $t1, $zero, __sl_fin
    addiu $v0, $v0, 1
    j     __sl_bucle
__sl_fin:
    jr    $ra
__sl_nula:
    li    $v0, 0
    jr    $ra

# ----------------------------------------------------------------------
# __str_cmp($a0, $a1) -> $v0 en {-1, 0, 1}
#   De aqui salen las seis comparaciones de cadenas.
# ----------------------------------------------------------------------
__str_cmp:
    bne   $a0, $zero, __sc_b
    la    $a0, __msg_null
__sc_b:
    bne   $a1, $zero, __sc_inicio
    la    $a1, __msg_null
__sc_inicio:
    move  $t2, $a0
    move  $t3, $a1
__sc_bucle:
    lb    $t0, 0($t2)
    lb    $t1, 0($t3)
    bne   $t0, $t1, __sc_distinto
    beq   $t0, $zero, __sc_igual
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    j     __sc_bucle
__sc_distinto:
    blt   $t0, $t1, __sc_menor
    li    $v0, 1
    jr    $ra
__sc_menor:
    li    $v0, -1
    jr    $ra
__sc_igual:
    li    $v0, 0
    jr    $ra

# ----------------------------------------------------------------------
# __str_dup($a0) -> $v0
#   Las cadenas son inmutables, asi que basta con devolver el puntero.
# ----------------------------------------------------------------------
__str_dup:
    move  $v0, $a0
    jr    $ra

# ----------------------------------------------------------------------
# __str_copy($a0) -> $v0
#   Copia a memoria fresca. Lo usan las conversiones, que trabajan sobre
#   un buffer compartido que se reutiliza.
# ----------------------------------------------------------------------
__str_copy:
    addiu $sp, $sp, -8
    sw    $ra, 0($sp)
    sw    $a0, 4($sp)
    jal   __str_len
    addiu $a0, $v0, 1
    jal   __alloc
    move  $a1, $v0
    lw    $t2, 4($sp)
    move  $t3, $a1
__scp_bucle:
    lb    $t1, 0($t2)
    sb    $t1, 0($t3)
    beq   $t1, $zero, __scp_fin
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    j     __scp_bucle
__scp_fin:
    move  $v0, $a1
    lw    $ra, 0($sp)
    addiu $sp, $sp, 8
    jr    $ra

# ----------------------------------------------------------------------
# __concat($a0, $a1) -> $v0
# ----------------------------------------------------------------------
# Una variable de tipo 'string' puede valer null; se concatena "null".
__concat:
    bne   $a0, $zero, __cc_a1
    la    $a0, __msg_null
__cc_a1:
    bne   $a1, $zero, __cc_inicio
    la    $a1, __msg_null
__cc_inicio:
    addiu $sp, $sp, -16
    sw    $ra, 0($sp)
    sw    $a0, 4($sp)
    sw    $a1, 8($sp)
    jal   __str_len
    sw    $v0, 12($sp)
    lw    $a0, 8($sp)
    jal   __str_len
    lw    $t0, 12($sp)
    add   $a0, $t0, $v0
    addiu $a0, $a0, 1
    jal   __alloc
    move  $a1, $v0
    lw    $t2, 4($sp)
    move  $t3, $a1
__cc_primera:
    lb    $t1, 0($t2)
    beq   $t1, $zero, __cc_segunda
    sb    $t1, 0($t3)
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    j     __cc_primera
__cc_segunda:
    lw    $t2, 8($sp)
__cc_bucle2:
    lb    $t1, 0($t2)
    beq   $t1, $zero, __cc_fin
    sb    $t1, 0($t3)
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    j     __cc_bucle2
__cc_fin:
    sb    $zero, 0($t3)
    move  $v0, $a1
    lw    $ra, 0($sp)
    addiu $sp, $sp, 16
    jr    $ra

# ----------------------------------------------------------------------
# __btoa($a0) -> $v0
# ----------------------------------------------------------------------
__btoa:
    beq   $a0, $zero, __bt_falso
    la    $v0, __msg_true
    jr    $ra
__bt_falso:
    la    $v0, __msg_false
    jr    $ra

# ----------------------------------------------------------------------
# __utoa_buf($a0 = valor >= 0, $a1 = destino) -> $v0 = fin del destino
#   Escribe los digitos en el buffer auxiliar al reves y luego los copia
#   en orden. No toca $a1 mas alla de lo escrito.
# ----------------------------------------------------------------------
__utoa_buf:
    la    $t0, __buf2
    addiu $t0, $t0, 31
    sb    $zero, 0($t0)
    move  $t1, $a0
    bne   $t1, $zero, __ub_bucle
    addiu $t0, $t0, -1
    li    $t2, 48
    sb    $t2, 0($t0)
    j     __ub_copia
__ub_bucle:
    beq   $t1, $zero, __ub_copia
    li    $t3, 10
    divu  $t1, $t3
    mflo  $t4
    mfhi  $t2
    addiu $t2, $t2, 48
    addiu $t0, $t0, -1
    sb    $t2, 0($t0)
    move  $t1, $t4
    j     __ub_bucle
__ub_copia:
    move  $t5, $a1
__ub_c1:
    lb    $t2, 0($t0)
    beq   $t2, $zero, __ub_fin
    sb    $t2, 0($t5)
    addiu $t0, $t0, 1
    addiu $t5, $t5, 1
    j     __ub_c1
__ub_fin:
    move  $v0, $t5
    jr    $ra

# ----------------------------------------------------------------------
# __itoa($a0) -> $v0 = cadena recien reservada
# ----------------------------------------------------------------------
__itoa:
    addiu $sp, $sp, -8
    sw    $ra, 0($sp)
    la    $a1, __buf
    bgez  $a0, __it_positivo
    li    $t0, 45
    sb    $t0, 0($a1)
    addiu $a1, $a1, 1
    negu  $a0, $a0
__it_positivo:
    jal   __utoa_buf
    sb    $zero, 0($v0)
    la    $a0, __buf
    jal   __str_copy
    lw    $ra, 0($sp)
    addiu $sp, $sp, 8
    jr    $ra

# ----------------------------------------------------------------------
# __ftoa($f12) -> $v0 = cadena recien reservada
#   Reproduce el formato de la maquina virtual del TAC: hasta seis
#   decimales, redondeados, sin ceros finales ni punto suelto.
# ----------------------------------------------------------------------
__ftoa:
    addiu $sp, $sp, -24
    sw    $ra, 0($sp)
    la    $a1, __buf

    # --- signo ---
    mtc1  $zero, $f4
    mtc1  $zero, $f5
    c.lt.d $f12, $f4
    bc1f  __ft_positivo
    li    $t0, 45
    sb    $t0, 0($a1)
    addiu $a1, $a1, 1
    neg.d $f12, $f12
__ft_positivo:
    # --- parte entera (truncada) ---
    trunc.w.d $f6, $f12
    mfc1  $a2, $f6

    # --- parte fraccionaria x 1000000, redondeada ---
    cvt.d.w $f8, $f6
    sub.d $f10, $f12, $f8
    li    $t0, 1000000
    mtc1  $t0, $f4
    cvt.d.w $f4, $f4
    mul.d $f10, $f10, $f4
    # Redondeo al entero mas cercano, explicito: sumar 0.5 y truncar.
    # 'cvt.w.d' dependeria del modo de redondeo del FCSR, que MARS no
    # implementa (trunca siempre), asi que el texto de un mismo numero
    # diferiria entre simuladores. El valor ya es positivo aqui.
    li    $t0, 1
    mtc1  $t0, $f4
    cvt.d.w $f4, $f4
    li    $t0, 2
    mtc1  $t0, $f6
    cvt.d.w $f6, $f6
    div.d $f4, $f4, $f6
    add.d $f10, $f10, $f4
    trunc.w.d $f6, $f10
    mfc1  $a3, $f6

    # El redondeo puede desbordar: 0.9999999 -> 1000000
    li    $t0, 1000000
    blt   $a3, $t0, __ft_escribe
    sub   $a3, $a3, $t0
    addiu $a2, $a2, 1

__ft_escribe:
    sw    $a3, 4($sp)
    move  $a0, $a2
    jal   __utoa_buf
    move  $a1, $v0
    lw    $a3, 4($sp)

    beq   $a3, $zero, __ft_fin
    li    $t0, 46
    sb    $t0, 0($a1)
    addiu $a1, $a1, 1

    # seis digitos con ceros a la izquierda
    li    $t3, 100000
__ft_frac:
    beq   $t3, $zero, __ft_recorta
    divu  $a3, $t3
    mflo  $t4
    mfhi  $a3
    addiu $t4, $t4, 48
    sb    $t4, 0($a1)
    addiu $a1, $a1, 1
    li    $t5, 10
    divu  $t3, $t5
    mflo  $t3
    j     __ft_frac

__ft_recorta:
    addiu $t6, $a1, -1
__ft_r1:
    lb    $t4, 0($t6)
    li    $t5, 48
    bne   $t4, $t5, __ft_r2
    move  $a1, $t6
    addiu $t6, $t6, -1
    j     __ft_r1
__ft_r2:
    addiu $t6, $a1, -1
    lb    $t4, 0($t6)
    li    $t5, 46
    bne   $t4, $t5, __ft_fin
    move  $a1, $t6

__ft_fin:
    sb    $zero, 0($a1)
    la    $a0, __buf
    jal   __str_copy
    lw    $ra, 0($sp)
    addiu $sp, $sp, 24
    jr    $ra

# ----------------------------------------------------------------------
# Manejadores de excepciones.
#   La pila guarda, por cada 'try' activo, la direccion del catch y los
#   punteros de pila y de marco de ese momento. Al lanzar se restauran y
#   se salta, lo que descarta de golpe los marcos intermedios.
# ----------------------------------------------------------------------
__handler_push:
    la    $t0, __handler_sp
    lw    $t1, 0($t0)
    la    $t2, __handlers
    li    $t4, 12
    mul   $t3, $t1, $t4
    add   $t2, $t2, $t3
    sw    $a0, 0($t2)
    sw    $sp, 4($t2)
    sw    $fp, 8($t2)
    addiu $t1, $t1, 1
    sw    $t1, 0($t0)
    jr    $ra

__handler_pop:
    la    $t0, __handler_sp
    lw    $t1, 0($t0)
    blez  $t1, __hp_fin
    addiu $t1, $t1, -1
    sw    $t1, 0($t0)
__hp_fin:
    jr    $ra

# __throw($a0 = mensaje)
__throw:
    la    $t0, __exc_msg
    sw    $a0, 0($t0)
    la    $t0, __handler_sp
    lw    $t1, 0($t0)
    blez  $t1, __th_sin_atrapar
    addiu $t1, $t1, -1
    sw    $t1, 0($t0)
    la    $t2, __handlers
    li    $t4, 12
    mul   $t3, $t1, $t4
    add   $t2, $t2, $t3
    lw    $t5, 0($t2)
    lw    $sp, 4($t2)
    lw    $fp, 8($t2)
    jr    $t5
__th_sin_atrapar:
    la    $a0, __msg_uncaught
    li    $v0, 4
    syscall
    la    $t0, __exc_msg
    lw    $a0, 0($t0)
    li    $v0, 4
    syscall
    la    $a0, __msg_nl
    li    $v0, 4
    syscall
    li    $v0, 10
    syscall

__exc_message:
    la    $t0, __exc_msg
    lw    $v0, 0($t0)
    jr    $ra
"""
