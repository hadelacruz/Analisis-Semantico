"""Generacion de codigo MIPS a partir del codigo de tres direcciones."""
from .asm import MipsProgram
from .generator import MipsGenerator, generate_mips
from .registers import RegisterAllocator

__all__ = ["MipsProgram", "MipsGenerator", "generate_mips", "RegisterAllocator"]
