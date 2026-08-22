"""Compilador de Compiscript - Fase de Análisis Semántico.

Paquete principal. El punto de entrada público es :func:`analyze`.
"""
from .analysis import AnalysisResult, analyze, analyze_file, analyze_source

__all__ = ["analyze", "analyze_file", "analyze_source", "AnalysisResult"]
__version__ = "1.0.0"
