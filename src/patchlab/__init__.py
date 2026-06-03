"""
PatchLab — Etiquetador de parches de imágenes (aplicación de escritorio).

Herramienta de escritorio multiplataforma (Windows / macOS / Linux) y de código
abierto, construida sobre PySide6 siguiendo una arquitectura
Modelo-Vista-Controlador (MVC):

- ``models``      : Entidades de datos puras y persistencia del dataset.
- ``services``    : Lógica de negocio reutilizable (extracción de parches,
                     renderizado de contexto, utilidades de imagen).
- ``controllers`` : Orquestación del flujo de etiquetado y estado de la sesión.
- ``views``       : Interfaz gráfica (ventanas, diálogos y widgets PySide6).

El punto de entrada es :func:`patchlab.main.run`.
"""

__all__ = ["__version__"]
__version__ = "1.0.0"
