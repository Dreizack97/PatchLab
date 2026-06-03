"""Subsistema de **etiquetado colaborativo local en tiempo real**.

Convierte PatchLab (modo Cuadrícula interactiva) en una herramienta cliente-
servidor ligera sobre la red local: un *Host* levanta un servicio WebSocket y
varios *Colaboradores* etiquetan en paralelo el mismo set de datos.

Capas (siguiendo la filosofía MVC del proyecto):

- :mod:`patchlab.collab.protocol` y :mod:`patchlab.collab.presence` son **puros**
  (sin Qt), por lo que se prueban de forma headless igual que ``models``/``services``.
- :mod:`patchlab.collab.server` y :mod:`patchlab.collab.client` encapsulan el
  transporte (``QtWebSockets``); :mod:`patchlab.collab.remote_controller` adapta
  el flujo de red a la misma API que espera la vista.
"""
