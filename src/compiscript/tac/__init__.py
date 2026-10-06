"""Generacion de codigo intermedio (TAC) de Compiscript."""
from .generator import TACGenerator, generate_tac
from .quadruple import Op, Operand, Quadruple, TACFunction, TACProgram
from .temporaries import LabelFactory, TempPool

__all__ = [
    "TACGenerator", "generate_tac", "Op", "Operand", "Quadruple",
    "TACFunction", "TACProgram", "TempPool", "LabelFactory",
]
