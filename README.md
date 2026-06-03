<div align="center">

# PatchLab

**Etiquetador de escritorio, multiplataforma y de código abierto para parches de imágenes.**

Construye datasets de clasificación de imágenes de forma rápida, ergonómica y reproducible.

[![Plataforma](https://img.shields.io/badge/plataforma-Windows%20%7C%20macOS%20%7C%20Linux-blue)](#-instalación)
[![Python](https://img.shields.io/badge/python-3.10%2B-green)](#-instalación)
[![Licencia](https://img.shields.io/badge/licencia-MIT-yellow)](LICENSE)
[![Interfaz](https://img.shields.io/badge/GUI-PySide6-41cd52)](https://doc.qt.io/qtforpython/)
[![PRs](https://img.shields.io/badge/PRs-bienvenidos-brightgreen)](CONTRIBUTING.md)

</div>

---

PatchLab es una herramienta gráfica para **recortar y etiquetar parches** a
partir de un conjunto de imágenes. Está pensada para acelerar la creación de
datasets de clasificación —por ejemplo, control de calidad visual (`OK` / `NG`)
o detección de anomalías— ofreciendo dos flujos de trabajo complementarios y una
salida directamente consumible por cualquier *pipeline* de entrenamiento.

## 📑 Tabla de contenidos

- [Características](#-características)
- [Capturas del flujo](#-capturas-del-flujo)
- [Instalación](#-instalación)
- [Uso](#️-uso)
- [Atajos de teclado](#️-atajos-de-teclado)
- [Salida generada](#-salida-generada)
- [Arquitectura](#-arquitectura)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Desarrollo y pruebas](#-desarrollo-y-pruebas)
- [Contribuir](#-contribuir)
- [Licencia](#-licencia)

## ✨ Características

| Área | Detalle |
|------|---------|
| **Extracción** | **Cuadrícula** (parches cuadrados regulares sobre toda la imagen) o **Parches YOLO** (recortes restringidos a las regiones segmentadas por un modelo, con su máscara aplicada — *opcional*). |
| **Interacción** | **Secuencial** (un parche cada vez) o **Cuadrícula interactiva** (se ve toda la rejilla y se "pinta" haciendo clic). |
| **Pintado por clic** | Clase fija ("sticky"): un clic aplica la clase activa con *feedback* visual instantáneo. Clic derecho o arrastre para limpiar/pintar. |
| **Llenado automático** | Etiqueta todas las celdas restantes con una sola acción, sin congelar la interfaz. |
| **Deshacer / Rehacer** | Historial completo en el flujo por clic (patrón *Command*). |
| **Rendimiento** | Lectura de imágenes, inferencia de YOLO y guardado por lotes en hilos secundarios: la interfaz nunca se bloquea. |
| **Ergonomía** | Atajos de teclado para todo el flujo, progreso por imagen y por celda, y tema claro/oscuro automático. |
| **Salida** | Carpetas por clase + `metadata.csv`, listo para entrenar. |

## 🖼 Capturas del flujo

> _Próximamente._ Las contribuciones con capturas o GIF de demostración son
> bienvenidas (ver [CONTRIBUTING.md](CONTRIBUTING.md)).

## 🚀 Instalación

Requisito previo: **Python 3.10 o superior**.

```bash
# 1. Clonar el repositorio
git clone https://github.com/Dreizack97/PatchLab.git
cd PatchLab

# 2. Crear y activar un entorno virtual
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate

# 3. Instalar PatchLab
pip install -e .
```

<details>
<summary>Alternativa sin empaquetado</summary>

```bash
pip install -r requirements.txt
```
</details>

### Modo YOLO (opcional)

Necesario solo si vas a cargar un modelo de segmentación `.pt`. Añade PyTorch a
través de `ultralytics`:

```bash
pip install -e ".[yolo]"      # o, simplemente:  pip install ultralytics
```

## ▶️ Uso

Una vez instalado, lanza la aplicación con cualquiera de estas opciones:

```bash
patchlab             # comando instalado (interfaz gráfica)
python -m patchlab   # equivalente, útil para depurar
```

Al iniciar se muestra un **diálogo de configuración**:

| Campo | Descripción |
|-------|-------------|
| Directorio de entrada | Carpeta con las imágenes a etiquetar (búsqueda recursiva). |
| Directorio de salida | Destino del dataset organizado por clases + `metadata.csv`. |
| Modelo YOLO | *Opcional.* Ruta a un `.pt`; si se omite, se usa el modo Cuadrícula. |
| Etiquetas | Lista separada por comas (p. ej. `OK, NG, REPARABLE`). |
| Tamaño de parche | Lado en píxeles de cada recorte cuadrado. |
| Padding YOLO | Contexto extra alrededor del recorte (`0.1` = 10 %). |
| Modo de etiquetado | **Secuencial** o **Cuadrícula interactiva**. |

## ⌨️ Atajos de teclado

<table>
<tr><th>Modo secuencial</th><th>Modo cuadrícula interactiva</th></tr>
<tr valign="top"><td>

| Tecla | Acción |
|-------|--------|
| `1` `2` `3` … | Asignar la etiqueta (en orden) |
| `S` | Omitir el parche |
| `U` / `Retroceso` | Deshacer |
| `Q` / `Esc` | Finalizar |

</td><td>

| Atajo | Acción |
|-------|--------|
| `1` `2` `3` … | Fijar la clase activa |
| `Tab` | Alternar a la siguiente clase |
| Clic izq. / der. | Pintar / limpiar celda |
| `F` | Etiquetar el resto de la grilla |
| `Ctrl+Z` / `Ctrl+Y` | Deshacer / Rehacer |
| `Enter` | Guardar y siguiente imagen |
| `Esc` / `Q` | Finalizar |

</td></tr>
</table>

Todos los botones de la interfaz muestran su atajo y son clicables.

## 📦 Salida generada

```text
<directorio-de-salida>/
├── metadata.csv          # columnas: file, patch_idx, label
├── OK/
│   ├── img1_grid_p0.jpg
│   └── …
└── NG/
    ├── img1_grid_p3.jpg
    └── …
```

- Las imágenes se agrupan en una **subcarpeta por etiqueta**.
- `metadata.csv` registra cada parche guardado. Reejecutar sobre el mismo
  directorio de salida **añade** registros al CSV existente.

## 🧩 Arquitectura

PatchLab aplica el patrón **Modelo–Vista–Controlador (MVC)** con una separación
estricta de responsabilidades, lo que facilita las pruebas y la extensión:

| Capa | Responsabilidad | Dependencias de Qt |
|------|-----------------|:------------------:|
| **Modelo** (`models/`) | Entidades de datos, lógica de la cuadrícula con deshacer/rehacer y persistencia. | ❌ |
| **Servicios** (`services/`) | Lógica de negocio pura: extracción, geometría, renderizado. | ❌ |
| **Controlador** (`controllers/`) | Estado de la sesión, traducción de acciones y delegación a hilos. | ✅ |
| **Vista** (`views/`) | Interfaz PySide6; observa señales y reenvía intenciones. | ✅ |

Esta frontera (Modelo y Servicios sin Qt) permite probar el núcleo de negocio de
forma headless, como en [`tests/`](tests/).

## 📁 Estructura del proyecto

```text
PatchLab/
├── pyproject.toml            # metadatos, dependencias y console scripts
├── requirements.txt          # dependencias principales (alternativa)
├── LICENSE                   # MIT
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── .gitignore
├── tests/                    # pruebas (pytest, sin interfaz)
└── src/
    └── patchlab/             # paquete de la aplicación (MVC)
        ├── __main__.py       # habilita  python -m patchlab
        ├── main.py           # función run() (punto de entrada)
        ├── models/           # config, patch, grid_session, repository
        ├── services/         # extractor, geometry, renderer, color, …
        ├── controllers/      # controller, grid_controller, workers
        └── views/            # ventanas, lienzo interactivo, diálogo, tema
```

## 🧪 Desarrollo y pruebas

```bash
pip install -e ".[dev]"      # instala pytest y ruff
ruff check src               # análisis estático / estilo
pytest                       # ejecuta la batería de pruebas
```

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Consulta [CONTRIBUTING.md](CONTRIBUTING.md)
para el flujo de trabajo, el estilo de código y cómo ejecutar las pruebas. Para
errores o propuestas, abre un *issue* en el
[gestor de incidencias](https://github.com/Dreizack97/PatchLab/issues).

## 📝 Licencia

Distribuido bajo la licencia **MIT**. Consulta [LICENSE](LICENSE) para más
detalles.

<div align="center">
<sub>Hecho con ❤ por <a href="https://github.com/Dreizack97">Dreizack97</a> y la comunidad.</sub>
</div>
