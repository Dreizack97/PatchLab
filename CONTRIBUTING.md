# Guía de contribución

¡Gracias por tu interés en mejorar **PatchLab**! Este es un proyecto de código
abierto bajo licencia MIT y agradece toda colaboración: informes de fallos,
ideas, mejoras de documentación, pruebas y, por supuesto, código.

Este documento describe cómo preparar tu entorno y qué esperamos de las
contribuciones para mantener la calidad y la coherencia del proyecto.

## Tabla de contenidos

- [Código de conducta](#código-de-conducta)
- [Formas de contribuir](#formas-de-contribuir)
- [Preparar el entorno de desarrollo](#preparar-el-entorno-de-desarrollo)
- [Flujo de trabajo con Git](#flujo-de-trabajo-con-git)
- [Estilo de código](#estilo-de-código)
- [Pruebas](#pruebas)
- [Pull Requests](#pull-requests)
- [Reportar fallos](#reportar-fallos)

## Código de conducta

Participar en este proyecto implica mantener un trato respetuoso y constructivo.
Buscamos una comunidad acogedora para todas las personas, con independencia de
su experiencia o procedencia. No se tolerarán comentarios ni conductas abusivas.

## Formas de contribuir

- **Informar de fallos** o proponer mejoras a través de *issues*.
- **Mejorar la documentación** (README, esta guía, *docstrings*).
- **Añadir pruebas** que aumenten la cobertura del núcleo de negocio.
- **Implementar funcionalidades** o corregir errores mediante *Pull Requests*.
- **Aportar capturas o GIF** que ilustren los flujos de la aplicación.

## Preparar el entorno de desarrollo

Requiere **Python 3.10 o superior**.

```bash
# 1. Hacer un fork y clonar tu copia
git clone https://github.com/<tu-usuario>/PatchLab.git
cd PatchLab

# 2. Crear y activar un entorno virtual
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate

# 3. Instalar en modo editable con las herramientas de desarrollo
pip install -e ".[dev]"

# 4. Comprobar que la aplicación arranca
patchlab
```

## Flujo de trabajo con Git

1. Sincroniza tu rama principal con el repositorio original (`upstream`).
2. Crea una rama descriptiva por cada cambio:
   - `feat/…` para nuevas funcionalidades.
   - `fix/…` para correcciones de errores.
   - `docs/…`, `test/…`, `refactor/…` según corresponda.
3. Realiza *commits* pequeños y con mensajes claros (se recomienda
   [Conventional Commits](https://www.conventionalcommits.org/es/), p. ej.
   `feat: añadir exportación a COCO`).

## Estilo de código

PatchLab sigue una arquitectura **MVC** estricta; respétala al contribuir:

- La **lógica de negocio** vive en `models/` y `services/` y **no** debe importar
  PySide6. La **interacción** vive en `controllers/` y `views/`.
- Usa **tipado estático** y **docstrings** en todas las funciones y clases
  públicas, en español y siguiendo el estilo existente.
- Comprueba el estilo con Ruff antes de subir cambios:

  ```bash
  ruff check src
  ```

## Pruebas

Acompaña los cambios de lógica con pruebas en `tests/`. El núcleo de negocio es
testeable sin interfaz gráfica.

```bash
pytest
```

Asegúrate de que **toda la batería pasa** antes de abrir un *Pull Request*.

## Pull Requests

Antes de abrir un PR, verifica que:

- [ ] El código pasa `ruff check src` y `pytest`.
- [ ] Se mantiene la separación de capas MVC.
- [ ] Hay *docstrings* y tipado en el código nuevo.
- [ ] Se actualizó la documentación afectada (incluido `CHANGELOG.md`).

En la descripción del PR, explica **qué** cambia y **por qué**, y enlaza el
*issue* relacionado si existe.

## Reportar fallos

Abre un *issue* incluyendo:

- Sistema operativo y versión de Python.
- Versión de PatchLab (o *commit*).
- Pasos para reproducir el problema.
- Comportamiento esperado y comportamiento real.
- Capturas de pantalla o trazas de error, si aplica.

¡Gracias por ayudar a que PatchLab sea mejor! 🙌
