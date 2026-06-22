# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el proyecto sigue [Versionado Semántico](https://semver.org/lang/es/).

## [Sin publicar]

> Cambios en desarrollo que aún no forman parte de una versión publicada.

## [2.0.0] - 2026-06-22

### Añadido
- **Sesiones de etiquetado colaborativas distribuidas**: un Host actúa como
  supervisor y trabajador, reparte el dataset por *shards* entre los
  colaboradores conectados y consolida sus resultados. Incluye protocolo de red
  saneado, servidor, lobby de participantes y diálogo para unirse a una sesión.
- **Modelo de clasificación opcional** que pre-clasifica la cuadrícula: cada
  parche llega con la clase sugerida ya pintada para que el usuario solo revise
  y corrija. En sesiones colaborativas, el Host ejecuta el modelo y propaga las
  sugerencias a los colaboradores (que no necesitan cargarlo).
- Selector del modelo de clasificación (`.pt`) y umbral de confianza mínima en
  el diálogo de inicio.

### Eliminado
- **Modo de etiquetado secuencial** (obsoleto): se retira el flujo parche a
  parche junto con su controlador, vista y selector de modo. La **Cuadrícula
  interactiva** pasa a ser el único modo de etiquetado. *(Cambio incompatible.)*

### Corregido
- Grilla duplicada y superpuesta en el modo Parches YOLO: las celdas de
  detecciones solapadas ahora se alinean a una rejilla global y se deduplican.
- *Crash* de PySide6 al ejecutar la inferencia de YOLO.

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

[Sin publicar]: https://github.com/Dreizack97/PatchLab/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/Dreizack97/PatchLab/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Dreizack97/PatchLab/releases/tag/v1.0.0
