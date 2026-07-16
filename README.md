# Window Macro Studio

Aplicación de escritorio para Windows que permite grabar y reproducir acciones de ratón y teclado dentro de una ventana autorizada, organizadas en presets independientes.

> Usa esta herramienta únicamente en aplicaciones y entornos donde tengas autorización.

## Requisitos

- Windows 10 u 11
- Python 3.10 o superior
- Una aplicación objetivo abierta

## Instalación

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

## Ejecución

```powershell
.\.venv\Scripts\python.exe .\window_macro_studio_v2.py
```

## Flujo de uso

1. Abre la aplicación objetivo.
2. Ejecuta Window Macro Studio.
3. Crea o selecciona un preset.
4. Indica el nombre del ejecutable y pulsa **Conectar a la ventana**.
5. Pulsa **Preparar grabación** y espera la cuenta regresiva.
6. Realiza las acciones cuando aparezca el indicador **GRABANDO**.
7. Pulsa `F9` o **Detener y guardar grabación**.
8. Pulsa **Ejecutar preset** para reproducirlo.

## Atajos

| Tecla | Acción |
| --- | --- |
| `F6` | Preset anterior |
| `F7` | Preset siguiente |
| `F8` | Cerrar el motor |
| `F9` | Iniciar o detener grabación |
| `F10` | Ejecutar preset |
| `F12` | Detener ejecución |

## Archivos

- `window_macro_studio_v2.py`: interfaz gráfica.
- `window_macro_recorder_v4.py`: motor de captura, persistencia y reproducción.
- `requirements.txt`: dependencias de Python.

Los presets se guardan localmente en `macros/` y no se versionan en Git.
