# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el proyecto sigue [Versionado Semántico](https://semver.org/lang/es/).

## [Sin publicar]

> Cambios en desarrollo que aún no forman parte de una versión publicada.

## [1.0.0] - 2026-06-03

### Añadido
- Aplicación de escritorio multiplataforma con PySide6 y arquitectura MVC.
- Dos modos de extracción de parches: **Cuadrícula** y **Parches YOLO** (opcional).
- **Modo secuencial**: etiquetado parche a parche con vista dual (parche +
  contexto) y atajos de teclado.
- **Modo cuadrícula interactiva (clic)**: selección de clase fija ("pintar"),
  *feedback* visual instantáneo, llenado automático de las celdas restantes y
  deshacer/rehacer (patrón *Command*).
- Procesamiento en segundo plano (extracción, inferencia y guardado por lotes)
  para mantener la interfaz fluida.
- Tema claro/oscuro automático según el sistema operativo.
- Salida lista para entrenar: carpetas por clase + `metadata.csv`.
- Empaquetado para distribución (`pyproject.toml`, *console scripts* `patchlab`).

[Sin publicar]: https://github.com/Dreizack97/PatchLab/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Dreizack97/PatchLab/releases/tag/v1.0.0
